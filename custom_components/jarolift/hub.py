"""Jarolift hub: sends KeeLoq encoded commands through a Home Assistant remote."""

from __future__ import annotations

import asyncio
from datetime import datetime
import glob
import logging
import os
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    BUTTON_LEARN,
    BUTTON_STOP,
    BUTTON_UP,
    COMMAND_CLEAR,
    COMMAND_LEARN,
    COUNTER_MASK,
    DEFAULT_REP_DELAY,
    DOMAIN,
    SIGNAL_COMMAND,
    SIGNAL_COUNTER,
    SIGNAL_TRAVEL,
)
from .keeloq import BuildPacket

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
LEGACY_COUNTER_GLOB = "counter_0x*.txt"


def _read_legacy_counter_files(config_dir: str) -> dict[str, int]:
    """Read counter_0x<serial>.txt files written by version 1.x."""
    counters = {}
    for filename in glob.glob(os.path.join(config_dir, LEGACY_COUNTER_GLOB)):
        key = os.path.basename(filename)[len("counter_") : -len(".txt")]
        try:
            with open(filename, encoding="utf-8") as fo:
                counters[key] = int(fo.readline()) & COUNTER_MASK
        except (OSError, ValueError):
            _LOGGER.error("Cannot read legacy Jarolift counter file %s", filename)
    return counters


def _rename_legacy_counter_files(config_dir: str, keys: list[str]) -> None:
    for key in keys:
        filename = os.path.join(config_dir, f"counter_{key}.txt")
        os.replace(filename, filename + ".migrated")


class JaroliftHub:
    """Sends commands and keeps the rolling code counters of one remote."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        remote_entity_id: str,
        msb: int,
        lsb: int,
        delay: float,
    ) -> None:
        self.hass = hass
        self.entry_id = entry_id
        self.remote_entity_id = remote_entity_id
        self._msb = msb
        self._lsb = lsb
        self._delay = delay
        # One transmission at a time through the remote. Counter handling
        # happens under this lock too, so a rolling code is never reused.
        self._lock = asyncio.Lock()
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}", atomic_writes=True
        )
        self._data: dict[str, Any] = {"counters": {}, "travel": {}}

    async def async_load(self) -> None:
        """Load counters, importing the counter files of version 1.x once."""
        if stored := await self._store.async_load():
            self._data["counters"].update(stored.get("counters", {}))
            self._data["travel"].update(stored.get("travel", {}))

        config_dir = self.hass.config.config_dir
        legacy = await self.hass.async_add_executor_job(
            _read_legacy_counter_files, config_dir
        )
        if not legacy:
            return
        for key, value in legacy.items():
            if key not in self._data["counters"]:
                _LOGGER.info("Importing Jarolift counter %s = %s", key, value)
                self._data["counters"][key] = value
        await self._store.async_save(self._data)
        await self.hass.async_add_executor_job(
            _rename_legacy_counter_files, config_dir, list(legacy)
        )

    async def async_prune_travel_times(self, cover_ids: set[str]) -> None:
        """Forget travel times of covers that no longer exist."""
        travel = self._data["travel"]
        stale = [cover_id for cover_id in travel if cover_id not in cover_ids]
        if stale:
            for cover_id in stale:
                del travel[cover_id]
            await self._store.async_save(self._data)

    # Counters

    def counter(self, serial: int) -> int:
        """Next counter value that will be used for this serial."""
        return self._data["counters"].get(hex(serial), 0)

    async def _async_reserve_counters(self, serial: int, count: int, explicit: int) -> int:
        """Return the first of `count` counter values. Caller holds the lock.

        An explicit counter (from the service call) is used as is and does
        not touch the stored counter.
        """
        if explicit:
            return explicit
        start = self.counter(serial)
        self._data["counters"][hex(serial)] = (start + count) & COUNTER_MASK
        # Saved before sending: a crash must never lead to reusing a code
        await self._store.async_save(self._data)
        async_dispatcher_send(self.hass, SIGNAL_COUNTER.format(self.entry_id), serial)
        return start

    # Travel times (configured via the number entities)

    def travel_time(self, cover_id: str, direction: str) -> float:
        return self._data["travel"].get(cover_id, {}).get(direction, 0.0)

    async def async_set_travel_time(
        self, cover_id: str, direction: str, value: float
    ) -> None:
        self._data["travel"].setdefault(cover_id, {})[direction] = value
        await self._store.async_save(self._data)
        async_dispatcher_send(self.hass, SIGNAL_TRAVEL.format(self.entry_id), cover_id)

    # Sending

    async def _async_send(self, packet: str) -> None:
        await self.hass.services.async_call(
            "remote",
            "send_command",
            {"entity_id": self.remote_entity_id, "command": [packet]},
            blocking=True,
        )

    def _packet(self, serial, group, button, counter, hold=False) -> str:
        return BuildPacket(group, serial, button, counter, self._msb, self._lsb, hold)

    def _notify(self, serial, group, button, hold, command, source) -> None:
        async_dispatcher_send(
            self.hass,
            SIGNAL_COMMAND.format(self.entry_id),
            {
                "serial": serial,
                "group": group,
                "button": button,
                "hold": hold,
                "command": command,
                "source": source,
                "at": dt_util.utcnow(),
            },
        )

    async def async_send_raw(self, packet: str) -> None:
        async with self._lock:
            await self._async_send(packet)

    async def async_send_command(
        self,
        serial: int,
        group: int,
        button: int,
        *,
        rep_count: int = 0,
        rep_delay: float = DEFAULT_REP_DELAY,
        hold: bool = False,
        counter: int = 0,
        command: str | None = None,
        source: object = None,
    ) -> datetime:
        """Send a button press. Returns when the first transmission went out."""
        async with self._lock:
            used = await self._async_reserve_counters(serial, 1, counter)
            packet = self._packet(serial, group, button, used, hold)
            sent_at = None
            # We want to send at least once. so rep_count 0 means range(1)
            for i in range(rep_count + 1):
                _LOGGER.debug(
                    "Sending: %s group: 0x%04X Serial: 0x%08X repeat: %s",
                    button,
                    group,
                    serial,
                    i,
                )
                await self._async_send(packet)
                if sent_at is None:
                    sent_at = dt_util.utcnow()
                    self._notify(serial, group, button, hold, command, source)
                if i < rep_count:
                    await asyncio.sleep(rep_delay)
            # This is the minimum delay between multiple different covers
            await asyncio.sleep(self._delay)
        return sent_at

    async def async_learn(self, serial: int, group: int, counter: int = 0) -> None:
        async with self._lock:
            used = await self._async_reserve_counters(serial, 2, counter)
            await self._async_send(self._packet(serial, group, BUTTON_LEARN, used))
            await asyncio.sleep(1)
            await self._async_send(self._packet(serial, group, BUTTON_STOP, used + 1))
            self._notify(serial, group, None, False, COMMAND_LEARN, None)

    async def async_clear(self, serial: int, group: int, counter: int = 0) -> None:
        async with self._lock:
            used = await self._async_reserve_counters(serial, 8, counter)
            await self._async_send(self._packet(serial, group, BUTTON_LEARN, used))
            await asyncio.sleep(1)
            for i in range(6):
                await self._async_send(
                    self._packet(serial, group, BUTTON_STOP, used + 1 + i)
                )
                await asyncio.sleep(0.5)
            await asyncio.sleep(1)
            await self._async_send(self._packet(serial, group, BUTTON_UP, used + 7))
            self._notify(serial, group, None, False, COMMAND_CLEAR, None)


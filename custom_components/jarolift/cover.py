"""
Support for Jarolift cover
"""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.cover import (
    ATTR_CURRENT_POSITION,
    ATTR_POSITION,
    PLATFORM_SCHEMA as COVER_PLATFORM_SCHEMA,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
    CoverState,
)
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .const import (
    BUTTON_DOWN,
    BUTTON_STOP,
    BUTTON_UP,
    COMMAND_CLOSE,
    COMMAND_INTERMEDIATE,
    COMMAND_OPEN,
    COMMAND_STOP,
    DOMAIN,
    DOWN,
    SIGNAL_COMMAND,
    SIGNAL_TRAVEL,
    UP,
    YAML_COVERS_SCHEMA,
)
from .entity import JaroliftEntity, add_cover_entities

_LOGGER = logging.getLogger(__name__)

# Kept so existing `cover: - platform: jarolift` blocks still validate. They are
# imported into the config entry by the integration setup (see __init__.py).
PLATFORM_SCHEMA = COVER_PLATFORM_SCHEMA.extend(
    {vol.Required("covers"): YAML_COVERS_SCHEMA}
)

TICK = timedelta(seconds=1)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Legacy YAML platform: nothing to do, the covers are imported."""
    _LOGGER.debug("Jarolift YAML covers are imported into the config entry")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    add_cover_entities(entry, async_add_entities, lambda e, s: [JaroliftCover(e, s)])


class JaroliftCover(JaroliftEntity, CoverEntity, RestoreEntity):
    """Jarolift cover with assumed state.

    Without feedback from the motor the state is what was sent last. When
    travel times are configured, the position is estimated from the time the
    cover has been moving, which also allows moving to a position.
    """

    _attr_name = None
    _attr_device_class = CoverDeviceClass.BLIND
    _attr_assumed_state = True

    def __init__(self, entry: ConfigEntry, subentry: ConfigSubentry) -> None:
        super().__init__(entry, subentry, None)
        self._closed: bool | None = None
        self._position: float | None = None
        # Movement tracking, only used with travel times
        self._direction = 0  # 1 opening, -1 closing
        self._move_start: datetime | None = None
        self._move_from = 0.0
        self._target: float | None = None
        self._unsub_tick: CALLBACK_TYPE | None = None
        self._unsub_end: CALLBACK_TYPE | None = None

    # Position estimation

    def _travel(self, direction: int) -> float:
        return self.hub.travel_time(self.cover_id, UP if direction > 0 else DOWN)

    @property
    def _positioning(self) -> bool:
        return self._travel(1) > 0 and self._travel(-1) > 0

    def _position_at(self, at: datetime) -> float | None:
        if not self._direction or self._move_start is None:
            return self._position
        elapsed = max(0.0, (at - self._move_start).total_seconds())
        position = self._move_from + self._direction * 100 * elapsed / self._travel(
            self._direction
        )
        if self._target is not None:
            if self._direction > 0:
                position = min(position, self._target)
            else:
                position = max(position, self._target)
        return min(100.0, max(0.0, position))

    @property
    def supported_features(self) -> CoverEntityFeature:
        features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
        if self._positioning:
            features |= CoverEntityFeature.SET_POSITION
        return features

    @property
    def current_cover_position(self) -> int | None:
        if not self._positioning:
            return None
        position = self._position_at(dt_util.utcnow())
        return None if position is None else round(position)

    @property
    def is_closed(self) -> bool | None:
        if self._positioning:
            position = self._position_at(dt_util.utcnow())
            if position is not None:
                return round(position) == 0
        return self._closed

    @property
    def is_opening(self) -> bool:
        return self._direction > 0

    @property
    def is_closing(self) -> bool:
        return self._direction < 0

    # Lifecycle

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            if last.state == CoverState.CLOSED:
                self._closed = True
            elif last.state in (CoverState.OPEN, CoverState.OPENING, CoverState.CLOSING):
                self._closed = False
            if (position := last.attributes.get(ATTR_CURRENT_POSITION)) is not None:
                self._position = float(position)
        entry_id = self.hub.entry_id
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_COMMAND.format(entry_id), self._on_command
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_TRAVEL.format(entry_id), self._on_travel
            )
        )
        self.async_on_remove(self._cancel_timers)

    @callback
    def _on_travel(self, cover_id: str) -> None:
        if cover_id == self.cover_id:
            self.async_write_ha_state()

    @callback
    def _on_command(self, payload: dict) -> None:
        """Follow commands for this cover sent by others (services, buttons)."""
        if payload["source"] is self or not self.matches(payload):
            return
        command = payload["command"] or self.command_for(payload["button"], payload["hold"])
        if command == COMMAND_OPEN:
            self._start_tracking(1, payload["at"], None)
        elif command == COMMAND_CLOSE:
            self._start_tracking(-1, payload["at"], None)
        elif command == COMMAND_STOP:
            self._stopped(payload["at"])
        elif command == COMMAND_INTERMEDIATE:
            # The motor moves to its programmed position, which we don't know
            self._cancel_timers()
            self._direction = 0
            self._position = None
            self._closed = False
            self.async_write_ha_state()

    # Commands

    async def async_open_cover(self, **kwargs: Any) -> None:
        await self._async_move(1, None)

    async def async_close_cover(self, **kwargs: Any) -> None:
        await self._async_move(-1, None)

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        target = float(kwargs[ATTR_POSITION])
        if target >= 100:
            await self._async_move(1, None)
            return
        if target <= 0:
            await self._async_move(-1, None)
            return
        current = self._position_at(dt_util.utcnow())
        if current is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="position_unknown"
            )
        if abs(target - current) < 1:
            return
        await self._async_move(1 if target > current else -1, target)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        # Freeze the estimate until the stop has actually been sent
        self._cancel_timers()
        sent_at = await self._async_press(BUTTON_STOP, COMMAND_STOP)
        self._stopped(sent_at)

    async def _async_press(self, button: int, command: str) -> datetime:
        return await self.hub.async_send_command(
            self.serial,
            self.group,
            button,
            rep_count=self.rep_count,
            rep_delay=self.rep_delay,
            command=command,
            source=self,
        )

    async def _async_move(self, direction: int, target: float | None) -> None:
        if direction > 0:
            button = BUTTON_DOWN if self.reverse else BUTTON_UP
            command = COMMAND_OPEN
        else:
            button = BUTTON_UP if self.reverse else BUTTON_DOWN
            command = COMMAND_CLOSE
        _LOGGER.debug("%s: sending %s (reversed=%s)", command, button, self.reverse)
        # The estimate keeps running until the command has actually been sent
        self._cancel_timers()
        sent_at = await self._async_press(button, command)
        self._start_tracking(direction, sent_at, target)

    # State handling

    @callback
    def _start_tracking(self, direction: int, at: datetime, target: float | None) -> None:
        start = self._position_at(at)
        self._cancel_timers()
        self._direction = 0
        if not self._positioning:
            self._closed = direction < 0
            self.async_write_ha_state()
            return
        if start is None:
            # Unknown: assume the worst case, the full way
            start = 0.0 if direction > 0 else 100.0
        end = target if target is not None else (100.0 if direction > 0 else 0.0)
        self._position = start
        self._move_from = start
        self._move_start = at
        self._target = target
        self._direction = direction
        duration = abs(end - start) / 100 * self._travel(direction)
        remaining = duration - (dt_util.utcnow() - at).total_seconds()
        self._unsub_end = async_call_later(self.hass, max(0.0, remaining), self._async_on_end)
        self._unsub_tick = async_track_time_interval(self.hass, self._on_tick, TICK)
        self.async_write_ha_state()

    async def _async_on_end(self, _now: datetime) -> None:
        self._unsub_end = None
        target = self._target
        end = target if target is not None else (100.0 if self._direction > 0 else 0.0)
        self._cancel_timers()
        self._direction = 0
        self._position = end
        self._closed = end == 0
        self.async_write_ha_state()
        if target is not None:
            # Intermediate position: the motor only stops at its end positions
            await self._async_press(BUTTON_STOP, COMMAND_STOP)

    @callback
    def _stopped(self, at: datetime) -> None:
        position = self._position_at(at)
        self._cancel_timers()
        self._direction = 0
        self._position = position
        if position is not None and self._positioning:
            self._closed = round(position) == 0
        else:
            self._closed = False
        self.async_write_ha_state()

    @callback
    def _on_tick(self, _now: datetime) -> None:
        self.async_write_ha_state()

    @callback
    def _cancel_timers(self) -> None:
        if self._unsub_tick:
            self._unsub_tick()
            self._unsub_tick = None
        if self._unsub_end:
            self._unsub_end()
            self._unsub_end = None

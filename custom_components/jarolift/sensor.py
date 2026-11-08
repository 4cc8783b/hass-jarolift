"""Diagnostic sensors of a Jarolift cover."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
)
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import SIGNAL_COMMAND, SIGNAL_COUNTER
from .entity import JaroliftEntity, add_cover_entities

ATTR_COMMAND = "command"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    add_cover_entities(
        entry,
        async_add_entities,
        lambda e, s: [CounterSensor(e, s), LastCommandSensor(e, s)],
    )


class CounterSensor(JaroliftEntity, SensorEntity):
    """Next rolling code counter of the cover's serial."""

    _attr_translation_key = "counter"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: ConfigEntry, subentry: ConfigSubentry) -> None:
        super().__init__(entry, subentry, "counter")

    @property
    def native_value(self) -> int:
        return self.hub.counter(self.serial)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_COUNTER.format(self.hub.entry_id), self._on_counter
            )
        )

    @callback
    def _on_counter(self, serial: int) -> None:
        if serial == self.serial:
            self.async_write_ha_state()


class LastCommandSensor(JaroliftEntity, RestoreSensor):
    """When the last command was sent to the cover, and which one."""

    _attr_translation_key = "last_command"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, entry: ConfigEntry, subentry: ConfigSubentry) -> None:
        super().__init__(entry, subentry, "last_command")
        self._command: str | None = None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {ATTR_COMMAND: self._command}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (data := await self.async_get_last_sensor_data()) is not None:
            value = data.native_value
            self._attr_native_value = value if isinstance(value, datetime) else None
        if (state := await self.async_get_last_state()) is not None:
            self._command = state.attributes.get(ATTR_COMMAND)
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_COMMAND.format(self.hub.entry_id), self._on_command
            )
        )

    @callback
    def _on_command(self, payload: dict) -> None:
        if not self.matches(payload):
            return
        self._attr_native_value = payload["at"]
        self._command = payload["command"] or self.command_for(
            payload["button"], payload["hold"]
        )
        if self._command is None and payload["button"] is not None:
            self._command = f"0x{payload['button']:x}"
        self.async_write_ha_state()

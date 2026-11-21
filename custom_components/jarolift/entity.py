"""Base entity: every entity of a cover belongs to that cover's device."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    BUTTON_DOWN,
    BUTTON_STOP,
    BUTTON_UP,
    COMMAND_CLOSE,
    COMMAND_INTERMEDIATE,
    COMMAND_OPEN,
    COMMAND_STOP,
    CONF_GROUP,
    CONF_REP_COUNT,
    CONF_REP_DELAY,
    CONF_REVERSE,
    CONF_SERIAL,
    DOMAIN,
    SUBENTRY_COVER,
)
from .hub import JaroliftHub


class JaroliftEntity(Entity):
    """Entity of one Jarolift cover (config subentry)."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, subentry: ConfigSubentry, key: str | None) -> None:
        self.hub: JaroliftHub = entry.runtime_data
        self.cover_id = subentry.subentry_id
        data = subentry.data
        self.serial: int = data[CONF_SERIAL]
        self.group: int = data[CONF_GROUP]
        self.rep_count: int = data[CONF_REP_COUNT]
        self.rep_delay: float = data[CONF_REP_DELAY]
        self.reverse: bool = data[CONF_REVERSE]
        self._attr_unique_id = self.cover_id if key is None else f"{self.cover_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self.cover_id)},
            name=subentry.title,
            manufacturer="Jarolift",
            model="Radio receiver",
            serial_number=f"0x{self.serial:x} / group 0x{self.group:04x}",
            via_device=(DOMAIN, entry.entry_id),
        )

    def matches(self, payload: dict) -> bool:
        """True if a hub command notification is for this cover."""
        return payload["serial"] == self.serial and payload["group"] == self.group

    def command_for(self, button: int | None, hold: bool) -> str | None:
        """What a button code means for this cover (honours `reverse`)."""
        if button == BUTTON_STOP:
            return COMMAND_INTERMEDIATE if hold else COMMAND_STOP
        if button == BUTTON_UP:
            return COMMAND_CLOSE if self.reverse else COMMAND_OPEN
        if button == BUTTON_DOWN:
            return COMMAND_OPEN if self.reverse else COMMAND_CLOSE
        return None


def add_cover_entities(
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    factory: Callable[[ConfigEntry, ConfigSubentry], Iterable[Entity]],
) -> None:
    """Create the entities of every cover subentry."""
    for subentry in entry.subentries.values():
        if subentry.subentry_type == SUBENTRY_COVER:
            async_add_entities(
                list(factory(entry, subentry)),
                config_subentry_id=subentry.subentry_id,
            )


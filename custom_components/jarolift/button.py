"""Buttons of a Jarolift cover: learn, clear and intermediate position."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import BUTTON_STOP, COMMAND_INTERMEDIATE
from .entity import JaroliftEntity, add_cover_entities


@dataclass(frozen=True, kw_only=True)
class JaroliftButtonDescription(ButtonEntityDescription):
    press: Callable[[JaroliftEntity], Awaitable[object]]


BUTTONS = (
    JaroliftButtonDescription(
        key="learn",
        translation_key="learn",
        entity_category=EntityCategory.CONFIG,
        press=lambda e: e.hub.async_learn(e.serial, e.group),
    ),
    JaroliftButtonDescription(
        key="clear",
        translation_key="clear",
        entity_category=EntityCategory.CONFIG,
        # Easy to press by accident and the cover then has to be learned again
        entity_registry_enabled_default=False,
        press=lambda e: e.hub.async_clear(e.serial, e.group),
    ),
    JaroliftButtonDescription(
        key="intermediate",
        translation_key="intermediate",
        # Long press of stop: moves to the programmed intermediate position
        press=lambda e: e.hub.async_send_command(
            e.serial,
            e.group,
            BUTTON_STOP,
            rep_count=e.rep_count,
            rep_delay=e.rep_delay,
            hold=True,
            command=COMMAND_INTERMEDIATE,
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    add_cover_entities(
        entry,
        async_add_entities,
        lambda e, s: [JaroliftButton(e, s, description) for description in BUTTONS],
    )


class JaroliftButton(JaroliftEntity, ButtonEntity):
    entity_description: JaroliftButtonDescription

    def __init__(
        self,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
        description: JaroliftButtonDescription,
    ) -> None:
        super().__init__(entry, subentry, description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        await self.entity_description.press(self)

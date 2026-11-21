"""Travel times of a Jarolift cover, used to estimate its position."""

from __future__ import annotations

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOWN, UP
from .entity import JaroliftEntity, add_cover_entities

DESCRIPTIONS = tuple(
    NumberEntityDescription(
        key=f"travel_time_{direction}",
        translation_key=f"travel_time_{direction}",
        entity_category=EntityCategory.CONFIG,
        device_class=NumberDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        native_min_value=0,
        native_max_value=300,
        native_step=0.5,
        mode=NumberMode.BOX,
    )
    for direction in (UP, DOWN)
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    add_cover_entities(
        entry,
        async_add_entities,
        lambda e, s: [TravelTimeNumber(e, s, d) for d in DESCRIPTIONS],
    )


class TravelTimeNumber(JaroliftEntity, NumberEntity):
    """Seconds the cover needs from one end position to the other. 0 = off."""

    def __init__(
        self,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
        description: NumberEntityDescription,
    ) -> None:
        super().__init__(entry, subentry, description.key)
        self.entity_description = description
        self._direction = description.key.removeprefix("travel_time_")

    @property
    def native_value(self) -> float:
        return self.hub.travel_time(self.cover_id, self._direction)

    async def async_set_native_value(self, value: float) -> None:
        await self.hub.async_set_travel_time(self.cover_id, self._direction, value)
        self.async_write_ha_state()

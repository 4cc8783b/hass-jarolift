"""Cover, buttons, sensors and travel time numbers."""

from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    mock_restore_cache,
)

from custom_components.jarolift.const import DOMAIN
from custom_components.jarolift.keeloq import BuildPacket

from .conftest import HUB_DATA, LSB, MSB, REMOTE

SERIAL = 0x106AA01
UP, STOP, DOWN = 0x8, 0x4, 0x2


def packet(group, button, counter, hold=False):
    return BuildPacket(group, SERIAL, button, counter, MSB, LSB, hold)


async def cover(hass, service, entity_id, **data):
    await hass.services.async_call(
        "cover", service, {"entity_id": entity_id, **data}, blocking=True
    )


async def set_travel(hass, name, up, down):
    for direction, value in (("up", up), ("down", down)):
        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": f"number.{name}_travel_time_{direction}", "value": value},
            blocking=True,
        )


async def test_open_close_stop_and_reverse(hass: HomeAssistant, entry, sent):
    state = hass.states.get("cover.wohnzimmer")
    assert state.state == "unknown"
    assert state.attributes["assumed_state"] is True
    assert "current_position" not in state.attributes

    await cover(hass, "close_cover", "cover.wohnzimmer")
    assert hass.states.get("cover.wohnzimmer").state == "closed"
    await cover(hass, "open_cover", "cover.kueche")  # reversed: sends down
    assert hass.states.get("cover.kueche").state == "open"
    await cover(hass, "stop_cover", "cover.wohnzimmer")
    assert hass.states.get("cover.wohnzimmer").state == "open"

    # Both covers share the serial and therefore the counter
    assert sent == [packet(1, DOWN, 0), packet(2, DOWN, 1), packet(1, STOP, 2)]
    assert hass.states.get("sensor.wohnzimmer_rolling_code_counter").state == "3"
    last = hass.states.get("sensor.kueche_last_command")
    assert last.attributes["command"] == "open"
    assert last.state != "unknown"


async def test_close_all_at_once(hass: HomeAssistant, entry, sent):
    await cover(hass, "close_cover", "all")
    assert sorted(sent) == sorted([packet(1, DOWN, 0), packet(2, UP, 1)]) or sorted(
        sent
    ) == sorted([packet(1, DOWN, 1), packet(2, UP, 0)])


async def test_time_based_position(hass: HomeAssistant, entry, sent, freezer):
    await set_travel(hass, "wohnzimmer", 20, 10)
    state = hass.states.get("cover.wohnzimmer")
    assert state.attributes["supported_features"] & 4  # SET_POSITION

    await cover(hass, "close_cover", "cover.wohnzimmer")
    assert hass.states.get("cover.wohnzimmer").state == "closing"
    freezer.tick(timedelta(seconds=11))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    state = hass.states.get("cover.wohnzimmer")
    assert state.state == "closed"
    assert state.attributes["current_position"] == 0

    # Open to 50 %: up for 10 s, then stop
    await cover(hass, "set_cover_position", "cover.wohnzimmer", position=50)
    assert hass.states.get("cover.wohnzimmer").state == "opening"
    freezer.tick(timedelta(seconds=5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get("cover.wohnzimmer").attributes["current_position"] == 25
    freezer.tick(timedelta(seconds=6))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    state = hass.states.get("cover.wohnzimmer")
    assert state.state == "open"
    assert state.attributes["current_position"] == 50
    assert sent[-2:] == [packet(1, UP, 1), packet(1, STOP, 2)]

    # Manual stop while closing: position is where it was
    await cover(hass, "close_cover", "cover.wohnzimmer")
    freezer.tick(timedelta(seconds=2))
    await cover(hass, "stop_cover", "cover.wohnzimmer")
    assert hass.states.get("cover.wohnzimmer").attributes["current_position"] == 30


async def test_set_position_unknown(hass: HomeAssistant, entry):
    await set_travel(hass, "wohnzimmer", 20, 20)
    with pytest.raises(ServiceValidationError):
        await cover(hass, "set_cover_position", "cover.wohnzimmer", position=50)


async def test_service_command_updates_cover(hass: HomeAssistant, entry):
    """jarolift.send_command from an automation is reflected in the cover state."""
    await hass.services.async_call(
        DOMAIN, "send_command", {"serial": "0x106aa01", "group": "0x0002", "button": "0x2"}, blocking=True
    )
    # Kueche is reversed: down code means open
    assert hass.states.get("cover.kueche").state == "open"
    assert hass.states.get("cover.wohnzimmer").state == "unknown"


async def test_buttons(hass: HomeAssistant, entry, sent):
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.wohnzimmer_intermediate_position"}, blocking=True
    )
    assert sent == [packet(1, STOP, 0, hold=True)]
    assert hass.states.get("sensor.wohnzimmer_last_command").attributes["command"] == "intermediate"

    await hass.services.async_call(
        "button", "press", {"entity_id": "button.wohnzimmer_learn"}, blocking=True
    )
    assert sent[1:] == [packet(1, 0xA, 1), packet(1, STOP, 2)]
    assert hass.states.get("sensor.wohnzimmer_last_command").attributes["command"] == "learn"


async def test_restore_state(hass: HomeAssistant, sent, subentries):
    entry = MockConfigEntry(domain=DOMAIN, unique_id=REMOTE, data=HUB_DATA, subentries_data=subentries)
    entry.add_to_hass(hass)
    mock_restore_cache(
        hass,
        [State("cover.wohnzimmer", "closed", {"current_position": 0}),
         State("sensor.wohnzimmer_last_command", dt_util.utcnow().isoformat(), {"command": "close"})],
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("cover.wohnzimmer").state == "closed"
    assert hass.states.get("sensor.wohnzimmer_last_command").attributes["command"] == "close"

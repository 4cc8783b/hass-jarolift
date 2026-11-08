"""Setup, services, counters, YAML import and devices."""

import asyncio

import pytest
import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er, issue_registry as ir
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.jarolift.const import DOMAIN
from custom_components.jarolift.keeloq import BuildPacket

from .conftest import HUB_DATA, LSB, MSB, REMOTE


def packet(serial, group, button, counter, hold=False):
    return BuildPacket(group, serial, button, counter, MSB, LSB, hold)


async def call(hass, service, data):
    await hass.services.async_call(DOMAIN, service, data, blocking=True)


async def test_concurrent_commands_unique_counters(hass: HomeAssistant, entry, sent):
    hub = entry.runtime_data
    await asyncio.gather(
        *[
            call(hass, "send_command", {"serial": "0x106aa01", "group": f"0x{g:04x}"})
            for g in (1, 2, 4, 8, 16, 32)
        ]
    )
    assert hub.counter(0x106AA01) == 6
    assert len(set(sent)) == 6


async def test_repeat_and_string_numbers(hass: HomeAssistant, entry, sent):
    await call(hass, "send_command", {"serial": "0x106aa01", "rep_count": "2", "rep_delay": "0"})
    assert len(sent) == 3 and len(set(sent)) == 1
    assert entry.runtime_data.counter(0x106AA01) == 1


async def test_wraparound(hass: HomeAssistant, entry, sent):
    hub = entry.runtime_data
    hub._data["counters"][hex(0x106AA01)] = 0xFFFF
    await call(hass, "send_command", {"serial": "0x106aa01"})
    assert hub.counter(0x106AA01) == 0
    assert sent == [packet(0x106AA01, 1, 2, 0xFFFF)]


async def test_learn_and_clear(hass: HomeAssistant, entry, sent):
    hub = entry.runtime_data
    await call(hass, "learn", {"serial": "0x106aa01"})
    assert hub.counter(0x106AA01) == 2 and len(sent) == 2
    await call(hass, "clear", {"serial": "0x106aa01"})
    assert hub.counter(0x106AA01) == 10 and len(sent) == 10


async def test_explicit_counter(hass: HomeAssistant, entry, sent):
    await call(hass, "send_command", {"serial": "0x106aa01", "counter": "0x0010"})
    assert entry.runtime_data.counter(0x106AA01) == 0
    assert sent == [packet(0x106AA01, 1, 2, 0x10)]


async def test_validation(hass: HomeAssistant, entry):
    with pytest.raises(vol.Invalid):
        await call(hass, "send_command", {"button": "0x2"})
    with pytest.raises(vol.Invalid):
        await call(hass, "send_command", {"serial": "xyz"})


async def test_raw(hass: HomeAssistant, entry, sent):
    await call(hass, "send_raw", {"packet": "b64:abc"})
    assert sent == ["b64:abc"]


async def test_service_without_entry(hass: HomeAssistant, sent):
    assert await async_setup_component(hass, DOMAIN, {})
    with pytest.raises(ServiceValidationError):
        await call(hass, "send_raw", {"packet": "b64:abc"})


async def test_counters_survive_reload(hass: HomeAssistant, entry):
    await call(hass, "send_command", {"serial": "0x106aa01"})
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.counter(0x106AA01) == 1


async def test_legacy_counter_files_imported(hass: HomeAssistant, sent, tmp_path):
    (tmp_path / "counter_0x106aa01.txt").write_text("1234")
    entry = MockConfigEntry(domain=DOMAIN, unique_id=REMOTE, data=HUB_DATA)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert entry.runtime_data.counter(0x106AA01) == 1234
    assert not (tmp_path / "counter_0x106aa01.txt").exists()
    assert (tmp_path / "counter_0x106aa01.txt.migrated").exists()
    await call(hass, "send_command", {"serial": "0x106aa01"})
    assert sent == [packet(0x106AA01, 1, 2, 1234)]


async def test_devices(hass: HomeAssistant, entry):
    dev_reg = dr.async_get(hass)
    hub = dev_reg.async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    assert hub is not None
    covers = [d for d in dr.async_entries_for_config_entry(dev_reg, entry.entry_id) if d.id != hub.id]
    assert sorted(d.name for d in covers) == ["Kueche", "Wohnzimmer"]
    assert all(d.via_device_id == hub.id for d in covers)

    ent_reg = er.async_get(hass)
    wohnzimmer = next(d for d in covers if d.name == "Wohnzimmer")
    entities = {e.entity_id for e in er.async_entries_for_device(ent_reg, wohnzimmer.id, include_disabled_entities=True)}
    assert entities == {
        "cover.wohnzimmer",
        "button.wohnzimmer_learn",
        "button.wohnzimmer_clear_learned_remote",
        "button.wohnzimmer_intermediate_position",
        "sensor.wohnzimmer_rolling_code_counter",
        "sensor.wohnzimmer_last_command",
        "number.wohnzimmer_travel_time_up",
        "number.wohnzimmer_travel_time_down",
    }
    # Clear is disabled by default
    assert hass.states.get("button.wohnzimmer_clear_learned_remote") is None


async def test_yaml_import(hass: HomeAssistant, sent, tmp_path):
    """YAML hub + covers are imported; the old cover entity keeps its entity_id."""
    ent_reg = er.async_get(hass)
    old = ent_reg.async_get_or_create(
        "cover", DOMAIN, "jarolift_0x116ea01", suggested_object_id="alter_name"
    )
    (tmp_path / "counter_0x116ea01.txt").write_text("42")

    config = {
        DOMAIN: {"remote_entity_id": REMOTE, "MSB": "0x12345678", "LSB": "0x87654321"},
        "cover": [
            {
                "platform": DOMAIN,
                "covers": [
                    {"name": "Wohnzimmer", "group": "0x0001", "serial": "0x116ea01"},
                    {"name": "Kueche", "group": "0x0002", "serial": "0x116ea01", "reverse": True},
                    {"name": "Kaputt", "group": "0x0001", "serial": "nope"},
                ],
            }
        ],
    }
    assert await async_setup_component(hass, DOMAIN, config)
    assert await async_setup_component(hass, "cover", config)
    await hass.async_block_till_done()

    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.data["MSB"] == 0x12345678
    assert sorted(s.title for s in entry.subentries.values()) == ["Kueche", "Wohnzimmer"]

    migrated = ent_reg.async_get(old.entity_id)
    assert migrated.config_entry_id == entry.entry_id
    assert hass.states.get(old.entity_id) is not None
    assert hass.states.get("cover.kueche") is not None
    assert entry.runtime_data.counter(0x116EA01) == 42

    assert ir.async_get(hass).async_get_issue(DOMAIN, "deprecated_yaml")

    # A second start with the YAML still present does not import again
    await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "import"}, data={**HUB_DATA, "covers": []}
    )
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_transmissions_do_not_interleave(hass: HomeAssistant, entry, sent):
    """Repeats of one command are sent back to back, not mixed with another cover."""
    await asyncio.gather(
        call(hass, "send_command", {"serial": "0x106aa01", "group": "0x0001", "rep_count": 2, "rep_delay": 0}),
        call(hass, "send_command", {"serial": "0x106aa01", "group": "0x0002", "rep_count": 2, "rep_delay": 0}),
    )
    assert len(sent) == 6
    assert len(set(sent[:3])) == 1 and len(set(sent[3:])) == 1 and sent[0] != sent[3]

import asyncio
import os
from pathlib import Path

import pytest
from homeassistant.core import ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.setup import async_setup_component
import voluptuous as vol

from custom_components.jarolift import BuildPacket

REF = Path(__file__).parent / "reference_packets.txt"
CONF = {
    "jarolift": {
        "remote_entity_id": "remote.rf",
        "MSB": "0x12345678",
        "LSB": "0x87654321",
    }
}


def test_packets_unchanged():
    for line in REF.read_text().splitlines():
        c, b, h, pkt = line.split(" ")
        assert BuildPacket(0x0001, 0x106aa01, int(b), int(c), 0x12345678, 0x87654321, h == "True") == pkt


def test_counter_is_masked():
    assert BuildPacket(1, 0x106aa01, 2, 0x10005, 0x12345678, 0x87654321, False) == \
        BuildPacket(1, 0x106aa01, 2, 0x5, 0x12345678, 0x87654321, False)


@pytest.fixture
async def setup(hass, tmp_path):
    hass.config.config_dir = str(tmp_path)
    sent = []

    async def fake_send(call: ServiceCall):
        await asyncio.sleep(0.01)
        sent.append(call.data["command"][0])

    assert await async_setup_component(hass, "jarolift", CONF)
    await hass.async_block_till_done()
    hass.services.async_register("remote", "send_command", fake_send)
    return tmp_path, sent


def counter(path, serial="0x106aa01"):
    return int((path / f"counter_{serial}.txt").read_text())


async def test_concurrent_commands_unique_counters(hass, setup):
    path, sent = setup
    await asyncio.gather(*[
        hass.services.async_call("jarolift", "send_command",
                                 {"serial": "0x106aa01", "group": f"0x{g:04x}", "button": "0x2"},
                                 blocking=True)
        for g in (1, 2, 4, 8, 16, 32)
    ])
    assert counter(path) == 6
    assert len(set(sent)) == 6
    assert not list(path.glob("*.tmp"))


async def test_repeat_and_string_numbers(hass, setup):
    path, sent = setup
    await hass.services.async_call("jarolift", "send_command",
                                   {"serial": "0x106aa01", "rep_count": "2", "rep_delay": "0"},
                                   blocking=True)
    assert len(sent) == 3 and len(set(sent)) == 1
    assert counter(path) == 1


async def test_wraparound(hass, setup):
    path, sent = setup
    (path / "counter_0x106aa01.txt").write_text(str(0xFFFF))
    await hass.services.async_call("jarolift", "send_command", {"serial": "0x106aa01"}, blocking=True)
    assert counter(path) == 0
    assert sent[0] == BuildPacket(1, 0x106aa01, 2, 0xFFFF, 0x12345678, 0x87654321, False)


async def test_learn_and_clear_counters(hass, setup):
    path, sent = setup
    await hass.services.async_call("jarolift", "learn", {"serial": "0x106aa01"}, blocking=True)
    assert counter(path) == 2 and len(sent) == 2
    await hass.services.async_call("jarolift", "clear", {"serial": "0x106aa01"}, blocking=True)
    assert counter(path) == 10 and len(sent) == 10


async def test_explicit_counter_does_not_touch_file(hass, setup):
    path, sent = setup
    await hass.services.async_call("jarolift", "send_command",
                                   {"serial": "0x106aa01", "counter": "0x0010"}, blocking=True)
    assert not (path / "counter_0x106aa01.txt").exists()
    assert sent[0] == BuildPacket(1, 0x106aa01, 2, 0x10, 0x12345678, 0x87654321, False)


async def test_validation(hass, setup):
    with pytest.raises(vol.Invalid):
        await hass.services.async_call("jarolift", "send_command", {"button": "0x2"}, blocking=True)
    with pytest.raises(vol.Invalid):
        await hass.services.async_call("jarolift", "send_command", {"serial": "xyz"}, blocking=True)


async def test_corrupt_counter_file(hass, setup):
    path, sent = setup
    (path / "counter_0x106aa01.txt").write_text("")
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call("jarolift", "send_command", {"serial": "0x106aa01"}, blocking=True)
    assert sent == []


async def test_raw(hass, setup):
    _, sent = setup
    await hass.services.async_call("jarolift", "send_raw", {"packet": "b64:abc"}, blocking=True)
    assert sent == ["b64:abc"]


async def test_cover(hass, setup):
    path, sent = setup
    assert await async_setup_component(hass, "cover", {"cover": [{
        "platform": "jarolift",
        "covers": [
            {"name": "Wohnzimmer", "group": "0x0001", "serial": "0x106aa01"},
            {"name": "Kueche", "group": "0x0002", "serial": "0x106aa02", "reverse": True},
        ],
    }]})
    await hass.async_block_till_done()
    st = hass.states.get("cover.wohnzimmer")
    assert st.attributes.get("assumed_state") is True

    await hass.services.async_call("cover", "close_cover", {"entity_id": "all"}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get("cover.wohnzimmer").state == "closed"
    assert hass.states.get("cover.kueche").state == "closed"
    assert counter(path) == 1 and counter(path, "0x106aa02") == 1
    assert set(sent) == {
        BuildPacket(1, 0x106aa01, 2, 0, 0x12345678, 0x87654321, False),  # down
        BuildPacket(2, 0x106aa02, 8, 0, 0x12345678, 0x87654321, False),  # reversed: up
    }

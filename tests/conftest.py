"""Fixtures for the Jarolift tests."""

import asyncio

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.jarolift.const import DOMAIN

pytest_plugins = ["pytest_homeassistant_custom_component"]

MSB = 0x12345678
LSB = 0x87654321
REMOTE = "remote.rf"
HUB_DATA = {"remote_entity_id": REMOTE, "MSB": MSB, "LSB": LSB, "delay": 0}


def cover_subentry(title, serial, group, reverse=False, rep_count=0):
    return ConfigSubentryData(
        data={
            "serial": serial,
            "group": group,
            "repeat_count": rep_count,
            "repeat_delay": 0,
            "reverse": reverse,
        },
        subentry_type="cover",
        title=title,
        unique_id=f"0x{serial:08x}_0x{group:04x}",
    )


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
async def sent(hass: HomeAssistant, tmp_path):
    """Fake remote: collects the packets sent through remote.send_command."""
    hass.config.config_dir = str(tmp_path)
    packets: list[str] = []
    assert await async_setup_component(hass, "remote", {})

    async def fake_send(call: ServiceCall):
        await asyncio.sleep(0)  # yield; real sleeps hang with a frozen clock
        packets.append(call.data["command"][0])

    hass.services.async_register("remote", "send_command", fake_send)
    return packets


@pytest.fixture
def subentries():
    return [
        cover_subentry("Wohnzimmer", 0x106AA01, 0x0001),
        cover_subentry("Kueche", 0x106AA01, 0x0002, reverse=True),
    ]


@pytest.fixture
async def entry(hass: HomeAssistant, sent, subentries):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Jarolift",
        unique_id=REMOTE,
        data=HUB_DATA,
        subentries_data=subentries,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry

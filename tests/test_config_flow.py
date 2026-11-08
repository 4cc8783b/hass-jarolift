"""Config flow and cover subentry flow."""

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.jarolift.const import DOMAIN

from .conftest import REMOTE

HUB_INPUT = {"remote_entity_id": REMOTE, "MSB": "0x12345678", "LSB": "0x87654321", "delay": 0.5}
COVER_INPUT = {
    "name": "Bad",
    "serial": "0x106aa03",
    "group": "0x0001",
    "repeat_count": 2,
    "repeat_delay": 0.2,
    "reverse": False,
}


async def test_user_flow(hass: HomeAssistant, sent):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {**HUB_INPUT, "MSB": "zz"})
    assert result["errors"] == {"MSB": "invalid_key"}

    result = await hass.config_entries.flow.async_configure(result["flow_id"], HUB_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"remote_entity_id": REMOTE, "MSB": 0x12345678, "LSB": 0x87654321, "delay": 0.5}

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], HUB_INPUT)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure_hub(hass: HomeAssistant, entry):
    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**HUB_INPUT, "delay": 1}
    )
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    assert entry.data["delay"] == 1
    assert entry.runtime_data._delay == 1  # reloaded


async def add_cover(hass, entry, cover_input, learn=False):
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "cover"), context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], cover_input)
    if result["type"] is FlowResultType.FORM and result["step_id"] == "learn":
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"], {"learn_now": learn}
        )
    await hass.async_block_till_done()
    return result


async def test_add_cover_and_learn(hass: HomeAssistant, entry, sent):
    result = await add_cover(hass, entry, COVER_INPUT, learn=True)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["serial"] == 0x106AA03
    assert len(sent) == 2  # learn sequence
    assert hass.states.get("cover.bad") is not None


async def test_add_cover_errors(hass: HomeAssistant, entry):
    result = await add_cover(hass, entry, {**COVER_INPUT, "serial": "0x1fffffff"})
    assert result["errors"] == {"serial": "invalid_serial"}
    result = await add_cover(hass, entry, {**COVER_INPUT, "serial": "0x106aa01"})
    assert result["errors"] == {"base": "already_configured"}


async def test_reconfigure_cover(hass: HomeAssistant, entry):
    sub = next(s for s in entry.subentries.values() if s.title == "Wohnzimmer")
    result = await entry.start_subentry_reconfigure_flow(hass, sub.subentry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {**COVER_INPUT, "name": "Wohnzimmer", "serial": "0x106aa01", "reverse": True},
    )
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    assert entry.subentries[sub.subentry_id].data["reverse"] is True
    assert entry.subentries[sub.subentry_id].data["repeat_count"] == 2
    assert hass.states.get("cover.wohnzimmer") is not None


async def test_remove_cover(hass: HomeAssistant, entry):
    sub = next(s for s in entry.subentries.values() if s.title == "Wohnzimmer")
    hass.config_entries.async_remove_subentry(entry, sub.subentry_id)
    await hass.async_block_till_done()
    assert hass.states.get("cover.wohnzimmer") is None
    assert hass.states.get("cover.kueche") is not None

"""
Support a 'Jarolift' remote as a separate remote.
Basically a proxy adding Keeloq encryption to commands sent via another remote then.
"""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_DELAY,
    CONF_LEGACY_UNIQUE_ID,
    CONF_LSB,
    CONF_MSB,
    CONF_REMOTE_ENTITY_ID,
    COUNTER_MASK,
    DEFAULT_REP_DELAY,
    DOMAIN,
    MAX_GROUP,
    MAX_KEY,
    MAX_SERIAL,
    YAML_COVERS_SCHEMA,
    hex_range,
)
from .hub import JaroliftHub
from .keeloq import BuildPacket  # noqa: F401  (kept for backwards compatibility)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BUTTON, Platform.COVER, Platform.NUMBER, Platform.SENSOR]

type JaroliftConfigEntry = ConfigEntry[JaroliftHub]

# Legacy YAML configuration, imported into a config entry on startup
CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_REMOTE_ENTITY_ID): cv.entity_id,
                vol.Required(CONF_MSB): hex_range(MAX_KEY),
                vol.Required(CONF_LSB): hex_range(MAX_KEY),
                vol.Optional(CONF_DELAY, default=0): vol.All(
                    vol.Coerce(float), vol.Range(min=0)
                ),
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)

_ENTRY = vol.Optional("config_entry_id")
_GROUP = hex_range(MAX_GROUP)
_SERIAL = hex_range(MAX_SERIAL)
_COUNTER = hex_range(COUNTER_MASK)

SEND_RAW_SCHEMA = vol.Schema({_ENTRY: cv.string, vol.Required("packet"): cv.string})

SEND_COMMAND_SCHEMA = vol.Schema(
    {
        _ENTRY: cv.string,
        vol.Required("serial"): _SERIAL,
        vol.Optional("group", default=0x0001): _GROUP,
        vol.Optional("button", default=0x2): hex_range(0xF),
        vol.Optional("rep_count", default=0): vol.All(
            vol.Coerce(int), vol.Range(min=0)
        ),
        vol.Optional("rep_delay", default=DEFAULT_REP_DELAY): vol.All(
            vol.Coerce(float), vol.Range(min=0)
        ),
        vol.Optional("hold", default=False): cv.boolean,
        vol.Optional("counter", default=0): _COUNTER,
    }
)

LEARN_CLEAR_SCHEMA = vol.Schema(
    {
        _ENTRY: cv.string,
        vol.Required("serial"): _SERIAL,
        vol.Optional("group", default=0x0001): _GROUP,
        vol.Optional("counter", default=0): _COUNTER,
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the services and import a legacy YAML configuration."""
    _async_register_services(hass)

    if DOMAIN in config:
        covers = _yaml_covers(config)
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": SOURCE_IMPORT},
                data={**config[DOMAIN], "covers": covers},
            )
        )
        ir.async_create_issue(
            hass,
            DOMAIN,
            "deprecated_yaml",
            is_fixable=False,
            is_persistent=False,
            issue_domain=DOMAIN,
            severity=ir.IssueSeverity.WARNING,
            translation_key="deprecated_yaml",
        )
    return True


def _yaml_covers(config: ConfigType) -> list[dict]:
    """Collect the covers of all `cover: - platform: jarolift` blocks."""
    covers: list[dict] = []
    for key, value in config.items():
        # "cover", or "cover 2" etc. for split configurations
        if key.split(" ")[0] != Platform.COVER:
            continue
        blocks = value if isinstance(value, list) else [value]
        for platform_config in blocks:
            if not isinstance(platform_config, dict):
                continue
            if platform_config.get("platform") != DOMAIN:
                continue
            for cover in platform_config.get("covers", []):
                try:
                    covers.extend(YAML_COVERS_SCHEMA([cover]))
                except vol.Invalid as err:
                    _LOGGER.error("Cannot import Jarolift cover %s: %s", cover, err)
    return covers


async def async_setup_entry(hass: HomeAssistant, entry: JaroliftConfigEntry) -> bool:
    hub = JaroliftHub(
        hass,
        entry.entry_id,
        entry.data[CONF_REMOTE_ENTITY_ID],
        entry.data[CONF_MSB],
        entry.data[CONF_LSB],
        entry.data.get(CONF_DELAY, 0),
    )
    await hub.async_load()
    await hub.async_prune_travel_times(set(entry.subentries))
    entry.runtime_data = hub

    _async_migrate_legacy_entities(hass, entry)
    _async_register_hub_device(hass, entry)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: JaroliftConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: JaroliftConfigEntry) -> None:
    """Covers were added, changed or removed: reload."""
    hass.config_entries.async_schedule_reload(entry.entry_id)


@callback
def _async_migrate_legacy_entities(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Hand the YAML cover entities over to the imported covers.

    Keeps entity_id, name customizations and history of the existing covers.
    """
    ent_reg = er.async_get(hass)
    for subentry in entry.subentries.values():
        legacy_uid = subentry.data.get(CONF_LEGACY_UNIQUE_ID)
        if not legacy_uid:
            continue
        entity_id = ent_reg.async_get_entity_id(Platform.COVER, DOMAIN, legacy_uid)
        if entity_id is None:
            continue
        if ent_reg.async_get_entity_id(Platform.COVER, DOMAIN, subentry.subentry_id):
            continue
        _LOGGER.info("Migrating %s to the imported Jarolift cover", entity_id)
        ent_reg.async_update_entity(entity_id, new_unique_id=subentry.subentry_id)


@callback
def _async_register_hub_device(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Device for the virtual Jarolift remote, linked to the sending remote."""
    dev_reg = dr.async_get(hass)
    via_device = None
    remote = er.async_get(hass).async_get(entry.data[CONF_REMOTE_ENTITY_ID])
    if remote and remote.device_id:
        remote_device = dev_reg.async_get(remote.device_id)
        if remote_device and remote_device.identifiers:
            via_device = next(iter(remote_device.identifiers))
    dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="Jarolift",
        model="KeeLoq transmitter (virtual)",
        via_device=via_device,
    )


def _hub_for_call(hass: HomeAssistant, call: ServiceCall) -> JaroliftHub:
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if entry_id := call.data.get("config_entry_id"):
        entries = [entry for entry in entries if entry.entry_id == entry_id]
    if len(entries) != 1:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="no_hub" if not entries else "multiple_hubs",
        )
    return entries[0].runtime_data


@callback
def _async_register_services(hass: HomeAssistant) -> None:
    async def handle_send_raw(call: ServiceCall) -> None:
        await _hub_for_call(hass, call).async_send_raw(call.data["packet"])

    async def handle_send_command(call: ServiceCall) -> None:
        await _hub_for_call(hass, call).async_send_command(
            call.data["serial"],
            call.data["group"],
            call.data["button"],
            rep_count=call.data["rep_count"],
            rep_delay=call.data["rep_delay"],
            hold=call.data["hold"],
            counter=call.data["counter"],
        )

    async def handle_learn(call: ServiceCall) -> None:
        await _hub_for_call(hass, call).async_learn(
            call.data["serial"], call.data["group"], call.data["counter"]
        )

    async def handle_clear(call: ServiceCall) -> None:
        await _hub_for_call(hass, call).async_clear(
            call.data["serial"], call.data["group"], call.data["counter"]
        )

    hass.services.async_register(DOMAIN, "send_raw", handle_send_raw, SEND_RAW_SCHEMA)
    hass.services.async_register(
        DOMAIN, "send_command", handle_send_command, SEND_COMMAND_SCHEMA
    )
    hass.services.async_register(DOMAIN, "learn", handle_learn, LEARN_CLEAR_SCHEMA)
    hass.services.async_register(DOMAIN, "clear", handle_clear, LEARN_CLEAR_SCHEMA)

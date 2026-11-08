"""Config flow for Jarolift: the hub (remote + key) and covers as subentries."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryData,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_DELAY,
    CONF_GROUP,
    CONF_LEGACY_UNIQUE_ID,
    CONF_LSB,
    CONF_MSB,
    CONF_REMOTE_ENTITY_ID,
    CONF_REP_COUNT,
    CONF_REP_DELAY,
    CONF_REVERSE,
    CONF_SERIAL,
    DEFAULT_REP_COUNT,
    DEFAULT_REP_DELAY,
    DOMAIN,
    MAX_GROUP,
    MAX_KEY,
    MAX_SERIAL,
    SUBENTRY_COVER,
    cover_uid,
    hex_range,
)

_LOGGER = logging.getLogger(__name__)

TITLE = "Jarolift"
CONF_LEARN_NOW = "learn_now"

_SECRET = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))

HUB_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_REMOTE_ENTITY_ID): EntitySelector(
            EntitySelectorConfig(domain="remote")
        ),
        vol.Required(CONF_MSB): _SECRET,
        vol.Required(CONF_LSB): _SECRET,
        vol.Required(CONF_DELAY, default=0): NumberSelector(
            NumberSelectorConfig(
                min=0, max=10, step=0.1, unit_of_measurement="s",
                mode=NumberSelectorMode.BOX,
            )
        ),
    }
)

COVER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): TextSelector(),
        vol.Required(CONF_SERIAL): TextSelector(),
        vol.Required(CONF_GROUP, default="0x0001"): TextSelector(),
        vol.Required(CONF_REP_COUNT, default=DEFAULT_REP_COUNT): NumberSelector(
            NumberSelectorConfig(min=0, max=20, step=1, mode=NumberSelectorMode.BOX)
        ),
        vol.Required(CONF_REP_DELAY, default=DEFAULT_REP_DELAY): NumberSelector(
            NumberSelectorConfig(
                min=0, max=5, step=0.1, unit_of_measurement="s",
                mode=NumberSelectorMode.BOX,
            )
        ),
        vol.Required(CONF_REVERSE, default=False): BooleanSelector(),
    }
)


def _validate_hub(user_input: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    errors: dict[str, str] = {}
    data = {
        CONF_REMOTE_ENTITY_ID: user_input[CONF_REMOTE_ENTITY_ID],
        CONF_DELAY: float(user_input.get(CONF_DELAY, 0)),
    }
    for key in (CONF_MSB, CONF_LSB):
        try:
            data[key] = hex_range(MAX_KEY)(user_input[key])
        except vol.Invalid:
            errors[key] = "invalid_key"
    return data, errors


def _hub_suggested(entry: ConfigEntry) -> dict[str, Any]:
    return {
        CONF_REMOTE_ENTITY_ID: entry.data[CONF_REMOTE_ENTITY_ID],
        CONF_MSB: f"0x{entry.data[CONF_MSB]:08x}",
        CONF_LSB: f"0x{entry.data[CONF_LSB]:08x}",
        CONF_DELAY: entry.data.get(CONF_DELAY, 0),
    }


def _cover_data(cover: dict[str, Any]) -> dict[str, Any]:
    """Validate cover input (form or YAML). Raises vol.Invalid with the key as path."""
    try:
        serial = hex_range(MAX_SERIAL)(cover[CONF_SERIAL])
    except vol.Invalid as err:
        raise vol.Invalid("invalid_serial", path=[CONF_SERIAL]) from err
    try:
        group = hex_range(MAX_GROUP)(cover[CONF_GROUP])
    except vol.Invalid as err:
        raise vol.Invalid("invalid_group", path=[CONF_GROUP]) from err
    return {
        CONF_SERIAL: serial,
        CONF_GROUP: group,
        CONF_REP_COUNT: int(cover.get(CONF_REP_COUNT, DEFAULT_REP_COUNT)),
        CONF_REP_DELAY: float(cover.get(CONF_REP_DELAY, DEFAULT_REP_DELAY)),
        CONF_REVERSE: bool(cover.get(CONF_REVERSE, False)),
    }


class JaroliftConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up the Jarolift hub."""

    VERSION = 1

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUBENTRY_COVER: CoverSubentryFlow}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data, errors = _validate_hub(user_input)
            if not errors:
                await self.async_set_unique_id(data[CONF_REMOTE_ENTITY_ID])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=TITLE, data=data)
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(HUB_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data, errors = _validate_hub(user_input)
            remote = data[CONF_REMOTE_ENTITY_ID]
            if any(
                other.unique_id == remote and other.entry_id != entry.entry_id
                for other in self._async_current_entries(include_ignore=False)
            ):
                errors[CONF_REMOTE_ENTITY_ID] = "already_configured"
            if not errors:
                # The update listener reloads the entry
                return self.async_update_and_abort(entry, unique_id=remote, data=data)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                HUB_SCHEMA, user_input or _hub_suggested(entry)
            ),
            errors=errors,
        )

    async def async_step_import(self, import_data: dict[str, Any]) -> ConfigFlowResult:
        """Import `jarolift:` and `cover: - platform: jarolift` from YAML (once)."""
        await self.async_set_unique_id(import_data[CONF_REMOTE_ENTITY_ID])
        self._abort_if_unique_id_configured()

        subentries: list[ConfigSubentryData] = []
        seen: set[str] = set()
        legacy_seen: set[str] = set()
        for cover in import_data.get("covers", []):
            try:
                data = _cover_data(cover)
            except vol.Invalid as err:
                _LOGGER.error("Not importing Jarolift cover %s: %s", cover["name"], err)
                continue
            uid = cover_uid(data[CONF_SERIAL], data[CONF_GROUP])
            if uid in seen:
                _LOGGER.error("Not importing duplicate Jarolift cover %s", cover["name"])
                continue
            seen.add(uid)
            # Version 1.x used "jarolift_<serial as written>" and only created
            # the first cover of a serial
            legacy_uid = "jarolift_" + cover[CONF_SERIAL]
            if legacy_uid not in legacy_seen:
                legacy_seen.add(legacy_uid)
                data[CONF_LEGACY_UNIQUE_ID] = legacy_uid
            subentries.append(
                ConfigSubentryData(
                    data=data,
                    subentry_type=SUBENTRY_COVER,
                    title=cover["name"],
                    unique_id=uid,
                )
            )

        return self.async_create_entry(
            title=TITLE,
            data={
                CONF_REMOTE_ENTITY_ID: import_data[CONF_REMOTE_ENTITY_ID],
                CONF_MSB: import_data[CONF_MSB],
                CONF_LSB: import_data[CONF_LSB],
                CONF_DELAY: import_data.get(CONF_DELAY, 0),
            },
            subentries=subentries,
        )


class CoverSubentryFlow(ConfigSubentryFlow):
    """Add or change a Jarolift cover."""

    def __init__(self) -> None:
        self._title: str = ""
        self._data: dict[str, Any] = {}

    def _validate(
        self, user_input: dict[str, Any], exclude_subentry_id: str | None
    ) -> dict[str, str]:
        try:
            self._data = _cover_data(user_input)
        except vol.Invalid as err:
            return {err.path[0]: err.msg}
        self._title = user_input[CONF_NAME]
        uid = cover_uid(self._data[CONF_SERIAL], self._data[CONF_GROUP])
        for subentry in self._get_entry().subentries.values():
            if subentry.unique_id == uid and subentry.subentry_id != exclude_subentry_id:
                return {"base": "already_configured"}
        return {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = self._validate(user_input, None)
            if not errors:
                return await self.async_step_learn()
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(COVER_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_learn(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Optionally teach the new cover right away."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input.get(CONF_LEARN_NOW):
                entry = self._get_entry()
                try:
                    if entry.state is not ConfigEntryState.LOADED:
                        raise HomeAssistantError("hub not loaded")
                    await entry.runtime_data.async_learn(
                        self._data[CONF_SERIAL], self._data[CONF_GROUP]
                    )
                except HomeAssistantError as err:
                    _LOGGER.error("Learning failed: %s", err)
                    errors["base"] = "send_failed"
            if not errors:
                return self.async_create_entry(
                    title=self._title,
                    data=self._data,
                    unique_id=cover_uid(self._data[CONF_SERIAL], self._data[CONF_GROUP]),
                )
        return self.async_show_form(
            step_id="learn",
            data_schema=vol.Schema(
                {vol.Required(CONF_LEARN_NOW, default=False): BooleanSelector()}
            ),
            description_placeholders={"name": self._title},
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        subentry = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = self._validate(user_input, subentry.subentry_id)
            if not errors:
                # The update listener of the entry reloads it
                return self.async_update_and_abort(
                    self._get_entry(),
                    subentry,
                    title=self._title,
                    data=self._data,
                    unique_id=cover_uid(self._data[CONF_SERIAL], self._data[CONF_GROUP]),
                )
        data = subentry.data
        suggested = user_input or {
            CONF_NAME: subentry.title,
            CONF_SERIAL: f"0x{data[CONF_SERIAL]:x}",
            CONF_GROUP: f"0x{data[CONF_GROUP]:04x}",
            CONF_REP_COUNT: data[CONF_REP_COUNT],
            CONF_REP_DELAY: data[CONF_REP_DELAY],
            CONF_REVERSE: data[CONF_REVERSE],
        }
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(COVER_SCHEMA, suggested),
            errors=errors,
        )

"""Constants and shared validators for the Jarolift integration."""

import voluptuous as vol

import homeassistant.helpers.config_validation as cv

DOMAIN = "jarolift"

SUBENTRY_COVER = "cover"

# Hub (config entry) keys
CONF_REMOTE_ENTITY_ID = "remote_entity_id"
CONF_MSB = "MSB"
CONF_LSB = "LSB"
CONF_DELAY = "delay"

# Cover (subentry) keys
CONF_GROUP = "group"
CONF_SERIAL = "serial"
CONF_REP_COUNT = "repeat_count"
CONF_REP_DELAY = "repeat_delay"
CONF_REVERSE = "reverse"
CONF_LEGACY_UNIQUE_ID = "legacy_unique_id"

DEFAULT_REP_COUNT = 0
DEFAULT_REP_DELAY = 0.2

# Button codes
BUTTON_DOWN = 0x2
BUTTON_STOP = 0x4
BUTTON_UP = 0x8
BUTTON_LEARN = 0xA

# The KeeLoq sync counter is 16 bits wide
COUNTER_MASK = 0xFFFF
MAX_GROUP = 0xFFFF
# Serial is placed at bit 32 of the packet, the button at bit 60 -> 28 bits max
MAX_SERIAL = 0x0FFFFFFF
MAX_KEY = 0xFFFFFFFF

# Travel directions
UP = "up"
DOWN = "down"

# Dispatcher signals, formatted with the config entry id
SIGNAL_COUNTER = "jarolift_counter_{}"
SIGNAL_COMMAND = "jarolift_command_{}"
SIGNAL_TRAVEL = "jarolift_travel_{}"

# Values reported by the "last command" sensor
COMMAND_OPEN = "open"
COMMAND_CLOSE = "close"
COMMAND_STOP = "stop"
COMMAND_INTERMEDIATE = "intermediate"
COMMAND_LEARN = "learn"
COMMAND_CLEAR = "clear"


def hex_value(value):
    """Accept hex strings like '0x0001' (or plain ints) and return an int."""
    if isinstance(value, bool):
        raise vol.Invalid(f"invalid hex value: {value!r}")
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip(), 16)
    except ValueError as err:
        raise vol.Invalid(f"invalid hex value: {value!r}") from err


def hex_range(max_value):
    """Validator for a hex value between 0 and max_value."""
    return vol.All(hex_value, vol.Range(min=0, max=max_value))


def cover_uid(serial: int, group: int) -> str:
    """Unique id of a cover: a serial can be shared by several groups."""
    return f"0x{serial:08x}_0x{group:04x}"


# Legacy YAML: cover platform entries (`cover: - platform: jarolift`)
YAML_COVERS_SCHEMA = vol.All(
    cv.ensure_list,
    [
        vol.Schema(
            {
                vol.Required("name"): cv.string,
                vol.Required(CONF_GROUP): cv.string,
                vol.Required(CONF_SERIAL): cv.string,
                vol.Optional(CONF_REP_COUNT, default=DEFAULT_REP_COUNT): cv.positive_int,
                vol.Optional(
                    CONF_REP_DELAY, default=DEFAULT_REP_DELAY
                ): cv.positive_float,
                vol.Optional(CONF_REVERSE, default=False): cv.boolean,
            }
        )
    ],
)

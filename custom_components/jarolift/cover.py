"""
Support for Jarolift cover
"""
import logging

import voluptuous as vol

from homeassistant.components.cover import (
    SUPPORT_OPEN,
    SUPPORT_CLOSE,
    SUPPORT_STOP,
    SUPPORT_SET_TILT_POSITION,
    PLATFORM_SCHEMA,
    CoverDeviceClass,
    CoverEntity,
)

from homeassistant.const import CONF_NAME
import homeassistant.helpers.config_validation as cv

CONF_COVERS = "covers"
CONF_GROUP = "group"
CONF_SERIAL = "serial"

_COVERS_SCHEMA = vol.All(
    cv.ensure_list,
    [
        vol.Schema(
            {
                CONF_NAME: cv.string,
                CONF_GROUP: cv.string,
                CONF_SERIAL: cv.string,
            }
        )
    ],
)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_COVERS): _COVERS_SCHEMA,
    }
)

DEPENDENCIES = ["jarolift"]

_LOGGER = logging.getLogger(__name__)


def setup_platform(hass, config, add_devices, discovery_info=None):
    """Set up the Jarolift covers."""
    covers = []
    covers_conf = config.get(CONF_COVERS)

    for cover in covers_conf:
        covers.append(
            JaroliftCover(cover[CONF_NAME], cover[CONF_GROUP], cover[CONF_SERIAL], hass)
        )
    add_devices(covers)


class JaroliftCover(CoverEntity):
    """Representation a jarolift Cover."""

    def __init__(self, name, group, serial, hass):
        """Initialize the jarolift device."""
        self._name = name
        self._group = group
        self._serial = serial
        self._hass = hass
        supported_features = 0
        supported_features |= SUPPORT_SET_TILT_POSITION
        supported_features |= SUPPORT_OPEN
        supported_features |= SUPPORT_CLOSE
        supported_features |= SUPPORT_STOP
        self._attr_supported_features = supported_features
        self._attr_device_class = CoverDeviceClass.BLIND

    @property
    def serial(self):
        """Return the serial of this cover."""
        return self._serial

    @property
    def name(self):
        """Return the name of the cover if any."""
        return self._name

    @property
    def group(self):
        """Return the name of the group if any."""
        return self._group

    @property
    def should_poll(self):
        """No polling available in Jarolift cover."""
        return False

    @property
    def is_closed(self):
        """Return true if cover is closed."""
        return None

    async def async_close_cover(self, **kwargs):
        """Close the cover."""
        await self._hass.services.async_call(
            "jarolift",
            "send_command",
            {"group": self._group, "serial": self._serial, "button": "0x2"},
        )

    async def async_open_cover(self, **kwargs):
        """Open the cover."""
        await self._hass.services.async_call(
            "jarolift",
            "send_command",
            {"group": self._group, "serial": self._serial, "button": "0x8"},
        )

    async def async_stop_cover(self, **kwargs):
        """Stop the cover."""
        await self._hass.services.async_call(
            "jarolift",
            "send_command",
            {"group": self._group, "serial": self._serial, "button": "0x4"},
        )

    async def async_set_cover_tilt_position(self, **kwargs):
        """Drive the cover to tilt position"""
        await self._hass.services.async_call(
            "jarolift",
            "send_command",
            {
                "group": self._group,
                "serial": self._serial,
                "button": "0x4",
                "hold": True,
            },
        )

"""
Support a 'Jarolift' remote as a separate remote.
Basically a proxy adding Keeloq encryption to commands sent via another remote then.
"""
import logging
import base64
import binascii
from time import sleep
import os
import threading

import voluptuous as vol

from homeassistant.exceptions import HomeAssistantError
import homeassistant.helpers.config_validation as cv

DOMAIN = "jarolift"
_LOGGER = logging.getLogger(__name__)
mutex = threading.Lock()

# The KeeLoq sync counter is 16 bits wide
COUNTER_MASK = 0xFFFF


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


def _hex_range(max_value):
    return vol.All(hex_value, vol.Range(min=0, max=max_value))


CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required("remote_entity_id"): cv.entity_id,
                vol.Required("MSB"): _hex_range(0xFFFFFFFF),
                vol.Required("LSB"): _hex_range(0xFFFFFFFF),
                vol.Optional("delay", default=0): vol.All(
                    vol.Coerce(float), vol.Range(min=0)
                ),
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)

_GROUP = _hex_range(0xFFFF)
# Serial is placed at bit 32 of the packet, the button at bit 60 -> 28 bits max
_SERIAL = _hex_range(0x0FFFFFFF)
_COUNTER = _hex_range(COUNTER_MASK)

SEND_RAW_SCHEMA = vol.Schema({vol.Required("packet"): cv.string})

SEND_COMMAND_SCHEMA = vol.Schema(
    {
        vol.Required("serial"): _SERIAL,
        vol.Optional("group", default=0x0001): _GROUP,
        vol.Optional("button", default=0x2): _hex_range(0xF),
        vol.Optional("rep_count", default=0): vol.All(
            vol.Coerce(int), vol.Range(min=0)
        ),
        vol.Optional("rep_delay", default=0.2): vol.All(
            vol.Coerce(float), vol.Range(min=0)
        ),
        vol.Optional("hold", default=False): cv.boolean,
        vol.Optional("counter", default=0): _COUNTER,
    }
)

LEARN_CLEAR_SCHEMA = vol.Schema(
    {
        vol.Required("serial"): _SERIAL,
        vol.Optional("group", default=0x0001): _GROUP,
        vol.Optional("counter", default=0): _COUNTER,
    }
)


def bitRead(value, bit):
    return ((value) >> (bit)) & 0x01


def bitSet(value, bit):
    return (value) | (1 << (bit))


def encrypt(x, keyHigh, keyLow):
    KeeLoq_NLF = 0x3A5C742E
    for r in range(0, 528):
        keyBitNo = r & 63
        if keyBitNo < 32:
            keyBitVal = bitRead(keyLow, keyBitNo)
        else:
            keyBitVal = bitRead(keyHigh, keyBitNo - 32)
        index = (
            1 * bitRead(x, 1)
            + 2 * bitRead(x, 9)
            + 4 * bitRead(x, 20)
            + 8 * bitRead(x, 26)
            + 16 * bitRead(x, 31)
        )
        bitVal = bitRead(x, 0) ^ bitRead(x, 16) ^ bitRead(KeeLoq_NLF, index) ^ keyBitVal
        x = (x >> 1) ^ bitVal << 31
    return x


def decrypt(x, keyHigh, keyLow):
    KeeLoq_NLF = 0x3A5C742E
    for r in range(0, 528):
        keyBitNo = (15 - r) & 63
        if keyBitNo < 32:
            keyBitVal = bitRead(keyLow, keyBitNo)
        else:
            keyBitVal = bitRead(keyHigh, keyBitNo - 32)
        index = (
            1 * bitRead(x, 0)
            + 2 * bitRead(x, 8)
            + 4 * bitRead(x, 19)
            + 8 * bitRead(x, 25)
            + 16 * bitRead(x, 30)
        )
        bitVal = (
            bitRead(x, 31) ^ bitRead(x, 15) ^ bitRead(KeeLoq_NLF, index) ^ keyBitVal
        )
        x = ((x << 1) & 0xFFFFFFFF) ^ bitVal
    return x


def BuildPacket(Grouping, Serial, Button, Counter, MSB, LSB, Hold):
    # Only 16 bits are available for the counter. Without masking, a counter
    # above 0xFFFF would overwrite the serial bits of the encrypted part.
    Counter &= COUNTER_MASK
    keylow = Serial | 0x20000000
    keyhigh = Serial | 0x60000000
    KeyLSB = decrypt(keylow, MSB, LSB)
    KeyMSB = decrypt(keyhigh, MSB, LSB)
    Decoded = Counter | ((Serial & 0xFF) << 16) | ((Grouping & 0xFF) << 24)
    Encoded = encrypt(Decoded, KeyMSB, KeyLSB)
    data = (
        (Encoded) | (Serial << 32) | (Button << 60) | (((Grouping >> 8) & 0xFF) << 64)
    )
    datastring = bin(data)[2:].zfill(72)[::-1]
    codedstring = ""
    for i in range(0, len(datastring)):
        if i == len(datastring) - 1:
            if datastring[i] == "1":
                codedstring = codedstring + "0c0005dc"
            else:
                codedstring = codedstring + "190005dc"
        else:
            if datastring[i] == "1":
                codedstring = codedstring + "0c19"
            else:
                codedstring = codedstring + "190c"
    codedstring = "190c1a0001e4310c0d0c0d0c0d0c0d0c0d0c0d0c0d0c0d7a" + codedstring
    slen = len(codedstring) / 2
    if Hold == True:
        codedstring = "b214" + hex(int(slen))[2:] + "00" + codedstring
    else:
        codedstring = "b200" + hex(int(slen))[2:] + "00" + codedstring
    packet = base64.b64encode(binascii.unhexlify(codedstring))
    return "b64:" + packet.decode("utf-8")


def ReadCounter(counter_file, serial):
    filename = counter_file + hex(serial) + ".txt"
    if not os.path.isfile(filename):
        return 0
    try:
        with open(filename, "r", encoding="utf-8") as fo:
            return int(fo.readline())
    except ValueError as err:
        # Falling back to 0 would re-send old rolling codes which the
        # receiver ignores, so fail loudly instead.
        raise HomeAssistantError(
            f"Jarolift counter file {filename} is corrupt. Restore the last "
            "counter value (decimal) into it."
        ) from err


def WriteCounter(counter_file, serial, Counter):
    filename = counter_file + hex(serial) + ".txt"
    tmp_filename = filename + ".tmp"
    # Write to a temp file and atomically replace, so a crash or power loss
    # never leaves an empty/partial counter file behind.
    with open(tmp_filename, "w", encoding="utf-8") as fo:
        fo.write(str(Counter & COUNTER_MASK))
        fo.flush()
        os.fsync(fo.fileno())
    os.replace(tmp_filename, filename)


def setup(hass, config):
    conf = config[DOMAIN]
    remote_entity_id = conf["remote_entity_id"]
    MSB = conf["MSB"]
    LSB = conf["LSB"]
    DELAY = conf["delay"]

    counter_file = hass.config.path("counter_")

    def send(packet):
        # blocking=True: wait until the remote has actually sent the packet,
        # so the delays below really space out the RF transmissions.
        hass.services.call(
            "remote",
            "send_command",
            {"entity_id": remote_entity_id, "command": [packet]},
            blocking=True,
        )

    def start_counter(call):
        """Return (counter to use, whether it comes from the counter file)."""
        counter = call.data["counter"]
        if counter == 0:
            return ReadCounter(counter_file, call.data["serial"]), True
        return counter, False

    def handle_send_raw(call):
        with mutex:
            send(call.data["packet"])

    def handle_send_command(call):
        Grouping = call.data["group"]
        Serial = call.data["serial"]
        rep_count = call.data["rep_count"]
        rep_delay = call.data["rep_delay"]
        Button = call.data["button"]
        Hold = call.data["hold"]

        # Counter handling must happen inside the mutex as well. Otherwise two
        # concurrent calls for the same serial read the same counter value and
        # send the same rolling code twice (the receiver ignores the second).
        with mutex:
            Counter, from_file = start_counter(call)
            packet = BuildPacket(Grouping, Serial, Button, Counter, MSB, LSB, Hold)
            if from_file:
                WriteCounter(counter_file, Serial, Counter + 1)

            # We want to send at least once. so rep_count 0 means range(1)
            send_count = rep_count + 1
            for i in range(send_count):
                _LOGGER.debug(
                    "Sending: %s group: 0x%04X Serial: 0x%08X repeat: %s",
                    Button,
                    Grouping,
                    Serial,
                    i,
                )
                send(packet)
                if i < send_count - 1:
                    # Only sleep when an additional command comes afterwards
                    sleep(rep_delay)
            # This is the minimum delay between multiple different covers
            sleep(DELAY)

    def handle_learn(call):
        Grouping = call.data["group"]
        Serial = call.data["serial"]

        with mutex:
            UsedCounter, from_file = start_counter(call)
            if from_file:
                WriteCounter(counter_file, Serial, UsedCounter + 2)
            send(BuildPacket(Grouping, Serial, 0xA, UsedCounter, MSB, LSB, False))
            sleep(1)
            send(BuildPacket(Grouping, Serial, 0x4, UsedCounter + 1, MSB, LSB, False))

    def handle_clear(call):
        Grouping = call.data["group"]
        Serial = call.data["serial"]

        with mutex:
            UsedCounter, from_file = start_counter(call)
            if from_file:
                WriteCounter(counter_file, Serial, UsedCounter + 8)
            send(BuildPacket(Grouping, Serial, 0xA, UsedCounter, MSB, LSB, False))
            sleep(1)
            for i in range(0, 6):
                send(
                    BuildPacket(
                        Grouping, Serial, 0x4, UsedCounter + 1 + i, MSB, LSB, False
                    )
                )
                sleep(0.5)
            sleep(1)
            send(BuildPacket(Grouping, Serial, 0x8, UsedCounter + 7, MSB, LSB, False))

    hass.services.register(DOMAIN, "send_raw", handle_send_raw, schema=SEND_RAW_SCHEMA)
    hass.services.register(
        DOMAIN, "send_command", handle_send_command, schema=SEND_COMMAND_SCHEMA
    )
    hass.services.register(DOMAIN, "learn", handle_learn, schema=LEARN_CLEAR_SCHEMA)
    hass.services.register(DOMAIN, "clear", handle_clear, schema=LEARN_CLEAR_SCHEMA)

    return True

"""
Support a 'Jarolift' remote as a separate remote.
Basically a proxy adding Keeloq encryption to commands sent via another remote then.
"""
import logging
import base64
import binascii
from time import sleep
import os.path
import threading

DOMAIN = "jarolift"
_LOGGER = logging.getLogger(__name__)
mutex = threading.Lock()

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
    if os.path.isfile(filename):
        #fo = open(filename, "r")
        #Counter = int(fo.readline())
        #fo.close()
        with open(filename, "r", encoding="utf-8") as fo:
            Counter = int(fo.readline())
        return Counter
    else:
        return 0


def WriteCounter(counter_file, serial, Counter):
    filename = counter_file + hex(serial) + ".txt"
    #_LOGGER.warning("Writing to " + filename + ": " + str(Counter) )
    #fo = open(filename, "w")
    #fo.write(str(Counter))
    #fo.close()
    with open(filename, "w", encoding="utf-8") as fo:
        fo.write(str(Counter))


def setup(hass, config):
    remote_entity_id = config["jarolift"]["remote_entity_id"]
    MSB = int(config["jarolift"]["MSB"], 16)
    LSB = int(config["jarolift"]["LSB"], 16)

    if "delay" in config["jarolift"]:
        DELAY = config["jarolift"]["delay"]
    else:
        DELAY = 0

    counter_file = hass.config.path("counter_")

    def handle_send_raw(call):
        with mutex:
            packet = call.data.get("packet", "")
            hass.services.call(
                "remote",
                "send_command",
                {"entity_id": remote_entity_id, "command": [packet]},
            )

    def handle_send_command(call):
        Grouping = int(call.data.get("group", "0x0001"), 16)
        Serial = int(call.data.get("serial", "0x106aa01"), 16)
        rep_count = call.data.get("rep_count", 0)
        rep_delay = call.data.get("rep_delay", 0.2)
        Button = int(call.data.get("button", "0x2"), 16)
        Hold = call.data.get("hold", False)
        RCounter = ReadCounter(counter_file, Serial)
        Counter = int(call.data.get("counter", "0x0000"), 16)
        if Counter == 0:
            packet = BuildPacket(Grouping, Serial, Button, RCounter, MSB, LSB, Hold)
            WriteCounter(counter_file, Serial, RCounter + 1)
        else:
            packet = BuildPacket(Grouping, Serial, Button, Counter, MSB, LSB, Hold)

        # Mutex used so that only one cover will be set when having rep_count > 0
        with mutex:
            # We want to send at least once. so rep_count 0 means range(1)
            send_count = rep_count + 1
            for i in range( send_count ):
                _LOGGER.debug(f"Sending: {Button} group: 0x{Grouping:04X} Serial: 0x{Serial:08X} repeat: {i}")
                hass.services.call(
                    "remote",
                    "send_command",
                    {"entity_id": remote_entity_id, "command": [packet]},
                )
                if i < send_count - 1:
                    # Only sleep when an additional command comes afterwards
                    sleep(rep_delay)
            # This is the minimum delay between multiple different covers
            sleep(DELAY)

    def handle_learn(call):
        Grouping = int(call.data.get("group", "0x0001"), 16)
        Serial = int(call.data.get("serial", "0x106aa01"), 16)
        Button = int("0xa", 16)
        RCounter = ReadCounter(counter_file, Serial)
        Counter = int(call.data.get("counter", "0x0000"), 16)
        if Counter == 0:
            UsedCounter = RCounter
        else:
            UsedCounter = Counter
        packet = BuildPacket(Grouping, Serial, Button, UsedCounter, MSB, LSB, False)

        with mutex:
            hass.services.call(
                "remote",
                "send_command",
                {"entity_id": remote_entity_id, "command": [packet]},
            )
            sleep(1)
            Button = int("0x4", 16)
            packet = BuildPacket(Grouping, Serial, Button, UsedCounter + 1, MSB, LSB, False)
            hass.services.call(
                "remote",
                "send_command",
                {"entity_id": remote_entity_id, "command": [packet]},
            )
            if Counter == 0:
                WriteCounter(counter_file, Serial, RCounter + 2)

    def handle_clear(call):
        Grouping = int(call.data.get("group", "0x0001"), 16)
        Serial = int(call.data.get("serial", "0x106aa01"), 16)
        Button = int("0xa", 16)
        RCounter = ReadCounter(counter_file, Serial)
        Counter = int(call.data.get("counter", "0x0000"), 16)
        if Counter == 0:
            UsedCounter = RCounter
        else:
            UsedCounter = Counter
        packet = BuildPacket(Grouping, Serial, Button, UsedCounter, MSB, LSB, False)

        with mutex:
            hass.services.call(
                "remote",
                "send_command",
                {"entity_id": remote_entity_id, "command": [packet]},
            )
            sleep(1)
            Button = int("0x4", 16)
            for i in range(0, 6):
                packet = BuildPacket(
                    Grouping, Serial, Button, UsedCounter + 1 + i, MSB, LSB, False
                )
                hass.services.call(
                    "remote",
                    "send_command",
                    {"entity_id": remote_entity_id, "command": [packet]},
                )
                sleep(0.5)
            sleep(1)
            Button = int("0x8", 16)
            packet = BuildPacket(Grouping, Serial, Button, UsedCounter + 7, MSB, LSB, False)
            hass.services.call(
                "remote",
                "send_command",
                {"entity_id": remote_entity_id, "command": [packet]},
            )
            if Counter == 0:
                WriteCounter(counter_file, Serial, RCounter + 8)

    hass.services.register(DOMAIN, "send_raw", handle_send_raw)
    hass.services.register(DOMAIN, "send_command", handle_send_command)
    hass.services.register(DOMAIN, "learn", handle_learn)
    hass.services.register(DOMAIN, "clear", handle_clear)

    return True

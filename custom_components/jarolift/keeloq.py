"""KeeLoq encryption and Broadlink packet encoding for Jarolift covers."""

import base64
import binascii

from .const import COUNTER_MASK


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

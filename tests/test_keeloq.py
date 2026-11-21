"""The packets must stay bit identical to version 1.x, or covers need relearning."""

from pathlib import Path

from custom_components.jarolift.keeloq import BuildPacket

REF = Path(__file__).parent / "reference_packets.txt"


def test_packets_unchanged():
    for line in REF.read_text().splitlines():
        counter, button, hold, packet = line.split(" ")
        assert (
            BuildPacket(0x0001, 0x106AA01, int(button), int(counter), 0x12345678, 0x87654321, hold == "True")
            == packet
        )


def test_counter_is_masked():
    assert BuildPacket(1, 0x106AA01, 2, 0x10005, 0x12345678, 0x87654321, False) == BuildPacket(
        1, 0x106AA01, 2, 0x5, 0x12345678, 0x87654321, False
    )

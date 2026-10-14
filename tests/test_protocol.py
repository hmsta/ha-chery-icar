"""Offline packet regression tests; no Home Assistant installation required."""

import json
import sys
import types
import unittest
from pathlib import Path

# Load pure protocol/client modules without executing HA's integration entrypoint.
PACKAGE = "icar_test"
ROOT = Path(__file__).resolve().parents[1] / "custom_components/chery_icar"
if PACKAGE not in sys.modules:
    package = types.ModuleType(PACKAGE)
    package.__path__ = [str(ROOT)]
    sys.modules[PACKAGE] = package

from icar_test.protocol import FrameBuffer, crc16, decode_status  # noqa: E402


def frame(body):
    return b"\xaa\x55" + len(body).to_bytes(2, "big") + body + crc16(body).to_bytes(2, "big")


# Synthetic fixture with known measurement values; no captured/private payload.
_data = bytearray(70)
_data[10:12] = (1419).to_bytes(2, "big")
_data[16:19] = (1403).to_bytes(3, "big")
_data[27:29] = (153).to_bytes(2, "big")
_data[26] = 35
_data[42:50] = bytes([113, 116, 112, 115, 70, 77, 69, 75])
SAVED = frame(b"\x77\x00" + _data)


class ProtocolTests(unittest.TestCase):
    def test_runtime_dependencies_are_owned_by_home_assistant(self):
        manifest = json.loads((ROOT / "manifest.json").read_text())
        self.assertIn("bluetooth", manifest["dependencies"])
        self.assertEqual(manifest["requirements"], [])

    def test_known_measurements(self):
        status = decode_status(SAVED)
        self.assertEqual(status["odometer"], 1403)
        self.assertEqual(status["remaining_range"], 153)
        self.assertEqual(status["battery"], 35)
        self.assertEqual(status["low_voltage"], 14.19)
        for wheel, pressure, temperature in (
            ("front_left", 226, 30),
            ("front_right", 232, 37),
            ("rear_left", 224, 29),
            ("rear_right", 230, 35),
        ):
            self.assertEqual(status[f"{wheel}_pressure"], pressure)
            self.assertEqual(status[f"{wheel}_temperature"], temperature)

    def test_all_fragment_boundaries(self):
        for split in range(len(SAVED) + 1):
            buffer = FrameBuffer()
            self.assertEqual(buffer.feed(SAVED[:split]) + buffer.feed(SAVED[split:]), [SAVED])

    def test_noise_crc_and_coalescing(self):
        bad = SAVED[:-1] + bytes([SAVED[-1] ^ 1])
        diagnostic = frame(b"\x77\x02ignored")
        buffer = FrameBuffer()
        self.assertEqual(
            buffer.feed(b"noise\xaa\x55\xff\xff" + bad + diagnostic + SAVED), [diagnostic, SAVED]
        )

    def test_rejects_corruption_and_unsupported_layout(self):
        for value in (
            SAVED[:-1],
            b"\x55\xaa" + SAVED[2:],
            frame(b"\x77\x00\x00"),
            SAVED[:-1] + bytes([SAVED[-1] ^ 1]),
        ):
            with self.assertRaises(ValueError):
                decode_status(value)

    def test_invalid_soc_not_published_as_percent(self):
        body = bytearray(SAVED[4:-2])
        body[28] = 255
        self.assertIsNone(decode_status(frame(body))["battery"])

    def test_fractional_odometer(self):
        data = bytearray(_data)
        data[16:19] = (0x800000 | 14037).to_bytes(3, "big")
        self.assertEqual(decode_status(frame(b"\x77\x00" + data))["odometer"], 1403.7)

    def test_range_unavailable_values(self):
        for value in (0, 1023):
            data = bytearray(_data)
            data[27:29] = value.to_bytes(2, "big")
            self.assertIsNone(decode_status(frame(b"\x77\x00" + data))["remaining_range"])

    def test_zero_odometer_and_valid_range_boundaries(self):
        for value in (1, 1022):
            data = bytearray(_data)
            data[16:19] = bytes(3)
            data[27:29] = value.to_bytes(2, "big")
            status = decode_status(frame(b"\x77\x00" + data))
            self.assertEqual(status["odometer"], 0)
            self.assertEqual(status["remaining_range"], value)

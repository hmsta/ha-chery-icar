"""Validated status fields from CarLinko 1.13.0, calibrated on the owner's car."""

from .const import WHEELS

CHARGING_STATES = {
    0: "idle", 1: "charging", 2: "completed", 3: "cancelled",
    4: "heating", 5: "stopped",
}
CHARGING_MODES = {
    0: "not_charging", 1: "slow", 2: "connected_not_charging", 16: "fast",
}


def crc16(body: bytes) -> int:
    """CRC-16/ARC over body only; encoded big endian on the wire."""
    value = 0
    for byte in body:
        value ^= byte
        for _ in range(8):
            value = (value >> 1) ^ (0xA001 if value & 1 else 0)
    return value


def valid_frame(frame: bytes) -> bool:
    return (
        len(frame) >= 7
        and frame[:2] == b"\xaa\x55"
        and int.from_bytes(frame[2:4], "big") == len(frame) - 6
        and crc16(frame[4:-2]) == int.from_bytes(frame[-2:], "big")
    )


def decode_status(frame: bytes) -> dict[str, int | float | str | None]:
    """Reject unfamiliar layouts instead of interpreting missing data as zero."""
    if not valid_frame(frame) or frame[4:6] != b"\x77\x00":
        raise ValueError("Invalid status frame")
    data = frame[6:-2]
    if len(data) != 70:
        raise ValueError(f"Unsupported status payload length: {len(data)}")
    mileage = int.from_bytes(data[16:19], "big")
    remaining_range = int.from_bytes(data[27:29], "big")
    wltc_range = int.from_bytes(data[66:68], "big")
    charging_minutes = int.from_bytes(data[56:58], "big")
    charging_power = int.from_bytes(data[60:62], "big")
    result = {
        "charging_status": CHARGING_STATES.get(data[55]),
        "charging_mode": CHARGING_MODES.get(data[54]),
        "charging_power": charging_power / 10 if charging_power != 0xFFFF else None,
        # CarLinko shows remaining time only in charging/heating states.
        "charging_time_remaining": (
            charging_minutes if data[55] in (1, 4) and charging_minutes != 0xFFFF else None
        ),
        "remaining_range_wltc": wltc_range if wltc_range not in (0, 1023, 0xFFFF) else None,
        "odometer": round((mileage & 0x7FFFFF) * (0.1 if mileage & 0x800000 else 1), 1),
        # Confirmed range field for the tested vehicle; app treats 0/1023 as unavailable.
        "remaining_range": remaining_range if remaining_range not in (0, 1023) else None,
        "battery": data[26] if data[26] <= 100 else None,
        "low_voltage": int.from_bytes(data[10:12], "big") / 100,
    }
    for index, wheel in enumerate(WHEELS):
        result[f"{wheel}_pressure"] = data[42 + index] * 2
        result[f"{wheel}_temperature"] = data[46 + index] - 40
    return result


class FrameBuffer:
    """Reassemble split/coalesced notifications, resynchronizing after bad CRCs."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, chunk: bytes) -> list[bytes]:
        self._buffer.extend(chunk)
        frames = []
        while self._buffer:
            start = self._buffer.find(b"\xaa\x55")
            if start < 0:
                self._buffer[:] = self._buffer[-1:] if self._buffer[-1:] == b"\xaa" else b""
                break
            del self._buffer[:start]
            if len(self._buffer) < 4:
                break
            length = int.from_bytes(self._buffer[2:4], "big")
            if not 1 <= length <= 4096:
                del self._buffer[0]
                continue
            if len(self._buffer) < length + 6:
                break
            frame = bytes(self._buffer[: length + 6])
            if not valid_frame(frame):
                del self._buffer[0]
                continue
            del self._buffer[: length + 6]
            frames.append(frame)
        return frames

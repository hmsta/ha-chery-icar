"""Validated status fields from CarLinko 1.13.0, calibrated on the owner's car."""

from .const import WHEELS


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


def decode_status(frame: bytes) -> dict[str, int | float | None]:
    """Reject unfamiliar layouts instead of interpreting missing data as zero."""
    if not valid_frame(frame) or frame[4:6] != b"\x77\x00":
        raise ValueError("Invalid status frame")
    data = frame[6:-2]
    if len(data) != 70:
        raise ValueError(f"Unsupported status payload length: {len(data)}")
    result = {
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

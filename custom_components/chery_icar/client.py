"""One short status-only connection using HA's proxy-aware BLEDevice."""

import asyncio
import logging

from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from .const import NOTIFY_UUID, SERVICE_UUID, STATUS_QUERY, WRITE_UUID
from .protocol import FrameBuffer, decode_status

_LOGGER = logging.getLogger(__name__)


async def read_status(device, *, response_timeout: float = 15) -> dict:
    """Connect, subscribe, request status once, and always release the connection."""
    frames = FrameBuffer()
    future = asyncio.get_running_loop().create_future()
    client = None

    def disconnected(_client):
        if not future.done():
            future.set_exception(BleakError("Car disconnected before replying"))

    def notification(_characteristic, value):
        for frame in frames.feed(value):
            if future.done() or frame[4:6] != b"\x77\x00":
                continue  # Ignore diagnostic/GPS messages; never store their content.
            try:
                status = decode_status(frame)
            except ValueError as err:
                future.set_exception(err)
            else:
                future.set_result(status)

    try:
        async with asyncio.timeout(60):
            client = await establish_connection(
                BleakClientWithServiceCache,
                device,
                device.name or "Chery iCar",
                disconnected_callback=disconnected,
                max_attempts=2,
                pair=False,
            )
            write = client.services.get_characteristic(WRITE_UUID)
            notify = client.services.get_characteristic(NOTIFY_UUID)
            if (
                write is None
                or notify is None
                or write.service_uuid.lower() != SERVICE_UUID
                or notify.service_uuid.lower() != SERVICE_UUID
                or "write" not in write.properties
                or "notify" not in notify.properties
            ):
                raise ValueError("Expected CarLinko UART characteristics not found")
            await client.start_notify(notify, notification)
            await asyncio.sleep(0.5)
            await client.write_gatt_char(write, STATUS_QUERY, response=True)
            async with asyncio.timeout(response_timeout):
                return await future
    finally:
        # Consume/cancel the future even if a write/subscription failed first.
        if not future.done():
            future.cancel()
        elif not future.cancelled():
            future.exception()
        if client is not None:
            try:
                async with asyncio.timeout(10):
                    await client.disconnect()
            except (BleakError, TimeoutError, OSError):
                _LOGGER.debug("BLE disconnect did not complete", exc_info=True)

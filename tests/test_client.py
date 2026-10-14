"""Simulate BLE lifecycle, split replies, errors and cancellation."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from test_protocol import SAVED, frame

# isort: split

from icar_test import client
from icar_test.const import NOTIFY_UUID, SERVICE_UUID, STATUS_QUERY, WRITE_UUID


class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.device = SimpleNamespace(name="Test car", address="AA:BB:CC:DD:EE:FF")
        self.write = SimpleNamespace(service_uuid=SERVICE_UUID, properties=["write"])
        self.notify = SimpleNamespace(service_uuid=SERVICE_UUID, properties=["notify"])
        self.ble = SimpleNamespace(
            services=SimpleNamespace(
                get_characteristic=lambda uuid: {
                    WRITE_UUID: self.write,
                    NOTIFY_UUID: self.notify,
                }.get(uuid)
            ),
            start_notify=AsyncMock(side_effect=self.subscribe),
            write_gatt_char=AsyncMock(side_effect=self.reply),
            disconnect=AsyncMock(),
        )
        self.connector = patch.object(
            client, "establish_connection", AsyncMock(return_value=self.ble)
        )
        self.connect = self.connector.start()
        self.addCleanup(self.connector.stop)

    async def subscribe(self, characteristic, callback):
        self.receive = callback

    async def reply(self, *args, **kwargs):
        self.receive(None, frame(b"\x77\x02diagnostic"))
        self.receive(None, SAVED[:19])
        self.receive(None, SAVED[19:])

    async def test_query_and_disconnect(self):
        result = await client.read_status(self.device)
        self.assertEqual(result["front_left_pressure"], 226)
        self.ble.write_gatt_char.assert_awaited_once_with(self.write, STATUS_QUERY, response=True)
        self.assertIs(self.connect.call_args.args[1], self.device)
        self.assertFalse(self.connect.call_args.kwargs["pair"])
        self.ble.disconnect.assert_awaited_once()

    async def test_missing_service_never_writes(self):
        self.write.service_uuid = "wrong"
        with self.assertRaises(ValueError):
            await client.read_status(self.device)
        self.ble.write_gatt_char.assert_not_awaited()
        self.ble.disconnect.assert_awaited_once()

    async def test_timeout_disconnects(self):
        self.ble.write_gatt_char.side_effect = None
        with self.assertRaises(TimeoutError):
            await client.read_status(self.device, response_timeout=0.01)
        self.ble.disconnect.assert_awaited_once()

    async def test_write_failure_disconnects(self):
        self.ble.write_gatt_char.side_effect = client.BleakError("write failed")
        with self.assertRaises(client.BleakError):
            await client.read_status(self.device)
        self.ble.disconnect.assert_awaited_once()

    async def test_cancellation_disconnects(self):
        subscribed = asyncio.Event()

        async def subscribe(*args):
            subscribed.set()

        self.ble.start_notify.side_effect = subscribe
        task = asyncio.create_task(client.read_status(self.device))
        await subscribed.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.ble.disconnect.assert_awaited_once()

    async def test_remote_disconnect_fails_promptly(self):
        async def disconnect(*args, **kwargs):
            self.connect.call_args.kwargs["disconnected_callback"](self.ble)

        self.ble.write_gatt_char.side_effect = disconnect
        with self.assertRaises(client.BleakError):
            await client.read_status(self.device)
        self.ble.disconnect.assert_awaited_once()

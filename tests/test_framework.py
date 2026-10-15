"""HA API contract doubles: these are not a full Home Assistant runtime test."""

import importlib
import sys
import types
import unittest
from datetime import timedelta
from unittest.mock import AsyncMock, Mock, patch

import test_protocol  # noqa: F401 -- initializes the isolated test package


class Flow:
    def __init_subclass__(cls, **kwargs):
        pass

    def __init__(self):
        self.context = {}
        self.config_entry = types.SimpleNamespace(options={}, data={})
        self.configured = False
        self.hass = object()
        self.entries = []

    async def async_set_unique_id(self, value):
        self.unique_id = value

    def _abort_if_unique_id_configured(self):
        if self.configured:
            raise ValueError("already_configured")

    def _async_current_entries(self):
        return self.entries

    def async_show_menu(self, **kwargs):
        return {"type": "menu", **kwargs}

    def async_create_entry(self, **kwargs):
        return {"type": "create_entry", **kwargs}

    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}


class Coordinator:
    def __init__(self, hass, logger, **kwargs):
        self.hass = hass
        self.update_interval = kwargs["update_interval"]
        kwargs["config_entry"].async_on_unload(self.async_shutdown)

    async def async_shutdown(self):
        self.stopped = True


class UpdateFailed(Exception):
    pass


class FrameworkTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        modules = {}
        for name in (
            "homeassistant",
            "homeassistant.config_entries",
            "homeassistant.const",
            "homeassistant.core",
            "homeassistant.components",
            "homeassistant.components.bluetooth",
            "homeassistant.helpers",
            "homeassistant.helpers.update_coordinator",
        ):
            module = modules[name] = types.ModuleType(name)
            if "." in name:
                parent, child = name.rsplit(".", 1)
                setattr(modules[parent], child, module)
        modules["homeassistant.config_entries"].ConfigFlow = Flow
        modules["homeassistant.config_entries"].OptionsFlow = Flow
        modules["homeassistant.const"].CONF_ADDRESS = "address"
        modules["homeassistant.const"].CONF_NAME = "name"
        modules["homeassistant.core"].callback = lambda fn: fn
        coordinator = modules["homeassistant.helpers.update_coordinator"]
        coordinator.DataUpdateCoordinator = Coordinator
        coordinator.UpdateFailed = UpdateFailed
        self.bluetooth = modules["homeassistant.components.bluetooth"]
        self.bluetooth.async_ble_device_from_address = Mock(return_value=None)
        self.bluetooth.async_discovered_service_info = Mock(return_value=[])
        self.bluetooth.async_scanner_count = Mock(return_value=1)
        self.unsubscribe = Mock()
        self.bluetooth.async_register_callback = Mock(return_value=self.unsubscribe)
        self.bluetooth.BluetoothScanningMode = types.SimpleNamespace(ACTIVE="active")
        self.patch = patch.dict(sys.modules, modules)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        for name in ("icar_test.config_flow", "icar_test.coordinator"):
            sys.modules.pop(name, None)
        self.flow_module = importlib.import_module("icar_test.config_flow")
        self.coordinator_module = importlib.import_module("icar_test.coordinator")
        self.entry = types.SimpleNamespace(
            data={"address": "AA:BB:CC:DD:EE:FF"}, options={}, async_on_unload=Mock()
        )

    def car(self, address="AA:BB:CC:DD:EE:FF", name="CHR test", connectable=True):
        return types.SimpleNamespace(address=address, name=name, connectable=connectable)

    async def test_manual_defaults_validation_and_duplicate(self):
        flow = self.flow_module.CheryConfigFlow()
        form = await flow.async_step_manual()
        data = form["data_schema"]({"address": "aa:bb:cc:dd:ee:ff"})
        result = await flow.async_step_manual(data)
        self.assertEqual(result["step_id"], "confirm")
        self.assertEqual(result["data_schema"]({})["poll_minutes"], 30)
        self.assertEqual(flow.unique_id, "AA:BB:CC:DD:EE:FF")
        result = await flow.async_step_manual({"address": "invalid"})
        self.assertEqual(result["errors"], {"address": "invalid_address"})
        flow.configured = True
        with self.assertRaisesRegex(ValueError, "already_configured"):
            await flow.async_step_manual(data)

    async def test_discovery_requires_successful_validation(self):
        flow = self.flow_module.CheryConfigFlow()
        result = await flow.async_step_bluetooth(self.car())
        self.assertEqual(result["step_id"], "confirm")
        result = await flow.async_step_confirm({"poll_minutes": 45})
        self.assertEqual(result["errors"]["base"], "not_found")
        self.assertEqual(result["data_schema"]({})["poll_minutes"], 45)
        self.bluetooth.async_ble_device_from_address.return_value = object()
        with patch.object(
            self.flow_module, "read_status", AsyncMock(return_value={"battery": 35})
        ) as read:
            result = await flow.async_step_confirm({"poll_minutes": 45})
            read.assert_awaited_once()
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["data"]["address"], "AA:BB:CC:DD:EE:FF")

    async def test_one_cached_car_skips_address_form(self):
        self.bluetooth.async_discovered_service_info.return_value = [self.car()]
        result = await self.flow_module.CheryConfigFlow().async_step_user()
        self.assertEqual(result["step_id"], "confirm")
        self.bluetooth.async_register_callback.assert_not_called()

    async def test_multiple_cars_picker_and_exclusions(self):
        flow = self.flow_module.CheryConfigFlow()
        flow.entries = [types.SimpleNamespace(data={"address": "AA:BB:CC:DD:EE:01"})]
        self.bluetooth.async_discovered_service_info.return_value = [
            self.car(),
            self.car("AA:BB:CC:DD:EE:02", "CHR second"),
            self.car("AA:BB:CC:DD:EE:01"),
            self.car(name="Other"),
            self.car("AA:BB:CC:DD:EE:03", connectable=False),
            self.car(),
        ]
        result = await flow.async_step_user()
        self.assertEqual(result["step_id"], "select")
        self.assertEqual(len(flow._devices), 2)
        result = await flow.async_step_select({"address": "AA:BB:CC:DD:EE:02"})
        self.assertEqual(result["description_placeholders"]["name"], "CHR second")
        result = await flow.async_step_select({"address": "manual"})
        self.assertEqual(result["step_id"], "manual")

    async def test_no_devices_retry_and_callback_cleanup(self):
        flow = self.flow_module.CheryConfigFlow()
        with patch.object(self.flow_module, "DISCOVERY_SECONDS", 0):
            result = await flow.async_step_user()
        self.assertEqual(result["type"], "menu")
        self.assertEqual(result["menu_options"], ["retry", "manual"])
        self.unsubscribe.assert_called_once()
        self.bluetooth.async_discovered_service_info.return_value = [self.car()]
        self.assertEqual((await flow.async_step_retry())["step_id"], "confirm")

    async def test_arriving_advertisement_is_collected(self):
        def register(hass, cb, matcher, mode):
            cb(self.car(), None)
            return self.unsubscribe

        self.bluetooth.async_register_callback.side_effect = register
        with patch.object(self.flow_module, "DISCOVERY_SECONDS", 0):
            result = await self.flow_module.CheryConfigFlow().async_step_user()
        self.assertEqual(result["step_id"], "confirm")
        self.unsubscribe.assert_called_once()

    async def test_missing_proxy_does_not_wait(self):
        self.bluetooth.async_scanner_count.return_value = 0
        result = await self.flow_module.CheryConfigFlow().async_step_user()
        self.assertIn("No active Bluetooth", result["description_placeholders"]["reason"])
        self.bluetooth.async_register_callback.assert_not_called()

    async def test_validation_failure_keeps_selection(self):
        flow = self.flow_module.CheryConfigFlow()
        await flow.async_step_bluetooth(self.car())
        self.bluetooth.async_ble_device_from_address.return_value = object()
        for exception, error in [
            (TimeoutError(), "cannot_connect"),
            (ValueError(), "unsupported_device"),
        ]:
            with patch.object(self.flow_module, "read_status", AsyncMock(side_effect=exception)):
                result = await flow.async_step_confirm({"poll_minutes": 60})
            self.assertEqual(result["errors"]["base"], error)
            self.assertEqual(result["description_placeholders"]["name"], "CHR test")
            self.assertEqual(result["data_schema"]({})["poll_minutes"], 60)

    async def test_options_interval(self):
        flow = self.flow_module.CheryOptionsFlow()
        flow.config_entry.options = {"poll_minutes": 60}
        form = await flow.async_step_init()
        self.assertEqual(form["data_schema"]({})["poll_minutes"], 60)
        result = await flow.async_step_init({"poll_minutes": 45})
        self.assertEqual(result["data"], {"poll_minutes": 45})
        for bad in (0, 1441):
            with self.assertRaises(self.flow_module.vol.Invalid):
                form["data_schema"]({"poll_minutes": bad})

    async def test_poll_interval_and_offline(self):
        coordinator = self.coordinator_module.CarCoordinator(object(), self.entry)
        self.assertEqual(coordinator.update_interval, timedelta(minutes=30))
        with self.assertRaises(UpdateFailed):
            await coordinator._async_update_data()
        self.bluetooth.async_ble_device_from_address.assert_called_once_with(
            coordinator.hass, self.entry.data["address"], connectable=True
        )
        self.entry.options = {"poll_minutes": 45}
        coordinator = self.coordinator_module.CarCoordinator(object(), self.entry)
        self.assertEqual(coordinator.update_interval, timedelta(minutes=45))

    async def test_poll_success_and_failure(self):
        device = object()
        self.bluetooth.async_ble_device_from_address.return_value = device
        coordinator = self.coordinator_module.CarCoordinator(object(), self.entry)
        with patch.object(
            self.coordinator_module, "read_status", AsyncMock(return_value={"battery": 35})
        ) as read:
            self.assertEqual(await coordinator._async_update_data(), {"battery": 35})
            read.assert_awaited_once_with(device)
        with patch.object(
            self.coordinator_module, "read_status", AsyncMock(side_effect=TimeoutError)
        ):
            for minutes in (1, 5):
                with self.assertRaises(UpdateFailed):
                    await coordinator._async_update_data()
                self.assertEqual(coordinator.update_interval, timedelta(minutes=minutes))
            for _ in range(2):
                with self.assertRaises(UpdateFailed):
                    await coordinator._async_update_data()
                self.assertEqual(coordinator.update_interval, timedelta(minutes=30))
        self.assertIsNone(coordinator._poll_task)
        with patch.object(self.coordinator_module, "read_status", AsyncMock(return_value={"battery": 40})):
            self.assertEqual(await coordinator._async_update_data(), {"battery": 40})
            self.assertEqual(coordinator.update_interval, timedelta(minutes=30))
            self.assertFalse(coordinator._retries_exhausted)
        self.bluetooth.async_ble_device_from_address.return_value = None
        with self.assertRaises(UpdateFailed):
            await coordinator._async_update_data()
        self.assertEqual(coordinator.update_interval, timedelta(minutes=1))

    async def test_short_polling_interval_caps_retries(self):
        self.entry.options = {"poll_minutes": 1}
        coordinator = self.coordinator_module.CarCoordinator(object(), self.entry)
        self.bluetooth.async_ble_device_from_address.return_value = object()
        with patch.object(self.coordinator_module, "read_status", AsyncMock(return_value={"battery": 40})):
            await coordinator._async_update_data()
        self.bluetooth.async_ble_device_from_address.return_value = None
        for _ in range(2):
            with self.assertRaises(UpdateFailed):
                await coordinator._async_update_data()
            self.assertEqual(coordinator.update_interval, timedelta(minutes=1))

    async def test_cancelled_read_does_not_consume_retry(self):
        import asyncio

        coordinator = self.coordinator_module.CarCoordinator(object(), self.entry)
        self.bluetooth.async_ble_device_from_address.return_value = object()
        with patch.object(self.coordinator_module, "read_status", AsyncMock(side_effect=asyncio.CancelledError)):
            with self.assertRaises(asyncio.CancelledError):
                await coordinator._async_update_data()
        self.assertEqual(coordinator._retry_count, 0)
        self.assertFalse(coordinator._has_read_status)
        self.assertIsNone(coordinator._poll_task)

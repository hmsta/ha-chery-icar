"""Sensor metadata and availability contract checks using lightweight HA doubles."""
import asyncio
import importlib
import sys
import types
import unittest
from unittest.mock import Mock, patch

import test_protocol  # noqa: F401


class SensorTests(unittest.TestCase):
    def test_metadata_and_remaining_time_lifecycle(self):
        sensor = types.ModuleType("homeassistant.components.sensor")
        sensor.SensorEntity = type("SensorEntity", (), {})
        sensor.SensorEntityDescription = types.SimpleNamespace
        sensor.SensorDeviceClass = types.SimpleNamespace(**{x: x for x in (
            "TIMESTAMP", "ENUM", "POWER", "DURATION", "DISTANCE", "BATTERY", "VOLTAGE", "PRESSURE", "TEMPERATURE"
        )})
        sensor.SensorStateClass = types.SimpleNamespace(MEASUREMENT="measurement", TOTAL_INCREASING="total_increasing")
        const = types.ModuleType("homeassistant.const")
        const.PERCENTAGE = "%"
        for name, member, value in (
            ("UnitOfPower", "KILO_WATT", "kW"), ("UnitOfTime", "MINUTES", "min"),
            ("UnitOfLength", "KILOMETERS", "km"), ("UnitOfElectricPotential", "VOLT", "V"),
            ("UnitOfPressure", "KPA", "kPa"), ("UnitOfTemperature", "CELSIUS", "C"),
        ):
            setattr(const, name, types.SimpleNamespace(**{member: value}))
        entity = types.ModuleType("icar_test.entity")

        class CarEntity:
            def __init__(self, coordinator, key):
                self.coordinator = coordinator

            @property
            def available(self):
                return self.coordinator.last_update_success

        entity.CarEntity = CarEntity
        modules = {"homeassistant.components.sensor": sensor, "homeassistant.const": const, "icar_test.entity": entity}
        with patch.dict(sys.modules, modules):
            sys.modules.pop("icar_test.sensor", None)
            module = importlib.import_module("icar_test.sensor")
            self.addCleanup(sys.modules.pop, "icar_test.sensor", None)
            descriptions = {d.key: d for d in module.DESCRIPTIONS}
            self.assertFalse(descriptions["remaining_range_wltc"].entity_registry_enabled_default)
            self.assertEqual(descriptions["remaining_range_wltc"].name, "Remaining range WLTC")
            self.assertEqual(descriptions["charging_time_remaining"].native_unit_of_measurement, "min")
            coordinator = types.SimpleNamespace(last_update_success=True, data={"charging_time_remaining": 717})
            remaining = module.CarSensor(coordinator, descriptions["charging_time_remaining"])
            self.assertTrue(remaining.available)
            self.assertEqual(remaining.native_value, 717)
            coordinator.data["charging_time_remaining"] = None
            self.assertFalse(remaining.available)
            coordinator.data["charging_time_remaining"] = 600
            self.assertTrue(remaining.available)
            coordinator.last_update_success = False
            self.assertFalse(remaining.available)

            self.assertNotIn("last_successful_update", descriptions)
            for description in descriptions.values():
                self.assertFalse(module.CarSensor(coordinator, description).available)

            helpers = types.ModuleType("homeassistant.helpers")
            registry_module = types.ModuleType("homeassistant.helpers.entity_registry")
            registry = Mock()
            registry_module.async_get = Mock(return_value=registry)
            helpers.entity_registry = registry_module
            coordinator.address = "AA:BB:CC:DD:EE:FF"
            entry = types.SimpleNamespace(runtime_data=coordinator, entry_id="this_car")
            registry.async_get_entity_id.return_value = "sensor.old_timestamp"
            with patch.dict(sys.modules, {
                "homeassistant.helpers": helpers,
                "homeassistant.helpers.entity_registry": registry_module,
            }):
                registry.async_get.return_value = types.SimpleNamespace(config_entry_id="other_car")
                asyncio.run(module.async_setup_entry(object(), entry, Mock()))
                registry.async_remove.assert_not_called()
                registry.async_get.return_value = types.SimpleNamespace(config_entry_id="this_car")
                asyncio.run(module.async_setup_entry(object(), entry, Mock()))
                registry.async_remove.assert_called_once_with("sensor.old_timestamp")

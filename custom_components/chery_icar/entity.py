"""Shared vehicle device and stable entity identifiers."""

from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


class CarEntity(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, key):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.address)},
            connections={(CONNECTION_BLUETOOTH, coordinator.address)},
            name=coordinator.entry.title,
            manufacturer="Chery",
            model="iCar (CarLinko BLE)",
        )

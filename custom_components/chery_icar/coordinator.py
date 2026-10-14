"""Scheduled polling through Home Assistant's Bluetooth adapters/proxies."""

import asyncio
import logging
from datetime import timedelta

from bleak.exc import BleakError
from homeassistant.components import bluetooth
from homeassistant.const import CONF_ADDRESS
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import read_status
from .const import CONF_POLL_MINUTES, DEFAULT_POLL_MINUTES, DOMAIN

_LOGGER = logging.getLogger(__name__)


class CarCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry):
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(
                minutes=entry.options.get(
                    CONF_POLL_MINUTES, entry.data.get(CONF_POLL_MINUTES, DEFAULT_POLL_MINUTES)
                )
            ),
        )
        self.address = entry.data[CONF_ADDRESS]
        self.entry = entry
        self._poll_task = None

    async def _async_update_data(self):
        device = bluetooth.async_ble_device_from_address(self.hass, self.address, connectable=True)
        if device is None:
            raise UpdateFailed("Car not reachable through an active Bluetooth adapter/proxy")
        self._poll_task = asyncio.create_task(read_status(device))
        try:
            return await self._poll_task
        except (BleakError, TimeoutError, OSError, ValueError) as err:
            raise UpdateFailed(f"Unable to read car status: {err}") from err
        finally:
            self._poll_task = None

    async def async_shutdown(self):
        await super().async_shutdown()
        if self._poll_task is not None:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass

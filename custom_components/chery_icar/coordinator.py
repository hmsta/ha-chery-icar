"""Scheduled polling through Home Assistant's Bluetooth adapters/proxies."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

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
        self._normal_interval = self.update_interval
        self._retry_count = 0
        self._retries_exhausted = False
        self._last_status = None
        self.last_successful_update = None

    async def _async_update_data(self):
        try:
            device = bluetooth.async_ble_device_from_address(self.hass, self.address, connectable=True)
            if device is None:
                raise BleakError("Car not reachable through an active Bluetooth adapter/proxy")
            self._poll_task = asyncio.create_task(read_status(device))
            status = await self._poll_task
        except (BleakError, TimeoutError, OSError, ValueError) as err:
            # Startup failures remain HA setup retries; never invent initial data.
            if self._last_status is not None and not self._retries_exhausted:
                delays = (timedelta(minutes=1), timedelta(minutes=5))
                if self._retry_count < len(delays):
                    self.update_interval = min(delays[self._retry_count], self._normal_interval)
                    self._retry_count += 1
                    _LOGGER.debug("Status read failed; retry %s in %s: %s",
                                  self._retry_count, self.update_interval, err)
                    return self._last_status
                self._retries_exhausted = True
            self.update_interval = self._normal_interval
            raise UpdateFailed(f"Unable to read car status: {err}") from err
        finally:
            self._poll_task = None
        self._last_status = status
        self.last_successful_update = datetime.now(UTC)
        self._retry_count = 0
        self._retries_exhausted = False
        self.update_interval = self._normal_interval
        return status

    async def async_shutdown(self):
        await super().async_shutdown()
        if self._poll_task is not None:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass

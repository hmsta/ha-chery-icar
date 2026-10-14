"""Discover nearby CarLinko vehicles through HA Bluetooth and ESPHome proxies."""

import asyncio
import re

import voluptuous as vol
from bleak.exc import BleakError
from homeassistant import config_entries
from homeassistant.components import bluetooth
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.core import callback

from .client import read_status
from .const import CONF_POLL_MINUTES, DEFAULT_POLL_MINUTES, DOMAIN

POLL_VALIDATOR = vol.All(vol.Coerce(int), vol.Range(min=1, max=1440))
DISCOVERY_SECONDS = 10


class CheryConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        super().__init__()
        self._devices = {}
        self._address = None
        self._name = "Chery iCar"
        self._poll_minutes = DEFAULT_POLL_MINUTES

    def _remember(self, info):
        address = info.address.upper()
        configured = {
            entry.data.get(CONF_ADDRESS, "").upper() for entry in self._async_current_entries()
        }
        name = info.name or ""
        if info.connectable and name.startswith("CHR") and address not in configured:
            self._devices[address] = name

    async def async_step_user(self, user_input=None):
        """Use cached discoveries first; briefly listen if none are known."""
        self._devices = {}
        for info in bluetooth.async_discovered_service_info(self.hass, connectable=True):
            self._remember(info)
        if not self._devices and bluetooth.async_scanner_count(self.hass, connectable=True):

            @callback
            def discovered(info, change):
                self._remember(info)

            unsubscribe = bluetooth.async_register_callback(
                self.hass,
                discovered,
                {"local_name": "CHR*", "connectable": True},
                bluetooth.BluetoothScanningMode.ACTIVE,
            )
            try:
                await asyncio.sleep(DISCOVERY_SECONDS)
            finally:
                unsubscribe()
            for info in bluetooth.async_discovered_service_info(self.hass, connectable=True):
                self._remember(info)
        if len(self._devices) == 1:
            self._address, self._name = next(iter(self._devices.items()))
            return await self.async_step_confirm()
        if self._devices:
            return await self.async_step_select()
        return self.async_show_menu(
            step_id="not_found",
            menu_options=["retry", "manual"],
            description_placeholders={
                "reason": (
                    "No active Bluetooth adapter or proxy is available. Check the ESPHome proxy is online "
                    "and active connections are enabled."
                    if not bluetooth.async_scanner_count(self.hass, connectable=True)
                    else "No new CHR vehicle was found. Move the proxy near the car and close CarLinko "
                    "so it releases its connection. Already configured cars are excluded."
                )
            },
        )

    async def async_step_retry(self, user_input=None):
        return await self.async_step_user()

    async def async_step_select(self, user_input=None):
        errors = {}
        if user_input is not None:
            selected = user_input[CONF_ADDRESS]
            if selected == "manual":
                return await self.async_step_manual()
            if selected == "retry":
                return await self.async_step_retry()
            if selected in self._devices:
                self._address, self._name = selected, self._devices[selected]
                return await self.async_step_confirm()
            errors["base"] = "not_found"
        choices = {
            address: f"{name} ({address})"
            for address, name in sorted(self._devices.items(), key=lambda item: (item[1], item[0]))
        }
        choices.update(retry="Search again", manual="Enter address manually")
        return self.async_show_form(
            step_id="select",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(choices),
                }
            ),
        )

    async def async_step_manual(self, user_input=None):
        errors = {}
        if user_input is not None:
            address = user_input[CONF_ADDRESS].strip().upper()
            if not re.fullmatch(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", address):
                errors[CONF_ADDRESS] = "invalid_address"
            else:
                self._address = address
                self._name = user_input.get(CONF_NAME, "Chery iCar").strip() or "Chery iCar"
                return await self.async_step_confirm()
        return self.async_show_form(
            step_id="manual",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): str,
                    vol.Optional(CONF_NAME, default="Chery iCar"): str,
                }
            ),
        )

    async def async_step_bluetooth(self, discovery_info):
        self._address = discovery_info.address.upper()
        self._name = discovery_info.name or "Chery iCar"
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input=None):
        await self.async_set_unique_id(self._address)
        self._abort_if_unique_id_configured()
        self.context["title_placeholders"] = {"name": self._name}
        errors = {}
        if user_input is not None:
            self._poll_minutes = user_input[CONF_POLL_MINUTES]
            device = bluetooth.async_ble_device_from_address(
                self.hass, self._address, connectable=True
            )
            if device is None:
                errors["base"] = "not_found"
            else:
                try:
                    await read_status(device)
                except (BleakError, TimeoutError, OSError):
                    errors["base"] = "cannot_connect"
                except ValueError:
                    errors["base"] = "unsupported_device"
                else:
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=self._name,
                        data={
                            CONF_ADDRESS: self._address,
                            CONF_NAME: self._name,
                            CONF_POLL_MINUTES: self._poll_minutes,
                        },
                    )
        return self.async_show_form(
            step_id="confirm",
            errors=errors,
            description_placeholders={"name": self._name},
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_POLL_MINUTES, default=self._poll_minutes): POLL_VALIDATOR,
                }
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return CheryOptionsFlow()


class CheryOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        interval = self.config_entry.options.get(
            CONF_POLL_MINUTES, self.config_entry.data.get(CONF_POLL_MINUTES, DEFAULT_POLL_MINUTES)
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_POLL_MINUTES, default=interval): POLL_VALIDATOR,
                }
            ),
        )

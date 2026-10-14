"""Chery iCar status via CarLinko BLE."""

from homeassistant.const import Platform

from .coordinator import CarCoordinator

PLATFORMS = [Platform.SENSOR, Platform.BUTTON]


async def async_setup_entry(hass, entry):
    coordinator = CarCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass, entry):
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry):
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

"""Manually request one status poll."""

from homeassistant.components.button import ButtonEntity

from .entity import CarEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([RefreshButton(entry.runtime_data)])


class RefreshButton(CarEntity, ButtonEntity):
    _attr_name = "Refresh status"
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator):
        super().__init__(coordinator, "refresh")

    @property
    def available(self):
        # Allow a retry even after a failed poll marked the sensors unavailable.
        return True

    async def async_press(self):
        await self.coordinator.async_request_refresh()

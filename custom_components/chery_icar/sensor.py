"""Confirmed battery, distance and per-wheel readings."""

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricPotential,
    UnitOfLength,
    UnitOfPower,
    UnitOfPressure,
    UnitOfTemperature,
    UnitOfTime,
)

from .const import WHEELS
from .entity import CarEntity
from .protocol import CHARGING_MODES, CHARGING_STATES

DESCRIPTIONS = (
    SensorEntityDescription(
        key="charging_status",
        name="Charging status",
        translation_key="charging_status",
        device_class=SensorDeviceClass.ENUM,
        options=list(CHARGING_STATES.values()),
        icon="mdi:ev-station",
    ),
    SensorEntityDescription(
        key="charging_mode",
        name="Charging mode",
        translation_key="charging_mode",
        device_class=SensorDeviceClass.ENUM,
        options=list(CHARGING_MODES.values()),
        icon="mdi:ev-plug-type2",
    ),
    SensorEntityDescription(
        key="charging_power",
        name="Charging power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="charging_time_remaining",
        name="Estimated charging time remaining",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="remaining_range_wltc",
        name="Remaining range WLTC",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        entity_registry_enabled_default=False,
    ),
    SensorEntityDescription(
        key="remaining_range",
        name="Remaining range",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="odometer",
        name="Odometer",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="battery",
        name="Main battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="low_voltage",
        name="12 V battery voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    *(
        SensorEntityDescription(
            key=f"{wheel}_pressure",
            name=f"{wheel.replace('_', ' ').capitalize()} tire pressure",
            device_class=SensorDeviceClass.PRESSURE,
            native_unit_of_measurement=UnitOfPressure.KPA,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=0,
        )
        for wheel in WHEELS
    ),
    *(
        SensorEntityDescription(
            key=f"{wheel}_temperature",
            name=f"{wheel.replace('_', ' ').capitalize()} tire temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=0,
        )
        for wheel in WHEELS
    ),
)


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(CarSensor(entry.runtime_data, description) for description in DESCRIPTIONS)


class CarSensor(CarEntity, SensorEntity):
    def __init__(self, coordinator, description):
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self):
        if not super().available:
            return False
        if self.entity_description.key == "charging_time_remaining":
            return self.coordinator.data.get("charging_time_remaining") is not None
        return True

    @property
    def native_value(self):
        return self.coordinator.data.get(self.entity_description.key)

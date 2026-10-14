"""CarLinko BLE constants."""

DOMAIN = "chery_icar"
DEFAULT_POLL_MINUTES = 30
CONF_POLL_MINUTES = "poll_minutes"
SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
WRITE_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
NOTIFY_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
STATUS_QUERY = bytes.fromhex("55aa0001772640")
WHEELS = ("front_left", "front_right", "rear_left", "rear_right")

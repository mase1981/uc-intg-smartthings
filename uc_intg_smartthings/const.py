"""
SmartThings constants and capability helpers.

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0, see LICENSE for more details.
"""

CAPABILITY_LIGHT = ["switchLevel", "colorControl", "colorTemperature"]
CAPABILITY_SWITCH = ["switch"]
CAPABILITY_SENSOR_TEMP = ["temperatureMeasurement"]
CAPABILITY_SENSOR_HUMIDITY = ["relativeHumidityMeasurement"]
CAPABILITY_SENSOR_MOTION = ["motionSensor"]
CAPABILITY_SENSOR_CONTACT = ["contactSensor"]
CAPABILITY_SENSOR_BATTERY = ["battery"]
CAPABILITY_CLIMATE = [
    "thermostat", "thermostatMode",
    "thermostatCoolingSetpoint", "thermostatHeatingSetpoint",
]
CAPABILITY_COVER = ["windowShade", "doorControl", "garageDoorControl"]
CAPABILITY_MEDIA_PLAYER = [
    "audioVolume", "mediaPlayback",
    "mediaInputSource", "samsungvd.mediaInputSource", "samsungvd.audioInputSource",
]
CAPABILITY_BUTTON = ["button", "momentary"]

INPUT_SOURCE_CAPABILITIES = [
    "mediaInputSource",
    "samsungvd.mediaInputSource",
    "samsungvd.audioInputSource",
]

CYCLING_ONLY_SOUNDBAR_MODELS = ["q950t", "hw-q70t", "q950a", "q990b", "q990f"]

SAMSUNG_SOUNDBAR_SOURCES = [
    "HDMI1", "HDMI2", "HDMI3", "HDMI4", "USB", "aux", "bluetooth",
    "optical", "coaxial", "network", "wifi",
]


def has_capability(device: dict, capability: str) -> bool:
    """Check if a device has a specific capability."""
    components = device.get("components", [])
    for component in components:
        capabilities = component.get("capabilities", [])
        for cap in capabilities:
            cap_id = cap.get("id", "") if isinstance(cap, dict) else cap
            if cap_id == capability:
                return True
    return False


def has_any_capability(device: dict, capabilities: list[str]) -> bool:
    """Check if a device has any of the specified capabilities."""
    return any(has_capability(device, cap) for cap in capabilities)


def get_device_capabilities(device: dict) -> list[str]:
    """Get all capabilities for a device."""
    caps = []
    components = device.get("components", [])
    for component in components:
        capabilities = component.get("capabilities", [])
        for cap in capabilities:
            cap_id = cap.get("id", "") if isinstance(cap, dict) else cap
            if cap_id:
                caps.append(cap_id)
    return caps


def detect_entity_type(device: dict) -> str | None:
    """Detect the primary entity type for a device."""
    if has_any_capability(device, CAPABILITY_CLIMATE):
        return "climate"
    if has_any_capability(device, CAPABILITY_COVER):
        return "cover"
    if has_any_capability(device, CAPABILITY_MEDIA_PLAYER):
        return "media_player"
    if has_any_capability(device, CAPABILITY_LIGHT):
        if not has_any_capability(device, ["lock", "doorControl", "thermostat"]):
            return "light"
    if has_any_capability(device, CAPABILITY_BUTTON):
        return "button"
    if has_any_capability(device, CAPABILITY_SWITCH):
        if not has_any_capability(device, CAPABILITY_LIGHT + CAPABILITY_COVER + CAPABILITY_CLIMATE):
            return "switch"
    return None


def detect_entity_type_from_caps(capabilities: list[str]) -> str | None:
    """Detect entity type from a flat capability list."""
    caps_set = set(capabilities)
    if caps_set & set(CAPABILITY_CLIMATE):
        return "climate"
    if caps_set & set(CAPABILITY_COVER):
        return "cover"
    if caps_set & set(CAPABILITY_MEDIA_PLAYER):
        return "media_player"
    if caps_set & set(CAPABILITY_LIGHT):
        if not (caps_set & {"lock", "doorControl", "thermostat"}):
            return "light"
    if caps_set & set(CAPABILITY_BUTTON):
        return "button"
    if caps_set & set(CAPABILITY_SWITCH):
        if not (caps_set & set(CAPABILITY_LIGHT + CAPABILITY_COVER + CAPABILITY_CLIMATE)):
            return "switch"
    return None


def get_sensor_types(capabilities: list[str]) -> list[str]:
    """Get sensor types from a capability list."""
    sensors = []
    if "temperatureMeasurement" in capabilities:
        sensors.append("temperature")
    if "relativeHumidityMeasurement" in capabilities:
        sensors.append("humidity")
    if "motionSensor" in capabilities:
        sensors.append("motion")
    if "contactSensor" in capabilities:
        sensors.append("contact")
    if "battery" in capabilities:
        sensors.append("battery")
    if "powerMeter" in capabilities:
        sensors.append("power")
    if "energyMeter" in capabilities:
        sensors.append("energy")
    if "presenceSensor" in capabilities:
        sensors.append("presence")
    if "illuminanceMeasurement" in capabilities:
        sensors.append("illuminance")
    return sensors


def detect_input_source_capability(name: str, caps: list[str]) -> str | None:
    """Detect the single correct input source capability for a device.

    Returns the capability name to use for SELECT_SOURCE, or None if the device
    is cycling-only or has no input source capability.
    """
    name_lower = name.lower()
    if any(model in name_lower for model in CYCLING_ONLY_SOUNDBAR_MODELS):
        return None

    for cap in INPUT_SOURCE_CAPABILITIES:
        if cap in caps:
            return cap
    return None


def is_samsung_soundbar(name: str, capabilities: list[str]) -> bool:
    """Check if device is a Samsung soundbar."""
    name_lower = name.lower()
    caps_set = set(capabilities)
    return (
        "soundbar" in name_lower
        or ("samsung" in name_lower and "q9" in name_lower)
        or ("audioVolume" in caps_set and "mediaPlayback" not in caps_set and "switch" in caps_set)
    )

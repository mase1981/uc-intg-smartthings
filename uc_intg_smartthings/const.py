"""
SmartThings constants and capability helpers.

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0, see LICENSE for more details.
"""

import logging

_LOG = logging.getLogger(__name__)

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

CYCLING_ONLY_SOUNDBAR_MODELS = ["q950t", "hw-q70t", "q950a"]

SAMSUNG_EXECUTE_SOUNDBAR_MODELS = ["q990", "hw-q990"]

SAMSUNG_TV_ONLY_CAPABILITIES = [
    "samsungvd.ambient",
    "samsungvd.supportsPowerOnByOcf",
    "samsungvd.remoteControl",
]

SAMSUNG_SOUNDBAR_SOURCES = [
    "HDMI1", "HDMI2", "HDMI3", "HDMI4", "USB", "aux", "bluetooth",
    "optical", "coaxial", "network", "wifi",
]

SAMSUNG_EXECUTE_SOURCE_MAP: dict[str, tuple[str, int]] = {
    "HDMI1": ("HDMI1", 3),
    "HDMI2": ("HDMI2", 21),
    "TV ARC": ("TV ARC", 25),
    "D-IN": ("D-IN", 1),
    "bluetooth": ("BT", 5),
    "wifi": ("Wi-Fi", 7),
    "optical": ("OPTICAL", 2),
}


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


def detect_input_source_capability(
    name: str, caps: list[str], device_type: str = ""
) -> str | None:
    """Detect the single correct input source capability for a device.

    Returns the capability name to use for SELECT_SOURCE, "execute" for Samsung
    soundbars requiring the execute API, or None if cycling-only/unsupported.

    Samsung soundbars require the execute API with /sec/networkaudio/soundFrom.
    Standard setInputSource does NOT work on Samsung soundbars even if they
    report mediaInputSource in their capabilities.

    Checks both user label (name) and manufacturer type name (device_type)
    since users often rename devices.
    """
    names_lower = [name.lower()]
    if device_type:
        names_lower.append(device_type.lower())

    _LOG.info(
        "Input source detection for '%s' (type='%s'): caps=%s",
        name, device_type, [c for c in caps if c in (
            "execute", "audioVolume", "audioMute", "mediaPlayback", "switch",
            "mediaInputSource", "samsungvd.mediaInputSource", "samsungvd.audioInputSource",
            "samsungvd.ambient", "samsungvd.supportsPowerOnByOcf", "samsungvd.remoteControl",
        )]
    )

    if any(model in n for n in names_lower for model in CYCLING_ONLY_SOUNDBAR_MODELS):
        _LOG.info("  -> cycling-only model detected, no direct input source")
        return None

    if any(model in n for n in names_lower for model in SAMSUNG_EXECUTE_SOUNDBAR_MODELS):
        _LOG.info("  -> execute soundbar model detected by name match")
        return "execute"

    if "execute" in caps and is_samsung_soundbar(name, caps, device_type):
        _LOG.info("  -> Samsung soundbar detected by capability heuristic, using execute API")
        return "execute"

    for cap in INPUT_SOURCE_CAPABILITIES:
        if cap in caps:
            _LOG.info("  -> standard input source capability: %s", cap)
            return cap

    _LOG.info("  -> no input source capability found")
    return None


def is_samsung_soundbar(
    name: str, capabilities: list[str], device_type: str = ""
) -> bool:
    """Check if device is a Samsung soundbar.

    Uses three detection strategies:
    1. Name/model patterns (user label or manufacturer type name)
    2. Samsung audio device without TV capabilities (execute + audioVolume, no TV caps)
    3. Audio-only heuristic (audioVolume + switch, no mediaPlayback)
    """
    caps_set = set(capabilities)

    if caps_set & set(SAMSUNG_TV_ONLY_CAPABILITIES):
        _LOG.debug("  is_samsung_soundbar('%s'): False (has TV-only caps)", name)
        return False

    names_lower = [name.lower()]
    if device_type:
        names_lower.append(device_type.lower())

    soundbar_name_patterns = [
        "soundbar", "sound bar", "hw-q", "hw-s", "hw-n", "hw-t",
    ]
    if any(p in n for n in names_lower for p in soundbar_name_patterns):
        _LOG.debug("  is_samsung_soundbar('%s'): True (name pattern match)", name)
        return True
    if any("samsung" in n and any(m in n for m in ("q9", "q8")) for n in names_lower):
        _LOG.debug("  is_samsung_soundbar('%s'): True (Samsung model match)", name)
        return True

    if "execute" in caps_set and "audioVolume" in caps_set:
        _LOG.debug("  is_samsung_soundbar('%s'): True (execute + audioVolume)", name)
        return True

    if "audioVolume" in caps_set and "switch" in caps_set and "mediaPlayback" not in caps_set:
        _LOG.debug("  is_samsung_soundbar('%s'): True (audio-only heuristic)", name)
        return True

    _LOG.debug("  is_samsung_soundbar('%s'): False (no match)", name)
    return False

"""Diagnostics support for the Renson Healthbox integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, CONF_HOST
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import HealthboxDataUpdateCoordinator

# Anything that could identify this device or its owner: the config
# entry's own host/key, and the device's serial/warranty numbers.
TO_REDACT = {
    CONF_API_KEY,
    CONF_HOST,
    "serial",
    "warranty_number",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: HealthboxDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    api = coordinator.api

    rooms = [
        {
            "room_id": room.room_id,
            "type": getattr(room, "room_type", None),
            "profile_name": room.profile_name,
            "airflow_ventilation_rate": room.airflow_ventilation_rate,
            "boost": (
                {
                    "level": room.boost.level,
                    "enabled": room.boost.enabled,
                    "remaining": room.boost.remaining,
                }
                if room.boost is not None
                else None
            ),
        }
        for room in api.rooms
    ]

    diagnostics: dict[str, Any] = {
        "entry_data": dict(entry.data),
        "advanced_api_enabled": api.advanced_api_enabled,
        "serial": api.serial,
        "description": api.description,
        "warranty_number": api.warranty_number,
        "firmware_version": api.firmware_version,
        "global_aqi": api.global_aqi,
        "error_count": api.error_count,
        "wifi": {
            "status": api.wifi.status,
            "internet_connection": api.wifi.internet_connection,
        },
        "fan": {
            "voltage": api.fan.voltage,
            "pressure": api.fan.pressure,
            "flow": api.fan.flow,
            "power": api.fan.power,
            "rpm": api.fan.rpm,
        },
        "rooms": rooms,
        "boost_defaults": {
            str(key): {"level": value.level, "duration_preset": value.duration_preset}
            for key, value in coordinator.boost_defaults.items()
        },
    }
    return async_redact_data(diagnostics, TO_REDACT)

"""Shared DeviceInfo builders and room lookup for healthbox entities.

Plain functions rather than a shared base class deliberately - fan.py
already has its own non-trivial shared base (HealthboxBoostFan), and
mixing that with a second inheritance chain just for DeviceInfo isn't
worth the MRO/__init__-chaining complexity it'd add. Every platform can
safely call these regardless of its own class hierarchy.
"""
from __future__ import annotations

from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN, MANUFACTURER, HealthboxRoom
from .coordinator import HealthboxDataUpdateCoordinator


def healthbox_device_info(coordinator: HealthboxDataUpdateCoordinator) -> DeviceInfo:
    """Return DeviceInfo for the main Healthbox device (device-wide entities)."""
    return DeviceInfo(
        name=f"{coordinator.api.serial}",
        identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
        manufacturer=MANUFACTURER,
        model=coordinator.api.description,
        hw_version=coordinator.api.warranty_number,
        sw_version=coordinator.api.firmware_version,
    )


def healthbox_room_device_info(
    coordinator: HealthboxDataUpdateCoordinator, room: HealthboxRoom
) -> DeviceInfo:
    """Return DeviceInfo for a room device."""
    return DeviceInfo(
        name=room.name,
        identifiers={
            (DOMAIN, f"{coordinator.config_entry.unique_id}_{room.room_id}")
        },
        manufacturer=MANUFACTURER,
        model="Healthbox Room",
    )


def find_room(
    coordinator: HealthboxDataUpdateCoordinator, room_id: int
) -> HealthboxRoom | None:
    """Return the current room data from the coordinator, or None if missing.

    room.room_id is really a string despite its `: int` type hint -
    pyhealthbox3 builds rooms from the API's string-keyed room dict and
    assigns the key straight through. Cast on both sides so this always
    matches correctly (see fan.py's Plan 003 post-mortem for the bug this
    once caused when it wasn't).
    """
    matching = [
        room for room in coordinator.api.rooms if int(room.room_id) == room_id
    ]
    return matching[0] if matching else None

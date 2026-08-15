"""Sensor platform for healthbox."""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)

from .const import DOMAIN, HealthboxRoom, LOGGER
from .coordinator import HealthboxDataUpdateCoordinator
from .entity import find_room, healthbox_room_device_info


@dataclass
class HealthboxRoomEntityDescriptionMixin:
    """Mixin values for Healthbox Room entities."""

    room: HealthboxRoom
    is_on: bool


@dataclass
class HealthboxRoomBinarySensorEntityDescription(
    BinarySensorEntityDescription, HealthboxRoomEntityDescriptionMixin
):
    """Class describing Healthbox Room binary sensor entities."""


def generate_binary_room_sensors_for_healthbox(
    coordinator: HealthboxDataUpdateCoordinator,
) -> list[HealthboxRoomBinarySensorEntityDescription]:
    """Generate binary sensors for each room."""
    room_binary_sensors: list[HealthboxRoomBinarySensorEntityDescription] = []

    for room in coordinator.api.rooms:
        if room.boost is not None:
            room_binary_sensors.append(
                HealthboxRoomBinarySensorEntityDescription(
                    key=f"{room.room_id}_boost_status",
                    name="Boost Status",
                    room=room,
                    is_on=lambda x: x.boost.enabled
                )
            )

    return room_binary_sensors


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    coordinator: HealthboxDataUpdateCoordinator = hass.data[DOMAIN][
        config_entry.entry_id
    ]

    room_binary_sensors = generate_binary_room_sensors_for_healthbox(
        coordinator=coordinator)

    entities = []

    for description in room_binary_sensors:
        entities.append(HealthboxRoomBinarySensor(coordinator, description))

    async_add_entities(entities)


class HealthboxRoomBinarySensor(
    CoordinatorEntity[HealthboxDataUpdateCoordinator], BinarySensorEntity
):
    """Representation of a Healthbox Room Sensor."""

    _attr_has_entity_name = True
    entity_description: HealthboxRoomBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: HealthboxDataUpdateCoordinator,
        description: HealthboxRoomBinarySensorEntityDescription,
    ) -> None:
        """Initialize Binary Sensor Domain."""
        super().__init__(coordinator)

        self.entity_description = description
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}-{description.room.room_id}-{description.key}"
        self._attr_name = description.name
        self._attr_device_info = healthbox_room_device_info(
            coordinator, description.room
        )

    @property
    def is_on(self) -> bool | None:
        """Binary Sensor native value."""
        room_id: int = int(self.entity_description.room.room_id)
        room = find_room(self.coordinator, room_id)

        if room is None:
            LOGGER.error("No matching room found for id %s", room_id)
            return None

        return self.entity_description.is_on(room)

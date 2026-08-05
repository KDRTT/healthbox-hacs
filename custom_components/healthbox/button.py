"""Button platform for healthbox - a one-tap "stop boost" per zone."""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from homeassistant.components.button import ButtonEntity

from .const import DOMAIN, HealthboxRoom
from .coordinator import HealthboxDataUpdateCoordinator
from .entity import healthbox_room_device_info


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the button platform."""
    coordinator: HealthboxDataUpdateCoordinator = hass.data[DOMAIN][
        config_entry.entry_id
    ]

    entities = [
        HealthboxStopBoostButton(coordinator, room)
        for room in coordinator.api.rooms
        if room.boost is not None
    ]
    async_add_entities(entities)


class HealthboxStopBoostButton(
    CoordinatorEntity[HealthboxDataUpdateCoordinator], ButtonEntity
):
    """A one-tap button to stop a room's boost.

    The fan entity's own toggle already does this (turning it off calls the
    same stop_room_boost), this is just a more discoverable single-purpose
    control for dashboards/automations that don't want to reach for the fan
    card.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:fan-off"
    _attr_name = "Stop Boost"

    def __init__(
        self, coordinator: HealthboxDataUpdateCoordinator, room: HealthboxRoom
    ) -> None:
        """Initialize the stop-boost button."""
        super().__init__(coordinator)

        self._room_id: int = int(room.room_id)
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}-{room.room_id}-stop_boost_button"
        )
        self._attr_device_info = healthbox_room_device_info(coordinator, room)

    async def async_press(self) -> None:
        """Stop the boost in this room."""
        await self.coordinator.stop_room_boost(room_id=self._room_id)
        await self.coordinator.async_request_refresh()

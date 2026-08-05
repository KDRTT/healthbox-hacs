"""Select platform for healthbox - default boost duration per zone."""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.restore_state import RestoreEntity

from homeassistant.components.select import SelectEntity

from .const import (
    BOOST_DEFAULTS_ALL_ROOMS_KEY,
    BOOST_DURATION_PRESETS,
    DOMAIN,
    MANUFACTURER,
    HealthboxRoom,
)
from .coordinator import HealthboxDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the select platform."""
    coordinator: HealthboxDataUpdateCoordinator = hass.data[DOMAIN][
        config_entry.entry_id
    ]

    boost_rooms = [room for room in coordinator.api.rooms if room.boost is not None]

    entities = [
        HealthboxBoostDefaultDurationSelect(coordinator, room) for room in boost_rooms
    ]
    if boost_rooms:
        entities.append(HealthboxBoostDefaultDurationSelect(coordinator, None))

    async_add_entities(entities)


class HealthboxBoostDefaultDurationSelect(
    CoordinatorEntity[HealthboxDataUpdateCoordinator], RestoreEntity, SelectEntity
):
    """The boost duration a zone's fan starts at when just toggled on.

    Used when no preset is explicitly chosen.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = list(BOOST_DURATION_PRESETS)
    _attr_icon = "mdi:timer-cog-outline"
    _attr_name = "Default Boost Duration"

    def __init__(
        self, coordinator: HealthboxDataUpdateCoordinator, room: HealthboxRoom | None
    ) -> None:
        """Initialize the default boost duration select entity.

        `room=None` is the "all rooms" boost fan's own default, kept
        separate from any single room's default.
        """
        super().__init__(coordinator)

        if room is None:
            self._defaults_key: int | str = BOOST_DEFAULTS_ALL_ROOMS_KEY
            self._attr_unique_id = (
                f"{coordinator.config_entry.entry_id}-boost_all_default_duration"
            )
            self._attr_device_info = DeviceInfo(
                name=f"{coordinator.api.serial}",
                identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
                manufacturer=MANUFACTURER,
                model=coordinator.api.description,
            )
        else:
            self._defaults_key = int(room.room_id)
            self._attr_unique_id = (
                f"{coordinator.config_entry.entry_id}-{room.room_id}-boost_default_duration"
            )
            self._attr_device_info = DeviceInfo(
                name=room.name,
                identifiers={
                    (DOMAIN, f"{coordinator.config_entry.unique_id}_{room.room_id}")
                },
                manufacturer=MANUFACTURER,
                model="Healthbox Room",
            )

    @property
    def current_option(self) -> str:
        """Return the currently configured default boost duration."""
        return self.coordinator.get_boost_defaults(self._defaults_key).duration_preset

    async def async_added_to_hass(self) -> None:
        """Restore the configured default across HA restarts."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in BOOST_DURATION_PRESETS:
            self.coordinator.get_boost_defaults(
                self._defaults_key
            ).duration_preset = last_state.state

    async def async_select_option(self, option: str) -> None:
        """Update the configured default boost duration."""
        self.coordinator.get_boost_defaults(self._defaults_key).duration_preset = option
        self.async_write_ha_state()

"""Number platform for healthbox - default boost level per zone."""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, PERCENTAGE
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from homeassistant.components.number import NumberEntity, RestoreNumber

from .const import (
    BOOST_DEFAULTS_ALL_ROOMS_KEY,
    BOOST_LEVEL_RANGE,
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
    """Set up the number platform."""
    coordinator: HealthboxDataUpdateCoordinator = hass.data[DOMAIN][
        config_entry.entry_id
    ]

    boost_rooms = [room for room in coordinator.api.rooms if room.boost is not None]

    entities = [
        HealthboxBoostDefaultLevelNumber(coordinator, room) for room in boost_rooms
    ]
    if boost_rooms:
        entities.append(HealthboxBoostDefaultLevelNumber(coordinator, None))

    async_add_entities(entities)


class HealthboxBoostDefaultLevelNumber(
    CoordinatorEntity[HealthboxDataUpdateCoordinator], RestoreNumber, NumberEntity
):
    """The boost level a zone's fan starts at when just toggled on.

    Used when no percentage is explicitly chosen (e.g. a quick tap, not
    the slider).
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_native_min_value = BOOST_LEVEL_RANGE[0]
    _attr_native_max_value = BOOST_LEVEL_RANGE[1]
    _attr_native_step = 5
    _attr_icon = "mdi:fan-chevron-up"
    _attr_name = "Default Boost Level"

    def __init__(
        self, coordinator: HealthboxDataUpdateCoordinator, room: HealthboxRoom | None
    ) -> None:
        """Initialize the default boost level number entity.

        `room=None` is the "all rooms" boost fan's own default, kept
        separate from any single room's default.
        """
        super().__init__(coordinator)

        if room is None:
            self._defaults_key: int | str = BOOST_DEFAULTS_ALL_ROOMS_KEY
            self._attr_unique_id = (
                f"{coordinator.config_entry.entry_id}-boost_all_default_level"
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
                f"{coordinator.config_entry.entry_id}-{room.room_id}-boost_default_level"
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
    def native_value(self) -> float:
        """Return the currently configured default boost level."""
        return self.coordinator.get_boost_defaults(self._defaults_key).level

    async def async_added_to_hass(self) -> None:
        """Restore the configured default across HA restarts."""
        await super().async_added_to_hass()
        last_data = await self.async_get_last_number_data()
        if last_data is not None and last_data.native_value is not None:
            self.coordinator.get_boost_defaults(self._defaults_key).level = round(
                last_data.native_value
            )

    async def async_set_native_value(self, value: float) -> None:
        """Update the configured default boost level."""
        self.coordinator.get_boost_defaults(self._defaults_key).level = round(value)
        self.async_write_ha_state()

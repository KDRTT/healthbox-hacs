"""Fan platform for healthbox - per-room boost control."""
from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util.percentage import (
    percentage_to_ranged_value,
    ranged_value_to_percentage,
)

from homeassistant.components.fan import FanEntity, FanEntityFeature

from .const import (
    BOOST_DURATION_PRESETS,
    DEFAULT_BOOST_DURATION_PRESET,
    DOMAIN,
    HealthboxRoom,
)
from .coordinator import HealthboxDataUpdateCoordinator

# Boost level range on the wire is 10-200%, not 0-100 - see
# start_room_boost's own service schema. A fan entity's percentage is
# always 0-100 with 0 meaning off, so this range is used with HA's own
# ranged_value_to_percentage/percentage_to_ranged_value helpers rather than
# hand-rolled math.
BOOST_LEVEL_RANGE = (10, 200)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the fan platform."""
    coordinator: HealthboxDataUpdateCoordinator = hass.data[DOMAIN][
        config_entry.entry_id
    ]

    entities = [
        HealthboxRoomBoostFan(coordinator, room)
        for room in coordinator.api.rooms
        if room.boost is not None
    ]
    async_add_entities(entities)


class HealthboxRoomBoostFan(
    CoordinatorEntity[HealthboxDataUpdateCoordinator], FanEntity
):
    """Represents a Healthbox room's boost as a Fan entity."""

    _attr_supported_features = (
        FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
        | FanEntityFeature.SET_SPEED
        | FanEntityFeature.PRESET_MODE
    )
    _attr_preset_modes = list(BOOST_DURATION_PRESETS)

    def __init__(
        self, coordinator: HealthboxDataUpdateCoordinator, room: HealthboxRoom
    ) -> None:
        """Initialize the boost fan entity."""
        super().__init__(coordinator)

        self._room_id: int = room.room_id
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}-{room.room_id}-boost_fan"
        )
        self._attr_name = "Boost"
        self._attr_device_info = DeviceInfo(
            name=room.name,
            identifiers={
                (
                    DOMAIN,
                    f"{coordinator.config_entry.unique_id}_{room.room_id}",
                )
            },
            manufacturer="Renson",
            model="Healthbox Room",
        )
        # There's no "current boost duration" in the API response (only
        # .remaining, a countdown) - remembered locally so set_percentage
        # and set_preset_mode can each change one axis (level or duration)
        # without clobbering the other, and so turn_on() has a sensible
        # default duration when the user hasn't touched the preset yet.
        self._last_duration_preset = DEFAULT_BOOST_DURATION_PRESET

    @property
    def _room(self):
        """Return the current room data from the coordinator, or None if missing."""
        matching = [
            room
            for room in self.coordinator.api.rooms
            if int(room.room_id) == self._room_id
        ]
        return matching[0] if matching else None

    @property
    def is_on(self) -> bool | None:
        """Return true if boost is currently active in this room."""
        room = self._room
        return room.boost.enabled if room and room.boost else False

    @property
    def percentage(self) -> int | None:
        """Return the current boost level as a percentage."""
        room = self._room
        if not room or not room.boost or not room.boost.enabled:
            return 0
        return ranged_value_to_percentage(BOOST_LEVEL_RANGE, room.boost.level)

    @property
    def preset_mode(self) -> str | None:
        """Return the currently selected boost duration preset."""
        return self._last_duration_preset

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Start a boost, defaulting to 100% level (matches the existing
        start_room_boost service's own documented default) and the
        last-used duration.
        """
        if preset_mode is not None:
            self._last_duration_preset = preset_mode
        level = (
            round(percentage_to_ranged_value(BOOST_LEVEL_RANGE, percentage))
            if percentage is not None
            else 100
        )
        await self._async_start_boost(level)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop the boost."""
        await self.coordinator.stop_room_boost(room_id=self._room_id)
        await self.coordinator.async_request_refresh()

    async def async_set_percentage(self, percentage: int) -> None:
        """Change the boost level, keeping the current duration preset."""
        if percentage == 0:
            await self.async_turn_off()
            return
        level = round(percentage_to_ranged_value(BOOST_LEVEL_RANGE, percentage))
        await self._async_start_boost(level)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Change the boost duration; re-applies immediately if already on."""
        self._last_duration_preset = preset_mode
        if self.is_on:
            room = self._room
            level = round(room.boost.level) if room and room.boost else BOOST_LEVEL_RANGE[1]
            await self._async_start_boost(level)
        else:
            self.async_write_ha_state()

    async def _async_start_boost(self, level: int) -> None:
        """Start (or restart) the boost at the given level, using the tracked duration."""
        duration_seconds = BOOST_DURATION_PRESETS[self._last_duration_preset]
        await self.coordinator.start_room_boost(
            room_id=self._room_id,
            boost_level=level,
            boost_timeout=duration_seconds,
        )
        await self.coordinator.async_request_refresh()

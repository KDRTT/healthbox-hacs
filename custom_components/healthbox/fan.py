"""Fan platform for healthbox - per-room and whole-house boost control."""
from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util.percentage import (
    percentage_to_ranged_value,
    ranged_value_to_percentage,
)

from homeassistant.components.fan import FanEntity, FanEntityFeature

from .const import (
    BOOST_DEFAULTS_ALL_ROOMS_KEY,
    BOOST_DURATION_PRESETS,
    BOOST_LEVEL_RANGE,
    DOMAIN,
    LOGGER,
    MANUFACTURER,
    HealthboxRoom,
)
from .coordinator import BoostDefaults, HealthboxDataUpdateCoordinator

_SUPPORTED_FEATURES = (
    FanEntityFeature.TURN_ON
    | FanEntityFeature.TURN_OFF
    | FanEntityFeature.SET_SPEED
    | FanEntityFeature.PRESET_MODE
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the fan platform."""
    coordinator: HealthboxDataUpdateCoordinator = hass.data[DOMAIN][
        config_entry.entry_id
    ]

    boost_rooms = [room for room in coordinator.api.rooms if room.boost is not None]

    entities: list[HealthboxBoostFan] = [
        HealthboxRoomBoostFan(coordinator, room) for room in boost_rooms
    ]
    if boost_rooms:
        entities.append(HealthboxAllRoomsBoostFan(coordinator))

    async_add_entities(entities)


class HealthboxBoostFan(CoordinatorEntity[HealthboxDataUpdateCoordinator], FanEntity):
    """Shared boost-fan behavior for a single room or for all rooms at once.

    A plain toggle-on (no percentage/preset_mode given - a tap, not the
    slider/dropdown) starts a boost at this zone's configured
    "Default Boost Level"/"Default Boost Duration" (see number.py/select.py),
    so it's immediately right without having to dial it in each time.
    Explicitly setting a percentage/preset while already on adjusts that
    one boost without changing the configured default.
    """

    _attr_supported_features = _SUPPORTED_FEATURES
    _attr_preset_modes = list(BOOST_DURATION_PRESETS)

    _defaults_key: int | str

    # --- overridden by subclasses ---

    def _target_room_ids(self) -> list[int]:
        raise NotImplementedError

    def _is_active(self) -> bool:
        raise NotImplementedError

    def _check_rooms_exist(self) -> None:
        raise NotImplementedError

    def _current_level(self) -> int:
        """Best-effort "level currently running", for adjusting preset_mode in place.

        Falls back to the configured default where there's no live value to
        read (see subclasses).
        """
        return self._defaults().level

    async def _async_apply(
        self, enable: bool, level: int | None = None, duration_preset: str | None = None
    ) -> None:
        raise NotImplementedError

    # --- shared behavior ---

    def _defaults(self) -> BoostDefaults:
        return self.coordinator.get_boost_defaults(self._defaults_key)

    @property
    def is_on(self) -> bool | None:
        """Return true if boost is currently active."""
        return self._is_active()

    @property
    def percentage(self) -> int:
        """Return the boost level rescaled to 0-100, or 0 if boost is off."""
        if not self._is_active():
            return 0
        return ranged_value_to_percentage(BOOST_LEVEL_RANGE, self._current_level())

    @property
    def preset_mode(self) -> str:
        """Return the configured default boost duration.

        There's no "current duration" to read back from the device (only
        .remaining, a countdown) - this always reflects the configured
        default, whether boost is on or off.
        """
        return self._defaults().duration_preset

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Start a boost.

        With no percentage/preset_mode given, uses this zone's configured
        defaults.
        """
        self._check_rooms_exist()
        defaults = self._defaults()
        level = (
            round(percentage_to_ranged_value(BOOST_LEVEL_RANGE, percentage))
            if percentage is not None
            else defaults.level
        )
        duration_preset = preset_mode if preset_mode is not None else defaults.duration_preset
        await self._async_apply(enable=True, level=level, duration_preset=duration_preset)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop the boost."""
        self._check_rooms_exist()
        await self._async_apply(enable=False)

    async def async_set_percentage(self, percentage: int) -> None:
        """Adjust the level of an already-active boost.

        Matches standard HA fan behavior: adjusting the slider while off
        doesn't implicitly turn boost on - use the toggle (which applies
        the configured default) or turn_on with an explicit percentage.
        """
        self._check_rooms_exist()
        if percentage == 0:
            await self._async_apply(enable=False)
            return
        if not self.is_on:
            return
        level = round(percentage_to_ranged_value(BOOST_LEVEL_RANGE, percentage))
        await self._async_apply(
            enable=True, level=level, duration_preset=self._defaults().duration_preset
        )

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Adjust the duration of an already-active boost.

        Same "only while on" behavior as async_set_percentage.
        """
        self._check_rooms_exist()
        if not self.is_on:
            return
        await self._async_apply(
            enable=True, level=self._current_level(), duration_preset=preset_mode
        )


class HealthboxRoomBoostFan(HealthboxBoostFan):
    """Boost fan for a single room."""

    def __init__(
        self, coordinator: HealthboxDataUpdateCoordinator, room: HealthboxRoom
    ) -> None:
        """Initialize the room boost fan entity."""
        super().__init__(coordinator)

        # pyhealthbox3 builds Healthbox3Room from the API's room dict (keyed
        # by string room ids, e.g. {"1": {...}}) and just assigns that
        # string straight through as .room_id, despite its own `: int` type
        # hint - cast explicitly here so every later comparison against it
        # (all of which correctly do int(room.room_id)) actually matches.
        self._room_id: int = int(room.room_id)
        self._defaults_key = self._room_id
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
            manufacturer=MANUFACTURER,
            model="Healthbox Room",
        )

    @property
    def _room(self):
        """Return the current room data from the coordinator, or None if missing."""
        matching = [
            room
            for room in self.coordinator.api.rooms
            if int(room.room_id) == self._room_id
        ]
        return matching[0] if matching else None

    def _is_active(self) -> bool:
        room = self._room
        return bool(room and room.boost and room.boost.enabled)

    def _current_level(self) -> int:
        room = self._room
        if room and room.boost and room.boost.enabled:
            return round(room.boost.level)
        return super()._current_level()

    def _target_room_ids(self) -> list[int]:
        return [self._room_id]

    def _check_rooms_exist(self) -> None:
        if self._room is None:
            raise HomeAssistantError(
                f"Room {self._room_id} is no longer reported by the Healthbox"
            )

    async def _async_apply(
        self, enable: bool, level: int | None = None, duration_preset: str | None = None
    ) -> None:
        if enable:
            await self.coordinator.start_room_boost(
                room_id=self._room_id,
                boost_level=level,
                boost_timeout=BOOST_DURATION_PRESETS[duration_preset],
            )
        else:
            await self.coordinator.stop_room_boost(room_id=self._room_id)
        await self.coordinator.async_request_refresh()


class HealthboxAllRoomsBoostFan(HealthboxBoostFan):
    """Boost fan for every room at once, at one shared level/duration.

    Mirrors how the Renson app's own "boost all" works: one shared
    level/timeout applied identically to every room, not each room at its
    own configured level. There's no such resource on the device itself -
    this synthesizes it by calling the per-room boost endpoint for every
    room in parallel.
    """

    _attr_name = "Boost All Rooms"
    _defaults_key = BOOST_DEFAULTS_ALL_ROOMS_KEY

    def __init__(self, coordinator: HealthboxDataUpdateCoordinator) -> None:
        """Initialize the whole-house boost fan entity."""
        super().__init__(coordinator)

        self._attr_unique_id = f"{coordinator.config_entry.entry_id}-boost_all_fan"
        self._attr_device_info = DeviceInfo(
            name=f"{coordinator.api.serial}",
            identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
            manufacturer=MANUFACTURER,
            model=coordinator.api.description,
        )

    def _target_room_ids(self) -> list[int]:
        # int(...) here for the same reason as HealthboxRoomBoostFan.__init__
        # - room.room_id is really a string despite its type hint.
        return [
            int(room.room_id)
            for room in self.coordinator.api.rooms
            if room.boost is not None
        ]

    def _is_active(self) -> bool:
        room_ids = self._target_room_ids()
        if not room_ids:
            return False
        active_rooms = {
            int(room.room_id): room
            for room in self.coordinator.api.rooms
            if room.boost is not None
        }
        return all(
            active_rooms[room_id].boost.enabled
            for room_id in room_ids
            if room_id in active_rooms
        )

    def _check_rooms_exist(self) -> None:
        if not self._target_room_ids():
            raise HomeAssistantError(
                "No Healthbox rooms with boost support are currently reported"
            )

    async def _async_apply(
        self, enable: bool, level: int | None = None, duration_preset: str | None = None
    ) -> None:
        room_ids = self._target_room_ids()

        async def _apply_one(room_id: int) -> None:
            if enable:
                await self.coordinator.start_room_boost(
                    room_id=room_id,
                    boost_level=level,
                    boost_timeout=BOOST_DURATION_PRESETS[duration_preset],
                )
            else:
                await self.coordinator.stop_room_boost(room_id=room_id)

        results = await asyncio.gather(
            *(_apply_one(room_id) for room_id in room_ids), return_exceptions=True
        )
        await self.coordinator.async_request_refresh()

        failed = [
            room_id
            for room_id, result in zip(room_ids, results)
            if isinstance(result, BaseException)
        ]
        if failed:
            for room_id, result in zip(room_ids, results):
                if isinstance(result, BaseException):
                    LOGGER.error(
                        "Failed to %s boost for room %s: %s",
                        "start" if enable else "stop",
                        room_id,
                        result,
                    )
            raise HomeAssistantError(
                f"Failed to {'start' if enable else 'stop'} boost for room(s): {failed}"
            )

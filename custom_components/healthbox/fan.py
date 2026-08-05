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
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util.percentage import (
    percentage_to_ranged_value,
    ranged_value_to_percentage,
)

from homeassistant.components.fan import (
    ATTR_PERCENTAGE,
    ATTR_PRESET_MODE,
    FanEntity,
    FanEntityFeature,
)

from .const import (
    BOOST_DURATION_PRESETS,
    DEFAULT_BOOST_DURATION_PRESET,
    DOMAIN,
    LOGGER,
    MANUFACTURER,
    HealthboxRoom,
)
from .coordinator import HealthboxDataUpdateCoordinator

# Boost level range on the wire is 10-200%, not 0-100 - see
# start_room_boost's own service schema. A fan entity's percentage is
# always 0-100 with 0 meaning off, so this range is used with HA's own
# ranged_value_to_percentage/percentage_to_ranged_value helpers rather than
# hand-rolled math.
BOOST_LEVEL_RANGE = (10, 200)

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


class HealthboxBoostFan(
    CoordinatorEntity[HealthboxDataUpdateCoordinator], RestoreEntity, FanEntity
):
    """Shared boost-fan behavior for a single room or for all rooms at once.

    percentage/preset_mode are local UI state - the API only reports the
    currently *active* boost's level (via .boost.level), never a "pending"
    one to start the next boost at, so the last value the user picked is
    remembered here and restored across HA restarts via RestoreEntity.
    """

    _attr_supported_features = _SUPPORTED_FEATURES
    _attr_preset_modes = list(BOOST_DURATION_PRESETS)

    def __init__(self, coordinator: HealthboxDataUpdateCoordinator) -> None:
        """Initialize the boost fan entity."""
        super().__init__(coordinator)
        self._last_duration_preset = DEFAULT_BOOST_DURATION_PRESET
        self._last_level = 100

    # --- overridden by subclasses ---

    def _target_room_ids(self) -> list[int]:
        raise NotImplementedError

    def _is_active(self) -> bool:
        raise NotImplementedError

    def _check_rooms_exist(self) -> None:
        raise NotImplementedError

    # --- shared behavior ---

    @property
    def is_on(self) -> bool | None:
        """Return true if boost is currently active."""
        return self._is_active()

    @property
    def percentage(self) -> int:
        """Return the boost level rescaled to 0-100, or 0 if boost is off."""
        if not self._is_active():
            return 0
        return ranged_value_to_percentage(BOOST_LEVEL_RANGE, self._last_level)

    @property
    def preset_mode(self) -> str | None:
        """Return the currently selected boost duration preset."""
        return self._last_duration_preset

    async def async_added_to_hass(self) -> None:
        """Restore the last set percentage/preset_mode across restarts."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is None:
            return
        percentage = last_state.attributes.get(ATTR_PERCENTAGE)
        # A restored 0 means "was off" - it carries no usable level
        # information, so leave the coordinator-seeded default in place.
        if percentage:
            self._last_level = round(
                percentage_to_ranged_value(BOOST_LEVEL_RANGE, percentage)
            )
        preset_mode = last_state.attributes.get(ATTR_PRESET_MODE)
        if preset_mode in BOOST_DURATION_PRESETS:
            self._last_duration_preset = preset_mode

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
        self._check_rooms_exist()
        if preset_mode is not None:
            self._last_duration_preset = preset_mode
        if percentage is not None:
            self._last_level = round(
                percentage_to_ranged_value(BOOST_LEVEL_RANGE, percentage)
            )
        await self._async_start_boost()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop the boost."""
        self._check_rooms_exist()
        await self._async_apply(enable=False)

    async def async_set_percentage(self, percentage: int) -> None:
        """Change the boost level, keeping the current duration preset."""
        self._check_rooms_exist()
        if percentage == 0:
            await self._async_apply(enable=False)
            return
        self._last_level = round(
            percentage_to_ranged_value(BOOST_LEVEL_RANGE, percentage)
        )
        await self._async_start_boost()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Change the boost duration; re-applies immediately if already on."""
        self._check_rooms_exist()
        self._last_duration_preset = preset_mode
        if self.is_on:
            await self._async_start_boost()
        else:
            self.async_write_ha_state()

    async def _async_start_boost(self) -> None:
        """(Re)start the boost at the tracked level/duration.

        Confirmed on real hardware by other Healthbox 3 integration authors:
        starting a boost while one is already active does not adjust it in
        place - it restarts the countdown from the full duration. Not
        surprising given the API only exposes "set enabled+level+timeout",
        never "adjust the running one".
        """
        await self._async_apply(enable=True)

    async def _async_apply(self, enable: bool) -> None:
        raise NotImplementedError


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

    def _target_room_ids(self) -> list[int]:
        return [self._room_id]

    def _check_rooms_exist(self) -> None:
        if self._room is None:
            raise HomeAssistantError(
                f"Room {self._room_id} is no longer reported by the Healthbox"
            )

    async def _async_apply(self, enable: bool) -> None:
        if enable:
            await self.coordinator.start_room_boost(
                room_id=self._room_id,
                boost_level=self._last_level,
                boost_timeout=BOOST_DURATION_PRESETS[self._last_duration_preset],
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

    async def _async_apply(self, enable: bool) -> None:
        room_ids = self._target_room_ids()

        async def _apply_one(room_id: int) -> None:
            if enable:
                await self.coordinator.start_room_boost(
                    room_id=room_id,
                    boost_level=self._last_level,
                    boost_timeout=BOOST_DURATION_PRESETS[self._last_duration_preset],
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

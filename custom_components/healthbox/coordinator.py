"""DataUpdateCoordinator for healthbox."""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_HOST
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from homeassistant.exceptions import ConfigEntryAuthFailed


from pyhealthbox3.healthbox3 import (
    Healthbox3,
    Healthbox3ApiClientAuthenticationError,
    Healthbox3ApiClientError,
)

from .const import (
    DEFAULT_BOOST_DURATION_PRESET,
    DEFAULT_BOOST_LEVEL,
    DOMAIN,
    LOGGER,
    SCAN_INTERVAL,
)


@dataclass
class BoostDefaults:
    """A zone's configured "what a plain boost toggle-on should do".

    Lives on the coordinator, shared between each zone's Fan (reads it for
    a plain turn_on with no explicit percentage/preset_mode) and its
    Number/Select "Default Boost Level"/"Default Boost Duration" entities
    (the only things that ever write to it). The dataclass instance itself
    is the source of truth; the config entities are just a UI for it and
    restore its fields from their own RestoreEntity state at startup.
    """

    level: int = DEFAULT_BOOST_LEVEL
    duration_preset: str = DEFAULT_BOOST_DURATION_PRESET


# https://developers.home-assistant.io/docs/integration_fetching_data#coordinated-single-api-poll-for-data-for-all-entities
class HealthboxDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the API."""

    config_entry: ConfigEntry

    api: Healthbox3

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, api: Healthbox3
    ) -> None:
        """Initialize."""

        self.hass = hass
        self.config_entry = entry
        self.host: str = entry.data[CONF_HOST]
        self.api: Healthbox3 = api
        self.boost_defaults: dict[int | str, BoostDefaults] = {}

        super().__init__(
            hass=hass,
            logger=LOGGER,
            name=f"{DOMAIN} - {self.host}",
            update_interval=SCAN_INTERVAL,
        )

    def get_boost_defaults(self, key: int | str) -> BoostDefaults:
        """Return the boost defaults for a room id or BOOST_DEFAULTS_ALL_ROOMS_KEY, creating them if needed."""
        return self.boost_defaults.setdefault(key, BoostDefaults())

    async def change_room_profile(
        self, room_id: int, profile_name: str
    ):
        """Start Boosting HB Room."""
        await self.api.async_change_room_profile(
            room_id=room_id, profile_name=profile_name
        )

    async def start_room_boost(
        self, room_id: int, boost_level: int, boost_timeout: int
    ):
        """Start Boosting HB Room."""
        await self.api.async_start_room_boost(
            room_id=room_id, boost_level=boost_level, boost_timeout=boost_timeout
        )

    async def stop_room_boost(self, room_id: int):
        """Stop Boosting HB Room."""
        await self.api.async_stop_room_boost(room_id=room_id)

    async def _async_update_data(self):
        """Update data via library."""
        try:
            await self.api.async_get_data()

        except Healthbox3ApiClientAuthenticationError as exception:
            raise ConfigEntryAuthFailed(exception) from exception
        except Healthbox3ApiClientError as exception:
            raise UpdateFailed(exception) from exception

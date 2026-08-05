"""Serial-number lookup used for device identity (config flow + migration).

The v1 API (``/v1/api/data/current``) is unauthenticated regardless of
whether an API key/advanced features are configured, so this deliberately
avoids going through the heavier ``pyhealthbox3`` v2 client just to read
one field.
"""
from __future__ import annotations

import asyncio

from aiohttp import ClientError, ClientSession
import async_timeout

from .const import LOGGER

_SERIAL_ENDPOINT = "/v1/api/data/current"
_REQUEST_TIMEOUT = 10


async def async_fetch_serial(host: str, session: ClientSession) -> str | None:
    """Return the device's serial number, or None if it can't be reached."""
    try:
        async with async_timeout.timeout(_REQUEST_TIMEOUT):
            response = await session.get(f"http://{host}{_SERIAL_ENDPOINT}")
            response.raise_for_status()
            data = await response.json()
    # asyncio.TimeoutError predates the 3.11 unification with the builtin
    # TimeoutError - catch both explicitly since HA's own minimum Python
    # version has moved over time.
    except (ClientError, TimeoutError, asyncio.TimeoutError) as exception:
        LOGGER.debug("Could not fetch serial from %s: %s", host, exception)
        return None

    return data.get("serial")

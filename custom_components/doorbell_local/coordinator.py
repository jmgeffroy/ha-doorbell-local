"""DataUpdateCoordinator : interroge périodiquement la liste des cartes."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .protocol import DoorbellClient, DoorbellError

_LOGGER = logging.getLogger(__name__)


class DoorbellCoordinator(DataUpdateCoordinator[list[dict]]):
    """Poll la doorbell et expose la liste des cartes."""

    def __init__(self, hass: HomeAssistant, client: DoorbellClient, scan_interval: int) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.client = client

    async def _async_update_data(self) -> list[dict]:
        try:
            return await self.hass.async_add_executor_job(self.client.list_cards)
        except DoorbellError as err:
            raise UpdateFailed(str(err)) from err

"""REST and SSE update coordinator for YouTube Audio Downloader."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import timedelta
from typing import Any, cast, override

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    InfoData,
    JobData,
    ServerSentEvent,
    StatusData,
    YoutubeAudioDownloaderApiClient,
    YoutubeAudioDownloaderAuthenticationError,
    YoutubeAudioDownloaderConnectionError,
    YoutubeAudioDownloaderResponseError,
    parse_status,
)
from .const import STATE_IDLE, TERMINAL_STATES

_LOGGER = logging.getLogger(__name__)
_RECONCILE_INTERVAL = timedelta(minutes=5)
_MAX_RECONNECT_DELAY = 30


class YoutubeAudioDownloaderCoordinator(DataUpdateCoordinator[StatusData]):
    """Coordinate initial REST state, SSE pushes, and REST reconciliation."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry[Any],
        client: YoutubeAudioDownloaderApiClient,
        info: InfoData,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name="YouTube Audio Downloader",
            update_interval=_RECONCILE_INTERVAL,
        )
        self.client = client
        self.info = info
        self.entry = entry
        self._event_task: asyncio.Task[None] | None = None
        self._stopping = False

    async def async_start(self) -> None:
        """Start the event stream after the first REST snapshot."""
        if self._event_task is None:
            self._event_task = self.entry.async_create_background_task(
                self.hass,
                self._async_event_loop(),
                name="youtube_audio_downloader event stream",
            )

    @override
    async def _async_update_data(self) -> StatusData:
        """Fetch and validate a complete REST snapshot."""
        try:
            return await self.client.async_get_status()
        except YoutubeAudioDownloaderAuthenticationError as err:
            raise ConfigEntryAuthFailed("The App rejected its discovery token") from err
        except (
            YoutubeAudioDownloaderConnectionError,
            YoutubeAudioDownloaderResponseError,
        ) as err:
            raise UpdateFailed("Unable to refresh App status") from err

    @override
    async def async_shutdown(self) -> None:
        """Stop SSE and close its response cleanly."""
        if self._stopping:
            return
        self._stopping = True
        await self.client.async_close()
        if self._event_task is not None:
            self._event_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._event_task
            self._event_task = None
        await super().async_shutdown()

    async def _async_event_loop(self) -> None:
        """Reconnect the SSE stream with bounded exponential backoff."""
        delay = 1
        first_connection = True
        while not self._stopping:
            try:
                if not first_connection:
                    snapshot = await self._async_update_data()
                    self.async_set_updated_data(snapshot)
                first_connection = False

                async for event in self.client.async_events():
                    delay = 1
                    await self._async_handle_event(event)
            except asyncio.CancelledError:
                raise
            except ConfigEntryAuthFailed as err:
                self.async_set_update_error(err)
                return
            except (
                YoutubeAudioDownloaderAuthenticationError,
                YoutubeAudioDownloaderConnectionError,
                YoutubeAudioDownloaderResponseError,
                UpdateFailed,
            ) as err:
                if self._stopping:
                    return
                self.async_set_update_error(
                    UpdateFailed("App event stream unavailable")
                )
                _LOGGER.debug("Event stream reconnect scheduled", exc_info=err)
                await asyncio.sleep(delay)
                delay = min(delay * 2, _MAX_RECONNECT_DELAY)

    async def _async_handle_event(self, event: ServerSentEvent) -> None:
        """Apply immediate job updates and reconcile structural changes."""
        if event.event == "status":
            try:
                self.async_set_updated_data(parse_status(event.data))
            except YoutubeAudioDownloaderResponseError:
                await self.async_refresh()
            return

        if event.event == "job_updated" and isinstance(event.data.get("job"), dict):
            self._async_apply_job(event.data["job"])
            return

        if event.event in {"job_completed", "job_failed", "queue_changed"}:
            await self.async_refresh()

    @callback
    def _async_apply_job(self, raw_job: dict[str, Any]) -> None:
        """Update progress immediately from a full job SSE payload."""
        if self.data is None or not isinstance(raw_job.get("state"), str):
            return
        job = cast("JobData", dict(raw_job))
        state = job["state"]
        if state in TERMINAL_STATES:
            current: JobData | None = None
            progress: float | None = 0
            state = STATE_IDLE
        else:
            current = job
            raw_progress = job.get("progress")
            progress = (
                float(raw_progress) if isinstance(raw_progress, int | float) else None
            )
        self.async_set_updated_data(
            StatusData(
                state=state,
                progress=progress,
                queue_length=self.data["queue_length"],
                current=current,
            )
        )

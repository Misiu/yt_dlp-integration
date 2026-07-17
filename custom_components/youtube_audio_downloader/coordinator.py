"""REST and SSE update coordinator for YouTube Audio Downloader."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Mapping
from contextlib import suppress
from datetime import timedelta
from pathlib import PurePosixPath, PureWindowsPath
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
from .const import (
    EVENT_DOWNLOAD_COMPLETED,
    EVENT_QUEUE_COMPLETED,
    STATE_IDLE,
    TERMINAL_STATES,
)

_LOGGER = logging.getLogger(__name__)
_RECONCILE_INTERVAL = timedelta(minutes=5)
_MAX_RECONNECT_DELAY = 30
_HISTORY_PAGE_SIZE = 100
_MAX_TRACKED_JOB_IDS = 1000
_MAX_EVENT_TEXT_LENGTH = 512
_MAX_EVENT_PATH_LENGTH = 1024


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
        self._processed_job_ids: set[str] = set()
        self._processed_job_order: deque[str] = deque()
        self._last_queue_completed_job_id: str | None = None
        self._completion_tracking_initialized = False

    async def async_initialize_completion_tracking(self) -> None:
        """Remember existing history without replaying old completion events."""
        try:
            history = await self.client.async_get_history(page_size=_HISTORY_PAGE_SIZE)
        except YoutubeAudioDownloaderAuthenticationError as err:
            raise ConfigEntryAuthFailed("The App rejected its discovery token") from err
        except (
            YoutubeAudioDownloaderConnectionError,
            YoutubeAudioDownloaderResponseError,
        ) as err:
            raise UpdateFailed("Unable to initialize App history") from err
        self._seed_completion_tracking(history["items"])

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
                    await self._async_reconcile_completion_events(snapshot)
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

        if event.event == "download_completed":
            if isinstance(event.data.get("job"), dict):
                self._async_emit_download_completed(event.data["job"])
            return

        if event.event == "queue_completed":
            if isinstance(event.data.get("last_job"), dict):
                last_job = event.data["last_job"]
                self._async_emit_download_completed(last_job)
                self._async_emit_queue_completed(last_job)
            return

        if event.event in {"job_completed", "job_failed", "queue_changed"}:
            await self.async_refresh()

    async def _async_reconcile_completion_events(self, snapshot: StatusData) -> None:
        """Replay completion signals missed during a short SSE disconnect."""
        history = await self.client.async_get_history(page_size=_HISTORY_PAGE_SIZE)
        jobs = history["items"]
        if not self._completion_tracking_initialized:
            self._seed_completion_tracking(jobs)
            return

        for job in reversed(jobs):
            self._async_emit_download_completed(job)

        if snapshot["queue_length"] == 0 and snapshot["current"] is None and jobs:
            self._async_emit_queue_completed(jobs[0])

    @callback
    def _seed_completion_tracking(self, jobs: list[JobData]) -> None:
        """Set a history baseline so integration startup emits no stale events."""
        for job in reversed(jobs):
            if job.get("state") == "completed" and (job_id := _terminal_job_id(job)):
                self._remember_job_id(job_id)
        if jobs and (job_id := _terminal_job_id(jobs[0])):
            self._last_queue_completed_job_id = job_id
        self._completion_tracking_initialized = True

    @callback
    def _async_emit_download_completed(self, raw_job: Mapping[str, Any]) -> None:
        """Fire one bounded HA event for a newly completed MP3."""
        if raw_job.get("state") != "completed" or not (
            job_id := _terminal_job_id(raw_job)
        ):
            return
        if not self._remember_job_id(job_id):
            return
        self.hass.bus.async_fire(
            EVENT_DOWNLOAD_COMPLETED,
            self._completion_event_data(raw_job),
        )

    @callback
    def _async_emit_queue_completed(self, raw_job: Mapping[str, Any]) -> None:
        """Fire one bounded HA event after the App queue becomes empty."""
        if not (job_id := _terminal_job_id(raw_job)):
            return
        if self._last_queue_completed_job_id == job_id:
            return
        self._last_queue_completed_job_id = job_id
        event_data = self._completion_event_data(raw_job)
        event_data["queue_length"] = 0
        self.hass.bus.async_fire(EVENT_QUEUE_COMPLETED, event_data)

    @callback
    def _remember_job_id(self, job_id: str) -> bool:
        """Remember a processed job ID in a bounded in-memory set."""
        if job_id in self._processed_job_ids:
            return False
        if len(self._processed_job_order) >= _MAX_TRACKED_JOB_IDS:
            oldest = self._processed_job_order.popleft()
            self._processed_job_ids.remove(oldest)
        self._processed_job_order.append(job_id)
        self._processed_job_ids.add(job_id)
        return True

    def _completion_event_data(self, raw_job: Mapping[str, Any]) -> dict[str, Any]:
        """Return the stable, local-only subset exposed on the HA event bus."""
        file_size = raw_job.get("file_size")
        if (
            not isinstance(file_size, int)
            or isinstance(file_size, bool)
            or file_size < 0
        ):
            file_size = None
        return {
            "instance_id": _bounded_text(self.info.get("instance_id"), 128),
            "job_id": _bounded_text(raw_job.get("id"), 128),
            "state": _bounded_text(raw_job.get("state"), 64),
            "title": _bounded_text(raw_job.get("title"), _MAX_EVENT_TEXT_LENGTH),
            "artist": _bounded_text(raw_job.get("artist"), _MAX_EVENT_TEXT_LENGTH),
            "relative_output_path": _relative_output_path(raw_job.get("output_file")),
            "file_size": file_size,
            "completed_at": _bounded_text(raw_job.get("finished_at"), 64),
        }

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


def _terminal_job_id(raw_job: Mapping[str, Any]) -> str | None:
    """Return a bounded job ID when the payload represents a terminal job."""
    if raw_job.get("state") not in TERMINAL_STATES:
        return None
    job_id = _bounded_text(raw_job.get("id"), 128)
    return job_id or None


def _bounded_text(value: Any, limit: int) -> str | None:
    """Return a bounded string or None for invalid event data."""
    if not isinstance(value, str):
        return None
    return value[:limit]


def _relative_output_path(value: Any) -> str | None:
    """Expose only a bounded relative path from the App media root."""
    path = _bounded_text(value, _MAX_EVENT_PATH_LENGTH)
    if not path:
        return None
    posix_path = PurePosixPath(path)
    windows_path = PureWindowsPath(path)
    if (
        posix_path.is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or ".." in posix_path.parts
        or ".." in windows_path.parts
    ):
        return None
    return path

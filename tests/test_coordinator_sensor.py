"""Tests for push updates, cleanup, and entity availability."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.youtube_audio_downloader import (
    YoutubeAudioDownloaderRuntimeData,
)
from custom_components.youtube_audio_downloader.api import (
    ServerSentEvent,
    YoutubeAudioDownloaderConnectionError,
)
from custom_components.youtube_audio_downloader.const import (
    DOMAIN,
    EVENT_DOWNLOAD_COMPLETED,
    EVENT_QUEUE_COMPLETED,
)
from custom_components.youtube_audio_downloader.coordinator import (
    YoutubeAudioDownloaderCoordinator,
)
from custom_components.youtube_audio_downloader.sensor import (
    SENSORS,
    YoutubeAudioDownloaderSensor,
)

from .const import DISCOVERY_CONFIG, IDLE_STATUS, INFO


async def test_event_stream_reconnects_and_reconciles(hass, monkeypatch) -> None:
    """A lost SSE connection backs off, refreshes REST, and resumes push updates."""
    entry = MockConfigEntry(domain=DOMAIN, data=DISCOVERY_CONFIG)
    entry.add_to_hass(hass)

    class ReconnectingClient:
        event_calls = 0
        history_calls = 0
        status_calls = 0
        coordinator = None

        async def async_get_status(self):
            self.status_calls += 1
            return IDLE_STATUS

        async def async_get_history(self, *, page_size):
            self.history_calls += 1
            items = [
                {
                    "id": "baseline-id",
                    "state": "completed",
                    "title": "Existing track",
                }
            ]
            if self.history_calls > 1:
                items.insert(
                    0,
                    {
                        "id": "missed-id",
                        "state": "completed",
                        "title": "Recovered track",
                        "artist": "Test artist",
                        "output_file": "youtube_audio/recovered.mp3",
                        "file_size": 123,
                        "finished_at": "2026-07-17T10:00:00Z",
                    },
                )
            return {"items": items, "page": 1, "page_size": page_size, "total": 2}

        async def async_events(self):
            self.event_calls += 1
            if self.event_calls == 1:
                raise YoutubeAudioDownloaderConnectionError
            yield ServerSentEvent(
                "job_updated",
                {"job": {"id": "job-id", "state": "downloading", "progress": 8}},
            )
            self.coordinator._stopping = True

    client = ReconnectingClient()
    coordinator = YoutubeAudioDownloaderCoordinator(hass, entry, client, INFO)
    client.coordinator = coordinator
    coordinator.async_set_updated_data(IDLE_STATUS)
    completed_events = []
    hass.bus.async_listen(
        EVENT_DOWNLOAD_COMPLETED,
        lambda event: completed_events.append(event.data),
    )
    await coordinator.async_initialize_completion_tracking()
    sleep = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep)

    await coordinator._async_event_loop()

    assert client.event_calls == 2
    assert client.status_calls == 1
    assert client.history_calls == 2
    assert coordinator.data["progress"] == 8
    assert [event["job_id"] for event in completed_events] == ["missed-id"]
    sleep.assert_awaited_once_with(1)


async def test_sse_job_update_and_shutdown_cleanup(hass) -> None:
    """Job events update sensors immediately and shutdown closes/cancels SSE."""
    entry = MockConfigEntry(domain=DOMAIN, data=DISCOVERY_CONFIG)
    entry.add_to_hass(hass)
    client = SimpleNamespace(async_close=AsyncMock())
    coordinator = YoutubeAudioDownloaderCoordinator(hass, entry, client, INFO)
    coordinator.async_set_updated_data(IDLE_STATUS)

    await coordinator._async_handle_event(
        ServerSentEvent(
            "job_updated",
            {
                "job": {
                    "id": "job-id",
                    "state": "downloading",
                    "progress": 36.4,
                    "title": "Test track",
                    "artist": "Test artist",
                }
            },
        )
    )
    assert coordinator.data["state"] == "downloading"
    assert coordinator.data["progress"] == 36.4

    coordinator._event_task = asyncio.create_task(asyncio.sleep(60))
    await coordinator.async_shutdown()
    client.async_close.assert_awaited_once()
    assert coordinator._event_task is None


async def test_completion_events_are_safe_bounded_and_deduplicated(hass) -> None:
    """Completion SSE events become stable HA bus events without private fields."""
    entry = MockConfigEntry(domain=DOMAIN, data=DISCOVERY_CONFIG)
    entry.add_to_hass(hass)
    coordinator = YoutubeAudioDownloaderCoordinator(
        hass, entry, SimpleNamespace(), INFO
    )
    completed_events = []
    queue_events = []
    hass.bus.async_listen(
        EVENT_DOWNLOAD_COMPLETED,
        lambda event: completed_events.append(event.data),
    )
    hass.bus.async_listen(
        EVENT_QUEUE_COMPLETED,
        lambda event: queue_events.append(event.data),
    )
    job = {
        "id": "job-id",
        "state": "completed",
        "title": "T" * 600,
        "artist": "Test artist",
        "url": "private-source-value",
        "output_file": "youtube_audio/Test artist - Test track.mp3",
        "file_size": 456,
        "finished_at": "2026-07-17T10:00:00Z",
    }

    await coordinator._async_handle_event(
        ServerSentEvent("download_completed", {"job": job})
    )
    await coordinator._async_handle_event(
        ServerSentEvent("download_completed", {"job": job})
    )
    await coordinator._async_handle_event(
        ServerSentEvent("queue_completed", {"queue_length": 0, "last_job": job})
    )
    await coordinator._async_handle_event(
        ServerSentEvent("queue_completed", {"queue_length": 0, "last_job": job})
    )

    assert len(completed_events) == 1
    assert len(queue_events) == 1
    assert completed_events[0] == {
        "instance_id": INFO["instance_id"],
        "job_id": "job-id",
        "state": "completed",
        "title": "T" * 512,
        "artist": "Test artist",
        "relative_output_path": "youtube_audio/Test artist - Test track.mp3",
        "file_size": 456,
        "completed_at": "2026-07-17T10:00:00Z",
    }
    assert queue_events[0] == {**completed_events[0], "queue_length": 0}
    assert "private-source-value" not in str(completed_events[0])


async def test_queue_completed_accepts_failed_job_and_hides_absolute_path(hass) -> None:
    """A final failure emits only queue completion and never leaks a host path."""
    entry = MockConfigEntry(domain=DOMAIN, data=DISCOVERY_CONFIG)
    entry.add_to_hass(hass)
    coordinator = YoutubeAudioDownloaderCoordinator(
        hass, entry, SimpleNamespace(), INFO
    )
    completed_events = []
    queue_events = []
    hass.bus.async_listen(
        EVENT_DOWNLOAD_COMPLETED,
        lambda event: completed_events.append(event.data),
    )
    hass.bus.async_listen(
        EVENT_QUEUE_COMPLETED,
        lambda event: queue_events.append(event.data),
    )

    await coordinator._async_handle_event(
        ServerSentEvent(
            "queue_completed",
            {
                "last_job": {
                    "id": "failed-id",
                    "state": "failed",
                    "output_file": "C:\\private\\track.mp3",
                }
            },
        )
    )

    assert completed_events == []
    assert queue_events[0]["job_id"] == "failed-id"
    assert queue_events[0]["relative_output_path"] is None


async def test_sensor_values_metadata_and_availability(hass) -> None:
    """Entities share coordinator availability and prefer parsed artist metadata."""
    entry = MockConfigEntry(domain=DOMAIN, data=DISCOVERY_CONFIG)
    entry.add_to_hass(hass)
    client = SimpleNamespace()
    coordinator = YoutubeAudioDownloaderCoordinator(hass, entry, client, INFO)
    coordinator.async_set_updated_data(
        {
            "state": "downloading",
            "progress": 12.5,
            "queue_length": 3,
            "current": {
                "id": "job-id",
                "state": "downloading",
                "title": "Test track",
                "artist": "Parsed artist",
                "channel": "Fallback channel",
            },
        }
    )
    entry.runtime_data = YoutubeAudioDownloaderRuntimeData(client, coordinator, INFO)

    queue = YoutubeAudioDownloaderSensor(entry, SENSORS[0])
    state = YoutubeAudioDownloaderSensor(entry, SENSORS[1])
    progress = YoutubeAudioDownloaderSensor(entry, SENSORS[2])
    assert queue.native_value == 3
    assert state.native_value == "downloading"
    assert progress.native_value == 12.5
    assert state.extra_state_attributes == {
        "job_id": "job-id",
        "title": "Test track",
        "artist": "Parsed artist",
    }
    assert state.available
    coordinator.last_update_success = False
    assert not state.available

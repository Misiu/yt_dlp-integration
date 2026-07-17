"""Tests for top-level action registration and App error mapping."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.exceptions import ServiceValidationError
from homeassistant.setup import async_setup_component

from custom_components.youtube_audio_downloader.api import (
    YoutubeAudioDownloaderResponseError,
)
from custom_components.youtube_audio_downloader.const import (
    DOMAIN,
    SERVICE_DOWNLOAD,
    SERVICE_DOWNLOAD_BATCH,
)


async def test_actions_are_registered_once_and_forward_payloads(hass) -> None:
    """Both actions are available before entry setup and send exact payloads."""
    assert await async_setup_component(hass, DOMAIN, {})
    assert hass.services.has_service(DOMAIN, SERVICE_DOWNLOAD)
    assert hass.services.has_service(DOMAIN, SERVICE_DOWNLOAD_BATCH)

    client = SimpleNamespace(
        async_download=AsyncMock(),
        async_download_batch=AsyncMock(),
    )
    coordinator = SimpleNamespace(async_request_refresh=AsyncMock())
    runtime = SimpleNamespace(client=client, coordinator=coordinator)
    with patch(
        "custom_components.youtube_audio_downloader._runtime_data",
        return_value=runtime,
    ):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_DOWNLOAD,
            {"url": "test-value"},
            blocking=True,
        )
        await hass.services.async_call(
            DOMAIN,
            SERVICE_DOWNLOAD_BATCH,
            {"urls": ["first-value", "second-value"]},
            blocking=True,
        )

    client.async_download.assert_awaited_once_with("test-value")
    client.async_download_batch.assert_awaited_once_with(
        ["first-value", "second-value"]
    )
    assert coordinator.async_request_refresh.await_count == 2


async def test_app_error_is_localized(hass) -> None:
    """Stable App codes become translatable ServiceValidationError instances."""
    assert await async_setup_component(hass, DOMAIN, {})
    runtime = SimpleNamespace(
        client=SimpleNamespace(
            async_download=AsyncMock(
                side_effect=YoutubeAudioDownloaderResponseError(
                    409, "queue_full", "Queue full."
                )
            )
        ),
        coordinator=SimpleNamespace(async_request_refresh=AsyncMock()),
    )
    with (
        patch(
            "custom_components.youtube_audio_downloader._runtime_data",
            return_value=runtime,
        ),
        pytest.raises(ServiceValidationError) as error,
    ):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_DOWNLOAD,
            {"url": "test-value"},
            blocking=True,
        )
    assert error.value.translation_key == "queue_full"

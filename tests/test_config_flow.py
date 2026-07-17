"""Tests for Supervisor discovery and confirmation."""

from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import (
    SOURCE_HASSIO,
    SOURCE_REAUTH,
    SOURCE_USER,
    ConfigEntryState,
)
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.hassio import HassioServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.youtube_audio_downloader.api import (
    YoutubeAudioDownloaderAuthenticationError,
)
from custom_components.youtube_audio_downloader.const import DOMAIN

from .const import DISCOVERY_CONFIG, INFO, INSTANCE_ID


def discovery(config=None) -> HassioServiceInfo:
    """Build Supervisor service information."""
    return HassioServiceInfo(
        config=config or dict(DISCOVERY_CONFIG),
        name="YouTube Audio Downloader",
        slug="youtube_audio_downloader",
        uuid="a" * 32,
    )


async def test_discovery_requires_confirmation(hass) -> None:
    """A valid discovery verifies identity and always asks for confirmation."""
    with (
        patch(
            "custom_components.youtube_audio_downloader.config_flow."
            "YoutubeAudioDownloaderApiClient.async_get_info",
            AsyncMock(return_value=INFO),
        ) as get_info,
        patch(
            "custom_components.youtube_audio_downloader.async_setup_entry",
            AsyncMock(return_value=True),
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_HASSIO},
            data=discovery(),
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "hassio_confirm"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == DISCOVERY_CONFIG
    assert result["result"].unique_id == INSTANCE_ID
    assert get_info.await_count == 2


async def test_rediscovery_updates_connection_and_reloads(hass) -> None:
    """A matching instance gets new endpoint credentials without another entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=INSTANCE_ID,
        data=DISCOVERY_CONFIG,
        source=SOURCE_HASSIO,
    )
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    updated = {**DISCOVERY_CONFIG, "host": "replacement-app", "auth_token": "new-token"}

    with (
        patch(
            "custom_components.youtube_audio_downloader.config_flow."
            "YoutubeAudioDownloaderApiClient.async_get_info",
            AsyncMock(return_value=INFO),
        ),
        patch.object(hass.config_entries, "async_schedule_reload") as reload_entry,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_HASSIO},
            data=discovery(updated),
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert dict(entry.data) == updated
    reload_entry.assert_called_once_with(entry.entry_id)


async def test_invalid_version_and_authentication_failure(hass) -> None:
    """Invalid API versions and rejected tokens abort with actionable reasons."""
    invalid = {**DISCOVERY_CONFIG, "api_version": 2}
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_HASSIO}, data=discovery(invalid)
    )
    assert result["reason"] == "incompatible_api_version"

    with patch(
        "custom_components.youtube_audio_downloader.config_flow."
        "YoutubeAudioDownloaderApiClient.async_get_info",
        AsyncMock(side_effect=YoutubeAudioDownloaderAuthenticationError),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_HASSIO},
            data=discovery(),
        )
    assert result["reason"] == "invalid_auth"


async def test_manual_flow_never_requests_credentials(hass) -> None:
    """The user step only explains App discovery and contains no fields."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["data_schema"] is None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["reason"] == "discovery_required"


async def test_reauth_never_requests_generated_token(hass) -> None:
    """An authentication repair instructs rediscovery and has no token field."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=INSTANCE_ID,
        data=DISCOVERY_CONFIG,
        source=SOURCE_HASSIO,
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=dict(entry.data),
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["data_schema"] is None

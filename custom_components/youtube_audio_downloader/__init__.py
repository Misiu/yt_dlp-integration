"""YouTube Audio Downloader integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    ServiceValidationError,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import (
    InfoData,
    YoutubeAudioDownloaderApiClient,
    YoutubeAudioDownloaderAuthenticationError,
    YoutubeAudioDownloaderConnectionError,
    YoutubeAudioDownloaderResponseError,
)
from .const import (
    API_VERSION,
    ATTR_URL,
    ATTR_URLS,
    CONF_AUTH_TOKEN,
    CONF_INSTANCE_ID,
    DOMAIN,
    PLATFORMS,
    SERVICE_DOWNLOAD,
    SERVICE_DOWNLOAD_BATCH,
)
from .coordinator import YoutubeAudioDownloaderCoordinator


@dataclass(slots=True)
class YoutubeAudioDownloaderRuntimeData:
    """Objects owned by a config entry for its loaded lifetime."""

    client: YoutubeAudioDownloaderApiClient
    coordinator: YoutubeAudioDownloaderCoordinator
    info: InfoData


type YoutubeAudioDownloaderConfigEntry = ConfigEntry[YoutubeAudioDownloaderRuntimeData]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_DOWNLOAD_SCHEMA = vol.Schema({vol.Required(ATTR_URL): cv.string})
_DOWNLOAD_BATCH_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_URLS): vol.All(
            cv.ensure_list, [cv.string], vol.Length(min=1, max=50)
        )
    }
)


async def async_setup(hass: HomeAssistant, _config: ConfigType) -> bool:
    """Register domain actions once, independently of config entries."""

    async def async_handle_download(call: ServiceCall) -> None:
        runtime = _runtime_data(hass)
        try:
            await runtime.client.async_download(call.data[ATTR_URL])
        except Exception as err:
            raise _service_error(err) from err
        await runtime.coordinator.async_request_refresh()

    async def async_handle_download_batch(call: ServiceCall) -> None:
        runtime = _runtime_data(hass)
        try:
            await runtime.client.async_download_batch(list(call.data[ATTR_URLS]))
        except Exception as err:
            raise _service_error(err) from err
        await runtime.coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN,
        SERVICE_DOWNLOAD,
        async_handle_download,
        schema=_DOWNLOAD_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_DOWNLOAD_BATCH,
        async_handle_download_batch,
        schema=_DOWNLOAD_BATCH_SCHEMA,
    )
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: YoutubeAudioDownloaderConfigEntry
) -> bool:
    """Set up a discovered App instance."""
    client = YoutubeAudioDownloaderApiClient(
        async_get_clientsession(hass),
        entry.data[CONF_HOST],
        entry.data[CONF_PORT],
        entry.data[CONF_AUTH_TOKEN],
    )
    try:
        info = await client.async_get_info()
    except YoutubeAudioDownloaderAuthenticationError as err:
        raise ConfigEntryAuthFailed("The App rejected its discovery token") from err
    except (
        YoutubeAudioDownloaderConnectionError,
        YoutubeAudioDownloaderResponseError,
    ) as err:
        raise ConfigEntryNotReady("Unable to connect to the App") from err
    if (
        info.get("api_version") != API_VERSION
        or info.get("instance_id") != entry.data[CONF_INSTANCE_ID]
    ):
        raise ConfigEntryNotReady("The App identity or API version changed")

    coordinator = YoutubeAudioDownloaderCoordinator(hass, entry, client, info)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = YoutubeAudioDownloaderRuntimeData(client, coordinator, info)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await coordinator.async_start()
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: YoutubeAudioDownloaderConfigEntry
) -> bool:
    """Unload entities and stop the streaming connection."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    await entry.runtime_data.coordinator.async_shutdown()
    return True


def _runtime_data(hass: HomeAssistant) -> YoutubeAudioDownloaderRuntimeData:
    """Return the single loaded entry runtime or an actionable action error."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if hasattr(entry, "runtime_data"):
            return cast("YoutubeAudioDownloaderRuntimeData", entry.runtime_data)
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="not_configured",
    )


def _service_error(err: Exception) -> ServiceValidationError:
    """Map stable App errors to localized, actionable action errors."""
    if isinstance(err, YoutubeAudioDownloaderAuthenticationError):
        return ServiceValidationError(
            translation_domain=DOMAIN, translation_key="invalid_auth"
        )
    if isinstance(err, YoutubeAudioDownloaderConnectionError):
        return ServiceValidationError(
            translation_domain=DOMAIN, translation_key="service_unavailable"
        )
    if isinstance(err, YoutubeAudioDownloaderResponseError):
        known_codes = {
            "invalid_request",
            "invalid_url",
            "unsupported_host",
            "duplicate_job",
            "queue_full",
            "service_stopping",
        }
        if err.code in known_codes:
            return ServiceValidationError(
                translation_domain=DOMAIN, translation_key=err.code
            )
        return ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="app_error",
            translation_placeholders={"code": err.code, "message": err.message},
        )
    return ServiceValidationError(
        translation_domain=DOMAIN, translation_key="service_unavailable"
    )

"""Config flow for YouTube Audio Downloader."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, override
from uuid import UUID

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.hassio import HassioServiceInfo

from .api import (
    InfoData,
    YoutubeAudioDownloaderApiClient,
    YoutubeAudioDownloaderAuthenticationError,
    YoutubeAudioDownloaderConnectionError,
    YoutubeAudioDownloaderResponseError,
)
from .const import (
    API_VERSION,
    CONF_API_VERSION,
    CONF_AUTH_TOKEN,
    CONF_INSTANCE_ID,
    DOMAIN,
    NAME,
)


class YoutubeAudioDownloaderConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle discovery-only configuration."""

    VERSION = 1
    MINOR_VERSION = 1

    _discovery_data: dict[str, Any] | None = None
    _discovery_name = NAME
    _info: InfoData | None = None

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Explain that credentials are delivered only through App discovery."""
        if user_input is not None:
            return self.async_abort(reason="discovery_required")
        self._set_confirm_only()
        return self.async_show_form(step_id="user")

    async def async_step_reauth(
        self, _entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Explain that only rediscovery can replace an invalid token."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Direct users to restart the App instead of asking for its token."""
        if user_input is not None:
            return self.async_abort(reason="discovery_required")
        self._set_confirm_only()
        return self.async_show_form(step_id="reauth_confirm")

    @override
    async def async_step_hassio(
        self, discovery_info: HassioServiceInfo
    ) -> ConfigFlowResult:
        """Validate and prepare a Supervisor-discovered App instance."""
        data = self._validated_discovery_data(discovery_info.config)
        if data is None:
            return self.async_abort(reason="invalid_discovery")
        if data[CONF_API_VERSION] != API_VERSION:
            return self.async_abort(reason="incompatible_api_version")

        info, error = await self._async_validate_connection(data)
        if error is not None:
            return self.async_abort(reason=error)
        assert info is not None

        await self.async_set_unique_id(data[CONF_INSTANCE_ID])
        self._abort_if_unique_id_configured(updates=data, reload_on_update=True)
        if self.hass.config_entries.async_entries(DOMAIN):
            return self.async_abort(reason="single_instance_allowed")

        self._discovery_data = data
        self._discovery_name = discovery_info.name or NAME
        self._info = info
        self._set_confirm_only()
        return self.async_show_form(
            step_id="hassio_confirm",
            description_placeholders={"app": self._discovery_name},
        )

    async def async_step_hassio_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm creation of a newly discovered config entry."""
        assert self._discovery_data is not None
        if user_input is None:
            return self.async_show_form(
                step_id="hassio_confirm",
                description_placeholders={"app": self._discovery_name},
            )

        info, error = await self._async_validate_connection(self._discovery_data)
        if error is not None:
            return self.async_show_form(
                step_id="hassio_confirm",
                description_placeholders={"app": self._discovery_name},
                errors={"base": error},
            )
        self._info = info
        return self.async_create_entry(
            title=self._discovery_name, data=self._discovery_data
        )

    async def _async_validate_connection(
        self, data: dict[str, Any]
    ) -> tuple[InfoData | None, str | None]:
        """Authenticate and ensure discovery and API identities match."""
        try:
            client = YoutubeAudioDownloaderApiClient(
                async_get_clientsession(self.hass),
                data[CONF_HOST],
                data[CONF_PORT],
                data[CONF_AUTH_TOKEN],
            )
            info = await client.async_get_info()
        except ValueError:
            return None, "invalid_response"
        except YoutubeAudioDownloaderAuthenticationError:
            return None, "invalid_auth"
        except YoutubeAudioDownloaderConnectionError:
            return None, "cannot_connect"
        except YoutubeAudioDownloaderResponseError:
            return None, "invalid_response"

        if (
            info.get(CONF_API_VERSION) != API_VERSION
            or info.get(CONF_INSTANCE_ID) != data[CONF_INSTANCE_ID]
        ):
            return None, "invalid_response"
        return info, None

    @staticmethod
    def _validated_discovery_data(config: dict[str, Any]) -> dict[str, Any] | None:
        """Validate required fields without ever exposing the token."""
        host = config.get(CONF_HOST)
        port = config.get(CONF_PORT)
        auth_token = config.get(CONF_AUTH_TOKEN)
        instance_id = config.get(CONF_INSTANCE_ID)
        api_version = config.get(CONF_API_VERSION)
        if (
            not isinstance(host, str)
            or not host.strip()
            or not isinstance(port, int)
            or isinstance(port, bool)
            or not 1 <= port <= 65535
            or not isinstance(auth_token, str)
            or not auth_token
            or not isinstance(instance_id, str)
            or not isinstance(api_version, int)
            or isinstance(api_version, bool)
        ):
            return None
        try:
            UUID(instance_id)
        except ValueError:
            return None
        return {
            CONF_HOST: host,
            CONF_PORT: port,
            CONF_AUTH_TOKEN: auth_token,
            CONF_INSTANCE_ID: instance_id,
            CONF_API_VERSION: api_version,
        }

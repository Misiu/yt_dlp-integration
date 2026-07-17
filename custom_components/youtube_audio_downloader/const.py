"""Constants for the YouTube Audio Downloader integration."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "youtube_audio_downloader"
NAME = "YouTube Audio Downloader"

CONF_AUTH_TOKEN = "auth_token"  # noqa: S105 - discovery field name, not a secret
CONF_INSTANCE_ID = "instance_id"
CONF_API_VERSION = "api_version"

API_VERSION = 1
DEFAULT_PORT = 8099

SERVICE_DOWNLOAD = "download"
SERVICE_DOWNLOAD_BATCH = "download_batch"
ATTR_URL = "url"
ATTR_URLS = "urls"

PLATFORMS = [Platform.SENSOR]

STATE_IDLE = "idle"
STATE_STOPPING = "stopping"
ACTIVE_STATES = {
    "extracting_metadata",
    "downloading",
    "processing",
    "embedding_metadata",
}
TERMINAL_STATES = {"completed", "failed", "cancelled"}
STATE_OPTIONS = [
    STATE_IDLE,
    "queued",
    "extracting_metadata",
    "downloading",
    "processing",
    "embedding_metadata",
    "completed",
    "failed",
    "cancelled",
    STATE_STOPPING,
]

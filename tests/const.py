"""Safe test fixtures with no personal data or source URLs."""

from homeassistant.const import CONF_HOST, CONF_PORT

from custom_components.youtube_audio_downloader.api import InfoData, StatusData
from custom_components.youtube_audio_downloader.const import (
    CONF_API_VERSION,
    CONF_AUTH_TOKEN,
    CONF_INSTANCE_ID,
)

INSTANCE_ID = "2d2fd3aa-291d-4e62-91ce-5ab6f58effaa"
TOKEN = "test-discovery-token-that-is-long-and-not-real"  # noqa: S105

DISCOVERY_CONFIG = {
    CONF_HOST: "youtube-audio-app",
    CONF_PORT: 8099,
    CONF_AUTH_TOKEN: TOKEN,
    CONF_INSTANCE_ID: INSTANCE_ID,
    CONF_API_VERSION: 1,
}

INFO = InfoData(
    version="0.1.4",
    api_version=1,
    instance_id=INSTANCE_ID,
    architecture="test-arch",
    output_directory="youtube_audio",
    queue_limit=50,
)

IDLE_STATUS = StatusData(
    state="idle",
    progress=0.0,
    queue_length=0,
    current=None,
)

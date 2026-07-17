"""Typed client for the YouTube Audio Downloader App API."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any, TypedDict, cast

from aiohttp import ClientError, ClientResponse, ClientSession, ClientTimeout
from yarl import URL


class JobData(TypedDict, total=False):
    """A download job returned by the App."""

    id: str
    state: str
    title: str | None
    artist: str | None
    source_title: str | None
    channel: str | None
    uploader: str | None
    thumbnail_url: str | None
    progress: float | None
    downloaded_bytes: int | None
    total_bytes: int | None
    speed_bytes_per_second: float | None
    eta_seconds: float | None
    created_at: str
    started_at: str | None
    finished_at: str | None
    output_file: str | None
    file_size: int | None
    error_code: str | None
    error_message: str | None
    warning_message: str | None


class InfoData(TypedDict, total=False):
    """App information."""

    version: str
    api_version: int
    instance_id: str
    yt_dlp_version: str
    ffmpeg_version: str
    architecture: str
    output_directory: str
    queue_limit: int


class StatusData(TypedDict):
    """Current App status."""

    state: str
    progress: float | None
    queue_length: int
    current: JobData | None


class HistoryData(TypedDict):
    """One terminal job history page."""

    items: list[JobData]
    page: int
    page_size: int
    total: int


@dataclass(frozen=True, slots=True)
class ServerSentEvent:
    """A parsed server-sent event."""

    event: str
    data: dict[str, Any]


class YoutubeAudioDownloaderApiError(Exception):
    """Base error raised by the API client."""


class YoutubeAudioDownloaderConnectionError(YoutubeAudioDownloaderApiError):
    """The App could not be reached."""


class YoutubeAudioDownloaderAuthenticationError(YoutubeAudioDownloaderApiError):
    """The App rejected the integration token."""


class YoutubeAudioDownloaderResponseError(YoutubeAudioDownloaderApiError):
    """The App returned an error response."""

    def __init__(self, status: int, code: str, message: str) -> None:
        """Initialize an API response error."""
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class YoutubeAudioDownloaderApiClient:
    """Small authenticated client for stable API v1."""

    def __init__(
        self,
        session: ClientSession,
        host: str,
        port: int,
        auth_token: str,
    ) -> None:
        """Initialize the client."""
        self._session = session
        self._base_url = URL.build(scheme="http", host=host, port=port)
        self._headers = {"Authorization": f"Bearer {auth_token}"}
        self._event_response: ClientResponse | None = None

    async def async_get_info(self) -> InfoData:
        """Return App and API information."""
        payload = await self._async_request("GET", "/api/v1/info", expected=200)
        if not isinstance(payload, Mapping):
            raise YoutubeAudioDownloaderResponseError(
                200, "invalid_response", "The App returned invalid information."
            )
        return cast("InfoData", dict(payload))

    async def async_get_status(self) -> StatusData:
        """Return the current App status."""
        payload = await self._async_request("GET", "/api/v1/status", expected=200)
        return parse_status(payload)

    async def async_get_history(
        self, *, page: int = 1, page_size: int = 100
    ) -> HistoryData:
        """Return a terminal job history page for completion reconciliation."""
        payload = await self._async_request(
            "GET",
            "/api/v1/history",
            expected=200,
            params={"page": page, "page_size": page_size},
        )
        return parse_history(payload)

    async def async_download(self, url: str) -> dict[str, Any]:
        """Queue a single download."""
        payload = await self._async_request(
            "POST", "/api/v1/downloads", expected=202, json_body={"url": url}
        )
        return _mapping_payload(payload)

    async def async_download_batch(self, urls: list[str]) -> dict[str, Any]:
        """Atomically queue multiple downloads."""
        payload = await self._async_request(
            "POST",
            "/api/v1/downloads/batch",
            expected=202,
            json_body={"urls": urls},
        )
        return _mapping_payload(payload)

    async def async_events(self) -> AsyncIterator[ServerSentEvent]:
        """Yield named server-sent events until disconnected."""
        try:
            response = await self._session.get(
                self._base_url.with_path("/api/v1/events"),
                headers=self._headers,
                timeout=ClientTimeout(total=None, connect=10, sock_read=45),
            )
        except (ClientError, TimeoutError) as err:
            raise YoutubeAudioDownloaderConnectionError(
                "Could not connect to the App event stream."
            ) from err

        self._event_response = response
        try:
            if response.status != 200:
                raise await self._async_response_error(response)

            event_name = ""
            data_lines: list[str] = []
            while True:
                raw_line = await response.content.readline()
                if not raw_line:
                    raise YoutubeAudioDownloaderConnectionError(
                        "The App event stream disconnected."
                    )
                line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")

                if not line:
                    if event_name and data_lines:
                        try:
                            data = json.loads("\n".join(data_lines))
                        except json.JSONDecodeError:
                            event_name = ""
                            data_lines.clear()
                            continue
                        if isinstance(data, dict):
                            yield ServerSentEvent(event_name, data)
                    event_name = ""
                    data_lines.clear()
                elif line.startswith("event:"):
                    event_name = line[6:].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())
                # Ignore heartbeat comments, retry fields, IDs, and unknown fields.
        except (ClientError, TimeoutError) as err:
            raise YoutubeAudioDownloaderConnectionError(
                "The App event stream disconnected."
            ) from err
        finally:
            response.close()
            if self._event_response is response:
                self._event_response = None

    async def async_close(self) -> None:
        """Close an active streaming response without closing HA's shared session."""
        if self._event_response is not None:
            self._event_response.close()
            self._event_response = None

    async def _async_request(
        self,
        method: str,
        path: str,
        *,
        expected: int,
        json_body: dict[str, Any] | None = None,
        params: Mapping[str, int | str] | None = None,
    ) -> Any:
        """Perform one authenticated JSON request."""
        try:
            async with self._session.request(
                method,
                self._base_url.with_path(path),
                headers=self._headers,
                json=json_body,
                params=params,
                timeout=ClientTimeout(total=15),
            ) as response:
                if response.status != expected:
                    raise await self._async_response_error(response)
                try:
                    return await response.json(content_type=None)
                except (json.JSONDecodeError, UnicodeDecodeError) as err:
                    raise YoutubeAudioDownloaderResponseError(
                        response.status,
                        "invalid_response",
                        "The App returned an invalid response.",
                    ) from err
        except YoutubeAudioDownloaderApiError:
            raise
        except (ClientError, TimeoutError) as err:
            raise YoutubeAudioDownloaderConnectionError(
                "Could not connect to the App."
            ) from err

    @staticmethod
    async def _async_response_error(
        response: ClientResponse,
    ) -> YoutubeAudioDownloaderApiError:
        """Convert a stable App error envelope into a typed exception."""
        code = "http_error"
        message = "The App rejected the request."
        try:
            payload = await response.json(content_type=None)
        except ClientError, json.JSONDecodeError, UnicodeDecodeError:
            payload = None
        if isinstance(payload, Mapping) and isinstance(payload.get("error"), Mapping):
            error = payload["error"]
            if isinstance(error.get("code"), str):
                code = error["code"]
            if isinstance(error.get("message"), str):
                message = error["message"]
        if response.status == 401:
            return YoutubeAudioDownloaderAuthenticationError(
                "The App rejected the integration token."
            )
        return YoutubeAudioDownloaderResponseError(response.status, code, message)


def parse_status(payload: Any) -> StatusData:
    """Validate and normalize a status payload."""
    if not isinstance(payload, Mapping):
        raise YoutubeAudioDownloaderResponseError(
            200, "invalid_response", "The App returned an invalid status."
        )
    state = payload.get("state")
    queue_length = payload.get("queue_length")
    progress = payload.get("progress")
    current = payload.get("current")
    if (
        not isinstance(state, str)
        or not isinstance(queue_length, int)
        or isinstance(queue_length, bool)
        or (progress is not None and not isinstance(progress, int | float))
        or isinstance(progress, bool)
        or (current is not None and not isinstance(current, Mapping))
    ):
        raise YoutubeAudioDownloaderResponseError(
            200, "invalid_response", "The App returned an invalid status."
        )
    return StatusData(
        state=state,
        progress=float(progress) if progress is not None else None,
        queue_length=queue_length,
        current=cast("JobData | None", dict(current) if current is not None else None),
    )


def parse_history(payload: Any) -> HistoryData:
    """Validate and normalize a terminal history page."""
    if not isinstance(payload, Mapping):
        raise YoutubeAudioDownloaderResponseError(
            200, "invalid_response", "The App returned invalid history."
        )
    raw_items = payload.get("items")
    page = payload.get("page")
    page_size = payload.get("page_size")
    total = payload.get("total")
    if (
        not isinstance(raw_items, list)
        or not isinstance(page, int)
        or isinstance(page, bool)
        or not isinstance(page_size, int)
        or isinstance(page_size, bool)
        or not isinstance(total, int)
        or isinstance(total, bool)
        or any(not isinstance(item, Mapping) for item in raw_items)
    ):
        raise YoutubeAudioDownloaderResponseError(
            200, "invalid_response", "The App returned invalid history."
        )
    return HistoryData(
        items=[cast("JobData", dict(item)) for item in raw_items],
        page=page,
        page_size=page_size,
        total=total,
    )


def _mapping_payload(payload: Any) -> dict[str, Any]:
    """Require an object response."""
    if not isinstance(payload, Mapping):
        raise YoutubeAudioDownloaderResponseError(
            200, "invalid_response", "The App returned an invalid response."
        )
    return dict(payload)

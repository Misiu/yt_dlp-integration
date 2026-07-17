"""Tests for authenticated REST and SSE client behavior."""

import pytest
from aiohttp import web

from custom_components.youtube_audio_downloader.api import (
    YoutubeAudioDownloaderApiClient,
    YoutubeAudioDownloaderAuthenticationError,
    YoutubeAudioDownloaderConnectionError,
    YoutubeAudioDownloaderResponseError,
)

from .const import INFO, INSTANCE_ID, TOKEN


async def test_rest_actions_and_error_envelope(aiohttp_client, socket_enabled) -> None:
    """The client authenticates, sends exact payloads, and maps App errors."""
    requests = []

    async def info(request):
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        return web.json_response(INFO)

    async def status(request):
        return web.json_response(
            {"state": "idle", "progress": 0, "queue_length": 2, "current": None}
        )

    async def download(request):
        payload = await request.json()
        requests.append(payload)
        if payload["url"] == "invalid-value":
            return web.json_response(
                {"error": {"code": "invalid_url", "message": "Invalid URL."}},
                status=400,
            )
        return web.json_response({"id": "job-id", "state": "queued"}, status=202)

    async def batch(request):
        payload = await request.json()
        requests.append(payload)
        return web.json_response({"items": [], "accepted": 2}, status=202)

    app = web.Application()
    app.router.add_get("/api/v1/info", info)
    app.router.add_get("/api/v1/status", status)
    app.router.add_post("/api/v1/downloads", download)
    app.router.add_post("/api/v1/downloads/batch", batch)
    server_client = await aiohttp_client(app)
    api = YoutubeAudioDownloaderApiClient(
        server_client.session, server_client.host, server_client.port, TOKEN
    )

    assert (await api.async_get_info())["instance_id"] == INSTANCE_ID
    assert (await api.async_get_status())["queue_length"] == 2
    await api.async_download("test-value")
    await api.async_download_batch(["first-value", "second-value"])
    assert requests == [
        {"url": "test-value"},
        {"urls": ["first-value", "second-value"]},
    ]

    with pytest.raises(YoutubeAudioDownloaderResponseError) as error:
        await api.async_download("invalid-value")
    assert error.value.code == "invalid_url"


async def test_authentication_error(aiohttp_client, socket_enabled) -> None:
    """HTTP 401 has a dedicated exception and does not expose the token."""

    async def unauthorized(_request):
        return web.json_response(
            {"error": {"code": "authentication_required", "message": "Unauthorized."}},
            status=401,
        )

    app = web.Application()
    app.router.add_get("/api/v1/info", unauthorized)
    server_client = await aiohttp_client(app)
    api = YoutubeAudioDownloaderApiClient(
        server_client.session, server_client.host, server_client.port, TOKEN
    )

    with pytest.raises(YoutubeAudioDownloaderAuthenticationError) as error:
        await api.async_get_info()
    assert TOKEN not in str(error.value)


async def test_sse_parsing_and_disconnect(aiohttp_client, socket_enabled) -> None:
    """Named SSE data is parsed and an EOF is treated as a reconnectable loss."""

    async def events(request):
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        await response.write(
            b"event: job_updated\n"
            b'data: {"job":{"id":"job-id","state":"downloading"}}\n\n'
        )
        await response.write_eof()
        return response

    app = web.Application()
    app.router.add_get("/api/v1/events", events)
    server_client = await aiohttp_client(app)
    api = YoutubeAudioDownloaderApiClient(
        server_client.session, server_client.host, server_client.port, TOKEN
    )
    stream = api.async_events()

    event = await anext(stream)
    assert event.event == "job_updated"
    assert event.data["job"]["id"] == "job-id"
    with pytest.raises(YoutubeAudioDownloaderConnectionError):
        await anext(stream)
    await api.async_close()

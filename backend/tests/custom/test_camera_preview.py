"""Prévia da câmera (Frigate latest.jpg) com o token de stream."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from backend.app.custom import camera_preview

URL = "/api/v1/custom/camera/stream/1/preview.jpg"
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 100 + b"\xff\xd9"


def _fake_client(status=200, content=JPEG, exc=None):
    client = MagicMock()
    client.get = AsyncMock(side_effect=exc) if exc else AsyncMock(return_value=MagicMock(status_code=status, content=content))
    return patch.object(camera_preview, "_http", return_value=client)


async def test_not_configured_is_404(async_client, monkeypatch):
    monkeypatch.delenv(camera_preview.ENV_URL, raising=False)
    assert (await async_client.get(URL)).status_code == 404


async def test_proxies_jpeg_without_cache(async_client, monkeypatch):
    monkeypatch.setenv(camera_preview.ENV_URL, "http://frigate:5000/api/cam_{printer_id}/latest.jpg")
    with _fake_client() as http:
        r = await async_client.get(URL)
    assert r.status_code == 200 and r.content == JPEG
    assert r.headers["content-type"] == "image/jpeg" and r.headers["cache-control"] == "no-store"
    http.return_value.get.assert_awaited_once_with("http://frigate:5000/api/cam_1/latest.jpg")


async def test_bad_upstream_is_502(async_client, monkeypatch):
    monkeypatch.setenv(camera_preview.ENV_URL, "http://frigate:5000/latest.jpg")
    with _fake_client(content=b"<html>"):
        assert (await async_client.get(URL)).status_code == 502
    with _fake_client(exc=httpx.ConnectError("down")):
        assert (await async_client.get(URL)).status_code == 502


def test_only_env_http_urls():
    import os

    os.environ[camera_preview.ENV_URL] = "file:///etc/passwd"
    try:
        assert camera_preview.preview_url(1) is None
    finally:
        del os.environ[camera_preview.ENV_URL]


async def test_requires_stream_token_when_auth_enabled(async_client, monkeypatch):
    from backend.tests.integration.test_makerworld_permission_gate import _setup_auth_with_admin

    monkeypatch.setenv(camera_preview.ENV_URL, "http://frigate:5000/latest.jpg")
    await _setup_auth_with_admin(async_client)
    with _fake_client():
        assert (await async_client.get(URL)).status_code == 401
        assert (await async_client.get(URL + "?token=nope")).status_code == 401

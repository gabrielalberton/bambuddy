"""Vídeo H.264 da câmera repassado do go2rtc (custom/docs/camera-h264.md)."""

import asyncio
import json
from unittest.mock import patch

import aiohttp

from backend.app.custom import camera_h264

URL = "ws://go2rtc:1984/api/ws?src=cam_{printer_id}"


class FakeBrowser:
    """WebSocket do Starlette: entrega as mensagens dadas e depois fica esperando (ou desconecta)."""

    def __init__(self, incoming=(), disconnect_after=True):
        self.incoming = list(incoming)
        self.disconnect_after = disconnect_after
        self.accepted = False
        self.closed_with = None
        self.sent = []
        self.release = asyncio.Event()

    async def accept(self):
        self.accepted = True

    async def close(self, code=1000):
        self.closed_with = code

    async def receive(self):
        if self.incoming:
            return {"type": "websocket.receive", "text": self.incoming.pop(0)}
        if not self.disconnect_after:
            await self.release.wait()
        return {"type": "websocket.disconnect", "code": 1000}

    async def send_bytes(self, data):
        self.sent.append(data)

    async def send_text(self, text):
        self.sent.append(text)


class FakeMsg:
    def __init__(self, type_, data):
        self.type = type_
        self.data = data


class FakeUpstream:
    def __init__(self, messages, wait_first=None):
        self.messages = list(messages)
        self.wait_first = wait_first
        self.sent = []

    async def send_str(self, text):
        self.sent.append(text)

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        if self.wait_first is not None:
            await self.wait_first.wait()
        for msg in self.messages:
            yield msg

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    def __init__(self, upstream=None, exc=None):
        self.upstream = upstream
        self.exc = exc
        self.urls = []

    def ws_connect(self, url, **_):
        self.urls.append(url)
        if self.exc:
            raise self.exc
        return self.upstream

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _session(fake):
    return patch.object(camera_h264.aiohttp, "ClientSession", return_value=fake)


def _auth(ok=True):
    async def fake(printer_id, token):
        return ok

    return patch.object(camera_h264, "authorized", side_effect=fake)


def test_only_env_ws_urls(monkeypatch):
    monkeypatch.delenv(camera_h264.ENV_URL, raising=False)
    assert camera_h264.upstream_url(1) is None
    monkeypatch.setenv(camera_h264.ENV_URL, "http://go2rtc:1984/api/ws")
    assert camera_h264.upstream_url(1) is None
    monkeypatch.setenv(camera_h264.ENV_URL, URL)
    assert camera_h264.upstream_url(7) == "ws://go2rtc:1984/api/ws?src=cam_7"


def test_browser_message_is_rewritten_and_validated():
    assert json.loads(camera_h264.browser_message('{"type":"mse","value":"avc1.640029,avc1.4D0029","x":1}')) == {
        "type": "mse",
        "value": "avc1.640029,avc1.4D0029",
    }
    assert camera_h264.browser_message('{"type":"webrtc/offer","value":"v=0"}') is None
    assert camera_h264.browser_message('{"type":"mse","value":"avc1\\"; rm"}') is None
    assert camera_h264.browser_message("not json") is None
    assert camera_h264.go2rtc_message('{"type":"mse","value":"video/mp4; codecs=\\"avc1.4D0029\\""}') is not None
    assert camera_h264.go2rtc_message('{"type":"webrtc/candidate","value":"x"}') is None


async def test_unauthorized_closes_4401(monkeypatch):
    monkeypatch.setenv(camera_h264.ENV_URL, URL)
    ws = FakeBrowser()
    with _auth(False), _session(FakeSession(exc=AssertionError("não deveria conectar"))):
        await camera_h264.camera_h264(ws, 1, "nope")
    assert ws.accepted and ws.closed_with == camera_h264.CLOSE_UNAUTHORIZED


async def test_not_configured_closes_4404(monkeypatch):
    monkeypatch.delenv(camera_h264.ENV_URL, raising=False)
    ws = FakeBrowser()
    with _auth(True):
        await camera_h264.camera_h264(ws, 1, None)
    assert ws.closed_with == camera_h264.CLOSE_UNAVAILABLE


async def test_relays_mse_handshake_and_video(monkeypatch):
    monkeypatch.setenv(camera_h264.ENV_URL, URL)
    go_on = asyncio.Event()
    upstream = FakeUpstream(
        [
            FakeMsg(aiohttp.WSMsgType.TEXT, '{"type":"mse","value":"video/mp4; codecs=\\"avc1.4D0029\\""}'),
            FakeMsg(aiohttp.WSMsgType.BINARY, b"ftyp-init"),
            FakeMsg(aiohttp.WSMsgType.BINARY, b"moof-frame"),
            FakeMsg(aiohttp.WSMsgType.CLOSED, None),
        ],
        wait_first=go_on,
    )
    session = FakeSession(upstream)
    ws = FakeBrowser(
        ['{"type":"mse","value":"avc1.640029"}', '{"type":"mse","value":"avc1.42E01E"}'],
        disconnect_after=False,
    )

    async def unblock():
        while not upstream.sent:
            await asyncio.sleep(0)
        await asyncio.sleep(0.01)  # a segunda mensagem do navegador já foi lida
        go_on.set()

    with _auth(True), _session(session):
        await asyncio.gather(camera_h264.camera_h264(ws, 3, "tok"), unblock())
    assert session.urls == ["ws://go2rtc:1984/api/ws?src=cam_3"]
    assert upstream.sent == ['{"type": "mse", "value": "avc1.640029"}']  # só a primeira
    assert ws.sent[1:] == [b"ftyp-init", b"moof-frame"]
    assert json.loads(ws.sent[0])["type"] == "mse"
    assert ws.closed_with == camera_h264.CLOSE_UPSTREAM
    assert camera_h264._sessions == 0


async def test_browser_leaving_ends_without_close(monkeypatch):
    monkeypatch.setenv(camera_h264.ENV_URL, URL)
    upstream = FakeUpstream([], wait_first=asyncio.Event())  # go2rtc nunca manda nada
    ws = FakeBrowser([])  # navegador sai logo
    with _auth(True), _session(FakeSession(upstream)):
        await camera_h264.camera_h264(ws, 1, None)
    assert ws.closed_with is None
    assert camera_h264._sessions == 0


async def test_go2rtc_down_closes_4502(monkeypatch):
    monkeypatch.setenv(camera_h264.ENV_URL, URL)
    ws = FakeBrowser()
    with _auth(True), _session(FakeSession(exc=aiohttp.ClientConnectionError("down"))):
        await camera_h264.camera_h264(ws, 1, None)
    assert ws.closed_with == camera_h264.CLOSE_UPSTREAM


async def test_session_limit(monkeypatch):
    monkeypatch.setenv(camera_h264.ENV_URL, URL)
    monkeypatch.setattr(camera_h264, "_sessions", camera_h264.MAX_SESSIONS)
    ws = FakeBrowser()
    with _auth(True):
        await camera_h264.camera_h264(ws, 1, None)
    assert ws.closed_with == camera_h264.CLOSE_BUSY


async def test_expired_token_closes_4401(monkeypatch):
    monkeypatch.setenv(camera_h264.ENV_URL, URL)
    monkeypatch.setattr(camera_h264, "REVALIDATE_S", 0.01)
    calls = []

    async def fake(printer_id, token):
        calls.append(token)
        return len(calls) == 1  # válido na entrada, vencido na revalidação

    upstream = FakeUpstream([], wait_first=asyncio.Event())
    ws = FakeBrowser([], disconnect_after=False)
    with patch.object(camera_h264, "authorized", side_effect=fake), _session(FakeSession(upstream)):
        await asyncio.wait_for(camera_h264.camera_h264(ws, 1, "tok"), 2)
    assert ws.closed_with == camera_h264.CLOSE_UNAUTHORIZED


async def test_authorized_uses_camera_stream_token(async_client):
    from backend.tests.integration.test_makerworld_permission_gate import _setup_auth_with_admin

    assert await camera_h264.authorized(1, None) is True  # auth desligada
    await _setup_auth_with_admin(async_client)
    assert await camera_h264.authorized(1, None) is False
    assert await camera_h264.authorized(1, "nope") is False


async def test_route_is_registered(async_client):
    from backend.app.custom.asgi import app

    assert any(getattr(r, "path", "") == "/api/v1/custom/camera/h264/{printer_id}/ws" for r in app.router.routes)

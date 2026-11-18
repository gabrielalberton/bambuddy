"""custom(chunk-recovery): 404 de /assets sem cache."""

import pytest

from backend.app.custom.asset_404 import Asset404NoStoreMiddleware


async def _run(path, status):
    sent = []

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": status, "headers": [(b"cache-control", b"max-age=14400")]})
        await send({"type": "http.response.body", "body": b""})

    async def send(msg):
        sent.append(msg)

    await Asset404NoStoreMiddleware(app)({"type": "http", "path": path}, None, send)
    return dict(sent[0]["headers"])[b"cache-control"]


@pytest.mark.asyncio
async def test_404_de_asset_sem_cache():
    assert await _run("/assets/SettingsPage-x.js", 404) == b"no-store"


@pytest.mark.asyncio
async def test_resto_inalterado():
    assert await _run("/assets/SettingsPage-x.js", 200) == b"max-age=14400"
    assert await _run("/api/v1/x", 404) == b"max-age=14400"

"""Curtidos/salvos do MakerWorld com transporte simulado (sem IO real)."""

import httpx
import pytest
from fastapi import HTTPException

from backend.app.custom.models_catalog.mine import my_designs

DESIGN = {
    "id": 11,
    "title": "Caixa",
    "cover": "https://makerworld.bblmw.com/a.png",
    "likeCount": 5,
    "designCreator": {"uid": 7, "name": "Ana"},
}


async def test_likes_use_token_and_hide_nsfw():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"total": 2, "hits": [DESIGN, {**DESIGN, "id": 12, "nsfw": True}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        out = await my_designs(client, "tok", "likes", 0, 24)
    assert seen[0].url.path == "/v1/design-service/my/design/like"
    assert seen[0].headers["Authorization"] == "Bearer tok"
    assert [i["id"] for i in out["items"]] == ["11"]
    assert out["total"] == 2 and out["has_more"] is False
    assert out["items"][0]["creator"] == "Ana"


async def test_saved_resolves_uid_from_profile():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/my/profile"):
            return httpx.Response(200, json={"uid": 99})
        assert request.url.path == "/v1/design-service/favorites/designs/99"
        return httpx.Response(200, json={"total": 30, "hits": [DESIGN]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        out = await my_designs(client, "tok", "saved", 0, 1)
    assert out["has_more"] is True


async def test_signed_out_and_expired_are_409_not_401():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(401, json={}))) as client:
        with pytest.raises(HTTPException) as no_token:
            await my_designs(client, None, "likes", 0, 24)
        with pytest.raises(HTTPException) as expired:
            await my_designs(client, "tok", "likes", 0, 24)
    assert no_token.value.status_code == 409
    assert expired.value.status_code == 409

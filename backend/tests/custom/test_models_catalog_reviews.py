"""Avaliações/comentários e números do detalhe (fixtures gravadas ao vivo em 2026-11-14, anonimizadas)."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from backend.app.custom.models_catalog import router as catalog
from backend.app.custom.models_catalog.base import ReviewsRequest, clean_text
from backend.app.custom.models_catalog.makerworld import (
    MakerWorldSource,
    design_stats,
    parse_review,
    rating_summary,
)
from backend.app.custom.models_catalog.printables import PrintablesSource
from backend.app.custom.models_catalog.thingiverse import ENV_KEY, ThingiverseSource
from backend.app.services.model_providers.base import ProviderUnavailableError
from backend.tests.integration.test_makerworld_permission_gate import _make_user, _setup_auth_with_admin

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "/api/v1/custom/models"


def fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


# ---------------------------------------------------------------- MakerWorld
async def test_makerworld_ratings_page_parsing_and_params():
    seen = []

    def handler(request):
        seen.append(request.url)
        return httpx.Response(200, json=fixture("makerworld_ratings.json"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        page = await MakerWorldSource().reviews(client, "42", ReviewsRequest(kind="ratings", sort="top", page=2))
    url = seen[0]
    assert (url.host, url.path) == ("api.bambulab.com", "/v1/comment-service/commentandrating")
    assert url.params["designId"] == "42" and url.params["type"] == "2" and url.params["offset"] == "10"
    assert url.params["limit"] == "10" and "sort" not in url.params
    assert page["total"] == 942 and page["has_more"] is True
    first, *_, low = page["items"]
    assert first["kind"] == "rating" and first["rating"] == 5 and first["author"] == "Maker 0"
    assert first["profile"] == {"id": "5", "name": "0.4 Nozzle - 0.28mm layer, 3 walls, 0% infill"}
    assert first["printed"] is True and first["created"] == "2026-11-02T19:41:11Z"
    assert first["images"][0]["thumb"].endswith("?x-oss-process=image/resize,w_240/format,webp")
    assert first["images"][0]["full"].startswith("https://makerworld.bblmw.com/")
    # Nota baixa sem texto: o motivo escrito vira o texto; o rótulo do problema vai em ``issues``.
    assert low["rating"] == 2 and low["text"] == "Broke when removing from the bed"
    assert low["issues"] == ["Strength Issue"] and low["printed"] is False


async def test_makerworld_comments_newest_with_reply_preview():
    seen = []

    def handler(request):
        seen.append(request.url)
        return httpx.Response(200, json=fixture("makerworld_comments.json"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        page = await MakerWorldSource().reviews(client, "42", ReviewsRequest(kind="comments", sort="newest"))
    assert seen[0].params["type"] == "1" and seen[0].params["sort"] == "1" and seen[0].params["offset"] == "0"
    first, second = page["items"]
    # Texto puro: o frontend nunca renderiza como HTML.
    assert first["text"] == "Great design, saved me a lot of filament! <b>not html</b>"
    assert first["kind"] == "comment" and first["rating"] is None and first["boosted"] is True
    assert first["reply_preview"][0]["author"] == "Maker 30" and first["reply_preview"][0]["text"] == "Thanks!"
    assert second["images"] == [] and second["reply_preview"] == []
    assert page["has_more"] is True  # 0 + 2 < 109


def test_makerworld_parse_review_drops_hidden_and_offsite_images():
    hit = fixture("makerworld_ratings.json")["hits"][0]
    hit["ratingItem"]["images"] = ["http://makerworld.bblmw.com/x.jpg", "https://evil.example/x.jpg"]
    assert parse_review(hit)["images"] == []
    hit["ratingItem"]["status"] = 3
    assert parse_review(hit) is None
    comment = fixture("makerworld_comments.json")["hits"][0]
    comment["comment"]["isValid"] = False
    assert parse_review(comment) is None
    assert parse_review({"type": 9}) is None


def test_makerworld_rating_summary_and_stats():
    instances = [
        {"ratingScoreTotal": 4230, "ratingCount": 863},
        {"ratingScoreTotal": 179, "ratingCount": 36},
        {"ratingScoreTotal": 0, "ratingCount": 0},
        {"title": "community profile without rating fields"},
    ]
    assert rating_summary(instances) == {"average": 4.9, "count": 899}
    assert rating_summary([]) == {"average": None, "count": 0}
    stats = design_stats(
        {
            "downloadCount": 42199,
            "printCount": 27880,
            "likeCount": 5747,
            "collectionCount": 1,
            "boostInfo": {"total": 313},
            "createTime": "2025-08-10T00:58:05Z",
        }
    )
    assert stats == {
        "downloads": 42199,
        "prints": 27880,
        "likes": 5747,
        "collections": 1,
        "boosts": 313,
        "published": "2025-08-10T00:58:05Z",
    }


async def test_makerworld_detail_profile_card_fields():
    design = {
        "id": 42,
        "title": "Base",
        "designCreator": {"uid": 1, "name": "Designer"},
        "downloadCount": 10,
        "boostInfo": {"total": 3},
        "instances": [
            {
                "id": 7,
                "profileId": 5,
                "title": "A1 0.4",
                "instanceCreator": {"uid": 1, "name": "Designer"},
                "ratingScoreTotal": 405,
                "ratingCount": 81,
                "publishTime": "2025-07-02T10:00:00Z",
                "updateTime": "2025-08-01T10:00:00Z",
                "downloadCount": 3700,
                "printCount": 1400,
                "prediction": 34920,
                "weight": 302,
                "instanceFilaments": [{"type": "PLA", "color": "#C0C0C0", "usedM": "100.1", "usedG": "302"}],
                "extention": {
                    "modelInfo": {
                        "compatibility": {"devModelName": "N2S", "devProductName": "A1", "nozzleDiameter": 0.4},
                        "otherCompatibility": [{"devModelName": "C12", "devProductName": "P1S"}],
                        "plates": [{"index": 1}, {"index": 2}],
                    }
                },
            }
        ],
    }

    def handler(request):
        if request.url.path.endswith("/instances"):
            return httpx.Response(200, json={"hits": [], "total": 0})
        return httpx.Response(200, json=design)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        detail = await MakerWorldSource().detail(client, "42", ["A1"])
    meta = detail["files"][0]["metadata"]
    assert meta["rating_average"] == 5.0 and meta["rating_count"] == 81 and meta["is_designer"] is True
    assert meta["published"] == "2025-07-02T10:00:00Z" and meta["updated"] == "2025-08-01T10:00:00Z"
    assert (meta["downloads"], meta["prints"], meta["plate_count"]) == (3700, 1400, 2)
    assert (meta["print_time_s"], meta["weight_g"], meta["nozzle_mm"]) == (34920, 302.0, 0.4)
    assert meta["filaments"] == [{"type": "PLA", "color": "#C0C0C0", "grams": 302.0}]
    assert meta["compatible_printers"] == ["A1", "P1S"]
    assert detail["rating"] == {"average": 5.0, "count": 81}
    assert detail["stats"]["boosts"] == 3 and detail["stats"]["downloads"] == 10


@pytest.mark.parametrize("status", [418, 429, 500])
async def test_makerworld_review_errors_are_not_empty_success(status):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(status))) as client:
        with pytest.raises(ProviderUnavailableError):
            await MakerWorldSource().reviews(client, "42", ReviewsRequest(kind="ratings"))


# ---------------------------------------------------------------- Printables
async def test_printables_comments_with_optional_rating_and_thumbs():
    bodies = []
    data = fixture("printables_comments.json")

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=data)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        page = await PrintablesSource().reviews(client, "42", ReviewsRequest(kind="all", page=3, page_size=3))
    assert bodies[0]["variables"] == {"id": "42", "limit": 4, "offset": 6}
    assert "rating" in bodies[0]["query"] and "comments(limit:$limit,offset:$offset)" in bodies[0]["query"]
    assert len(page["items"]) == 3 and page["has_more"] is True and page["total"] is None
    plain, rated = page["items"][0], page["items"][1]
    assert plain["kind"] == "comment" and plain["rating"] is None
    assert rated["kind"] == "rating" and rated["rating"] == 4
    thumb = plain["images"][0]["thumb"]
    assert thumb.startswith("https://media.printables.com/media/comment_images/ab/")
    assert "/thumbs/inside/320x240/jpg/" in thumb and thumb.endswith(".webp")
    assert "/thumbs/inside/1280x960/" in plain["images"][0]["full"]


def test_printables_rating_from_string_average():
    from backend.app.custom.models_catalog.printables import rating_summary

    assert rating_summary({"ratingAvg": "4.9404194471", "ratingCount": 4196}) == {"average": 4.94, "count": 4196}
    assert rating_summary({"ratingAvg": "0", "ratingCount": 0}) == {"average": None, "count": 0}
    assert rating_summary({"ratingAvg": "abc", "ratingCount": 3}) == {"average": None, "count": 3}


# ---------------------------------------------------------------- Thingiverse
async def test_thingiverse_comments_behind_token(monkeypatch):
    monkeypatch.setenv(ENV_KEY, "token")
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=[{"id": 1, "body": "nice", "user": {"name": "u"}, "added": "2024-01-01"}])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        page = await ThingiverseSource().reviews(client, "9", ReviewsRequest(kind="comments", sort="newest", page=2))
    assert seen[0].url.path == "/things/9/comments" and seen[0].url.params["page"] == "2"
    assert seen[0].headers["authorization"] == "Bearer token"
    assert page["items"][0]["text"] == "nice" and page["has_more"] is False


def test_clean_text_strips_control_chars_and_caps():
    assert clean_text("a\x00b\x1b[31m\r\nc\t") == "ab[31m\nc"
    assert clean_text(None) == ""
    assert clean_text("x" * 50, 10) == "x" * 10 + "…"


# ---------------------------------------------------------------- rota
async def test_reviews_route_defaults_cache_and_validation(async_client, monkeypatch):
    monkeypatch.delenv(ENV_KEY, raising=False)
    fake = AsyncMock(return_value={"items": [], "total": 0, "has_more": False})
    with patch.object(catalog.SOURCES["makerworld"], "reviews", fake):
        r = await async_client.get(f"{BASE}/makerworld/42/reviews")
        again = await async_client.get(f"{BASE}/makerworld/42/reviews")
        other = await async_client.get(f"{BASE}/makerworld/42/reviews", params={"kind": "all", "sort": "newest", "page": 2})
    assert r.status_code == 200, r.text
    assert r.json() == {"items": [], "total": 0, "has_more": False, "kind": "ratings", "sort": "top", "page": 1, "page_size": 10}
    assert again.json() == r.json()
    # "all" não é tipo do MakerWorld → volta ao padrão; "newest" é aceito.
    assert other.json()["kind"] == "ratings" and other.json()["sort"] == "newest" and other.json()["page"] == 2
    assert fake.await_count == 2  # segunda chamada igual veio do cache
    assert (await async_client.get(f"{BASE}/makerworld/42/reviews", params={"page": 0})).status_code == 422
    assert (await async_client.get(f"{BASE}/makerworld/abc/reviews")).status_code == 400
    assert (await async_client.get(f"{BASE}/thingiverse/42/reviews")).status_code == 503
    assert (await async_client.get(f"{BASE}/evil/42/reviews")).status_code == 404


async def test_detail_route_reports_review_capabilities(async_client):
    fake = AsyncMock(return_value={"id": "42", "files": [], "rating": {"average": 4.9, "count": 3}})
    with patch.object(catalog.SOURCES["printables"], "detail", fake):
        r = await async_client.get(f"{BASE}/printables/42")
    assert r.status_code == 200, r.text
    assert r.json()["reviews"] == {"kinds": ["all"], "sorts": ["top"], "page_size": 10}
    assert r.json()["rating"] == {"average": 4.9, "count": 3} and r.json()["stats"] == {}


async def test_reviews_route_permissions(async_client):
    admin = await _setup_auth_with_admin(async_client)
    assert (await async_client.get(f"{BASE}/makerworld/42/reviews")).status_code == 401
    nobody = await _make_user(async_client, admin, username="noreviews", permissions=["printers:read"])
    h = {"Authorization": f"Bearer {nobody}"}
    assert (await async_client.get(f"{BASE}/makerworld/42/reviews", headers=h)).status_code == 403
    assert (await async_client.get(f"{BASE}/printables/42/reviews", headers=h)).status_code == 403
    viewer = await _make_user(async_client, admin, username="mwviewer", permissions=["makerworld:view"])
    fake = AsyncMock(return_value={"items": [], "total": 0, "has_more": False})
    with patch.object(catalog.SOURCES["makerworld"], "reviews", fake):
        ok = await async_client.get(f"{BASE}/makerworld/42/reviews", headers={"Authorization": f"Bearer {viewer}"})
    assert ok.status_code == 200, ok.text

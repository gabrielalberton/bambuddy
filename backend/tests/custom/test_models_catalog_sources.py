"""Fontes do catálogo com transporte simulado (sem IO real).

Parte portada de 1337faye/bambuddy-model-search (commit 1b3b65b59); o filtro
por impressora e o Thingiverse são do fork.
"""

import json

import httpx
import pytest

from backend.app.custom.models_catalog.base import BrowseRequest, order_files
from backend.app.custom.models_catalog.makerworld import MakerWorldSource, printer_match
from backend.app.custom.models_catalog.printables import PrintablesSource
from backend.app.custom.models_catalog.printer_models import (
    makerworld_codes,
    normalize_model,
    printables_ids,
    resolve_models,
)
from backend.app.custom.models_catalog.thingiverse import ENV_KEY, ThingiverseSource
from backend.app.services.model_providers.base import (
    ProviderAuthError,
    ProviderForbiddenError,
    ProviderNotFoundError,
    ProviderUnavailableError,
)
from backend.tests.custom.helpers import valid_stl


# ---------------------------------------------------------------- impressoras
@pytest.mark.parametrize(
    "raw,expected",
    [("A1", "A1"), ("N2S", "A1"), ("Bambu Lab A1", "A1"), ("a1 mini", "A1 MINI"), ("N1", "A1 MINI"), ("C12", "P1S")],
)
def test_normalize_model(raw, expected):
    assert normalize_model(raw) == expected


def test_resolve_models_fallback_and_codes():
    assert resolve_models([]) == ["A1"]
    assert resolve_models(None) == ["A1"]
    assert resolve_models(["N2S", "A1", "P1S,X1C"]) == ["A1", "P1S", "X1C"]
    assert makerworld_codes(["A1", "A1 MINI"]) == ["N2S", "N1"]
    assert printables_ids(["A1"]) == [711]
    assert makerworld_codes(["UNKNOWN"]) == []


def test_order_files_puts_printer_first_and_preselects():
    files = [
        {"id": "1", "sliceable": True, "printer_match": "other"},
        {"id": "2", "sliceable": True, "printer_match": "unknown"},
        {"id": "3", "sliceable": True, "printer_match": "compatible"},
        {"id": "4", "sliceable": True, "printer_match": "native"},
    ]
    ordered, pre = order_files(files)
    assert [f["id"] for f in ordered] == ["4", "3", "2", "1"]
    assert pre == "4"
    _, pre = order_files([{"id": "9", "sliceable": True, "printer_match": "unknown"}])
    assert pre == "9"
    _, pre = order_files([{"id": "9", "sliceable": True, "printer_match": "other"}])
    assert pre is None


# ---------------------------------------------------------------- MakerWorld
def test_makerworld_filter_goes_to_server_and_trending_switches_feed():
    mw = MakerWorldSource()
    path, params, codes = mw.build_params(BrowseRequest(sort="trending", models=["A1"], printer_filter=True))
    assert path == "/select/design2" and params["devModelNames"] == "N2S" and codes == ["N2S"]
    assert "navKey" not in params
    path, params, codes = mw.build_params(BrowseRequest(sort="trending", models=["A1"], printer_filter=False))
    assert path == "/select/design/nav" and params["navKey"] == "Trending" and "devModelNames" not in params
    _, params, _ = mw.build_params(BrowseRequest(sort="popular", query="vase", models=["A1", "P1S"]))
    assert params["orderBy"] == "downloadCount" and params["devModelNames"] == "N2S,C12"
    _, params, _ = mw.build_params(BrowseRequest(sort="newest", models=["A1"]))
    assert params["designCreateSince"] == 1


async def test_makerworld_browse_uses_search_service_and_hides_nsfw():
    seen = []

    def handler(request):
        seen.append(request.url)
        return httpx.Response(
            200,
            json={
                "hits": [
                    {
                        "id": 42,
                        "title": "Vase",
                        "designCreator": {"name": "C"},
                        "cover": "https://makerworld.bblmw.com/v.jpg",
                    },
                    {"id": 43, "title": "nsfw", "nsfw": True},
                ],
                "total": 100,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        data = await MakerWorldSource().browse(
            client, BrowseRequest(query="vase", sort="relevance", category="100", offset=24, models=["A1"])
        )
    assert seen[0].host == "api.bambulab.com"
    assert seen[0].path == "/v1/search-service/select/design2"
    assert seen[0].params["devModelNames"] == "N2S" and seen[0].params["categories"] == "100"
    assert [i["id"] for i in data["items"]] == ["42"]
    assert data["has_more"] and data["printer_filter"] == {"mode": "server", "applied": True, "codes": ["N2S"]}


@pytest.mark.parametrize("status", [418, 429, 500])
async def test_makerworld_search_errors_are_not_empty_success(status):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(status))) as client:
        with pytest.raises(ProviderUnavailableError):
            await MakerWorldSource().browse(client, BrowseRequest(query="x", models=["A1"]))


def test_printer_match_semantics():
    assert printer_match("N2S", [], ["N2S"]) == "native"
    assert printer_match("C12", ["N2S"], ["N2S"]) == "compatible"
    assert printer_match("C12", ["BL-P001"], ["N2S"]) == "other"
    assert printer_match(None, [], ["N2S"]) == "unknown"


async def test_makerworld_detail_a1_profile_first_and_preselected():
    def handler(request):
        if request.url.path.endswith("/instances"):
            return httpx.Response(200, json={"hits": [{"id": 9, "profileId": 3, "title": "community"}], "total": 1})
        return httpx.Response(
            200,
            json={
                "id": 42,
                "title": "Colour vase",
                "license": "BY",
                "instances": [
                    {
                        "id": 7,
                        "profileId": 5,
                        "title": "P1S",
                        "extention": {"modelInfo": {"compatibility": {"devModelName": "C12", "devProductName": "P1S"}}},
                    },
                    {
                        "id": 8,
                        "profileId": 6,
                        "title": "A1 profile",
                        "needAms": True,
                        "extention": {
                            "modelInfo": {
                                "compatibility": {"devModelName": "N2S", "devProductName": "A1"},
                                "plates": [{"index": 1, "filaments": [{"color": "#FF0000"}]}],
                            }
                        },
                    },
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        detail = await MakerWorldSource().detail(client, "42", ["A1"])
    assert [f["id"] for f in detail["files"]] == ["6", "3", "5"]
    assert [f["printer_match"] for f in detail["files"]] == ["native", "unknown", "other"]
    assert detail["preselect_file_id"] == "6"
    assert detail["files"][0]["metadata"]["requires_ams"] is True
    assert detail["files"][0]["metadata"]["plates"][0]["filaments"][0]["color"] == "#FF0000"


# ---------------------------------------------------------------- Printables
def _printables_hit():
    return {
        "id": "42",
        "name": "Vase",
        "user": {"publicUsername": "Maker"},
        "image": {"filePath": "media/vase.jpg"},
        "downloadCount": 123,
    }


async def test_printables_search_variables_and_no_author_filter_by_default():
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"data": {"searchPrints2": {"totalCount": 40, "items": [_printables_hit()]}}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        pr = PrintablesSource()
        result = await pr.browse(
            client, BrowseRequest(query="vase", sort="newest", category="13", offset=24, limit=12, models=["A1"])
        )
        strict = await pr.browse(client, BrowseRequest(query="vase", models=["A1"], author_printer=True))
        off = await pr.browse(
            client, BrowseRequest(query="vase", models=["A1"], printer_filter=False, author_printer=True)
        )
    assert bodies[0]["variables"] == {
        "q": "vase",
        "limit": 12,
        "offset": 24,
        "order": "latest",
        "category": "13",
        "printers": None,
    }
    assert (
        result["has_more"] is True and result["items"][0]["thumbnail"] == "https://media.printables.com/media/vase.jpg"
    )
    assert result["printer_filter"]["applied"] is False
    assert bodies[1]["variables"]["printers"] == [711] and strict["printer_filter"]["applied"] is True
    assert bodies[2]["variables"]["printers"] is None and off["printer_filter"]["applied"] is False


async def test_printables_detail_files_and_membership():
    model = {
        "id": "42",
        "name": "Vase",
        "description": "<p>Useful</p>",
        "license": {"name": "CC BY"},
        "printer": {"id": "711", "name": "Bambu Lab A1"},
        "stls": [{"id": "5", "name": "vase.stl", "fileSize": 134}],
        "otherFiles": [{"id": "6", "name": "project.3mf"}, {"id": "7", "name": "readme.pdf"}],
        "gcodes": [{"id": "8", "name": "a1.gcode", "printer": {"id": "711", "name": "Bambu Lab A1"}}],
    }
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"data": {"print": model}}))
    ) as client:
        pr = PrintablesSource()
        detail = await pr.detail(client, "42", ["A1"])
        with pytest.raises(ProviderNotFoundError):
            await pr.download(client, "42", "stl:999")
    by_id = {f["id"]: f for f in detail["files"]}
    assert by_id["stl:5"]["sliceable"] and by_id["other:6"]["sliceable"] and not by_id["other:7"]["sliceable"]
    assert by_id["gcode:8"]["printer_match"] == "native" and not by_id["gcode:8"]["sliceable"]
    assert detail["files"][0]["id"] == "gcode:8"
    # O gcode da A1 vem primeiro, mas o pré-selecionado é o primeiro arquivo fatiável.
    assert detail["preselect_file_id"] == "stl:5"
    assert detail["metadata"]["author_printer"] == "Bambu Lab A1"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(429),
        httpx.Response(500),
        httpx.Response(200, json={"errors": [{"message": "schema changed"}]}),
        httpx.Response(200, text="challenge"),
    ],
)
async def test_printables_failures_are_not_empty_success(response):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: response)) as client:
        with pytest.raises(ProviderUnavailableError):
            await PrintablesSource().browse(client, BrowseRequest(query="vase"))


async def test_printables_download_flow_and_protected_file():
    def handler(request):
        if request.url.host == "files.printables.com":
            return httpx.Response(200, content=valid_stl())
        body = json.loads(request.content)
        if "Detail" in body["query"]:
            return httpx.Response(200, json={"data": {"print": {"id": "42", "stls": [{"id": "5", "name": "v.stl"}]}}})
        ok = body["variables"]["id"] == "5"
        return httpx.Response(
            200,
            json={
                "data": {
                    "getDownloadLink": {
                        "ok": ok,
                        "output": {"link": "https://files.printables.com/v.stl"} if ok else None,
                    }
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        got = await PrintablesSource().download(client, "42", "stl:5")
    assert got.data == valid_stl() and got.filename == "v.stl"
    assert got.canonical_url == "https://www.printables.com/model/42#file-stl:5"

    def denied(request):
        body = json.loads(request.content)
        if "Detail" in body["query"]:
            return httpx.Response(200, json={"data": {"print": {"id": "42", "stls": [{"id": "5", "name": "v.stl"}]}}})
        return httpx.Response(200, json={"data": {"getDownloadLink": {"ok": False, "errors": []}}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(denied)) as client:
        with pytest.raises(ProviderForbiddenError):
            await PrintablesSource().download(client, "42", "stl:5")


# ---------------------------------------------------------------- Thingiverse
def test_thingiverse_disabled_without_key(monkeypatch):
    monkeypatch.delenv(ENV_KEY, raising=False)
    enabled, reason = ThingiverseSource().enabled()
    assert enabled is False and ENV_KEY in reason


async def test_thingiverse_without_key_never_calls_api(monkeypatch):
    monkeypatch.delenv(ENV_KEY, raising=False)
    calls = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(200))) as c:
        with pytest.raises(ProviderAuthError):
            await ThingiverseSource().browse(c, BrowseRequest(query="x"))
    assert calls == []


async def test_thingiverse_search_detail_and_download(monkeypatch):
    monkeypatch.setenv(ENV_KEY, "tok")
    seen = []

    def handler(request):
        seen.append(request)
        path = request.url.path
        if path.startswith("/search/"):
            return httpx.Response(
                200, json={"total": 50, "hits": [{"id": 9, "name": "Box", "creator": {"name": "Z"}, "thumbnail": "t"}]}
            )
        if path == "/things/9":
            return httpx.Response(
                200, json={"id": 9, "name": "Box", "license": "CC BY", "description_html": "<p>x</p>"}
            )
        if path == "/things/9/files":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 1,
                        "name": "box.stl",
                        "size": 134,
                        "download_url": "https://api.thingiverse.com/files/1/download",
                    },
                    {"id": 2, "name": "notes.pdf", "download_url": "https://api.thingiverse.com/files/2/download"},
                ],
            )
        if path == "/things/9/images":
            return httpx.Response(
                200,
                json=[{"sizes": [{"type": "display", "size": "large", "url": "https://cdn.thingiverse.com/a.jpg"}]}],
            )
        if path == "/files/1/download":
            return httpx.Response(302, headers={"location": "https://cdn.thingiverse.com/assets/box.stl"})
        if request.url.host == "cdn.thingiverse.com":
            return httpx.Response(200, content=valid_stl())
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        tv = ThingiverseSource()
        res = await tv.browse(client, BrowseRequest(query="box", sort="popular", offset=24, limit=12))
        detail = await tv.detail(client, "9", ["A1"])
        got = await tv.download(client, "9", "1")
    assert seen[0].url.path == "/search/box" and seen[0].url.params["page"] == "3"
    assert seen[0].headers["authorization"] == "Bearer tok"
    assert res["items"][0]["id"] == "9" and res["has_more"]
    assert [f["sliceable"] for f in detail["files"]] == [True, False]
    assert "_download" not in detail["files"][0]
    assert detail["images"] == ["https://cdn.thingiverse.com/a.jpg"]
    assert got.data == valid_stl() and got.canonical_url == "https://www.thingiverse.com/thing:9#file-1"
    cdn = [r for r in seen if r.url.host == "cdn.thingiverse.com"][0]
    assert "authorization" not in cdn.headers

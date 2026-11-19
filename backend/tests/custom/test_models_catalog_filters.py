"""Filtro avançado do catálogo: esquema por fonte, validação, parâmetros enviados e chave de cache (sem IO real)."""

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from backend.app.custom.models_catalog import filters as F
from backend.app.custom.models_catalog.base import BrowseRequest
from backend.app.custom.models_catalog.makerworld import MakerWorldSource, build_schema, card
from backend.app.custom.models_catalog.printables import PrintablesSource
from backend.app.custom.models_catalog.thingiverse import ENV_KEY, FILTER_SCHEMA, ThingiverseSource

BASE = "/api/v1/custom/models"

CFG2 = {
    "orderBy": {"design": [{"name": "hotScore"}]},
    "filter": {
        "design": [
            {
                "name": "print_profile",
                "option": None,
                "children": [
                    {"name": "devModelNames", "option": [{"value": "N2S", "displayName": "A1"}]},
                    {"name": "volumeTypes", "option": [{"value": "Standard", "displayName": "Std"}]},
                    {
                        "name": "print_duration",
                        "option": [
                            {"value": "15", "displayName": "15 min"},
                            {"value": "60", "displayName": "1 hr"},
                            {"value": "-", "displayName": "∞"},
                        ],
                    },
                    {"name": "total_weight", "option": [{"value": "10", "displayName": "10 g"}]},
                ],
            },
            {"name": "filament", "children": [{"name": "my_filament", "option": [{"value": "color"}]}]},
            {
                "name": "model_tag",
                "option": [{"value": "cb", "displayName": "CyberBrick"}, {"value": "new", "displayName": "New tag"}],
            },
        ]
    },
}


def ids(schema):
    return {f["id"] for g in schema["groups"] for f in g["filters"]}


async def test_makerworld_schema_from_cfg2_drops_what_does_not_work():
    def handler(request):
        assert request.url.path.endswith("/cfg2")
        return httpx.Response(200, json=CFG2)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        schema = await MakerWorldSource().filter_schema(client)
    assert schema["origin"] == "cfg2"
    assert {"devModelNames", "total_weight", "my_filament", "designType", "materialTypes"}.isdisjoint(ids(schema))
    by_id = F.index(schema)
    assert [o["value"] for o in by_id["model_tag"]["options"]] == ["cb", "new"]  # opções novas do cfg2 entram
    assert [o["value"] for o in by_id["printDuration"]["options"]] == ["15", "60"]  # ∞ = sem limite
    assert by_id["printDuration"]["options"][1]["label"]["pt"] == "1 h"
    # o que o cfg2 não trouxe vem da lista estática
    assert {"nozzleDiameters", "multiColor", "licenses", "designCreateSince", "isPrintable"} <= ids(schema)


async def test_makerworld_schema_falls_back_to_static():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(418))) as client:
        schema = await MakerWorldSource().filter_schema(client)
    assert schema["origin"] == "static" and "cb" in [o["value"] for o in F.index(schema)["model_tag"]["options"]]


def test_validate_normalizes_and_rejects():
    schema = build_schema({}, "static")
    ok = F.validate(
        schema,
        {
            "nozzleDiameters": ["0.6", "0.2", "0.2"],
            "isPrintable": True,
            "printDuration": [None, "60"],
            "licenses": [],
            "multiColor": None,
        },
    )
    assert ok == {"isPrintable": True, "nozzleDiameters": ["0.2", "0.6"], "printDuration": [None, "60"]}
    for bad in (
        {"evil": "x"},
        {"model_tag": "nope"},
        {"model_tag": ["cb"]},
        {"isPrintable": "yes"},
        {"nozzleDiameters": ["0.3"]},
        {"printDuration": ["60", "15"]},
        {"printDuration": ["60"]},
        {"designCreateSince": "2"},
    ):
        with pytest.raises(F.FilterError):
            F.validate(schema, bad)
    # Thingiverse: o fim do período exige o início
    with pytest.raises(F.FilterError):
        F.validate(FILTER_SCHEMA, {"posted": [None, "now-7d"]})
    assert F.validate(FILTER_SCHEMA, {"posted": ["now-365d", None]}) == {"posted": ["now-365d", None]}
    assert F.cache_token({"b": 1, "a": [1]}) == F.cache_token({"a": [1], "b": 1}) and F.cache_token({}) == ""
    with pytest.raises(F.FilterError):
        F.parse_filters("[1]")
    with pytest.raises(F.FilterError):
        F.parse_filters("{bad")


def test_makerworld_params_sorts_and_filters():
    mw = MakerWorldSource()
    filters = {
        "model_tag": "cb",
        "nozzleDiameters": ["0.2", "0.4"],
        "printDuration": [None, "60"],
        "designCreateSince": "7",
        "isPrintable": True,
        "multiColor": "true",
    }
    path, params, _ = mw.build_params(BrowseRequest(sort="trending", printer_filter=False, filters=filters))
    # com filtro o feed nav (que ignora filtros) não é usado
    assert path == "/select/design2" and "navKey" not in params
    assert params["model_tag"] == "cb" and params["nozzleDiameters"] == "0.2,0.4"
    assert params["printDuration"] == "0-60" and params["designCreateSince"] == 7
    assert params["isPrintable"] == "true" and params["multiColor"] == "true"
    _, params, _ = mw.build_params(BrowseRequest(filters={"printDuration": ["300", None]}))
    assert params["printDuration"] == "300-"
    for sort, order in (
        ("likes", "likeCount"),
        ("boosts", "boosts"),
        ("random", "random"),
        ("prints", "printCount"),
        ("collections", "collectionCount"),
    ):
        assert mw.build_params(BrowseRequest(sort=sort, query="x"))[1]["orderBy"] == order
    assert card({"id": 1, "cyberBrickNeeded": True})["cyberbrick"] is True
    assert card({"id": 1, "isFeaturedCyberBrick": True})["cyberbrick"] is True
    assert card({"id": 1})["cyberbrick"] is False


async def test_printables_schema_and_filter_args():
    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        if "licenses" in body["query"] and "searchPrints2" not in body["query"]:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "licenses": [{"id": "1", "name": "Attribution", "abbreviation": "CC-BY"}],
                        "materials": [{"id": "1", "name": "PLA"}, {"id": "4", "name": "Flex"}],
                    }
                },
            )
        return httpx.Response(200, json={"data": {"searchPrints2": {"totalCount": 3, "items": []}}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        pr = PrintablesSource()
        schema = await pr.filter_schema(client)
        by_id = F.index(schema)
        assert schema["origin"] == "graphql"
        assert [o["label"]["pt"] for o in by_id["materialIds"]["options"]] == ["PLA", "Flexível"]
        assert {
            "hasMake",
            "featured",
            "competitionAwarded",
            "aiGenerated",
            "licenses",
            "materialIds",
            "nozzleDiameters",
            "filesType",
            "paid",
            "publishedDateLimitDays",
            "sale",
        } == ids(schema)
        filters = F.validate(
            schema,
            {
                "hasMake": True,
                "materialIds": ["1"],
                "licenses": ["1"],
                "paid": "free",
                "nozzleDiameters": ["0.4"],
                "filesType": "GCODE",
                "publishedDateLimitDays": "30",
            },
        )
        await pr.browse(client, BrowseRequest(query="esp32", sort="makes", filters=filters))
    q = bodies[-1]["query"]
    assert bodies[-1]["variables"]["order"] == "makes_count"
    for frag in (
        "hasMake:true",
        "materialIds:[1]",
        'licenses:["1"]',
        "paid:free",
        "nozzleDiameters:[0.4]",
        "filesType:GCODE",
        "publishedDateLimitDays:30",
    ):
        assert frag in q, frag


async def test_thingiverse_params_and_categories(monkeypatch):
    monkeypatch.setenv(ENV_KEY, "k")
    seen = []

    def handler(request):
        seen.append(request)
        assert request.headers["user-agent"].startswith("Bambuddy")
        if request.url.path == "/categories":
            return httpx.Response(200, json=[{"name": "Hobby", "url": "https://api.thingiverse.com/categories/hobby"}])
        if request.url.path == "/categories/hobby":
            return httpx.Response(200, json={"children": [{"id": 92, "name": "Electronics"}]})
        return httpx.Response(200, json={"hits": [], "total": 0})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        tv = ThingiverseSource()
        cats = await tv.categories(client)
        filters = F.validate(FILTER_SCHEMA, {"posted": ["now-365d", "now-30d"], "has_makes": True, "license": "cc"})
        await tv.browse(client, BrowseRequest(query="esp32", sort="makes", category="92", filters=filters))
    assert cats == [{"id": "92", "name": "Hobby / Electronics"}]
    params = seen[-1].url.params
    assert params["sort"] == "makes" and params["category_id"] == "92" and params["license"] == "cc"
    assert params["posted_after"] == "now-365d" and params["posted_before"] == "now-30d" and params["has_makes"] == "1"


async def test_routes_schema_validation_and_cache_key(async_client):
    schema = build_schema({}, "static")
    fake_schema = AsyncMock(return_value=schema)
    fake = AsyncMock(return_value={"hits": [{"id": 1, "title": "x", "cyberBrickNeeded": True}], "total": 1})
    with (
        patch.object(MakerWorldSource, "filter_schema", fake_schema),
        patch("backend.app.custom.models_catalog.makerworld._search", fake),
    ):
        r = await async_client.get(f"{BASE}/makerworld/filters")
        assert r.status_code == 200 and r.json()["sorts"][0] == "trending" and r.json()["groups"]
        plain = await async_client.get(f"{BASE}/makerworld/browse", params={"query": "box"})
        assert plain.status_code == 200 and plain.json()["filters"] == {}
        one = await async_client.get(
            f"{BASE}/makerworld/browse", params={"query": "box", "filters": json.dumps({"model_tag": "cb"})}
        )
        assert one.status_code == 200, one.text
        assert one.json()["filters"] == {"model_tag": "cb"} and one.json()["items"][0]["cyberbrick"] is True
        # mesmos filtros (outra ordem/forma) = mesma chave de cache; filtro diferente = nova busca
        same = await async_client.get(
            f"{BASE}/makerworld/browse",
            params={"query": "box", "filters": json.dumps({"model_tag": "cb", "licenses": []})},
        )
        assert same.status_code == 200
        bad = await async_client.get(f"{BASE}/makerworld/browse", params={"filters": json.dumps({"x": 1})})
        bad_value = await async_client.get(
            f"{BASE}/makerworld/browse", params={"filters": json.dumps({"model_tag": "zzz"})}
        )
        assert (
            await async_client.get(f"{BASE}/makerworld/browse", params={"query": "box", "sort": "likes"})
        ).status_code == 200
    assert bad.status_code == 400 and bad_value.status_code == 400 and "Invalid filters" in bad.json()["detail"]
    assert fake.await_count == 3  # plain, one, sorted (same veio do cache)
    assert fake.await_args_list[1].args[2]["model_tag"] == "cb"
    assert fake.await_args_list[2].args[2]["orderBy"] == "likeCount"
    assert fake_schema.await_count == 1  # esquema cacheado (1 h)
    # sort de outra fonte cai no padrão da fonte em vez de quebrar
    with patch(
        "backend.app.custom.models_catalog.printables.graphql",
        AsyncMock(return_value={"searchPrints2": {"totalCount": 0, "items": []}}),
    ) as gql:
        r = await async_client.get(f"{BASE}/printables/browse", params={"sort": "boosts"})
    assert r.status_code == 200 and r.json()["sort"] == "popular" and gql.await_args.args[2]["order"] == "popular"

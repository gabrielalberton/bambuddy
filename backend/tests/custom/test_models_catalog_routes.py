"""Rotas /api/v1/custom/models/* com a persistência real da biblioteca."""

from unittest.mock import AsyncMock, patch

import pytest

from backend.app.custom.models_catalog import router as catalog
from backend.app.custom.models_catalog.base import DownloadedFile
from backend.app.custom.models_catalog.thingiverse import ENV_KEY
from backend.app.models.library import LibraryFile
from backend.app.schemas.makerworld import MakerWorldImportResponse
from backend.tests.custom.helpers import valid_stl
from backend.tests.integration.test_makerworld_permission_gate import _make_user, _setup_auth_with_admin

BASE = "/api/v1/custom/models"


def test_routes_sit_before_spa_catch_all():
    from backend.app.main import app

    paths = [getattr(r, "path", "") for r in app.router.routes]
    custom = [i for i, p in enumerate(paths) if p.startswith(BASE)]
    assert len(custom) == 8
    assert max(custom) < paths.index("/{full_path:path}")


async def test_sources_report_filter_semantics(async_client, monkeypatch):
    monkeypatch.delenv(ENV_KEY, raising=False)
    r = await async_client.get(f"{BASE}/sources", params={"printer_models": "N2S"})
    assert r.status_code == 200, r.text
    data = r.json()
    by_id = {s["id"]: s for s in data["sources"]}
    assert by_id["makerworld"]["printer_filter"] == "server"
    assert by_id["printables"]["printer_filter"] == "author_printer"
    assert by_id["thingiverse"]["enabled"] is False and ENV_KEY in by_id["thingiverse"]["disabled_reason"]
    assert data["printer_models"] == ["A1"] and data["makerworld_codes"] == ["N2S"]
    # Sem impressora informada: fallback A1.
    assert (await async_client.get(f"{BASE}/sources")).json()["printer_models"] == ["A1"]


async def test_browse_passes_printer_models_to_makerworld(async_client):
    fake = AsyncMock(return_value={"hits": [{"id": 1, "title": "x"}], "total": 1})
    with patch("backend.app.custom.models_catalog.makerworld._search", fake):
        on = await async_client.get(f"{BASE}/makerworld/browse", params={"query": "vase", "printer_models": ["A1"]})
        off = await async_client.get(
            f"{BASE}/makerworld/browse", params={"query": "vase", "printer_models": ["A1"], "printer_filter": "false"}
        )
    assert on.status_code == off.status_code == 200, (on.text, off.text)
    assert fake.await_args_list[0].args[2]["devModelNames"] == "N2S"
    assert "devModelNames" not in fake.await_args_list[1].args[2]
    assert on.json()["printer_filter"]["applied"] is True and off.json()["printer_filter"]["applied"] is False


async def test_disabled_source_and_bad_inputs(async_client, monkeypatch):
    monkeypatch.delenv(ENV_KEY, raising=False)
    assert (await async_client.get(f"{BASE}/thingiverse/browse")).status_code == 503
    assert (await async_client.get(f"{BASE}/evil/browse")).status_code == 404
    assert (await async_client.get(f"{BASE}/printables/not-a-number")).status_code == 400
    assert (await async_client.get(f"{BASE}/printables/browse", params={"offset": -1})).status_code == 422
    thumb = await async_client.get(f"{BASE}/printables/thumbnail", params={"url": "http://127.0.0.1/secret"})
    assert thumb.status_code == 400
    bad = await async_client.post(f"{BASE}/printables/42/save", json={"file_id": "../x"})
    assert bad.status_code == 422


def _download():
    return DownloadedFile(
        data=valid_stl(),
        filename="vase.stl",
        canonical_url="https://www.printables.com/model/42#file-stl:5",
        page_url="https://www.printables.com/model/42",
    )


async def test_printables_save_persists_attribution_and_deduplicates(async_client, db_session):
    download = AsyncMock(return_value=_download())
    with (
        patch.object(catalog.SOURCES["printables"], "download", download),
        patch("backend.app.api.routes.library._render_stl_thumbnail", AsyncMock(return_value=None)),
    ):
        first = await async_client.post(f"{BASE}/printables/42/save", json={"file_id": "stl:5"})
        second = await async_client.post(f"{BASE}/printables/42/save", json={"file_id": "stl:5"})
    assert first.status_code == 200, first.text
    assert second.json()["library_file_id"] == first.json()["library_file_id"]
    assert first.json()["was_existing"] is False and second.json()["was_existing"] is True
    download.assert_awaited_once()
    row = await db_session.get(LibraryFile, first.json()["library_file_id"])
    assert row.source_type == "printables"
    assert row.source_url == "https://www.printables.com/model/42#file-stl:5"
    assert row.external_url == "https://www.printables.com/model/42"
    assert row.folder_id is not None  # pasta padrão "Printables"


async def test_makerworld_save_delegates_to_upstream_importer(async_client):
    importer = AsyncMock(
        return_value=MakerWorldImportResponse(
            library_file_id=77, filename="a.3mf", folder_id=3, profile_id=6, was_existing=False
        )
    )
    with patch.object(catalog, "import_instance", importer):
        r = await async_client.post(f"{BASE}/makerworld/42/save", json={"file_id": "6"})
    assert r.status_code == 200, r.text
    assert r.json() == {"library_file_id": 77, "filename": "a.3mf", "folder_id": 3, "was_existing": False}
    body = importer.await_args.kwargs["body"]
    assert (body.model_id, body.profile_id, body.folder_id) == (42, 6, None)
    assert (await async_client.post(f"{BASE}/makerworld/42/save", json={"file_id": "stl:6"})).status_code == 400


async def test_permission_boundaries(async_client):
    admin = await _setup_auth_with_admin(async_client)
    assert (await async_client.get(f"{BASE}/printables/browse")).status_code == 401
    assert (await async_client.post(f"{BASE}/printables/42/save", json={"file_id": "stl:5"})).status_code == 401
    nobody = await _make_user(async_client, admin, username="nocatalog", permissions=["printers:read"])
    h = {"Authorization": f"Bearer {nobody}"}
    assert (await async_client.get(f"{BASE}/printables/browse", headers=h)).status_code == 403
    assert (await async_client.get(f"{BASE}/makerworld/browse", headers=h)).status_code == 403
    viewer = await _make_user(async_client, admin, username="catviewer", permissions=["library:read_own"])
    download = AsyncMock(return_value=_download())
    with patch.object(catalog.SOURCES["printables"], "download", download):
        r = await async_client.post(
            f"{BASE}/printables/42/save", headers={"Authorization": f"Bearer {viewer}"}, json={"file_id": "stl:5"}
        )
    assert r.status_code == 403
    download.assert_not_awaited()
    # MakerWorld sem makerworld:import: recusado pelo importador do upstream.
    mw_viewer = await _make_user(async_client, admin, username="mwviewer", permissions=["makerworld:view"])
    r = await async_client.post(
        f"{BASE}/makerworld/42/save", headers={"Authorization": f"Bearer {mw_viewer}"}, json={"file_id": "6"}
    )
    assert r.status_code == 403


async def test_save_sends_web_push_once_and_on_failure(async_client):
    """Salvar do catálogo avisa no PWA (Web Push) quando baixa um arquivo novo e quando o download falha."""
    import asyncio

    from backend.app.services.model_providers.base import ProviderError

    sent = AsyncMock()
    download = AsyncMock(return_value=_download())
    with (
        patch("backend.app.custom.webpush.provider.notify", sent),
        patch.object(catalog.SOURCES["printables"], "download", download),
        patch("backend.app.api.routes.library._render_stl_thumbnail", AsyncMock(return_value=None)),
    ):
        ok = await async_client.post(f"{BASE}/printables/43/save", json={"file_id": "stl:5"})
        again = await async_client.post(f"{BASE}/printables/43/save", json={"file_id": "stl:5"})
        await asyncio.sleep(0)
        assert ok.status_code == 200 and again.json()["was_existing"] is True
        assert sent.await_count == 1
        title, url = sent.await_args.args[1], sent.await_args.args[3]
        assert title == "Modelo salvo na biblioteca" and url == "/files"

        download.side_effect = ProviderError("upstream down")
        failed = await async_client.post(f"{BASE}/printables/44/save", json={"file_id": "stl:6"})
        await asyncio.sleep(0)
        assert failed.status_code >= 500
        assert sent.await_count == 2
        assert sent.await_args.args[1].startswith("Catálogo") and sent.await_args.args[3] == "/model-sources"


async def test_makerworld_author_lists_designs(async_client):
    envelope = {"total": 3, "hits": [{"id": 11, "title": "a", "designCreator": {"uid": 99, "name": "Ana"}}, {"id": 12, "title": "b", "nsfw": True}]}
    fake = AsyncMock(return_value=envelope)
    with patch("backend.app.custom.models_catalog.makerworld._api_json", fake):
        r = await async_client.get(f"{BASE}/makerworld/author/99", params={"offset": 0, "limit": 2})
    assert r.status_code == 200, r.text
    data = r.json()
    assert [i["id"] for i in data["items"]] == ["11"] and data["items"][0]["creator_id"] == "99"
    assert data["has_more"] is True and data["author"] == {"id": "99", "name": "Ana"}
    assert "/published/99/design" in fake.await_args.args[1]
    assert (await async_client.get(f"{BASE}/makerworld/author/abc")).status_code == 400
    assert (await async_client.get(f"{BASE}/printables/author/1")).status_code == 404

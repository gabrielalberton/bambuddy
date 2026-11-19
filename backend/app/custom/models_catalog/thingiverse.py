"""Thingiverse: API REST oficial (api.thingiverse.com), exige App Token gratuito.

Fica DESLIGADA até existir a variável de ambiente
``BAMBUDDY_CUSTOM_THINGIVERSE_API_KEY`` (token criado em
https://www.thingiverse.com/apps/create, tipo "Web App"/"Desktop App").
Sem token a API responde 401 ``NO_TOKEN_PROVIDED`` (conferido em 2026-11-14).

Não há conceito de impressora nem dimensões nos "things": o filtro A1 é
"não aplicável" nesta fonte.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import quote

import httpx

from backend.app.services.model_providers.base import (
    ProviderAuthError,
    ProviderForbiddenError,
    ProviderNotFoundError,
    ProviderUnavailableError,
)

from . import filters as F
from .base import BrowseRequest, CatalogSource, DownloadedFile, ReviewsRequest, order_files, review_item, safe_count
from .transport import HEADERS, fetch_asset, safe_filename

API = "https://api.thingiverse.com"
CDN_HOSTS = ("cdn.thingiverse.com",)
API_HOSTS = ("api.thingiverse.com",)
ENV_KEY = "BAMBUDDY_CUSTOM_THINGIVERSE_API_KEY"
SORTS = {
    "trending": "popular",
    "popular": "popular",
    "newest": "newest",
    "relevance": "relevant",
    "makes": "makes",
    "text": "text",
}
LICENSES = [
    ("cc", "CC BY"), ("cc-sa", "CC BY-SA"), ("cc-nd", "CC BY-ND"), ("cc-nc", "CC BY-NC"), ("cc-nc-sa", "CC BY-NC-SA"),
    ("cc-nc-nd", "CC BY-NC-ND"), ("pd0", "CC0"), ("gpl", "GPL"), ("lgpl", "LGPL"), ("bsd", "BSD"),
]
# Período: ``posted_after``/``posted_before`` (o "antes" só funciona junto com o "depois", medido em 2026-11-19).
POSTED = [
    F.opt("now-365d", "1 ano atrás", "1 year ago"),
    F.opt("now-30d", "30 dias atrás", "30 days ago"),
    F.opt("now-7d", "7 dias atrás", "7 days ago"),
]
FILTER_SCHEMA = F.schema(
    "thingiverse",
    [
        F.group("model", "Modelo", "Model", [
            F.fdef("posted", "range", "Publicado entre", "Posted between", POSTED, requires_min=True,
                   hint=("O Thingiverse só aceita o fim junto com o início.", "Thingiverse needs a start to use an end.")),
            F.fdef("has_makes", "bool", "Com makes (impressões postadas)", "Has makes"),
            F.fdef("is_featured", "bool", "Destaque", "Featured"),
            F.fdef("customizable", "bool", "Customizável (Customizer/OpenSCAD)", "Customizable"),
            F.fdef("is_derivative", "bool", "Só remixes", "Remixes only"),
            F.fdef("is_wip", "bool", "Só em andamento (WIP)", "Work in progress only"),
        ]),
        F.group("license", "Licença", "License", [
            F.fdef("license", "enum", "Licença", "License",
                   [F.opt(v, "Domínio público (CC0)" if v == "pd0" else n, n) for v, n in LICENSES]),
        ]),
    ],
    "static",
)


def apply_filters(params: dict[str, Any], filters: dict[str, Any]) -> None:
    for fid, value in filters.items():
        if fid == "posted":
            lo, hi = value
            params["posted_after"] = lo
            if hi:
                params["posted_before"] = hi
        elif value is True:
            params[fid] = 1
        else:
            params[fid] = value


def api_key() -> str | None:
    value = os.environ.get(ENV_KEY, "").strip()
    return value or None


def card(thing: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": "thingiverse",
        "id": str(thing["id"]),
        "title": thing.get("name") or "Untitled model",
        "url": thing.get("public_url") or f"https://www.thingiverse.com/thing:{thing['id']}",
        "creator": (thing.get("creator") or {}).get("name") or "Unknown creator",
        "thumbnail": thing.get("thumbnail") or thing.get("preview_image") or None,
        "downloads": thing.get("download_count"),
        "likes": thing.get("like_count"),
    }


class ThingiverseSource(CatalogSource):
    id = "thingiverse"
    name = "Thingiverse"
    default_folder = "Thingiverse"
    thumbnail_hosts = CDN_HOSTS
    permission_kind = "library"
    printer_filter = "none"
    sorts = ("popular", "newest", "relevance", "makes", "text")
    # Thingiverse não tem estrelas; só comentários (``/things/{id}/comments``, NÃO verificado ao vivo: sem token).
    review_kinds = ("comments",)
    review_sorts = ("newest",)

    def enabled(self) -> tuple[bool, str | None]:
        if api_key():
            return True, None
        return False, f"Thingiverse needs a free App Token in {ENV_KEY}"

    def printer_filter_note(self) -> str:
        return "not applicable: Thingiverse has no printer or size data"

    async def _get(self, client: httpx.AsyncClient, path: str, params: dict[str, Any] | None = None) -> Any:
        key = api_key()
        if not key:
            raise ProviderAuthError(f"Thingiverse is disabled: set {ENV_KEY}")
        try:
            response = await client.get(
                f"{API}{path}",
                params=params,
                headers={**HEADERS, "Authorization": f"Bearer {key}"},
                follow_redirects=False,
                timeout=30,
            )
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError("Thingiverse request failed or timed out") from exc
        if response.status_code == 401:
            raise ProviderAuthError("Thingiverse rejected the App Token")
        if response.status_code == 403:
            raise ProviderForbiddenError("Thingiverse refused access to this resource")
        if response.status_code == 404:
            raise ProviderNotFoundError("Thingiverse model not found")
        if response.status_code == 429:
            raise ProviderUnavailableError("Thingiverse rate-limited this request. Try again later.")
        if response.status_code != 200:
            raise ProviderUnavailableError(f"Thingiverse returned HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderUnavailableError("Thingiverse returned non-JSON data") from exc

    def page_url(self, model_id: str) -> str:
        return f"https://www.thingiverse.com/thing:{model_id}"

    async def browse(self, client: httpx.AsyncClient, req: BrowseRequest) -> dict[str, Any]:
        page = req.offset // req.limit + 1
        params: dict[str, Any] = {
            "type": "things", "page": page, "per_page": req.limit, "sort": SORTS.get(req.sort, "popular"),
        }
        if req.category:
            params["category_id"] = req.category
        apply_filters(params, req.filters)
        data = await self._get(client, f"/search/{quote(req.query.strip(), safe='')}", params)
        if isinstance(data, dict):
            hits, total = data.get("hits"), data.get("total")
        else:
            hits, total = data, None
        if not isinstance(hits, list):
            raise ProviderUnavailableError("Thingiverse returned an invalid model list")
        return {
            "items": [card(t) for t in hits if isinstance(t, dict) and t.get("id")],
            "total": total if isinstance(total, int) else None,
            "has_more": req.offset + len(hits) < total if isinstance(total, int) else len(hits) == req.limit,
            "printer_filter": {"mode": "none", "applied": False},
        }

    async def filter_schema(self, client: httpx.AsyncClient) -> dict[str, Any]:
        return FILTER_SCHEMA

    async def categories(self, client: httpx.AsyncClient) -> list[dict[str, str]]:
        """Subcategorias (``/categories/{slug}`` → ``children``; o ``category_id`` da busca aceita só elas com id)."""
        top = await self._get(client, "/categories")
        slugs = [
            (str(c["name"])[:60], str(c["url"]).rstrip("/").rsplit("/", 1)[-1])
            for c in top if isinstance(c, dict) and c.get("name") and isinstance(c.get("url"), str)
        ] if isinstance(top, list) else []
        slots = asyncio.Semaphore(3)

        async def children(name: str, slug: str) -> list[dict[str, str]]:
            if not slug.replace("-", "").isalnum():
                return []
            async with slots:
                data = await self._get(client, f"/categories/{slug}")
            kids = data.get("children") if isinstance(data, dict) else None
            return [
                {"id": str(k["id"]), "name": f"{name} / {str(k['name'])[:60]}"}
                for k in kids or [] if isinstance(k, dict) and isinstance(k.get("id"), int) and k.get("name")
            ]

        groups = await asyncio.gather(*(children(n, s) for n, s in slugs))
        return [c for g in groups for c in g]

    async def _files(self, client: httpx.AsyncClient, model_id: str) -> list[dict[str, Any]]:
        raw = await self._get(client, f"/things/{model_id}/files")
        files = []
        for f in raw if isinstance(raw, list) else []:
            if not isinstance(f, dict) or not f.get("id"):
                continue
            name = f.get("name") or "unnamed"
            ext = PurePosixPath(name).suffix.lower().lstrip(".")
            files.append(
                {
                    "id": str(f["id"]),
                    "name": name,
                    "format": ext or "file",
                    "size": f.get("size"),
                    "sliceable": ext in ("stl", "3mf"),
                    "printer_match": "unknown",
                    "printer": None,
                    "metadata": {},
                    "_download": f.get("download_url") or f.get("direct_url"),
                }
            )
        return files

    async def detail(self, client: httpx.AsyncClient, model_id: str, models: list[str]) -> dict[str, Any]:
        thing = await self._get(client, f"/things/{model_id}")
        if not isinstance(thing, dict) or not thing.get("id"):
            raise ProviderNotFoundError("Thingiverse model not found")
        files = [{k: v for k, v in f.items() if k != "_download"} for f in await self._files(client, model_id)]
        images_raw = await self._get(client, f"/things/{model_id}/images")
        images = []
        for img in images_raw if isinstance(images_raw, list) else []:
            sizes = img.get("sizes") if isinstance(img, dict) else None
            best = next(
                (s.get("url") for s in sizes or [] if s.get("type") == "display" and s.get("size") == "large"), None
            )
            if isinstance(best, str):
                images.append(best)
        ordered, preselect = order_files(files)
        return {
            **card(thing),
            "description_html": thing.get("description_html") or "",
            "images": images[:40],
            "license": thing.get("license"),
            "files": ordered,
            "preselect_file_id": preselect,
            "printer_models": models,
            "metadata": {},
            "rating": None,
            "stats": {
                "downloads": safe_count(thing.get("download_count")),
                "likes": safe_count(thing.get("like_count")),
                "makes": safe_count(thing.get("make_count")),
                "published": thing.get("added") if isinstance(thing.get("added"), str) else None,
            },
        }

    async def reviews(self, client: httpx.AsyncClient, model_id: str, req: ReviewsRequest) -> dict[str, Any]:
        raw = await self._get(
            client, f"/things/{model_id}/comments", {"page": req.page, "per_page": req.page_size}
        )
        hits = [c for c in raw if isinstance(c, dict) and c.get("id")] if isinstance(raw, list) else []
        items = [
            review_item(
                item_id=f"c{c['id']}",
                kind="comment",
                author=(c.get("user") or {}).get("name"),
                text=c.get("body"),
                created=c.get("added"),
            )
            for c in hits
        ]
        return {"items": items, "total": None, "has_more": len(hits) >= req.page_size}

    async def download(self, client: httpx.AsyncClient, model_id: str, file_id: str) -> DownloadedFile:
        files = await self._files(client, model_id)
        selected = next((f for f in files if f["id"] == file_id), None)
        if selected is None or not isinstance(selected.get("_download"), str):
            raise ProviderNotFoundError("Select a file belonging to this Thingiverse model")
        url = selected["_download"]
        key = api_key() or ""
        # download_url (api.thingiverse.com/files/<id>/download) redireciona uma vez para o CDN.
        payload, _ = await fetch_asset(
            client,
            url,
            API_HOSTS + CDN_HOSTS,
            headers={"Authorization": f"Bearer {key}"} if url.startswith(API) else None,
            redirect_hosts=CDN_HOSTS,
        )
        return DownloadedFile(
            data=payload,
            filename=safe_filename(selected["name"], f"thingiverse-{model_id}.{selected['format']}"),
            canonical_url=self.canonical_url(model_id, file_id),
            page_url=self.page_url(model_id),
        )

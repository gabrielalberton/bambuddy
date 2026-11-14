"""MakerWorld: catálogo pelo search-service público da Bambu (não o design/search vazio).

Portado de 1337faye/bambuddy-model-search (commit 1b3b65b59, AGPL-3.0,
``makerworld/catalogue.py``) e estendido com o filtro por impressora:
``devModelNames=<código>`` no ``select/design2`` filtra no servidor pelos
modelos com algum perfil compatível (``compatibility`` ou
``otherCompatibility``) com a impressora. Evidência: custom/docs/fontes-de-modelos.md.

Detalhe e download continuam no ``MakerWorldService`` do upstream (download
pelo ``/makerworld/import`` com a credencial Bambu Cloud já salva).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

import httpx

from backend.app.services.model_providers.base import (
    ProviderForbiddenError,
    ProviderNotFoundError,
    ProviderResourceRef,
    ProviderUnavailableError,
)
from backend.app.services.model_providers.makerworld.http import MAKERWORLD_CDN_HOSTS
from backend.app.services.model_providers.makerworld.service import MakerWorldService

from .base import BrowseRequest, CatalogSource, order_files
from .printer_models import makerworld_codes
from .transport import HEADERS

SEARCH_BASE = "https://api.bambulab.com/v1/search-service"


def card(design: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": "makerworld",
        "id": str(design["id"]),
        "title": design.get("title") or "Untitled model",
        "url": f"https://makerworld.com/en/models/{design['id']}",
        "creator": (design.get("designCreator") or {}).get("name") or "Unknown creator",
        "thumbnail": design.get("coverUrl") or design.get("cover") or None,
        "downloads": design.get("downloadCount"),
        "likes": design.get("likeCount"),
    }


def _dev_codes(info: dict[str, Any], instance: dict[str, Any]) -> tuple[str | None, list[str]]:
    primary = info.get("compatibility") or instance.get("compatibility") or {}
    others = info.get("otherCompatibility") or instance.get("otherCompatibility") or []
    code = primary.get("devModelName") if isinstance(primary, dict) else None
    other_codes = [o.get("devModelName") for o in others if isinstance(o, dict) and o.get("devModelName")]
    return code, other_codes


def printer_match(code: str | None, others: list[str], wanted: list[str]) -> str:
    if not code and not others:
        return "unknown"
    if code in wanted:
        return "native"
    if any(o in wanted for o in others):
        return "compatible"
    return "other"


async def _search(client: httpx.AsyncClient, path: str, params: dict[str, Any]) -> dict[str, Any]:
    try:
        response = await client.get(f"{SEARCH_BASE}{path}?{urlencode(params)}", headers=HEADERS, timeout=30)
    except httpx.HTTPError as exc:
        raise ProviderUnavailableError("MakerWorld search request failed or timed out") from exc
    if response.status_code == 403:
        raise ProviderForbiddenError("MakerWorld refused the search request")
    if response.status_code == 404:
        raise ProviderNotFoundError("MakerWorld search endpoint not found")
    if response.status_code == 418:
        raise ProviderUnavailableError(
            "MakerWorld is challenging this IP (HTTP 418, CAPTCHA). It usually clears in a few hours."
        )
    if response.status_code == 429:
        raise ProviderUnavailableError("MakerWorld rate-limited the request (HTTP 429). Try again shortly.")
    if response.status_code != 200:
        raise ProviderUnavailableError(f"MakerWorld search returned HTTP {response.status_code}")
    try:
        data = response.json()
    except ValueError as exc:
        raise ProviderUnavailableError("MakerWorld search returned non-JSON data") from exc
    if not isinstance(data, dict) or not isinstance(data.get("hits") or [], list):
        raise ProviderUnavailableError("MakerWorld returned an invalid search response")
    return data


class MakerWorldSource(CatalogSource):
    id = "makerworld"
    name = "MakerWorld"
    default_folder = "MakerWorld"
    thumbnail_hosts = MAKERWORLD_CDN_HOSTS
    permission_kind = "makerworld"
    printer_filter = "server"
    sorts = ("trending", "popular", "newest", "relevance")

    def printer_filter_note(self) -> str:
        return "server: search-service devModelNames (profile compatibility)"

    def build_params(self, req: BrowseRequest) -> tuple[str, dict[str, Any], list[str]]:
        codes = makerworld_codes(req.models) if req.printer_filter else []
        params: dict[str, Any] = {"keyword": req.query, "offset": req.offset, "limit": req.limit}
        if req.category:
            params["categories"] = req.category
        if req.sort == "popular":
            params["orderBy"] = "downloadCount"
        elif req.sort == "newest":
            # O search-service ignora chaves de "mais novo"; o filtro real é
            # "criados nas últimas 24 h" (rótulo "Recentes · 24 h" na UI).
            params["designCreateSince"] = 1
        if codes:
            params["devModelNames"] = ",".join(codes)
        # O feed Trending (nav) ignora devModelNames (conferido ao vivo); com o
        # filtro ligado usamos o ranking padrão do design2, que é o mesmo feed
        # de "em alta" sem palavra-chave.
        if not req.query and not req.category and req.sort == "trending" and not codes:
            params["navKey"] = "Trending"
            return "/select/design/nav", params, codes
        return "/select/design2", params, codes

    async def browse(self, client: httpx.AsyncClient, req: BrowseRequest) -> dict[str, Any]:
        path, params, codes = self.build_params(req)
        envelope = await _search(client, path, params)
        hits = envelope.get("hits") or []
        items = [card(h) for h in hits if isinstance(h, dict) and h.get("id") and not h.get("nsfw")]
        total = envelope.get("total")
        return {
            "items": items,
            "total": total if isinstance(total, int) else None,
            "has_more": req.offset + len(hits) < total if isinstance(total, int) else len(hits) == req.limit,
            "printer_filter": {"mode": "server", "applied": bool(codes), "codes": codes},
        }

    async def categories(self, client: httpx.AsyncClient) -> list[dict[str, str]]:
        service = MakerWorldService(client=client)
        root = await service._get_json("/design/category")
        result: list[dict[str, str]] = []

        def walk(nodes: list[Any], parent: str = "") -> None:
            for node in nodes:
                if not isinstance(node, dict) or "id" not in node or "name" not in node:
                    continue
                name = f"{parent} / {node['name']}" if parent else node["name"]
                result.append({"id": str(node["id"]), "name": name})
                walk(node.get("children") or [], name)

        walk(root.get("children") or [])
        return result

    async def detail(self, client: httpx.AsyncClient, model_id: str, models: list[str]) -> dict[str, Any]:
        service = MakerWorldService(client=client)
        resolved = await service.resolve(ProviderResourceRef(source_type="makerworld", external_id=model_id))
        design = resolved.design
        wanted = makerworld_codes(models)
        by_profile: dict[str, dict[str, Any]] = {
            str(i.get("profileId")): i for i in design.get("instances") or [] if isinstance(i, dict)
        }
        for instance in resolved.instances:
            if isinstance(instance, dict) and instance.get("profileId"):
                key = str(instance["profileId"])
                by_profile[key] = {**instance, **by_profile.get(key, {})}
        files = []
        for pid, instance in by_profile.items():
            if not pid.isdigit() or int(pid) <= 0:
                continue
            info = (instance.get("extention") or {}).get("modelInfo") or {}
            code, others = _dev_codes(info, instance)
            primary = info.get("compatibility") or instance.get("compatibility") or {}
            plates = info.get("plates") or []
            files.append(
                {
                    "id": pid,
                    "name": instance.get("title") or f"Print profile {pid}",
                    "format": "3mf",
                    "size": (info.get("f3mf") or {}).get("size") or None,
                    "sliceable": True,
                    "printer_match": printer_match(code, others, wanted),
                    "printer": (primary.get("devProductName") if isinstance(primary, dict) else None) or None,
                    "metadata": {
                        "printer_code": code,
                        "compatible_codes": others,
                        "plates": plates if isinstance(plates, list) else [],
                        "requires_ams": bool(instance.get("needAms", False)),
                        "creator": (instance.get("instanceCreator") or instance.get("creator") or {}).get("name"),
                        "downloads": instance.get("downloadCount"),
                    },
                }
            )
        ordered, preselect = order_files(files)
        ext = design.get("designExtension") or {}
        images = [
            p["url"]
            for key in ("design_pictures", "real_pictures")
            for p in ext.get(key) or []
            if isinstance(p, dict) and p.get("url")
        ]
        license_value = design.get("license")
        return {
            **card(design),
            "description_html": design.get("summary") or "",
            "images": images[:40],
            "license": license_value if isinstance(license_value, str) else None,
            "files": ordered,
            "preselect_file_id": preselect,
            "printer_models": models,
            "metadata": {"tags": design.get("tags") or []},
        }

"""Printables: GraphQL público (api.printables.com/graphql/), anônimo.

Portado de 1337faye/bambuddy-model-search (commit 1b3b65b59, AGPL-3.0,
``model_providers/printables``). O site printables.com fica atrás de desafio
Cloudflare; a API GraphQL pública e o CDN respondem direto, sem contornar nada.

Filtro por impressora: o Printables não publica dimensões do modelo nem
perfis por impressora. O único dado é a "impressora usada pelo autor"
(``print.printer``), filtrável no servidor por ``searchPrints2(printerIds:)``.
Ele é raro (ex.: A1 = 127 modelos no catálogo todo), então NÃO é aplicado pelo
filtro padrão; existe como opção explícita (``author_printer``).
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

import httpx

from backend.app.services.model_providers.base import (
    ProviderAuthError,
    ProviderForbiddenError,
    ProviderNotFoundError,
    ProviderUnavailableError,
    ProviderUrlError,
)

from .base import BrowseRequest, CatalogSource, DownloadedFile, order_files
from .printer_models import printables_ids
from .transport import HEADERS, fetch_asset, safe_filename

API = "https://api.printables.com/graphql/"
CDN_HOSTS = ("media.printables.com", "files.printables.com")
CARD_FIELDS = "id name likesCount downloadCount user { publicUsername } image { filePath }"
DETAIL_FIELDS = (
    CARD_FIELDS
    + """
 description license { name } images { filePath } printer { id name }
 stls { id name fileSize } otherFiles { id name fileSize }
 gcodes { id name fileSize printer { id name } } slas { id name fileSize }
"""
)
ORDERING = {"trending": "popular", "popular": "popular", "newest": "latest", "relevance": "best_match"}


_IMAGE_PATH = re.compile(r"^(?P<dir>media/prints/\d+/images/[^/]+)/(?P<stem>[^/]+)\.(?P<ext>[A-Za-z0-9]{2,5})$")


def image_url(image: dict | None, size: str | None = None) -> str | None:
    """URL da imagem; com ``size`` usa a miniatura webp que o CDN do Printables gera.

    ``size`` = "cover/640x480" (cards) ou "inside/1280x960" (galeria). O
    original passa de 1-7 MB; a miniatura tem dezenas de KB (celular).
    """
    path = (image or {}).get("filePath")
    if not isinstance(path, str) or not path:
        return None
    if path.startswith("https://"):
        return path
    path = path.lstrip("/")
    match = _IMAGE_PATH.match(path)
    if size and match:
        return f"https://media.printables.com/{match['dir']}/thumbs/{size}/{match['ext'].lower()}/{match['stem']}.webp"
    return "https://media.printables.com/" + path


def card(model: dict) -> dict:
    return {
        "provider": "printables",
        "id": str(model["id"]),
        "title": model.get("name") or "Untitled model",
        "url": f"https://www.printables.com/model/{model['id']}",
        "creator": (model.get("user") or {}).get("publicUsername") or "Unknown creator",
        "thumbnail": image_url(model.get("image"), "cover/640x480"),
        "downloads": model.get("downloadCount"),
        "likes": model.get("likesCount"),
    }


async def graphql(client: httpx.AsyncClient, query: str, variables: dict | None = None) -> dict:
    try:
        response = await client.post(
            API, json={"query": query, "variables": variables or {}}, headers=HEADERS, follow_redirects=False
        )
    except httpx.HTTPError as exc:
        raise ProviderUnavailableError("Printables request failed or timed out") from exc
    if response.status_code == 401:
        raise ProviderAuthError("Printables requires authentication for this resource")
    if response.status_code == 403:
        raise ProviderForbiddenError("Printables refused access to this resource; it may be restricted")
    if response.status_code == 404:
        raise ProviderNotFoundError("Printables model or file was not found")
    if response.status_code == 429:
        raise ProviderUnavailableError("Printables rate-limited this request. Try again later.")
    if response.status_code != 200:
        raise ProviderUnavailableError(f"Printables returned HTTP {response.status_code}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise ProviderUnavailableError("Printables returned non-JSON data") from exc
    if not isinstance(payload, dict) or payload.get("errors") or not isinstance(payload.get("data"), dict):
        raise ProviderUnavailableError(
            "Printables could not fulfil this query; its API may have changed or access is restricted"
        )
    return payload["data"]


class PrintablesSource(CatalogSource):
    id = "printables"
    name = "Printables"
    default_folder = "Printables"
    thumbnail_hosts = CDN_HOSTS
    permission_kind = "library"
    printer_filter = "author_printer"
    sorts = ("popular", "newest", "relevance")

    def printer_filter_note(self) -> str:
        return "not applicable: no dimensions/printer profiles; optional author-declared printer (printerIds)"

    def page_url(self, model_id: str) -> str:
        return f"https://www.printables.com/model/{model_id}"

    async def browse(self, client: httpx.AsyncClient, req: BrowseRequest) -> dict[str, Any]:
        ordering = ORDERING.get(req.sort)
        if ordering is None:
            raise ProviderUrlError("Unsupported Printables sort")
        ids = printables_ids(req.models) if (req.printer_filter and req.author_printer) else []
        variables: dict[str, Any] = {
            "q": req.query,
            "limit": req.limit,
            "offset": req.offset,
            "order": ordering,
            "category": req.category or None,
            "printers": ids or None,
        }
        data = await graphql(
            client,
            """query Browse($q:String!,$limit:Int,$offset:Int,$order:SearchChoicesEnum,$category:ID,$printers:[Int]) {
          searchPrints2(query:$q,printType:print,limit:$limit,offset:$offset,ordering:$order,categoryId:$category,printerIds:$printers) {
            totalCount items { """
            + CARD_FIELDS
            + " } } }",
            variables,
        )
        result = data.get("searchPrints2")
        if not isinstance(result, dict) or not isinstance(result.get("items"), list):
            raise ProviderUnavailableError("Printables returned an invalid model list")
        hits = result["items"]
        total = result.get("totalCount")
        return {
            "items": [card(m) for m in hits if isinstance(m, dict) and m.get("id")],
            "total": total if isinstance(total, int) else None,
            "has_more": req.offset + len(hits) < total if isinstance(total, int) else len(hits) == req.limit,
            "printer_filter": {"mode": "author_printer", "applied": bool(ids), "printer_ids": ids},
        }

    async def categories(self, client: httpx.AsyncClient) -> list[dict[str, str]]:
        data = await graphql(client, "{ categories { id name } }")
        if not isinstance(data.get("categories"), list):
            raise ProviderUnavailableError("Printables returned invalid categories")
        return [{"id": str(c["id"]), "name": c["name"]} for c in data["categories"] if c.get("id") and c.get("name")]

    async def _model(self, client: httpx.AsyncClient, model_id: str) -> dict[str, Any]:
        data = await graphql(
            client, "query Detail($id:ID!) { print(id:$id) { " + DETAIL_FIELDS + " } }", {"id": model_id}
        )
        model = data.get("print")
        if not isinstance(model, dict):
            raise ProviderNotFoundError("This Printables model is deleted, private, or unavailable")
        return model

    def _files(self, model: dict[str, Any], wanted_ids: list[int]) -> list[dict[str, Any]]:
        files = []
        for group, kind in (("stls", "stl"), ("otherFiles", "other"), ("gcodes", "gcode"), ("slas", "sla")):
            for file in model.get(group) or []:
                if not isinstance(file, dict) or not file.get("id"):
                    continue
                name = file.get("name") or "unnamed"
                ext = PurePosixPath(name).suffix.lower().lstrip(".")
                printer = file.get("printer") if isinstance(file.get("printer"), dict) else None
                if printer and printer.get("id"):
                    match = "native" if int(printer["id"]) in wanted_ids else "other"
                else:
                    # STL/3MF do Printables não declaram impressora nem tamanho.
                    match = "unknown"
                files.append(
                    {
                        "id": f"{kind}:{file['id']}",
                        "name": name,
                        "format": ext or kind,
                        "size": file.get("fileSize"),
                        "sliceable": ext in ("stl", "3mf"),
                        "printer_match": match,
                        "printer": (printer or {}).get("name"),
                        "metadata": {"file_group": kind},
                    }
                )
        return files

    async def detail(self, client: httpx.AsyncClient, model_id: str, models: list[str]) -> dict[str, Any]:
        model = await self._model(client, model_id)
        ordered, preselect = order_files(self._files(model, printables_ids(models)))
        author_printer = (model.get("printer") or {}).get("name") if isinstance(model.get("printer"), dict) else None
        return {
            **card(model),
            "description_html": model.get("description") or "",
            "thumbnail": image_url(model.get("image"), "inside/1280x960"),
            "images": [u for img in (model.get("images") or [])[:40] if (u := image_url(img, "inside/1280x960"))],
            "license": (model.get("license") or {}).get("name"),
            "files": ordered,
            "preselect_file_id": preselect,
            "printer_models": models,
            "metadata": {"author_printer": author_printer},
        }

    async def download(self, client: httpx.AsyncClient, model_id: str, file_id: str) -> DownloadedFile:
        model = await self._model(client, model_id)
        selected = next((f for f in self._files(model, []) if f["id"] == file_id), None)
        if selected is None:
            raise ProviderNotFoundError("Select a file belonging to this Printables model")
        kind, raw_id = selected["id"].split(":", 1)
        data = await graphql(
            client,
            """mutation Download($id:ID!,$model:ID!,$type:DownloadFileTypeEnum!) {
          getDownloadLink(id:$id,printId:$model,fileType:$type,source:model_detail) {
            ok errors { field messages } output { link }
          }
        }""",
            {"id": raw_id, "model": model_id, "type": kind},
        )
        result = data.get("getDownloadLink") or {}
        link = (result.get("output") or {}).get("link")
        if not result.get("ok") or not isinstance(link, str) or not link:
            raise ProviderForbiddenError(
                "Printables did not grant a download for this file. It may require sign-in or be restricted."
            )
        payload, _ = await fetch_asset(client, link, CDN_HOSTS)
        filename = safe_filename(selected["name"], f"printables-{model_id}.{selected['format']}")
        return DownloadedFile(
            data=payload,
            filename=filename,
            canonical_url=self.canonical_url(model_id, file_id),
            page_url=self.page_url(model_id),
        )

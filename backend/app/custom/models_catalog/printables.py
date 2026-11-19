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

from . import filters as F
from .base import BrowseRequest, CatalogSource, DownloadedFile, ReviewsRequest, order_files, review_item, safe_count
from .printer_models import printables_ids
from .transport import HEADERS, fetch_asset, safe_filename

API = "https://api.printables.com/graphql/"
CDN_HOSTS = ("media.printables.com", "files.printables.com")
CARD_FIELDS = "id name likesCount downloadCount user { publicUsername } image { filePath }"
DETAIL_FIELDS = (
    CARD_FIELDS
    + """
 description license { name } images { filePath } printer { id name }
 ratingAvg ratingCount makesCount datePublished
 stls { id name fileSize } otherFiles { id name fileSize }
 gcodes { id name fileSize printer { id name } } slas { id name fileSize }
"""
)
ORDERING = {
    "trending": "popular",
    "popular": "popular",
    "newest": "latest",
    "relevance": "best_match",
    "rating": "rating",
    "makes": "makes_count",
}
NOZZLES = ["0.2", "0.25", "0.3", "0.4", "0.5", "0.6", "0.8", "1.0"]
_LICENSE_PT = {
    "7": "Domínio público (CC0)",
    "13": "Licença padrão de arquivo digital",
    "15": "Uso comercial",
    "14": "Uso comercial, sem derivados",
}
_MATERIAL_PT = {
    "Flex": "Flexível",
    "Special": "Especial",
    "Carbon filled": "Com fibra de carbono",
    "Metal filled": "Com metal",
    "Wood filled": "Com madeira",
}


def build_schema(licenses: list[tuple[str, str]], materials: list[tuple[str, str]], origin: str) -> dict[str, Any]:
    """Argumentos do ``searchPrints2`` achados e medidos em 2026-11-19 (introspecção desligada no Printables)."""
    return F.schema(
        "printables",
        [
            F.group(
                "model",
                "Modelo",
                "Model",
                [
                    F.fdef("publishedDateLimitDays", "days", "Publicado", "Published", F.DAYS_OPTIONS),
                    F.fdef("hasMake", "bool", "Com makes (impressões postadas)", "Has makes"),
                    F.fdef("featured", "bool", "Destaque", "Featured"),
                    F.fdef("competitionAwarded", "bool", "Premiado em concurso", "Competition winner"),
                    F.fdef(
                        "aiGenerated",
                        "bool",
                        "Só gerados por IA",
                        "AI-generated only",
                        hint=(
                            "O Printables não deixa excluir os de IA, só mostrar apenas eles.",
                            "Printables can only show AI models, not hide them.",
                        ),
                    ),
                ],
            ),
            F.group(
                "files",
                "Arquivos e impressão",
                "Files and printing",
                [
                    F.fdef(
                        "filesType",
                        "enum",
                        "G-code",
                        "G-code",
                        [
                            F.opt("GCODE", "Com G-code", "Has G-code"),
                            F.opt("NONE", "Sem G-code", "No G-code"),
                        ],
                    ),
                    F.fdef(
                        "nozzleDiameters",
                        "multi",
                        "Diâmetro do bico (G-code)",
                        "Nozzle diameter (G-code)",
                        [F.opt(n, f"{n} mm") for n in NOZZLES],
                        hint=("Do G-code enviado pelo autor.", "From the author's G-code."),
                    ),
                    F.fdef(
                        "materialIds",
                        "multi",
                        "Material declarado",
                        "Declared material",
                        [F.opt(i, _MATERIAL_PT.get(n, n), n) for i, n in materials],
                    ),
                ],
            ),
            F.group(
                "price",
                "Preço",
                "Price",
                [
                    F.fdef(
                        "paid",
                        "enum",
                        "Preço",
                        "Price",
                        [
                            F.opt("free", "Grátis", "Free"),
                            F.opt("paid", "Pagos", "Paid"),
                            F.opt("club", "Clube (assinatura)", "Club"),
                            F.opt("all", "Todos (grátis, pagos e clube)", "All"),
                        ],
                    ),
                    F.fdef("sale", "bool", "Em promoção", "On sale"),
                ],
            ),
            F.group(
                "license",
                "Licença",
                "License",
                [
                    F.fdef(
                        "licenses",
                        "multi",
                        "Licença",
                        "License",
                        [F.opt(i, _LICENSE_PT.get(i, n), n) for i, n in licenses],
                    ),
                ],
            ),
        ],
        origin,
    )


STATIC_LICENSES = [
    ("7", "CC0"),
    ("1", "CC-BY"),
    ("2", "CC-BY-SA"),
    ("8", "CC-BY-ND"),
    ("3", "CC-BY-NC"),
    ("4", "CC-BY-NC-SA"),
    ("6", "CC-BY-NC-ND"),
    ("9", "GPL 2.0"),
    ("12", "GPL 3.0"),
    ("10", "LGPL"),
    ("11", "BSD"),
    ("13", "Standard Digital File"),
    ("15", "Commercial Use"),
]
STATIC_MATERIALS = [
    ("1", "PLA"),
    ("8", "PET"),
    ("3", "ASA"),
    ("4", "Flex"),
    ("2", "ABS"),
    ("7", "PC"),
    ("16", "PA"),
    ("6", "Nylon"),
    ("11", "Carbon filled"),
]


def _gql_literal(fid: str, value: Any) -> str:
    """Valor já validado contra o esquema → literal GraphQL (enums sem aspas, IDs como string)."""
    if value is True:
        return "true"
    if fid in ("filesType", "paid"):
        return str(value)
    if fid == "publishedDateLimitDays":
        return str(int(value))
    if fid == "nozzleDiameters":
        return "[" + ",".join(str(float(v)) for v in value) + "]"
    if fid == "materialIds":  # [Int] (licenses é [ID]); medido: "1" dá erro de tipo
        return "[" + ",".join(str(int(v)) for v in value) + "]"
    return "[" + ",".join(f'"{int(v)}"' for v in value) + "]"


def filter_args(filters: dict[str, Any]) -> str:
    return "".join(f",{fid}:{_gql_literal(fid, v)}" for fid, v in sorted(filters.items()))


_IMAGE_PATH = re.compile(
    r"^(?P<dir>media/(?:prints/\d+/images/[^/]+|comment_images/[0-9a-f]{2}/[0-9a-f-]{8,40}))"
    r"/(?P<stem>[^/]+)\.(?P<ext>[A-Za-z0-9]{2,5})$"
)
# Comentários (com nota opcional de 1-5): ``print.comments(limit, offset)`` já vem ordenado por curtidas.
# A raiz ``comments(targetObjectId, targetType: print)`` também existe, mas o tipo dela não traz ``rating``.
COMMENT_FIELDS = "id text created likesCount rating author { publicUsername } images { filePath } replies { id }"


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


def rating_summary(model: dict) -> dict[str, Any]:
    # ``ratingAvg`` vem como string ("4.9404194471").
    try:
        average = round(float(model.get("ratingAvg")), 2) if model.get("ratingAvg") not in (None, "") else None
    except (TypeError, ValueError):
        average = None
    count = safe_count(model.get("ratingCount")) or 0
    return {"average": average if count and average and 0 < average <= 5 else None, "count": count}


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
    sorts = ("popular", "newest", "relevance", "rating", "makes")
    review_kinds = ("all",)
    review_sorts = ("top",)

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
          searchPrints2(query:$q,printType:print,limit:$limit,offset:$offset,ordering:$order,categoryId:$category,printerIds:$printers"""
            + filter_args(req.filters)
            + """) {
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

    async def filter_schema(self, client: httpx.AsyncClient) -> dict[str, Any]:
        try:
            data = await graphql(client, "{ licenses { id name abbreviation } materials { id name } }")
            lic = [
                (str(x["id"]), str(x.get("abbreviation") or x["name"])[:60])
                for x in data.get("licenses") or []
                if isinstance(x, dict) and str(x.get("id", "")).isdigit() and x.get("name")
            ]
            mat = [
                (str(x["id"]), str(x["name"])[:60])
                for x in data.get("materials") or []
                if isinstance(x, dict) and str(x.get("id", "")).isdigit() and x.get("name")
            ]
        except Exception:  # noqa: BLE001 - sem a API, a lista estática medida
            lic, mat = [], []
        if lic and mat:
            return build_schema(lic, mat, "graphql")
        return build_schema(STATIC_LICENSES, STATIC_MATERIALS, "static")

    async def categories(self, client: httpx.AsyncClient) -> list[dict[str, str]]:
        data = await graphql(client, "{ categories { id name path { name } } }")
        if not isinstance(data.get("categories"), list):
            raise ProviderUnavailableError("Printables returned invalid categories")

        def full(c: dict[str, Any]) -> str:
            path = [
                p.get("name") for p in c.get("path") or [] if isinstance(p, dict) and isinstance(p.get("name"), str)
            ]
            return " / ".join(path) if len(path) > 1 else c["name"]

        return [{"id": str(c["id"]), "name": full(c)} for c in data["categories"] if c.get("id") and c.get("name")]

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
            "rating": rating_summary(model),
            "stats": {
                "downloads": safe_count(model.get("downloadCount")),
                "likes": safe_count(model.get("likesCount")),
                "makes": safe_count(model.get("makesCount")),
                "published": model.get("datePublished") if isinstance(model.get("datePublished"), str) else None,
            },
        }

    async def reviews(self, client: httpx.AsyncClient, model_id: str, req: ReviewsRequest) -> dict[str, Any]:
        # Pede um a mais para saber se há próxima página (a API não dá total de comentários de primeiro nível).
        data = await graphql(
            client,
            "query Reviews($id:ID!,$limit:Int,$offset:Int) { print(id:$id) { comments(limit:$limit,offset:$offset) { "
            + COMMENT_FIELDS
            + " } } }",
            {"id": model_id, "limit": req.page_size + 1, "offset": req.offset},
        )
        model = data.get("print")
        if not isinstance(model, dict):
            raise ProviderNotFoundError("This Printables model is deleted, private, or unavailable")
        raw = [c for c in model.get("comments") or [] if isinstance(c, dict) and c.get("id")]
        items = []
        for c in raw[: req.page_size]:
            images = [
                {"thumb": thumb, "full": image_url(img, "inside/1280x960") or thumb}
                for img in (c.get("images") or [])[:6]
                if isinstance(img, dict) and (thumb := image_url(img, "inside/320x240"))
            ]
            rating = c.get("rating")
            items.append(
                review_item(
                    item_id=f"c{c['id']}",
                    kind="rating" if isinstance(rating, int) and rating > 0 else "comment",
                    author=(c.get("author") or {}).get("publicUsername"),
                    rating=rating,
                    text=c.get("text"),
                    created=c.get("created"),
                    likes=c.get("likesCount"),
                    replies=len(c["replies"]) if isinstance(c.get("replies"), list) else None,
                    images=images,
                )
            )
        return {"items": items, "total": None, "has_more": len(raw) > req.page_size}

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

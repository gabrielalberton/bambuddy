"""Interface comum das fontes do catálogo (busca + detalhe + download)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

PrinterFilterMode = Literal["server", "author_printer", "none"]
# As 4 primeiras valem em todas as fontes; as demais só onde a fonte ordena por elas (``CatalogSource.sorts``).
Sort = Literal[
    "trending", "popular", "newest", "relevance", "likes", "boosts", "prints", "collections", "random", "rating",
    "makes", "text",
]
# Avaliações/comentários: "ratings" (estrelas), "comments" (sem nota) ou "all" (a fonte mistura os dois).
ReviewKind = Literal["ratings", "comments", "all"]
ReviewSort = Literal["top", "newest"]
REVIEWS_PAGE_SIZE = 10
_MAX_REVIEW_TEXT = 4000
_MAX_REVIEW_IMAGES = 6

# Ordem dos perfis/arquivos no detalhe: o que serve na impressora do usuário primeiro.
MATCH_ORDER = {"native": 0, "compatible": 1, "unknown": 2, "other": 3}


@dataclass
class BrowseRequest:
    query: str = ""
    sort: Sort = "trending"
    category: str | None = None
    offset: int = 0
    limit: int = 24
    # Modelos normalizados da(s) impressora(s) do usuário ("A1", ...).
    models: list[str] = field(default_factory=list)
    printer_filter: bool = True
    # Printables: exigir "impressora usada pelo autor" = modelo do usuário (opcional, raro).
    author_printer: bool = False
    # Filtro avançado já validado contra o esquema da fonte (``filters.validate``).
    filters: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReviewsRequest:
    kind: ReviewKind
    sort: ReviewSort = "top"
    page: int = 1
    page_size: int = REVIEWS_PAGE_SIZE

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


@dataclass
class DownloadedFile:
    data: bytes
    filename: str
    canonical_url: str
    page_url: str


class CatalogSource(ABC):
    id: str
    name: str
    default_folder: str
    thumbnail_hosts: tuple[str, ...] = ()
    # 'makerworld' = permissões makerworld:view/import; 'library' = leitura/upload da biblioteca.
    permission_kind: Literal["makerworld", "library"] = "library"
    printer_filter: PrinterFilterMode = "none"
    sorts: tuple[Sort, ...] = ("popular", "newest", "relevance")
    # Vazio = a fonte não expõe avaliações/comentários. O primeiro é o padrão.
    review_kinds: tuple[ReviewKind, ...] = ()
    review_sorts: tuple[ReviewSort, ...] = ("top",)

    def enabled(self) -> tuple[bool, str | None]:
        """(ligada?, motivo quando desligada)."""
        return True, None

    def printer_filter_note(self) -> str:
        return ""

    @abstractmethod
    async def browse(self, client: httpx.AsyncClient, req: BrowseRequest) -> dict[str, Any]: ...

    async def categories(self, client: httpx.AsyncClient) -> list[dict[str, str]]:
        return []

    async def filter_schema(self, client: httpx.AsyncClient) -> dict[str, Any]:
        """Esquema do filtro avançado (``filters.schema``); vazio = a fonte não tem filtros extras."""
        return {"source": self.id, "origin": "static", "groups": []}

    @abstractmethod
    async def detail(self, client: httpx.AsyncClient, model_id: str, models: list[str]) -> dict[str, Any]: ...

    supports_author = False

    async def author(self, client: httpx.AsyncClient, author_id: str, offset: int, limit: int) -> dict[str, Any]:
        raise NotImplementedError

    def page_url(self, model_id: str) -> str:
        raise NotImplementedError

    def canonical_url(self, model_id: str, file_id: str) -> str:
        """Chave de dedupe na biblioteca (``LibraryFile.source_url``): um registro por arquivo."""
        return f"{self.page_url(model_id)}#file-{file_id}"

    async def download(self, client: httpx.AsyncClient, model_id: str, file_id: str) -> DownloadedFile:
        raise NotImplementedError

    def review_capabilities(self) -> dict[str, Any] | None:
        if not self.review_kinds:
            return None
        return {"kinds": list(self.review_kinds), "sorts": list(self.review_sorts), "page_size": REVIEWS_PAGE_SIZE}

    async def reviews(self, client: httpx.AsyncClient, model_id: str, req: ReviewsRequest) -> dict[str, Any]:
        raise NotImplementedError


def order_files(files: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str | None]:
    """Ordena por compatibilidade e escolhe o pré-selecionado (primeiro fatiável compatível)."""
    ordered = sorted(files, key=lambda f: MATCH_ORDER.get(f.get("printer_match", "unknown"), 2))
    preselect = next(
        (f["id"] for f in ordered if f.get("sliceable") and f.get("printer_match") in ("native", "compatible")),
        None,
    )
    if preselect is None:
        preselect = next((f["id"] for f in ordered if f.get("sliceable") and f.get("printer_match") != "other"), None)
    return ordered, preselect


def clean_text(value: Any, limit: int = _MAX_REVIEW_TEXT) -> str:
    """Texto puro: sem caracteres de controle (mantém quebra de linha/tab), tamanho limitado.

    O frontend renderiza como texto (nunca HTML); aqui só se evita lixo e payload enorme.
    """
    if not isinstance(value, str):
        return ""
    text = "".join(c for c in value if c in "\n\t" or (ord(c) >= 32 and ord(c) != 127))
    text = text.replace("\r", "").strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def safe_count(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def review_item(
    *,
    item_id: str,
    kind: Literal["rating", "comment"],
    author: Any,
    text: Any,
    created: Any,
    rating: Any = None,
    likes: Any = None,
    replies: Any = None,
    images: list[dict[str, str]] | None = None,
    profile: dict[str, str] | None = None,
    printed: bool | None = None,
    issues: list[str] | None = None,
    boosted: bool = False,
    reply_preview: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Formato único de avaliação/comentário entregue ao frontend (todas as fontes)."""
    score = rating if isinstance(rating, (int, float)) and not isinstance(rating, bool) and 0 < rating <= 5 else None
    return {
        "id": item_id,
        "kind": kind,
        "author": clean_text(author, 80) or "—",
        "rating": score,
        "text": clean_text(text),
        "created": created if isinstance(created, str) and len(created) <= 40 else None,
        "likes": safe_count(likes),
        "replies": safe_count(replies),
        "images": (images or [])[:_MAX_REVIEW_IMAGES],
        "profile": profile,
        "printed": printed,
        "issues": [clean_text(i, 120) for i in (issues or []) if clean_text(i, 120)][:5],
        "boosted": boosted,
        "reply_preview": (reply_preview or [])[:3],
    }

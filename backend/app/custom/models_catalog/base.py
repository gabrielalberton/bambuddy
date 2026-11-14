"""Interface comum das fontes do catálogo (busca + detalhe + download)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

PrinterFilterMode = Literal["server", "author_printer", "none"]
Sort = Literal["trending", "popular", "newest", "relevance"]

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

    def enabled(self) -> tuple[bool, str | None]:
        """(ligada?, motivo quando desligada)."""
        return True, None

    def printer_filter_note(self) -> str:
        return ""

    @abstractmethod
    async def browse(self, client: httpx.AsyncClient, req: BrowseRequest) -> dict[str, Any]: ...

    async def categories(self, client: httpx.AsyncClient) -> list[dict[str, str]]:
        return []

    @abstractmethod
    async def detail(self, client: httpx.AsyncClient, model_id: str, models: list[str]) -> dict[str, Any]: ...

    def page_url(self, model_id: str) -> str:
        raise NotImplementedError

    def canonical_url(self, model_id: str, file_id: str) -> str:
        """Chave de dedupe na biblioteca (``LibraryFile.source_url``): um registro por arquivo."""
        return f"{self.page_url(model_id)}#file-{file_id}"

    async def download(self, client: httpx.AsyncClient, model_id: str, file_id: str) -> DownloadedFile:
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

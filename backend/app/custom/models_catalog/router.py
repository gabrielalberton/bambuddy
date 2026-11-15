"""Rotas do catálogo de modelos (fork gabriel): ``/api/v1/custom/models/*``.

Busca/detalhe são públicos nas fontes (sem credencial do usuário, nada privado
entra no cache). Salvar:
- MakerWorld: delega para a rota do upstream ``POST /makerworld/import``
  (mesmas permissões, pasta padrão, dedupe e download com a credencial Bambu
  Cloud salva) — nada de downloader paralelo.
- Printables/Thingiverse: download pela fonte e ``save_3mf_bytes_to_library``
  do upstream (dedupe por ``source_url``, parser, miniatura).

"Fatiar no Bambuddy" = salvar (ou reaproveitar o já salvo) e abrir o SliceModal
existente no frontend. Nada aqui inicia impressão.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.routes.cloud import resolve_api_key_cloud_owner
from backend.app.api.routes.library import save_3mf_bytes_to_library
from backend.app.api.routes.makerworld import _map_service_error, import_instance
from backend.app.core.auth import (
    ApiKeyActor,
    RequestActor,
    require_actor_still_exists,
    require_auth_if_enabled,
    require_ownership_permission,
    require_permission_if_auth_enabled,
    security,
)
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.core.row_visibility import owned_row_clauses
from backend.app.models.library import LibraryFile
from backend.app.models.user import User
from backend.app.schemas.makerworld import MakerWorldImportRequest
from backend.app.services.library_folder_access import default_import_folder, get_writable_folder
from backend.app.services.model_providers.base import ProviderError

from .base import BrowseRequest, CatalogSource, ReviewsRequest
from .makerworld import MakerWorldSource
from .printables import PrintablesSource
from .printer_models import display_name, makerworld_codes, printables_ids, resolve_models
from .thingiverse import ThingiverseSource
from .transport import cached, fetch_asset, validate_model_file

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/custom/models", tags=["custom-models"])

SOURCES: dict[str, CatalogSource] = {s.id: s for s in (MakerWorldSource(), PrintablesSource(), ThingiverseSource())}
_save_slots = asyncio.Semaphore(2)
_save_locks = [asyncio.Lock() for _ in range(64)]


def catalog_enabled() -> bool:
    return os.environ.get("BAMBUDDY_CUSTOM_MODELS_CATALOG", "1").strip().lower() not in ("0", "false", "off", "no")


class SaveRequest(BaseModel):
    file_id: str = Field(min_length=1, max_length=80, pattern=r"^(?:stl:|other:|gcode:|sla:)?[1-9][0-9]*$")
    folder_id: int | None = Field(default=None, gt=0)


class SavedFile(BaseModel):
    library_file_id: int
    filename: str
    folder_id: int | None
    was_existing: bool


def get_source(source_id: str, *, require_enabled: bool = True) -> CatalogSource:
    source = SOURCES.get(source_id)
    if source is None:
        raise HTTPException(404, "Unknown model source")
    if require_enabled:
        enabled, reason = source.enabled()
        if not enabled:
            raise HTTPException(503, reason or "This model source is disabled")
    return source


async def authorize_view(source: CatalogSource, credentials, x_api_key) -> None:
    if source.permission_kind == "makerworld":
        await require_permission_if_auth_enabled(Permission.MAKERWORLD_VIEW)(
            credentials=credentials, x_api_key=x_api_key
        )
    else:
        await require_ownership_permission(Permission.LIBRARY_READ_ALL, Permission.LIBRARY_READ_OWN)(
            credentials=credentials, x_api_key=x_api_key
        )


def check_id(model_id: str) -> None:
    if not model_id.isascii() or not model_id.isdigit() or not 0 < int(model_id) < 2**63:
        raise HTTPException(400, "Invalid model identifier")


def parse_models(printer_models: list[str] | None) -> list[str]:
    return resolve_models([m[:40] for m in (printer_models or [])][:8])


@router.get("/sources", dependencies=[Depends(require_auth_if_enabled)])
async def list_sources(printer_models: list[str] | None = Query(default=None)):
    """Fontes, se estão ligadas e o que o filtro por impressora significa em cada uma."""
    models = parse_models(printer_models)
    out = []
    for source in SOURCES.values():
        enabled, reason = source.enabled()
        out.append(
            {
                "id": source.id,
                "name": source.name,
                "enabled": enabled,
                "disabled_reason": reason,
                "permission": source.permission_kind,
                "sorts": list(source.sorts),
                "printer_filter": source.printer_filter,
                "printer_filter_note": source.printer_filter_note(),
            }
        )
    return {
        "sources": out,
        "printer_models": [display_name(m) for m in models],
        "makerworld_codes": makerworld_codes(models),
        "printables_printer_ids": printables_ids(models),
    }


@router.get("/{source_id}/browse", dependencies=[Depends(require_auth_if_enabled)])
async def browse(
    source_id: str,
    query: str = Query(default="", max_length=200),
    sort: Literal["trending", "popular", "newest", "relevance"] = "trending",
    category: str | None = Query(default=None, max_length=12, pattern=r"^[0-9]*$"),
    offset: int = Query(default=0, ge=0, le=9984),
    limit: int = Query(default=24, ge=1, le=48),
    printer_models: list[str] | None = Query(default=None),
    printer_filter: bool = True,
    author_printer: bool = False,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    source = get_source(source_id)
    await authorize_view(source, credentials, x_api_key)
    if sort not in source.sorts:
        sort = source.sorts[0]
    req = BrowseRequest(
        query=query.strip(),
        sort=sort,
        category=category or None,
        offset=offset,
        limit=limit,
        models=parse_models(printer_models),
        printer_filter=printer_filter,
        author_printer=author_printer,
    )
    key = (
        source_id,
        "browse",
        req.query,
        req.sort,
        req.category,
        offset,
        limit,
        tuple(req.models),
        printer_filter,
        author_printer,
    )

    async def load():
        async with httpx.AsyncClient(timeout=30) as client:
            result = await source.browse(client, req)
        result["sort"] = req.sort
        result["printer_models"] = [display_name(m) for m in req.models]
        return result

    try:
        return await cached(key, load)
    except ProviderError as exc:
        raise _map_service_error(exc) from exc


@router.get("/{source_id}/categories", dependencies=[Depends(require_auth_if_enabled)])
async def categories(
    source_id: str,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    source = get_source(source_id)
    await authorize_view(source, credentials, x_api_key)

    async def load():
        async with httpx.AsyncClient(timeout=30) as client:
            return await source.categories(client)

    try:
        return await cached((source_id, "categories"), load, ttl=3600)
    except ProviderError as exc:
        raise _map_service_error(exc) from exc


@router.get("/{source_id}/thumbnail")
async def thumbnail(source_id: str, url: str = Query(max_length=3000)):
    """Sem auth de propósito (como ``/makerworld/thumbnail``): ``<img>`` não manda
    Authorization e o CSP só permite imagens do próprio Bambuddy. Restrito ao
    CDN público de cada fonte (allowlist), sem redirect: não vira proxy aberto."""
    source = get_source(source_id, require_enabled=False)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            payload, mime = await fetch_asset(client, url, source.thumbnail_hosts, image=True)
    except ProviderError as exc:
        raise _map_service_error(exc) from exc
    return Response(
        payload,
        media_type=mime,
        headers={"Cache-Control": "public, max-age=86400", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/{source_id}/author/{author_id}", dependencies=[Depends(require_auth_if_enabled)])
async def author_models(
    source_id: str,
    author_id: str,
    offset: int = Query(default=0, ge=0, le=5000),
    limit: int = Query(default=24, ge=1, le=60),
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    """Modelos publicados por um autor (link interno do nome do autor no detalhe)."""
    source = get_source(source_id)
    await authorize_view(source, credentials, x_api_key)
    if not source.supports_author:
        raise HTTPException(404, "This source does not list models by author")
    if not author_id.isdigit() or len(author_id) > 20:
        raise HTTPException(400, "Invalid author id")

    async def load():
        async with httpx.AsyncClient(timeout=30) as client:
            return await source.author(client, author_id, offset, limit)

    try:
        return await cached((source_id, "author", author_id, offset, limit), load)
    except ProviderError as exc:
        raise _map_service_error(exc) from exc


@router.get("/{source_id}/{model_id}", dependencies=[Depends(require_auth_if_enabled)])
async def detail(
    source_id: str,
    model_id: str,
    printer_models: list[str] | None = Query(default=None),
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    source = get_source(source_id)
    await authorize_view(source, credentials, x_api_key)
    check_id(model_id)
    models = parse_models(printer_models)

    async def load():
        async with httpx.AsyncClient(timeout=30) as client:
            result = await source.detail(client, model_id, models)
        result.setdefault("rating", None)
        result.setdefault("stats", {})
        result["reviews"] = source.review_capabilities()
        return result

    try:
        return await cached((source_id, "detail", model_id, tuple(models)), load)
    except ProviderError as exc:
        raise _map_service_error(exc) from exc


@router.get("/{source_id}/{model_id}/reviews", dependencies=[Depends(require_auth_if_enabled)])
async def reviews(
    source_id: str,
    model_id: str,
    kind: Literal["ratings", "comments", "all"] | None = None,
    sort: Literal["top", "newest"] | None = None,
    page: int = Query(default=1, ge=1, le=200),
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    """Avaliações/comentários públicos da fonte, paginados (texto puro; imagens via ``/thumbnail``)."""
    source = get_source(source_id)
    await authorize_view(source, credentials, x_api_key)
    check_id(model_id)
    if not source.review_kinds:
        raise HTTPException(404, "This source does not expose reviews")
    req = ReviewsRequest(
        kind=kind if kind in source.review_kinds else source.review_kinds[0],
        sort=sort if sort in source.review_sorts else source.review_sorts[0],
        page=page,
    )

    async def load():
        async with httpx.AsyncClient(timeout=30) as client:
            result = await source.reviews(client, model_id, req)
        return {**result, "kind": req.kind, "sort": req.sort, "page": req.page, "page_size": req.page_size}

    try:
        return await cached((source_id, "reviews", model_id, req.kind, req.sort, req.page), load)
    except ProviderError as exc:
        raise _map_service_error(exc) from exc


@router.post("/{source_id}/{model_id}/save", response_model=SavedFile, dependencies=[Depends(require_auth_if_enabled)])
async def save(
    source_id: str,
    model_id: str,
    body: SaveRequest,
    db: AsyncSession = Depends(get_db, scope="function"),
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    api_key_cloud_owner: User | None = Depends(resolve_api_key_cloud_owner),
    actor: User | ApiKeyActor | None = RequestActor,
):
    # Download pode demorar e o PWA pode estar em segundo plano: avisa por Web Push quando termina ou falha.
    try:
        saved = await _save(source_id, model_id, body, db, credentials, x_api_key, api_key_cloud_owner, actor)
    except HTTPException as exc:
        if exc.status_code not in (400, 401, 403, 404, 422):
            _push_save_result(actor, source_id, None, f"Falha ao baixar o modelo ({exc.status_code}): {exc.detail}")
        raise
    except Exception:
        _push_save_result(actor, source_id, None, "Falha ao baixar o modelo (erro interno).")
        raise
    if not saved.was_existing:
        _push_save_result(actor, source_id, saved, None)
    return saved


_push_tasks: set[asyncio.Task] = set()


def _push_save_result(actor, source_id: str, saved: SavedFile | None, error: str | None) -> None:
    """Dispara a notificação sem atrasar a resposta; nunca derruba o salvamento."""
    try:
        from backend.app.custom.webpush.provider import notify

        user_ids = [actor.id] if isinstance(actor, User) else None
        if saved is not None:
            title, body, url, tag = "Modelo salvo na biblioteca", saved.filename, "/files", f"catalog-save-{saved.library_file_id}"
        else:
            title, body, url, tag = f"Catálogo ({source_id})", error or "", "/model-sources", "catalog-save-error"
        task = asyncio.get_running_loop().create_task(notify(user_ids, title, body, url, tag))
        _push_tasks.add(task)
        task.add_done_callback(_push_tasks.discard)
    except Exception:  # noqa: BLE001 - notificação é acessória
        logger.debug("Web Push do catálogo falhou", exc_info=True)


async def _save(source_id, model_id, body, db, credentials, x_api_key, api_key_cloud_owner, actor) -> SavedFile:
    source = get_source(source_id)
    check_id(model_id)

    if source.id == "makerworld":
        if not body.file_id.isdigit():
            raise HTTPException(400, "MakerWorld profiles are identified by a numeric profile id")
        # Mesmo fluxo do importador por URL (permissão makerworld:import, pasta
        # "MakerWorld", dedupe por perfil, credencial Bambu Cloud salva).
        result = await import_instance(
            body=MakerWorldImportRequest(
                model_id=int(model_id), profile_id=int(body.file_id), folder_id=body.folder_id
            ),
            db=db,
            credentials=credentials,
            x_api_key=x_api_key,
            api_key_cloud_owner=api_key_cloud_owner,
            actor=actor,
        )
        return SavedFile(
            library_file_id=result.library_file_id,
            filename=result.filename,
            folder_id=result.folder_id,
            was_existing=result.was_existing,
        )

    await require_permission_if_auth_enabled(Permission.LIBRARY_UPLOAD)(credentials=credentials, x_api_key=x_api_key)
    await require_ownership_permission(Permission.LIBRARY_READ_ALL, Permission.LIBRARY_READ_OWN)(
        credentials=credentials, x_api_key=x_api_key
    )
    if body.folder_id is not None:
        folder = await get_writable_folder(db, body.folder_id, actor)
        if folder.is_external and folder.external_readonly:
            raise HTTPException(403, "Cannot save to a read-only folder")
        folder_id: int | None = body.folder_id
    else:
        folder_id = (await default_import_folder(db, source.default_folder, actor)).id

    readable = owned_row_clauses(LibraryFile, actor, Permission.LIBRARY_READ_ALL, Permission.LIBRARY_READ_OWN)
    owner_id = actor.id if actor else None
    lock = _save_locks[hash((owner_id, source.id, model_id, body.file_id)) % len(_save_locks)]
    async with lock, _save_slots:
        canonical = source.canonical_url(model_id, body.file_id)
        if readable is not None:
            existing = (
                await db.execute(LibraryFile.active().where(LibraryFile.source_url == canonical, *readable).limit(1))
            ).scalar_one_or_none()
            if existing is not None:
                return SavedFile(
                    library_file_id=existing.id,
                    filename=existing.filename,
                    folder_id=existing.folder_id,
                    was_existing=True,
                )
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                downloaded = await source.download(client, model_id, body.file_id)
            await asyncio.to_thread(validate_model_file, downloaded.data, downloaded.filename)
        except ProviderError as exc:
            raise _map_service_error(exc) from exc
        await require_actor_still_exists(db, actor)
        row, was_existing = await save_3mf_bytes_to_library(
            db,
            file_bytes=downloaded.data,
            filename=downloaded.filename,
            folder_id=folder_id,
            source_type=source.id,
            source_url=downloaded.canonical_url,
            owner_id=owner_id,
            dedupe_within=readable,
        )
        if not was_existing and not row.external_url:
            # Atribuição: link da página original (campo do upstream para isso).
            row.external_url = downloaded.page_url
            await db.commit()
    return SavedFile(library_file_id=row.id, filename=row.filename, folder_id=row.folder_id, was_existing=was_existing)

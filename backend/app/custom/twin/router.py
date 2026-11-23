"""Rotas do gêmeo digital (somente GET), sob `{api_prefix}/custom/twin/...`.

Autorização igual à da câmera: `stream/{id}/events`, `stream/{id}/job/{job}` e `stream/{id}/model.glb` são
carregados pelo navegador sem cabeçalho (EventSource / fetch), então aceitam o token de stream da câmera
(`?token=`, `POST /printers/camera/stream-token`, permissão `camera:view` + escopo da impressora). Para isso o
prefixo `.../custom/twin/stream/` entra em `PUBLIC_API_PREFIXES` do middleware global do upstream (ele só "sai
da frente", como faz para `/camera/stream`; quem valida é a dependência da rota). `{id}/health` exige o mesmo
`camera:view` por cabeçalho (JWT/API key) e continua atrás do middleware. Com a autenticação desligada, tudo
abre, como a câmera.

Interruptor: `BAMBUDDY_CUSTOM_TWIN=0` desliga (todas as rotas respondem 404).
"""

from __future__ import annotations

import asyncio
import contextlib
import math
import os
import pathlib
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse

from backend.app.core import database
from backend.app.core.auth import (
    RequireCameraStreamTokenIfAuthEnabled,
    RequirePrinterPermissionIfAuthEnabled,
    StreamOpener,
    stream_opener_still_allowed,
)
from backend.app.core.permissions import Permission

from .hub import MAX_CLIENTS, data_dir, get_hub

router = APIRouter(prefix="/custom/twin", tags=["custom-twin"])

RECHECK_SECONDS = 30.0
HEARTBEAT_SECONDS = 12.0
_visual_lock = asyncio.Lock()


def enabled() -> bool:
    return os.environ.get("BAMBUDDY_CUSTOM_TWIN", "1") != "0"


async def _printer_or_404(printer_id: int) -> None:
    if not enabled():
        raise HTTPException(404, "Not found")
    from backend.app.models.printer import Printer

    async with database.async_session() as db:
        if await db.get(Printer, printer_id) is None:
            raise HTTPException(404, "Printer not found")


@router.get("/stream/{printer_id}/events")
async def twin_events(printer_id: int, opener: StreamOpener = RequireCameraStreamTokenIfAuthEnabled):
    """SSE com o estado público (lista branca) da impressora + job + `since_pr`."""
    await _printer_or_404(printer_id)
    hub = get_hub(printer_id)
    if len(hub.clients) >= MAX_CLIENTS:
        raise HTTPException(503, "Too many twin viewers")
    q: asyncio.Queue = asyncio.Queue(maxsize=4)
    hub.clients.add(q)
    q.put_nowait(hub.encode())

    async def gen():
        next_check = time.monotonic() + RECHECK_SECONDS
        try:
            yield b"retry: 1500\n\n"
            while True:
                if time.monotonic() >= next_check:
                    # como a câmera: sessão encerrada/permissão retirada derruba o stream
                    try:
                        allowed = await stream_opener_still_allowed(opener, printer_id)
                    except Exception:  # noqa: BLE001
                        allowed = False
                    if not allowed:
                        return
                    next_check = time.monotonic() + RECHECK_SECONDS
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=HEARTBEAT_SECONDS)
                    yield f"data: {msg}\n\n".encode()
                except TimeoutError:
                    yield b": hb\n\n"
        finally:
            hub.clients.discard(q)

    return StreamingResponse(
        gen(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
    )


@router.get("/stream/{printer_id}/job/{job_id}")
async def twin_job(printer_id: int, job_id: str, _: StreamOpener = RequireCameraStreamTokenIfAuthEnabled):
    """Pacote binário (gzip) do G-code interpretado do job em curso."""
    await _printer_or_404(printer_id)
    j = get_hub(printer_id).jobs.current
    if not j or j.status != "ready" or j.id != job_id:
        raise HTTPException(404, "Job not ready")
    return Response(
        content=j.blob_gz,
        media_type="application/octet-stream",
        headers={"Content-Encoding": "gzip", "Cache-Control": "private, max-age=31536000, immutable"},
    )


@router.get("/stream/{printer_id}/model.glb")
async def twin_model(printer_id: int, _: StreamOpener = RequireCameraStreamTokenIfAuthEnabled):
    """Modelo 3D opcional da A1 (`<data>/custom/twin/a1.glb`, fora do git: licença desconhecida). 404 = usa o procedural."""
    await _printer_or_404(printer_id)
    p = data_dir() / "a1.glb"
    if not p.is_file():
        raise HTTPException(404, "No A1 model installed")
    return FileResponse(p, media_type="model/gltf-binary", headers={"Cache-Control": "private, max-age=86400"})


@router.get("/stream/{printer_id}/visual-check")
async def twin_visual_check(
    printer_id: int,
    _: StreamOpener = RequireCameraStreamTokenIfAuthEnabled,
    x: float | None = None,
    y: float | None = None,
    z: float | None = None,
):
    """Compara a pose do twin com duas imagens da câmera quando existe uma referência local."""
    from backend.app.custom.camera_preview import preview_url, read_preview

    from .visual_route import compare_previews

    await _printer_or_404(printer_id)
    profile = data_dir() / "visual" / str(printer_id) / "profile.json"
    if not profile.is_file() or preview_url(printer_id) is None:
        raise HTTPException(404, "Visual reference unavailable")
    if (x, y, z) == (None, None, None):
        return {"available": True}
    if any(value is None or not math.isfinite(value) for value in (x, y, z)):
        raise HTTPException(422, "Expected a finite XYZ pose")
    if _visual_lock.locked():
        return {"comparison": "unknown"}
    async with _visual_lock:
        first = await read_preview(printer_id)
        await asyncio.sleep(1.2)
        second = await read_preview(printer_id)
        return await asyncio.to_thread(compare_previews, profile, first, second, (x, y, z))


@router.get("/{printer_id}/health")
async def twin_health(printer_id: int, _=RequirePrinterPermissionIfAuthEnabled(Permission.CAMERA_VIEW)):
    """Saúde do twin (sem segredos)."""
    await _printer_or_404(printer_id)
    rss = 0
    with contextlib.suppress(OSError, ValueError):
        for ln in pathlib.Path("/proc/self/status").read_text().splitlines():
            if ln.startswith("VmRSS:"):
                rss = int(ln.split()[1]) // 1024
    return {**get_hub(printer_id).health(), "rss_mb": rss}


def include_twin(app, prefix: str | None = None) -> list[str]:
    """Registra as rotas do twin no app do Bambuddy ANTES do catch-all do SPA (`/{full_path:path}`). Idempotente."""
    if getattr(app.state, "custom_twin_included", False):
        return []
    if prefix is None:
        from backend.app.core.config import settings

        prefix = settings.api_prefix
    before = len(app.router.routes)
    app.include_router(router, prefix=prefix)
    added = app.router.routes[before:]
    del app.router.routes[before:]
    idx = next(
        (i for i, r in enumerate(app.router.routes) if getattr(r, "path", "") == "/{full_path:path}"),
        len(app.router.routes),
    )
    app.router.routes[idx:idx] = added
    # O middleware global de autenticação (main.py) lê esta lista a cada requisição. Sem a entrada, as rotas de
    # token respondem 401 antes da dependência: falha fechada, nunca aberta.
    from backend.app import main as upstream_main

    public = getattr(upstream_main, "PUBLIC_API_PREFIXES", None)
    stream_prefix = f"{prefix}/custom/twin/stream/"
    if isinstance(public, list) and stream_prefix not in public:
        public.append(stream_prefix)
    app.state.custom_twin_included = True
    return [getattr(r, "path", "") for r in added]

"""Prévia instantânea da câmera enquanto o vídeo em alta abre (custom/docs/camera-previa.md).

Abrir a câmera externa "do zero" leva ~8 s: a Thingino só manda quadro-chave a cada 4 s e o ffmpeg do upstream
espera por ele. O Frigate já mantém a última imagem da câmera (``/api/<câmera>/latest.jpg``, 640x360, ~3 fps,
responde em ~20 ms). Esta rota repassa essa imagem com o mesmo token de stream da câmera, e o frontend a mostra
até o primeiro quadro em alta chegar.

Ligar: ``BAMBUDDY_CUSTOM_CAMERA_PREVIEW_URL`` (pode conter ``{printer_id}``), por exemplo
``http://frigate-standalone:5000/api/thingino_135/latest.jpg``. Sem a variável a rota responde 404 e o frontend
simplesmente não mostra prévia. A URL vem só do ambiente (administrador), nunca do usuário.
"""

from __future__ import annotations

import logging
import os

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from backend.app.core.auth import RequireCameraStreamTokenIfAuthEnabled, StreamOpener

logger = logging.getLogger(__name__)

ENV_URL = "BAMBUDDY_CUSTOM_CAMERA_PREVIEW_URL"
MAX_BYTES = 2 * 1024 * 1024
TIMEOUT = httpx.Timeout(3.0)
STREAM_PREFIX = "/custom/camera/stream/"

router = APIRouter(prefix="/custom/camera", tags=["custom-camera"])

_client: httpx.AsyncClient | None = None


def preview_url(printer_id: int) -> str | None:
    template = os.environ.get(ENV_URL, "").strip()
    if not template or not template.startswith(("http://", "https://")):
        return None
    return template.replace("{printer_id}", str(printer_id))


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False)
    return _client


async def read_preview(printer_id: int) -> bytes:
    """Última imagem da câmera vinda do Frigate."""
    url = preview_url(printer_id)
    if url is None:
        raise HTTPException(404, "Camera preview not configured")
    try:
        resp = await _http().get(url)
    except httpx.HTTPError as exc:
        logger.debug("Prévia da câmera indisponível: %s", type(exc).__name__)
        raise HTTPException(502, "Camera preview unavailable") from exc
    body = resp.content
    if resp.status_code != 200 or not body.startswith(b"\xff\xd8") or len(body) > MAX_BYTES:
        raise HTTPException(502, "Camera preview unavailable")
    return body


@router.get("/stream/{printer_id}/preview.jpg")
async def camera_preview(printer_id: int, _: StreamOpener = RequireCameraStreamTokenIfAuthEnabled):
    body = await read_preview(printer_id)
    return Response(content=body, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


def add_public_prefix(api_prefix: str) -> None:
    """``<img>`` não manda cabeçalho: o middleware global deixa passar e quem valida o token é a dependência da
    rota (mesmo arranjo de ``/camera/stream`` e do twin). Se o upstream renomear a lista: 401 (falha fechada)."""
    from backend.app import main as upstream_main

    public = getattr(upstream_main, "PUBLIC_API_PREFIXES", None)
    prefix = f"{api_prefix}{STREAM_PREFIX}"
    if isinstance(public, list) and prefix not in public:
        public.append(prefix)

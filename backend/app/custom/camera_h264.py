"""Vídeo ao vivo em H.264 da câmera externa, repassado do go2rtc (custom/docs/camera-h264.md).

O MJPEG do upstream decodifica o H.264 da câmera e recodifica cada quadro em JPEG: em resolução cheia
(2304x1296, 10 fps) isso dá ~18 Mbps até o navegador. O go2rtc entrega o mesmo H.264 em MP4 fragmentado para
Media Source Extensions (~1,5 Mbps, sem recodificar). Esta rota repassa o WebSocket ``/api/ws`` do go2rtc com o
mesmo token de stream da câmera usado pelo ``/camera/stream``.

Ligar: ``BAMBUDDY_CUSTOM_H264_WS_URL`` (pode conter ``{printer_id}``), por exemplo
``ws://frigate-standalone:1984/api/ws?src=thingino_135``. Sem a variável a conexão fecha com 4404 e o frontend
fica no MJPEG. A URL vem só do ambiente (administrador), nunca do usuário.

Protocolo (o mesmo do ``video-rtc.js`` do go2rtc): o navegador manda ``{"type":"mse","value":"<codecs>"}``, o
go2rtc responde ``{"type":"mse","value":"video/mp4; codecs=..."}`` e depois só mensagens binárias (init + um
fragmento por quadro). Do navegador só passa a primeira mensagem ``mse``, reescrita e com a lista de codecs
validada; do go2rtc só passam binários e texto ``mse``/``error``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re

import aiohttp
from fastapi import APIRouter, HTTPException, WebSocket

from backend.app.core.auth import require_camera_stream_token_if_auth_enabled

logger = logging.getLogger(__name__)

ENV_URL = "BAMBUDDY_CUSTOM_H264_WS_URL"
MAX_SESSIONS = 6
REVALIDATE_S = 300.0
CONNECT_TIMEOUT_S = 5.0
MAX_MESSAGE_BYTES = 4 * 1024 * 1024
CODECS_RE = re.compile(r"^[A-Za-z0-9.,]{1,256}$")

# Códigos de fechamento (faixa privada 4000-4999) lidos pelo frontend.
CLOSE_UNAUTHORIZED = 4401
CLOSE_UNAVAILABLE = 4404
CLOSE_BUSY = 4429
CLOSE_UPSTREAM = 4502

router = APIRouter(prefix="/custom/camera", tags=["custom-camera"])

_sessions = 0


def upstream_url(printer_id: int) -> str | None:
    template = os.environ.get(ENV_URL, "").strip()
    if not template.startswith(("ws://", "wss://")):
        return None
    return template.replace("{printer_id}", str(printer_id))


def browser_message(text: str) -> str | None:
    """A mensagem ``mse`` do navegador, reescrita; qualquer outra coisa é descartada."""
    try:
        msg = json.loads(text)
    except ValueError:
        return None
    if not isinstance(msg, dict) or msg.get("type") != "mse":
        return None
    value = msg.get("value")
    if not isinstance(value, str) or not CODECS_RE.match(value):
        return None
    return json.dumps({"type": "mse", "value": value})


def go2rtc_message(text: str) -> str | None:
    """Texto do go2rtc que o player entende (``mse`` com o codec escolhido ou ``error``)."""
    try:
        msg = json.loads(text)
    except ValueError:
        return None
    if not isinstance(msg, dict) or msg.get("type") not in ("mse", "error") or not isinstance(msg.get("value"), str):
        return None
    return json.dumps({"type": msg["type"], "value": msg["value"][:512]})


async def authorized(printer_id: int, token: str | None) -> bool:
    checker = require_camera_stream_token_if_auth_enabled()
    try:
        await checker(printer_id, token)
    except HTTPException:
        return False
    except Exception:  # falha ao ler o token: recusa (fecha em vez de abrir)
        logger.warning("Vídeo H.264: falha ao validar o token da câmera", exc_info=True)
        return False
    return True


async def _close(websocket: WebSocket, code: int) -> None:
    with contextlib.suppress(Exception):
        await websocket.close(code=code)


@router.websocket("/h264/{printer_id}/ws")
async def camera_h264(websocket: WebSocket, printer_id: int, token: str | None = None) -> None:
    global _sessions
    ok = await authorized(printer_id, token)
    url = upstream_url(printer_id)
    # Aceita antes de fechar para o navegador receber o código (fechar sem aceitar vira 403 sem código).
    await websocket.accept()
    if not ok:
        await _close(websocket, CLOSE_UNAUTHORIZED)
        return
    if url is None:
        await _close(websocket, CLOSE_UNAVAILABLE)
        return
    if _sessions >= MAX_SESSIONS:
        await _close(websocket, CLOSE_BUSY)
        return
    _sessions += 1
    try:
        code = await _relay(websocket, url, printer_id, token)
    finally:
        _sessions -= 1
    if code is not None:
        await _close(websocket, code)


async def _relay(websocket: WebSocket, url: str, printer_id: int, token: str | None) -> int | None:
    """Repassa até um dos lados fechar. Devolve o código para fechar o navegador (None: ele já saiu)."""
    timeout = aiohttp.ClientTimeout(total=None, connect=CONNECT_TIMEOUT_S, sock_connect=CONNECT_TIMEOUT_S)
    try:
        async with (
            aiohttp.ClientSession(timeout=timeout) as session,
            session.ws_connect(url, max_msg_size=MAX_MESSAGE_BYTES, heartbeat=30.0) as upstream,
        ):
            tasks = [
                asyncio.create_task(_from_browser(websocket, upstream)),
                asyncio.create_task(_from_go2rtc(upstream, websocket)),
                asyncio.create_task(_revalidate(printer_id, token)),
            ]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            first = next(iter(done))
            if first.cancelled():
                return CLOSE_UPSTREAM
            exc = first.exception()
            if exc is not None:
                logger.debug("Vídeo H.264 encerrado: %s", type(exc).__name__)
                return CLOSE_UPSTREAM
            return first.result()
    except (TimeoutError, aiohttp.ClientError) as exc:
        logger.info("Vídeo H.264: go2rtc indisponível (%s)", type(exc).__name__)
        return CLOSE_UPSTREAM


async def _from_browser(websocket: WebSocket, upstream: aiohttp.ClientWebSocketResponse) -> int | None:
    sent = False
    while True:
        msg = await websocket.receive()
        if msg["type"] == "websocket.disconnect":
            return None
        text = msg.get("text")
        if sent or not text:
            continue
        forward = browser_message(text)
        if forward is not None:
            await upstream.send_str(forward)
            sent = True


async def _from_go2rtc(upstream: aiohttp.ClientWebSocketResponse, websocket: WebSocket) -> int | None:
    async for msg in upstream:
        if msg.type == aiohttp.WSMsgType.BINARY:
            await websocket.send_bytes(msg.data)
        elif msg.type == aiohttp.WSMsgType.TEXT:
            text = go2rtc_message(msg.data)
            if text is not None:
                await websocket.send_text(text)
        else:
            break
    return CLOSE_UPSTREAM


async def _revalidate(printer_id: int, token: str | None) -> int | None:
    """O token de stream vale 60 min: sessão longa fecha quando ele deixa de valer (o player reconecta com o novo)."""
    while True:
        await asyncio.sleep(REVALIDATE_S)
        if not await authorized(printer_id, token):
            return CLOSE_UNAUTHORIZED

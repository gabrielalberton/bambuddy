"""Single-frame matching against the configured local camera preview."""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from functools import lru_cache
from pathlib import Path

import cv2
import httpx
import numpy as np
from fastapi import HTTPException

from backend.app.custom.camera_preview import MAX_BYTES, preview_url

from . import store
from .vision import PlateTracker

log = logging.getLogger(__name__)
_locks = [asyncio.Lock() for _ in range(8)]


def profile_path(printer_id: int) -> Path:
    return store.base_dir() / "vision" / f"{printer_id}.json"


@lru_cache(maxsize=8)
def _tracker(path: Path, revised: int) -> PlateTracker:
    return PlateTracker(path)


def _detect(path: Path, revised: int, image: bytes) -> dict:
    frame = cv2.imdecode(np.frombuffer(image, np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("A câmera não retornou uma imagem válida.")
    tracker = _tracker(path, revised)
    result = tracker.locate(frame, at=time.monotonic())
    return {**result, "image": base64.b64encode(image).decode("ascii")}


async def match(printer_id: int) -> dict:
    path = profile_path(printer_id)
    url = preview_url(printer_id)
    if not url or not path.is_file():
        raise HTTPException(404, "Rastreamento não configurado para esta câmera.")
    lock = _locks[printer_id % len(_locks)]
    if lock.locked():
        raise HTTPException(429, "A câmera já está processando um quadro.")
    async with lock:
        try:
            async with httpx.AsyncClient(timeout=3, follow_redirects=False) as client:
                async with client.stream("GET", url) as response:
                    response.raise_for_status()
                    buffer = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(buffer) + len(chunk) > MAX_BYTES:
                            raise ValueError("Quadro grande demais.")
                        buffer.extend(chunk)
            source_at = time.time()
            result = await asyncio.to_thread(_detect, path, path.stat().st_mtime_ns, bytes(buffer))
        except (ValueError, KeyError, OSError, cv2.error, httpx.HTTPError) as exc:
            log.warning("Câmera do plotter indisponível: %s", type(exc).__name__)
            raise HTTPException(502, "Câmera do plotter indisponível.") from exc
    return {**result, "received_at": source_at}

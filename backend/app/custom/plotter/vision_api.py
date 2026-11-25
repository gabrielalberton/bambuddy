"""Single-frame matching against the configured local camera preview."""

from __future__ import annotations

import asyncio
import base64
import logging
import os
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
_recent: dict[tuple[int, bool], tuple[float, int, dict]] = {}
TOP_MARGIN_MM = 30
DETECT_SIZE = (640, 360)
SNAPSHOT_ENV = "BAMBUDDY_CUSTOM_PLOTTER_SNAPSHOT_URL"
TOP_QUALITY = 82
REUSE_SECONDS = 0.16
_client: httpx.AsyncClient | None = None


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=3, follow_redirects=False)
    return _client


def snapshot_url(printer_id: int) -> str | None:
    template = os.environ.get(SNAPSHOT_ENV, "").strip()
    if not template.startswith(("http://", "https://")):
        return None
    return template.replace("{printer_id}", str(printer_id))


def profile_path(printer_id: int) -> Path:
    return store.base_dir() / "vision" / f"{printer_id}.json"


@lru_cache(maxsize=8)
def _tracker(path: Path, revised: int) -> PlateTracker:
    return PlateTracker(path)


def _detect(path: Path, revised: int, image: bytes, topdown: bool = False) -> dict:
    frame = cv2.imdecode(np.frombuffer(image, np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("A câmera não retornou uma imagem válida.")
    tracker = _tracker(path, revised)
    # Locate on a small copy (fast), flatten from the full-resolution frame (sharp).
    small = cv2.resize(frame, DETECT_SIZE, interpolation=cv2.INTER_AREA) if frame.shape[1] > 1.5 * DETECT_SIZE[0] else frame
    result = tracker.locate(small, at=time.monotonic())
    if not topdown:
        return {**result, "image": base64.b64encode(image).decode("ascii")}
    if result.get("found"):
        top = tracker.top_view(frame, result["front_plane_mm"], margin_mm=TOP_MARGIN_MM)
        ok, encoded = cv2.imencode(".jpg", top, [cv2.IMWRITE_JPEG_QUALITY, TOP_QUALITY])
        if not ok:
            raise ValueError("Falha ao codificar a vista superior.")
        result["topdown"] = {"image": base64.b64encode(encoded.tobytes()).decode("ascii"), "margin": TOP_MARGIN_MM}
    return result


async def _fetch(urls: list[str]) -> bytes:
    for index, url in enumerate(urls):
        try:
            async with _http().stream("GET", url) as response:
                response.raise_for_status()
                buffer = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(buffer) + len(chunk) > MAX_BYTES:
                        raise ValueError("Quadro grande demais.")
                    buffer.extend(chunk)
            return bytes(buffer)
        except (ValueError, httpx.HTTPError):
            if index == len(urls) - 1:
                raise
    raise ValueError("Sem fonte de imagem.")


async def match(printer_id: int, topdown: bool = False) -> dict:
    path = profile_path(printer_id)
    url = preview_url(printer_id)
    if not url or not path.is_file():
        raise HTTPException(404, "Rastreamento não configurado para esta câmera.")
    lock = _locks[printer_id % len(_locks)]
    async with lock:
        try:
            revised = path.stat().st_mtime_ns
            recent = _recent.get((printer_id, topdown))
            if recent and recent[1] == revised and time.monotonic() - recent[0] < REUSE_SECONDS:
                return recent[2]
            sharp = snapshot_url(printer_id) if topdown else None
            image = await _fetch([sharp, url] if sharp else [url])
            source_at = time.time()
            result = await asyncio.to_thread(_detect, path, revised, image, topdown)
        except (ValueError, KeyError, OSError, cv2.error, httpx.HTTPError) as exc:
            log.warning("Câmera do plotter indisponível: %s", type(exc).__name__)
            raise HTTPException(502, "Câmera do plotter indisponível.") from exc
        result["received_at"] = source_at
        if len(_recent) >= 8 and (printer_id, topdown) not in _recent:
            del _recent[next(iter(_recent))]
        _recent[(printer_id, topdown)] = (time.monotonic(), revised, result)
        return result

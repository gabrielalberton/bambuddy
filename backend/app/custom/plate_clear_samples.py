"""Record operator-labelled clean-plate samples before releasing the print queue."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np

from backend.app.core.config import settings
from backend.app.custom.camera_preview import MAX_BYTES, fetch_preview, preview_url
from backend.app.custom.native_plate_detection import capture_native_plate

log = logging.getLogger(__name__)
WAIT_SECONDS = 5
_locks = [asyncio.Lock() for _ in range(8)]
ACTIVE_STATES = {"PREPARE", "RUNNING", "PAUSE", "PAUSED", "SLICING", "INIT"}


async def _external(printer):
    if not printer.external_camera_enabled:
        return None
    if preview_url(printer.id):
        first = await fetch_preview(printer.id)
        while True:
            await asyncio.sleep(0.25)
            current = await fetch_preview(printer.id)
            if current != first:
                return current

    from backend.app.api.routes.camera import live_frame_for_capture
    from backend.app.services.external_camera import capture_frame

    defer, buffered = live_frame_for_capture(printer.id)
    if defer:
        while True:
            await asyncio.sleep(0.25)
            still_live, current = live_frame_for_capture(printer.id)
            if current and current != buffered:
                return current
            if not still_live:
                break
    if printer.external_camera_url and printer.external_camera_type:
        return await capture_frame(
            printer.external_camera_url, printer.external_camera_type, timeout=WAIT_SECONDS,
            snapshot_url=printer.external_camera_snapshot_url,
        )
    return None


async def _read(capture):
    try:
        async with asyncio.timeout(WAIT_SECONDS):
            result = await capture
    except TimeoutError:
        return "timeout", None, None
    except Exception as exc:
        log.info("Clean-plate camera unavailable (%s)", type(exc).__name__)
        return "error", None, None
    if not result:
        return "unavailable", None, None
    return "captured", result, datetime.now(UTC).isoformat()


def _save(root: Path, printer_id: int, confirmed_at: datetime, state: str | None, captures: dict) -> None:
    parent = root / str(printer_id)
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    samples = {}
    with tempfile.TemporaryDirectory(dir=parent, prefix=".capture-") as temporary:
        directory = Path(temporary)
        for name, (status, jpeg, received_at) in captures.items():
            sample = samples[name] = {"status": status, "received_at": received_at}
            if jpeg is None:
                continue
            image = None
            if len(jpeg) <= MAX_BYTES and jpeg.startswith(b"\xff\xd8") and jpeg.endswith(b"\xff\xd9"):
                image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_REDUCED_GRAYSCALE_2)
            if image is None:
                sample["status"] = "invalid_jpeg"
                continue
            sample.update(file=f"{name}.jpg", mean_luma=round(float(image.mean()), 1))
            (directory / sample["file"]).write_bytes(jpeg)
        metadata = {
            "schema": 1, "label": "clean", "label_source": "operator_clear_plate",
            "printer_id": printer_id, "confirmed_at": confirmed_at.isoformat(),
            "printer_state": state, "cameras": samples,
        }
        (directory / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
        directory.rename(parent / f"{confirmed_at:%Y%m%dT%H%M%S.%fZ}-{uuid4().hex[:8]}")


async def capture_confirmation(printer, current_state: Callable[[], str | None]) -> None:
    if os.environ.get("BAMBUDDY_CUSTOM_PLATE_CLEAR_DATASET") != "1":
        return

    confirmed_at = datetime.now(UTC)
    lock = _locks[printer.id % len(_locks)]
    async with lock:
        if (time.time() - confirmed_at.timestamp()) > WAIT_SECONDS:
            return
        state = current_state()
        if state in ACTIVE_STATES:
            return
        native, external = await asyncio.gather(
            _read(capture_native_plate(
                printer.id, printer.ip_address, printer.access_code, printer.model,
                bool(printer.external_camera_enabled), light=False,
            )),
            _read(_external(printer)),
        )
        if current_state() in ACTIVE_STATES:
            return
        try:
            await asyncio.to_thread(
                _save, settings.base_dir / "custom" / "plate-clear-dataset", printer.id, confirmed_at,
                state, {"native": native, "external": external},
            )
        except (OSError, cv2.error):
            log.warning("Failed to save clean-plate sample", exc_info=True)

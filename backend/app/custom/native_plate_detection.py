"""Capture lit, fresh frames from the printer camera for plate detection."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import aclosing
from pathlib import Path
from types import SimpleNamespace

from backend.app.custom.plate_roi_quad import (
    PlateROI,
    external_plate_roi,
    normalize_update,
    read_json,
    roi_from_dict,
    save_external_quad,
    write_json,
)
from backend.app.services.camera_light import camera_light, chamber_light_is_on, wait_for_previous_flash

_STARTUP_TIMEOUT_SECONDS = 10.0
_FLASH_TIMEOUT_SECONDS = 6.5
# Ignore normal exposure noise. On the A1, the flash changed the dark
# stream's mean brightness from about 2 to over 140 in live measurements.
_MIN_FLASH_LUMA_GAIN = 10.0
_MIN_LIT_LUMA = 12.0
# The build surface fills the lower half of the A1's frame when the bed is parked.
DEFAULT_NATIVE_PLATE_ROI = (0.10, 0.42, 0.70, 0.52)
_ROI_FIELDS = ("x", "y", "w", "h")


def native_plate_check_enabled() -> bool:
    return os.environ.get("BAMBUDDY_CUSTOM_NATIVE_PLATE_DETECTION") == "1"


def native_plate_reference_dir(base: Path) -> Path:
    return base / "native-camera"


def _roi_path(printer_id: int) -> Path:
    from backend.app.core.config import settings

    return native_plate_reference_dir(settings.plate_calibration_dir) / f"printer_{printer_id}_roi.json"


def native_plate_roi(printer_id: int, legacy: tuple[float, float, float, float] | None) -> PlateROI | None:
    """Área de detecção em uso: a da câmera nativa (modo nativo) ou a da câmera externa (colunas do upstream).

    Devolve ``PlateROI`` (retângulo envolvente + 4 cantos); áreas antigas sem cantos migram na leitura.
    """
    if not native_plate_check_enabled():
        return external_plate_roi(printer_id, legacy)
    return roi_from_dict(read_json(_roi_path(printer_id))) or PlateROI(DEFAULT_NATIVE_PLATE_ROI)


def save_native_plate_roi(printer_id: int, roi: dict | None) -> bool:
    """Grava a área (gancho no PATCH da impressora). True: área nativa gravada aqui, o upstream não mexe nas
    colunas. False: segue o upstream, que grava o retângulo envolvente; os cantos ficam no arquivo nosso."""
    if isinstance(roi, dict):
        roi.update(normalize_update(roi))  # o upstream achata este mesmo dict nas colunas
    if not native_plate_check_enabled():
        save_external_quad(printer_id, roi)
        return False
    path = _roi_path(printer_id)
    if roi is None:
        path.unlink(missing_ok=True)
    else:
        data = {name: roi[name] for name in _ROI_FIELDS}
        if "points" in roi:
            data["points"] = roi["points"]
        write_json(path, data)
    return True


async def capture_native_plate(
    printer_id: int, ip_address: str, access_code: str, model: str | None, has_external_camera: bool,
    *, light: bool = True,
) -> bytes | None:
    from backend.app.api.routes import camera
    from backend.app.services.camera_fanout import get_or_create_broadcaster, iter_subscriber

    key = f"printer-{printer_id}"
    stream_id = None if has_external_camera else camera._new_fanout_stream_id(printer_id)
    generator = (
        camera.generate_chamber_mjpeg_stream
        if camera.is_chamber_image_model(model)
        else camera.generate_rtsp_mjpeg_stream
    )

    def factory(disconnect_event: asyncio.Event):
        return generator(
            ip_address=ip_address,
            access_code=access_code,
            model=model,
            fps=5,
            stream_id=stream_id,
            disconnect_event=disconnect_event,
            printer_id=None if has_external_camera else printer_id,
        )

    if not await wait_for_previous_flash(printer_id):
        return None
    try:
        broadcaster = await get_or_create_broadcaster(key, factory)
        try:
            queue = await broadcaster.subscribe(replay_latest=False)
        except RuntimeError:
            broadcaster = await get_or_create_broadcaster(key, factory)
            queue = await broadcaster.subscribe(replay_latest=False)
        async with (
            aclosing(iter_subscriber(broadcaster, queue)) as subscription,
            aclosing(_photos(subscription)) as frames,
        ):
            async with asyncio.timeout(_STARTUP_TIMEOUT_SECONDS):
                baseline = await anext(frames, None)
            if baseline is None:
                return None

            # Bring the camera up before acquiring the light. The first
            # valid JPEG is also the baseline for spotting the light change.
            jpeg, luma = baseline
            if not light:
                return jpeg
            async with camera_light(SimpleNamespace(id=printer_id), any_mode=True, wait=False, flash=True) as lit_at:
                already_on = lit_at is None and chamber_light_is_on(printer_id)
                if lit_at is None:
                    if not already_on:
                        return None
                    if luma >= _MIN_LIT_LUMA:
                        return jpeg
                lit_before_frame = already_on
                async with asyncio.timeout(_FLASH_TIMEOUT_SECONDS):
                    async for photo, brightness in frames:
                        reported_on = chamber_light_is_on(printer_id)
                        # Bright rooms can hide the optical step. In that case
                        # use a frame after the printer reported the light on.
                        optical_step = brightness - luma >= _MIN_FLASH_LUMA_GAIN
                        if brightness >= _MIN_LIT_LUMA and (optical_step or (lit_before_frame and reported_on)):
                            return photo
                        lit_before_frame = reported_on
    except TimeoutError:
        return None
    return None


async def _photos(chunks: AsyncIterator[bytes]) -> AsyncIterator[tuple[bytes, float]]:
    import cv2
    import numpy as np

    async for chunk in chunks:
        _, _, jpeg = chunk.partition(b"\r\n\r\n")
        jpeg = jpeg.removesuffix(b"\r\n")
        if not jpeg.startswith(b"\xff\xd8") or not jpeg.endswith(b"\xff\xd9"):
            continue
        image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_REDUCED_GRAYSCALE_8)
        if image is not None:
            yield jpeg, float(image.mean())

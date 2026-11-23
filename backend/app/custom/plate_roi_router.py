"""Fundo do editor da área da mesa: a referência mais recente (mesa vazia, mesma câmera da verificação).

A miniatura do upstream tem 150 px, pequena demais para arrastar cantos no celular; aqui sai com até 960 px.
O frontend cai para a imagem de análise quando não há referência.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from backend.app.core.auth import RequireCameraStreamTokenIfAuthEnabled

router = APIRouter(prefix="/custom/plate-roi", tags=["custom-plate-roi"])

MAX_SIZE = 960


@router.get("/{printer_id}/backdrop.jpg")
async def plate_roi_backdrop(printer_id: int, _: None = RequireCameraStreamTokenIfAuthEnabled):
    from backend.app.services.plate_detection import PlateDetector, is_plate_detection_available

    if not is_plate_detection_available():
        raise HTTPException(503, "Plate detection not available")
    detector = PlateDetector()
    paths = detector._get_reference_paths(printer_id)
    if not paths:
        raise HTTPException(404, "No plate reference")
    newest = max(paths, key=lambda p: p.stat().st_mtime)
    index = int(newest.stem.rsplit("_", 1)[1])
    image = detector.get_reference_thumbnail(printer_id, index, max_size=MAX_SIZE)
    if image is None:
        raise HTTPException(404, "No plate reference")
    return Response(content=image, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

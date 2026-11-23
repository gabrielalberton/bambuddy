"""Área de detecção da mesa como quadrilátero livre (custom/CUSTOMIZATIONS.md, "Área da mesa em quadrilátero").

O upstream guarda a área como retângulo (x, y, w, h em frações da imagem, colunas ``plate_detection_roi_*``).
Vista de lado, a mesa é um trapézio; o retângulo pega fundo, laterais e o bico. Aqui a área vira 4 cantos livres
(``points``, frações 0-1, ordem: sup. esq., sup. dir., inf. dir., inf. esq.):

- câmera externa: o retângulo envolvente continua nas colunas do upstream e os cantos ficam em
  ``plate_calibration/printer_<id>_roi.json``. Se as colunas mudarem por outro caminho (API do upstream sem
  ``points``), o arquivo deixa de valer e volta o retângulo;
- câmera nativa: ``plate_calibration/native-camera/printer_<id>_roi.json`` ganha ``points``;
- área antiga sem ``points`` é lida como os 4 cantos do retângulo (migração na leitura, nada é regravado).

A comparação usa o retângulo envolvente (como o upstream) com máscara do polígono: fora dele a imagem é
neutralizada antes do desfoque e a média da diferença conta só os pixels de dentro. Um quadrilátero que é o
próprio retângulo dispensa a máscara e reproduz o upstream exatamente.

Desligar: ``BAMBUDDY_CUSTOM_PLATE_QUAD=0`` ignora os cantos salvos (volta ao retângulo envolvente).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field

ENV = "BAMBUDDY_CUSTOM_PLATE_QUAD"
_EPS = 1e-3

Point = tuple[Annotated[float, Field(ge=0.0, le=1.0)], Annotated[float, Field(ge=0.0, le=1.0)]]
# Campo opcional acrescentado ao PlateDetectionROI do upstream (schemas/printer.py).
QuadPoints = Annotated[list[Point], Field(min_length=4, max_length=4)]

Points = tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]]


def quad_enabled() -> bool:
    return os.environ.get(ENV, "1") != "0"


class PlateROI(tuple):
    """``(x, y, w, h)`` do retângulo envolvente, como o upstream espera, mais os 4 cantos em ``points``."""

    points: Points

    def __new__(cls, rect: tuple[float, float, float, float], points: Points | None = None) -> PlateROI:
        obj = super().__new__(cls, tuple(float(v) for v in rect))
        obj.points = points or rect_points(obj)
        return obj

    @property
    def is_rectangle(self) -> bool:
        return all(
            abs(a - b) <= _EPS
            for p, q in zip(self.points, rect_points(self), strict=True)
            for a, b in zip(p, q, strict=True)
        )

    def as_dict(self) -> dict[str, Any]:
        x, y, w, h = self
        return {"x": x, "y": y, "w": w, "h": h, "points": [list(p) for p in self.points]}


def rect_points(rect) -> Points:
    x, y, w, h = (float(v) for v in rect[:4])
    return ((x, y), (x + w, y), (x + w, y + h), (x, y + h))


def bounding_rect(points) -> tuple[float, float, float, float]:
    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)


def parse_points(value) -> Points | None:
    """Cantos válidos (4 pares dentro de 0-1, área não nula) ou None."""
    try:
        pts = tuple((float(p[0]), float(p[1])) for p in value)
    except (TypeError, ValueError, IndexError, KeyError):
        return None
    if len(pts) != 4 or not all(0.0 <= c <= 1.0 for p in pts for c in p):
        return None
    _, _, w, h = bounding_rect(pts)
    if w <= 0.01 or h <= 0.01:
        return None
    return pts  # type: ignore[return-value]


def roi_from_dict(data: dict | None) -> PlateROI | None:
    """Lê ``{"x","y","w","h","points"?}``; sem ``points`` (formato antigo) vira os cantos do retângulo."""
    if not isinstance(data, dict):
        return None
    points = parse_points(data.get("points")) if quad_enabled() else None
    if points is not None:
        return PlateROI(bounding_rect(points), points)
    try:
        return PlateROI((data["x"], data["y"], data["w"], data["h"]))
    except (KeyError, TypeError, ValueError):
        return None


def normalize_update(roi: dict | None) -> dict | None:
    """Payload do PATCH: com ``points`` válidos, o retângulo passa a ser o envolvente deles."""
    if not isinstance(roi, dict):
        return roi
    points = parse_points(roi.get("points"))
    out = {k: roi[k] for k in ("x", "y", "w", "h") if k in roi}
    if points is not None:
        out.update(zip(("x", "y", "w", "h"), bounding_rect(points), strict=True))
        out["points"] = [list(p) for p in points]
    return out


def read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data))
    temp.replace(path)


def _same_rect(a, b) -> bool:
    return all(abs(float(p) - float(q)) <= _EPS for p, q in zip(a, b, strict=False))


def external_quad_path(printer_id: int) -> Path:
    from backend.app.core.config import settings

    return settings.plate_calibration_dir / f"printer_{printer_id}_roi.json"


def external_plate_roi(printer_id: int, legacy) -> PlateROI | None:
    """Área da câmera externa: retângulo das colunas + cantos do arquivo, se o arquivo ainda bater com ele."""
    if legacy is None:
        return None
    rect = tuple(legacy)[:4]
    if quad_enabled():
        saved = roi_from_dict(read_json(external_quad_path(printer_id)))
        if saved is not None and _same_rect(saved, rect):
            return saved
    return PlateROI(rect)


def save_external_quad(printer_id: int, roi: dict | None) -> None:
    path = external_quad_path(printer_id)
    points = parse_points(roi.get("points")) if isinstance(roi, dict) else None
    if points is None:
        path.unlink(missing_ok=True)
        return
    write_json(
        path,
        {**dict(zip(("x", "y", "w", "h"), bounding_rect(points), strict=True)), "points": [list(p) for p in points]},
    )


# --- Detector ---------------------------------------------------------------------------------------------------


def _detector_class():
    from backend.app.services.plate_detection import PlateDetector

    class QuadPlateDetector(PlateDetector):
        """PlateDetector com máscara do quadrilátero dentro do retângulo envolvente."""

        roi_mask = None

        def _extract_roi(self, frame):
            result = super()._extract_roi(frame)
            self.roi_mask = _crop_mask(self.roi, frame.shape[:2], result)
            return result

        def _preprocess_for_comparison(self, frame):
            mask = self.roi_mask
            if mask is None or mask.shape != frame.shape[:2] or not mask.any():
                return super()._preprocess_for_comparison(frame)
            import cv2
            import numpy as np

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            # Fora do polígono: o tom médio de dentro, para o desfoque não trazer bordas de fora para dentro.
            gray[~mask] = int(gray[mask].mean())
            blurred = cv2.GaussianBlur(gray, (51, 51), 0)
            normalized = cv2.normalize(blurred, None, 0, 255, cv2.NORM_MINMAX, mask=mask.astype(np.uint8))
            normalized[~mask] = 0
            return normalized

    return QuadPlateDetector


_QUAD_DETECTOR = None


def make_plate_detector(roi):
    """Detector usado na verificação (gancho em ``check_plate_empty``). A classe nasce aqui, e não no import,
    porque ``services/plate_detection.py`` importa este pacote."""
    global _QUAD_DETECTOR
    if _QUAD_DETECTOR is None:
        _QUAD_DETECTOR = _detector_class()
    return _QUAD_DETECTOR(roi=roi)


def _crop_mask(roi, frame_shape, extracted):
    """Máscara booleana do polígono no recorte; None quando é retângulo (comportamento do upstream)."""
    if not isinstance(roi, PlateROI) or roi.is_rectangle:
        return None
    import cv2
    import numpy as np

    crop, x0, y0, _, _ = extracted
    height, width = frame_shape
    mask = np.zeros(crop.shape[:2], np.uint8)
    pts = np.array([[round(px * width) - x0, round(py * height) - y0] for px, py in roi.points], np.int32)
    cv2.fillPoly(mask, [pts], 255)
    return mask.astype(bool)


def roi_mean(detector, diff) -> float:
    """Média da diferença só dentro do polígono (gancho em ``PlateDetector.analyze_frame``)."""
    import numpy as np

    mask = getattr(detector, "roi_mask", None)
    if mask is not None and mask.shape == diff.shape[:2] and mask.any():
        return float(diff[mask].mean())
    return float(np.mean(diff))


def draw_roi_outline(detector, image, top_left, bottom_right) -> None:
    """Contorno verde da área na imagem de análise: o polígono, ou o retângulo do upstream."""
    import cv2
    import numpy as np

    roi = detector.roi
    if isinstance(roi, PlateROI) and not roi.is_rectangle:
        height, width = image.shape[:2]
        pts = np.array([[round(px * width), round(py * height)] for px, py in roi.points], np.int32)
        cv2.polylines(image, [pts], True, (0, 255, 0), 2)
        return
    cv2.rectangle(image, top_left, bottom_right, (0, 255, 0), 2)


def roi_response(roi) -> dict[str, Any]:
    """``roi`` da resposta da verificação, sempre com ``points`` (antigas viram os cantos do retângulo)."""
    return (roi if isinstance(roi, PlateROI) else PlateROI(roi)).as_dict()

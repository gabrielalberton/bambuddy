"""Validação de dois quadros da mesma câmera para a conferência visual do twin."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def compare_previews(profile, first, second, xyz):
    if first == second:
        return {"comparison": "unknown"}
    try:
        import cv2
        import numpy as np

        from .visual_check import VisualReference

        reference = VisualReference(profile)
        frames = [cv2.imdecode(np.frombuffer(raw, dtype="uint8"), cv2.IMREAD_COLOR) for raw in (first, second)]
        if any(frame is None for frame in frames):
            return {"comparison": "unknown"}
        a, b = [reference.compare(frame, xyz) for frame in frames]
        if a["comparison"] != b["comparison"] or a["camera_reference"] != b["camera_reference"]:
            return {"comparison": "unknown"}
        # Não compara cenas em movimento. Ambos os quadros precisam sustentar o mesmo resultado.
        for part, spot in a["locations_px"].items():
            other = b["locations_px"][part]
            if spot is None and other is None:
                continue
            if spot is None or other is None or np.linalg.norm(np.subtract(spot, other)) > 3:
                return {"comparison": "unknown"}
        return {"comparison": a["comparison"]}
    except Exception as exc:  # noqa: BLE001
        logger.debug("Conferência visual do twin indisponível: %s", type(exc).__name__)
        return {"comparison": "unknown"}

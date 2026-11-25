"""Padrões de calibração: caminhos prontos (mm da mesa, aperto explícito), sem passar pela vetorização.

- ``pressure_ladder``: linhas com aperto crescente + uma linha em cunha; mede-se a largura de cada uma e
  o resultado vira a tabela aperto -> largura da caneta;
- ``offset_cross``: cruz num ponto conhecido; a diferença entre onde ela saiu e onde deveria sair corrige
  o offset da caneta em relação ao bico;
- ``frame``: contorno da área útil, para conferir o alinhamento do papel antes de um desenho.
"""

from __future__ import annotations

import numpy as np

from .plan import PenPath, PlanError
from .profile import PenProfile

Area = tuple[float, float, float, float]

LADDER_LINE = 45.0
LADDER_GAP = 6.0
LADDER_WEDGE = 60.0


def default_ladder_depths(pen: PenProfile, steps: int = 8) -> list[float]:
    top = min(pen.max_compression, max(pen.depth_max, 1.5))
    base = [0.0, 0.1, 0.2, 0.35, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0]
    out = [d for d in base if d <= top + 1e-9]
    if len(out) > steps:
        idx = np.round(np.linspace(0, len(out) - 1, steps)).astype(int)
        out = [out[i] for i in sorted(set(idx.tolist()))]
    return out


def _line(x0: float, y0: float, x1: float, y1: float, d0: float, d1: float | None = None) -> PenPath:
    return PenPath(np.array([[x0, y0, d0], [x1, y1, d0 if d1 is None else d1]], dtype=np.float64))


def pressure_ladder(area: Area, pen: PenProfile, depths: list[float] | None = None) -> tuple[list[PenPath], dict]:
    """Linhas horizontais de cima para baixo, da mais leve para a mais apertada, e a cunha por último."""
    depths = sorted({round(float(d), 3) for d in (depths or default_ladder_depths(pen))})
    if len(depths) < 2:
        raise PlanError("a folha de teste precisa de pelo menos dois apertos")
    if depths[0] < 0 or depths[-1] > pen.max_compression + 1e-9:
        raise PlanError("aperto da folha de teste fora do limite do suporte")
    x0, y0, x1, y1 = area
    need_w = max(LADDER_LINE, LADDER_WEDGE) + 4.0
    need_h = (len(depths) + 1) * LADDER_GAP + 4.0
    if x1 - x0 < need_w or y1 - y0 < need_h:
        raise PlanError(f"a folha de teste precisa de {need_w:.0f} x {need_h:.0f} mm livres na área útil")
    left = x0 + 2.0
    top = y1 - 2.0
    paths: list[PenPath] = []
    rows = []
    for i, depth in enumerate(depths):
        y = top - i * LADDER_GAP
        a, b = (left, left + LADDER_LINE) if i % 2 == 0 else (left + LADDER_LINE, left)  # vai e volta
        paths.append(_line(a, y, b, y, depth))
        rows.append({"depth": depth, "y": round(y, 2)})
    wy = top - len(depths) * LADDER_GAP
    paths.append(_line(left, wy, left + LADDER_WEDGE, wy, depths[0], depths[-1]))
    info = {
        "rows": rows,
        "wedge": {"y": round(wy, 2), "from": depths[0], "to": depths[-1], "length": LADDER_WEDGE},
        "box": [round(left, 2), round(wy, 2), round(left + need_w - 4.0, 2), round(top, 2)],
    }
    return paths, info


def offset_cross(area: Area, pen: PenProfile, target: tuple[float, float] | None = None, size: float = 30.0):
    """Cruz + quadradinho centrados em ``target`` (padrão: meio da área útil)."""
    x0, y0, x1, y1 = area
    cx, cy = target if target is not None else ((x0 + x1) / 2.0, (y0 + y1) / 2.0)
    half = size / 2.0
    if cx - half < x0 or cx + half > x1 or cy - half < y0 or cy + half > y1:
        raise PlanError("a cruz de teste não cabe na área útil nesse ponto")
    depth = min(pen.depth_max, pen.depth_min + 0.15)
    box = 3.0
    square = np.array(
        [
            [cx - box, cy - box, depth],
            [cx + box, cy - box, depth],
            [cx + box, cy + box, depth],
            [cx - box, cy + box, depth],
            [cx - box, cy - box, depth],
        ],
        dtype=np.float64,
    )
    paths = [_line(cx - half, cy, cx + half, cy, depth), _line(cx, cy - half, cx, cy + half, depth), PenPath(square)]
    return paths, {"target": [round(cx, 2), round(cy, 2)], "size": size}


def frame(area: Area, pen: PenProfile) -> tuple[list[PenPath], dict]:
    """Contorno da área útil (onde a caneta de fato desenha)."""
    x0, y0, x1, y1 = area
    depth = min(pen.depth_max, pen.depth_min + 0.1)
    loop = np.array(
        [[x0, y0, depth], [x1, y0, depth], [x1, y1, depth], [x0, y1, depth], [x0, y0, depth]], dtype=np.float64
    )
    return [PenPath(loop)], {"area": [round(v, 2) for v in area]}


def corrected_offset(pen: PenProfile, expected: tuple[float, float], measured: tuple[float, float]) -> tuple[float, float]:
    """Novo offset a partir de onde a cruz deveria sair e de onde saiu (ambos em mm da mesa)."""
    return (
        round(pen.offset_x + (measured[0] - expected[0]), 2),
        round(pen.offset_y + (measured[1] - expected[1]), 2),
    )

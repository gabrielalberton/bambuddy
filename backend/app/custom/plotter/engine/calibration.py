"""Padrões de calibração: caminhos prontos (mm da mesa, aperto explícito), sem passar pela vetorização.

Um teste de espessura e dois de alinhamento.

- ``z_sweep`` (teste de altura): várias linhas horizontais, cada uma com o bico descendo de Z=5 a Z=8 mm ao
  longo da linha (do apertado ao fora do papel), cruzadas por verticais numeradas com o Z de cada posição.
  Só as horizontais são o teste; as verticais, a régua e os números saem leves e iguais. Quem olha a folha lê
  em que Z a linha começa a afinar e em que Z ela some;
- ``offset_cross``: cruz num ponto conhecido; a diferença entre onde ela saiu e onde deveria sair corrige
  o offset da caneta em relação ao bico;
- ``frame``: contorno da área útil, para conferir o alinhamento do papel antes de um desenho.
"""

from __future__ import annotations

import numpy as np

from . import font
from .plan import PenPath, PlanError
from .profile import PenProfile

Area = tuple[float, float, float, float]

TEXT_H = 2.5  # altura dos números (mm)
Z_FROM = 5.0  # Z do bico (mm) onde cada linha começa: apertada
Z_TO = 8.0  # Z do bico onde termina: acima do contato, sem marcar
Z_LINES = 5  # linhas de teste repetidas
Z_LINE_PITCH = 8.0  # mm entre as linhas
Z_MAJOR = 0.5  # verticais numeradas a cada 0,5 mm de Z
Z_MINOR = 0.1  # marcas curtas a cada 0,1 mm de Z
Z_WIDTH_SHARE = 0.8  # fração da largura do papel que o teste ocupa


def _light(pen: PenProfile) -> float:
    """Aperto leve e seguro para grade, cruz, contorno e números: um pouco acima do mínimo."""
    return min(pen.depth_max, pen.depth_min + min(0.15, 0.3 * (pen.depth_max - pen.depth_min)))


def _line(x0: float, y0: float, x1: float, y1: float, d0: float, d1: float | None = None) -> PenPath:
    return PenPath(np.array([[x0, y0, d0], [x1, y1, d0 if d1 is None else d1]], dtype=np.float64))


def _text(text: str, x: float, y: float, height: float, depth: float, align: str = "left") -> list[PenPath]:
    out = []
    for line in font.polylines(text, x, y, height, align):
        pts = np.column_stack([line, np.full(len(line), depth)])
        out.append(PenPath(pts))
    return out


def z_sweep(
    area: Area,
    pen: PenProfile,
    touch: float,
    paper_w: float,
    z_from: float | None = None,
    z_to: float | None = None,
    lines: int = Z_LINES,
) -> tuple[list[PenPath], dict]:
    """Linhas com o bico indo de ``z_from`` a ``z_to`` (padrão 5 -> 8 mm), com verticais numeradas por Z.

    ``touch`` é o Z do bico em que a ponta encosta no papel neste plot; o aperto de cada ponto é ``touch - Z``
    (negativo quando o bico está acima do contato). A largura é 80% da do papel e a altura, uns 50 mm.
    """
    z0 = Z_FROM if z_from is None else float(z_from)
    z1 = Z_TO if z_to is None else float(z_to)
    if z1 <= z0:
        raise PlanError("o Z final do teste precisa ser maior que o inicial")
    if touch - z0 > pen.max_compression + 1e-9:
        raise PlanError(f"Z={z0:g} aperta {touch - z0:.2f} mm: mais que o limite do suporte ({pen.max_compression:g} mm)")
    x0, y0, x1, y1 = area
    avail = x1 - x0 - 6.0  # folga para o meio número que passa da última vertical
    length = round(min(Z_WIDTH_SHARE * paper_w, avail), 1)
    pad = 4.0
    tick = 1.5
    need_h = 2 * pad + (lines - 1) * Z_LINE_PITCH + 3.0 + TEXT_H + tick + 2.0
    if length < 60.0 or y1 - y0 < need_h:
        raise PlanError(f"o teste precisa de {max(60.0, length):.0f} x {need_h:.0f} mm livres na área útil")
    left = x0 + (x1 - x0 - length) / 2.0
    top = y1 - 2.0
    first = top - pad
    bottom = first - (lines - 1) * Z_LINE_PITCH - pad
    light = _light(pen)

    def x_of(z: float) -> float:
        return left + (z - z0) / (z1 - z0) * length

    count = int(round((z1 - z0) / Z_MINOR))
    majors = [round(z0 + k * Z_MAJOR, 3) for k in range(int(round((z1 - z0) / Z_MAJOR)) + 1)]
    paths: list[PenPath] = []
    # régua: linha de base com marcas curtas a cada 0,1 mm de Z
    ruler = [[left, bottom, light]]
    for k in range(count + 1):
        x = x_of(z0 + k * Z_MINOR)
        ruler += [[x, bottom, light], [x, bottom - tick, light], [x, bottom, light]]
    paths.append(PenPath(np.array(ruler, dtype=np.float64)))
    # verticais numeradas (zigue-zague: duas descidas só) e o número do Z embaixo de cada uma
    vertical = []
    for k, z in enumerate(majors):
        a, b = (top, bottom) if k % 2 == 0 else (bottom, top)
        vertical += [[x_of(z), a, light], [x_of(z), b, light]]
    paths.append(PenPath(np.array(vertical, dtype=np.float64)))
    for z in majors:
        paths += _text(font.number(z), x_of(z), bottom - tick - 1.5 - TEXT_H, TEXT_H, light, "center")
    # o teste: cada linha desce do Z inicial ao final, sempre da esquerda para a direita
    rows = []
    for i in range(lines):
        y = first - i * Z_LINE_PITCH
        paths.append(_line(left, y, left + length, y, touch - z0, touch - z1))
        rows.append(round(y, 2))
    info = {
        "test": "zsweep",
        "z_from": z0,
        "z_to": z1,
        "touch": round(touch, 3),
        "length": length,
        "left": round(left, 2),
        "top": round(top, 2),
        "bottom": round(bottom, 2),
        "rows": rows,
        "marks": [{"z": z, "x": round(x_of(z), 2)} for z in majors],
        "box": [round(left, 2), round(bottom - tick - 1.5 - TEXT_H, 2), round(left + length, 2), round(top, 2)],
    }
    return paths, info


def offset_cross(area: Area, pen: PenProfile, target: tuple[float, float] | None = None, size: float = 30.0):
    """Cruz + quadradinho centrados em ``target`` (padrão: meio da área útil)."""
    x0, y0, x1, y1 = area
    cx, cy = target if target is not None else ((x0 + x1) / 2.0, (y0 + y1) / 2.0)
    half = size / 2.0
    if cx - half < x0 or cx + half > x1 or cy - half < y0 or cy + half > y1:
        raise PlanError("a cruz de teste não cabe na área útil nesse ponto")
    depth = _light(pen)
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
    depth = _light(pen)
    loop = np.array(
        [[x0, y0, depth], [x1, y0, depth], [x1, y1, depth], [x0, y1, depth], [x0, y0, depth]], dtype=np.float64
    )
    return [PenPath(loop)], {"area": [round(v, 2) for v in area]}


def corrected_offset(
    pen: PenProfile, expected: tuple[float, float], measured: tuple[float, float]
) -> tuple[float, float]:
    """Novo offset a partir de onde a cruz deveria sair e de onde saiu (ambos em mm da mesa)."""
    return (
        round(pen.offset_x + (measured[0] - expected[0]), 2),
        round(pen.offset_y + (measured[1] - expected[1]), 2),
    )

"""Padrões de calibração: caminhos prontos (mm da mesa, aperto explícito), sem passar pela vetorização.

Quatro testes de espessura (a largura do traço em função do aperto). Todos saem sobre uma grade de 10 mm com
as colunas numeradas embaixo: ela localiza cada resultado na folha (inclusive numa foto, onde os quadrados de
10 mm servem de escala) e é desenhada primeiro, leve, o que também escorva a tinta.

- ``pressure_ladder`` (teste 1, escada numerada): uma linha por aperto, com o aperto escrito ao lado; mede-se
  a largura de cada linha e o resultado vira a tabela aperto -> largura da caneta;
- ``spacing_comb`` (teste 2, pente): para alguns apertos, células hachuradas com espaçamento crescente; a
  última célula que fecha (vira mancha cheia) dá a largura sem precisar de paquímetro;
- ``ruler_wedge`` (teste 3, cunha): uma linha com aperto subindo do zero ao máximo e a volta descendo; a
  grade numerada é a régua. Dá onde a caneta começa a marcar, onde passa do ponto e a diferença ida/volta
  (atrito do suporte);
- ``wave_tapers`` (teste 4, onda e pontas): uma linha longa com o aperto oscilando do mínimo ao máximo em
  ondas cada vez mais curtas (onde ela para de afinar é o limite de resposta) e traços que afinam até sumir
  nas duas pontas, com rampas de comprimentos diferentes.

E dois de alinhamento:

- ``offset_cross``: cruz num ponto conhecido; a diferença entre onde ela saiu e onde deveria sair corrige
  o offset da caneta em relação ao bico;
- ``frame``: contorno da área útil, para conferir o alinhamento do papel antes de um desenho.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from . import font
from .plan import PenPath, PlanError
from .profile import PenProfile

Area = tuple[float, float, float, float]

GRID = 10.0  # mm; a primeira coluna de cada teste guarda os números de aperto
TEXT_H = 2.5  # altura dos números (mm)
SMALL_H = 2.0
NUMBER_BAND = 1.5 + TEXT_H  # faixa embaixo da grade com o número das colunas
LADDER_LINE = 50.0
COMB_CELL = 5.0
WEDGE_LEN = 100.0
WAVE_LEN = 150.0
WAVE_PERIODS = (50.0, 12.0)  # mm: a onda começa longa e vai encurtando
TAPER_RAMPS = (5.0, 10.0, 20.0, 40.0)
TAPER_HOLD = 10.0


def default_ladder_depths(pen: PenProfile, steps: int = 8) -> list[float]:
    """Apertos da folha de teste: do zero até o aperto máximo do perfil (ou o mínimo útil do modo).

    Com mola os passos são de décimos a meio mm; sem mola, de 0,05 mm, porque a ponta travada passa de
    "não marca" a "esmaga" em poucos décimos.
    """
    spec = pen.mount_spec
    top = min(pen.max_compression, max(pen.depth_max * 1.25, spec.ladder_top))
    out = [d for d in spec.ladder if d <= top + 1e-9]
    if len(out) > steps:
        idx = np.round(np.linspace(0, len(out) - 1, steps)).astype(int)
        out = [out[i] for i in sorted(set(idx.tolist()))]
    return out


def comb_depths(pen: PenProfile, count: int = 4) -> list[float]:
    """Apertos do pente: a faixa do perfil (mínimo ao máximo) em ``count`` passos de 0,01 mm."""
    values = np.linspace(pen.depth_min, pen.depth_max, count)
    return sorted({round(float(v), 2) for v in values})


def comb_spacings(pen: PenProfile, count: int = 8) -> list[float]:
    """Espaçamentos do pente em torno da largura nominal: de metade a três vezes, em progressão geométrica.

    O maior fica em 60% da célula (ainda cabem duas linhas nela), o que cobre até marcador de ~3 mm.
    """
    hi = min(max(0.2, 3.0 * pen.line_width), 0.6 * COMB_CELL)
    lo = min(max(0.1, 0.5 * pen.line_width), hi / 2.0)
    values = np.geomspace(lo, hi, count)
    return sorted({max(0.1, round(float(v) / 0.05) * 0.05) for v in values})


def _content_room(area: Area | None, longest: float) -> float:
    """Comprimento (múltiplo de 10 mm, até ``longest``) que cabe à direita da coluna dos números."""
    if area is None:
        return longest
    room = area[2] - area[0] - 4.0 - GRID - TEXT_H  # TEXT_H: meio número "10"/"15" passa da última linha
    return min(longest, float(max(0, math.floor(room / GRID + 1e-9)) * GRID))


def wedge_length(area: Area | None) -> float:
    return _content_room(area, WEDGE_LEN)


def taper_ramps(pen: PenProfile, room: float = WAVE_LEN) -> list[float]:
    """Rampas das pontas (mm), alongadas se preciso para não passar da variação de aperto que o modo aceita."""
    shortest = pen.depth_max / (0.9 * pen.mount_spec.max_slope)
    ramps = sorted({math.ceil(max(r, shortest) / 5.0) * 5.0 for r in TAPER_RAMPS})
    return [r for r in ramps if 2 * r + TAPER_HOLD <= room + 1e-9]


def thickness_layouts(pen: PenProfile, area: Area | None) -> dict:
    """Parâmetros que a tela usa para montar os formulários de resultado de cada teste."""
    top = default_ladder_depths(pen)[-1]
    wave = _content_room(area, WAVE_LEN)
    return {
        "ladder": {"depths": default_ladder_depths(pen)},
        "comb": {"depths": comb_depths(pen), "spacings": [round(s, 2) for s in comb_spacings(pen)]},
        "wedge": {"from": 0.0, "to": top, "length": wedge_length(area)},
        "wave": {"length": wave, "from": pen.depth_min, "to": pen.depth_max, "ramps": taper_ramps(pen, wave)},
    }


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


def _check_depths(pen: PenProfile, depths: list[float], minimum: int, what: str) -> list[float]:
    depths = sorted({round(float(d), 3) for d in depths})
    if len(depths) < minimum:
        raise PlanError(f"{what} precisa de pelo menos {minimum} apertos")
    if depths[0] < 0 or depths[-1] > pen.max_compression + 1e-9:
        raise PlanError(f"aperto {what} fora do limite do suporte")
    return depths


@dataclass(frozen=True)
class Grid:
    """Grade de ``cols`` x ``rows`` quadrados de 10 mm com o canto de cima à esquerda em (left, top)."""

    left: float
    top: float
    cols: int
    rows: int

    def x(self, col: float) -> float:
        return self.left + col * GRID

    def y(self, row: float) -> float:
        return self.top - row * GRID

    @property
    def right(self) -> float:
        return self.x(self.cols)

    @property
    def bottom(self) -> float:
        return self.y(self.rows)

    def info(self) -> dict:
        """Para localizar resultados: a coluna 0 da numeração começa na segunda linha vertical."""
        return {
            "left": round(self.left, 2),
            "top": round(self.top, 2),
            "pitch": GRID,
            "cols": self.cols,
            "rows": self.rows,
            "zero_x": round(self.x(1), 2),
        }


def _grid(area: Area, cols: int, rows: int, what: str) -> Grid:
    x0, y0, x1, y1 = area
    need_w = cols * GRID + 4.0 + font.width(str(cols - 1), TEXT_H) / 2.0
    need_h = rows * GRID + NUMBER_BAND + 4.0
    if x1 - x0 < need_w - 1e-9 or y1 - y0 < need_h - 1e-9:
        raise PlanError(f"{what} precisa de {need_w:.0f} x {need_h:.0f} mm livres na área útil")
    return Grid(x0 + 2.0, y1 - 2.0, cols, rows)


def _grid_paths(g: Grid, depth: float) -> list[PenPath]:
    """Linhas verticais e horizontais em zigue-zague (duas descidas só) e a numeração das colunas embaixo."""
    vertical, horizontal = [], []
    for k in range(g.cols + 1):
        a, b = (g.top, g.bottom) if k % 2 == 0 else (g.bottom, g.top)
        vertical += [[g.x(k), a, depth], [g.x(k), b, depth]]
    for k in range(g.rows + 1):
        a, b = (g.left, g.right) if k % 2 == 0 else (g.right, g.left)
        horizontal += [[a, g.y(k), depth], [b, g.y(k), depth]]
    paths = [PenPath(np.array(vertical, dtype=np.float64)), PenPath(np.array(horizontal, dtype=np.float64))]
    for k in range(1, g.cols + 1):
        paths += _text(str(k - 1), g.x(k), g.bottom - NUMBER_BAND, TEXT_H, depth, "center")
    return paths


def _box(g: Grid) -> list[float]:
    """Retângulo ocupado: a grade, a faixa dos números e a metade do último número, que passa da borda."""
    right = g.right + font.width(str(g.cols - 1), TEXT_H) / 2.0
    return [round(g.left, 2), round(g.bottom - NUMBER_BAND, 2), round(right, 2), round(g.top, 2)]


def _label(g: Grid, row: float, text: str, depth: float) -> list[PenPath]:
    """Texto alinhado à direita na coluna dos números, centrado na fileira ``row`` (0 = de cima)."""
    return _text(text, g.x(1) - 1.5, g.y(row + 0.5) - TEXT_H / 2.0, TEXT_H, depth, "right")


def pressure_ladder(area: Area, pen: PenProfile, depths: list[float] | None = None) -> tuple[list[PenPath], dict]:
    """Teste 1: uma linha de 50 mm por fileira da grade, da mais leve (em cima) à mais apertada, com o aperto escrito.

    Grade e números saem primeiro, com aperto leve; depois as linhas, em vai e volta.
    """
    depths = _check_depths(pen, depths or default_ladder_depths(pen), 2, "da escada")
    g = _grid(area, 1 + int(LADDER_LINE / GRID), len(depths), "a escada")
    light = _light(pen)
    paths = _grid_paths(g, light)
    for i, depth in enumerate(depths):
        paths += _label(g, i, font.number(depth), light)
    rows = []
    for i, depth in enumerate(depths):
        y = g.y(i + 0.5)
        a, b = (g.x(1), g.x(1) + LADDER_LINE) if i % 2 == 0 else (g.x(1) + LADDER_LINE, g.x(1))  # vai e volta
        paths.append(_line(a, y, b, y, depth))
        rows.append({"depth": depth, "y": round(y, 2)})
    return paths, {"test": "ladder", "rows": rows, "line": LADDER_LINE, "grid": g.info(), "box": _box(g)}


def _hatch(x: float, top: float, size: float, spacing: float, depth: float) -> PenPath:
    """Célula ``size`` x ``size`` hachurada em zigue-zague (uma descida só da caneta)."""
    n = int(math.floor(size / spacing + 1e-9)) + 1
    pts = []
    for k in range(n):
        y = top - k * spacing
        a, b = (x, x + size) if k % 2 == 0 else (x + size, x)
        pts += [[a, y, depth], [b, y, depth]]
    return PenPath(np.array(pts, dtype=np.float64))


def spacing_comb(
    area: Area, pen: PenProfile, depths: list[float] | None = None, spacings: list[float] | None = None
) -> tuple[list[PenPath], dict]:
    """Teste 2: uma fileira por aperto; em cada quadrado da grade, uma célula de 5 mm com linhas a ``espaçamento`` mm.

    Onde o traço é mais largo que o espaçamento a célula fecha numa mancha cheia: a última célula fechada de
    cada fileira dá a largura daquele aperto. A primeira fileira traz o espaçamento de cada coluna; a grade
    passa só entre as células.
    """
    depths = _check_depths(pen, depths or comb_depths(pen), 1, "do pente")
    spacings = sorted({round(float(s), 3) for s in (spacings or comb_spacings(pen))})
    if not 2 <= len(spacings) <= 12 or spacings[0] < 0.05 or spacings[-1] > COMB_CELL:
        raise PlanError("o pente usa de 2 a 12 espaçamentos entre 0,05 e 5 mm")
    g = _grid(area, 1 + len(spacings), 1 + len(depths), "o pente")
    light = _light(pen)
    inset = (GRID - COMB_CELL) / 2.0
    paths = _grid_paths(g, light)
    for j, spacing in enumerate(spacings):
        paths += _text(font.number(spacing), g.x(1 + j + 0.5), g.y(0.5) - SMALL_H / 2.0, SMALL_H, light, "center")
    rows = []
    for i, depth in enumerate(depths):
        paths += _label(g, 1 + i, font.number(depth), light)
        rows.append({"depth": depth, "y": round(g.y(1 + i + 0.5), 2)})
    for i, depth in enumerate(depths):
        for j, spacing in enumerate(spacings):
            paths.append(_hatch(g.x(1 + j) + inset, g.y(1 + i) - inset, COMB_CELL, spacing, depth))
    info = {"test": "comb", "rows": rows, "spacings": spacings, "cell": COMB_CELL, "grid": g.info(), "box": _box(g)}
    return paths, info


def _arrow(x: float, y: float, direction: int, depth: float) -> list[PenPath]:
    tip = x + 3.0 * direction
    shaft = _line(x - 3.0 * direction, y, tip, y, depth)
    head = PenPath(
        np.array(
            [[tip - 1.5 * direction, y + 1.5, depth], [tip, y, depth], [tip - 1.5 * direction, y - 1.5, depth]],
            dtype=np.float64,
        )
    )
    return [shaft, head]


def ruler_wedge(area: Area, pen: PenProfile, top_depth: float | None = None) -> tuple[list[PenPath], dict]:
    """Teste 3: ida (fileira de cima) com o aperto subindo de 0 ao máximo e volta (de baixo) descendo.

    A grade numerada de 0 a 10 é a régua. A volta corre da direita para a esquerda com o mesmo aperto da ida
    em cada coluna: se a mola agarra no tubo, a volta continua marcando além de onde a ida começou.
    """
    d1 = round(float(top_depth if top_depth is not None else default_ladder_depths(pen)[-1]), 3)
    if not 0 < d1 <= pen.max_compression + 1e-9:
        raise PlanError("aperto final da cunha fora do limite do suporte")
    length = wedge_length(area)
    if length < 40.0:
        raise PlanError("a cunha precisa de pelo menos 54 mm de largura livre na área útil")
    g = _grid(area, 1 + int(length / GRID), 2, "a cunha")
    light = _light(pen)
    paths = _grid_paths(g, light)
    fy, ry = g.y(0.5), g.y(1.5)
    paths += _arrow(g.x(0.5), fy, 1, light) + _arrow(g.x(0.5), ry, -1, light)
    paths.append(_line(g.x(1), fy, g.x(1) + length, fy, 0.0, d1))
    paths.append(_line(g.x(1) + length, ry, g.x(1), ry, d1, 0.0))
    info = {
        "test": "wedge",
        "length": length,
        "marks": int(round(length / GRID)),
        "from": 0.0,
        "to": d1,
        "forward_y": round(fy, 2),
        "return_y": round(ry, 2),
        "grid": g.info(),
        "box": _box(g),
    }
    return paths, info


def _wave(x0: float, y: float, length: float, d0: float, d1: float, periods: tuple[float, float]) -> PenPath:
    """Aperto d0 + (d1 - d0)(1 - cos φ)/2 com o período encolhendo linearmente ao longo da linha."""
    xs = np.arange(0.0, length + 1e-9, 0.5)
    period = periods[0] + (periods[1] - periods[0]) * xs / length
    phase = np.concatenate([[0.0], np.cumsum(2.0 * np.pi * np.diff(xs) / period[:-1])])
    depth = d0 + (d1 - d0) * (1.0 - np.cos(phase)) / 2.0
    return PenPath(np.column_stack([x0 + xs, np.full_like(xs, y), depth]))


def wave_tapers(area: Area, pen: PenProfile) -> tuple[list[PenPath], dict]:
    """Teste 4: onda de aperto (fileira de cima) e pontas que afinam até sumir (uma por fileira, rampa escrita ao lado).

    A onda vai do aperto mínimo ao máximo do perfil; o período cai de 50 para 12 mm (ou o mais curto que o
    modo aceita sem passar da variação de aperto por mm). Cada ponta sai do aperto zero, sobe até o máximo
    em ``rampa`` mm, segura 10 mm e desce de novo a zero: pela grade se lê a que distância da ponta o
    traço sumiu.
    """
    d0, d1 = pen.depth_min, pen.depth_max
    if d1 <= d0:
        raise PlanError("a onda precisa de aperto máximo maior que o mínimo")
    length = _content_room(area, WAVE_LEN)
    ramps = taper_ramps(pen, length)
    if length < 60.0 or len(ramps) < 2:
        raise PlanError("a onda precisa de pelo menos 74 mm de largura livre na área útil")
    slope = 0.9 * pen.mount_spec.max_slope
    shortest = (d1 - d0) * math.pi / slope
    periods = (max(WAVE_PERIODS[0], shortest), max(WAVE_PERIODS[1], shortest))
    g = _grid(area, 1 + int(length / GRID), 1 + len(ramps), "a onda")
    light = _light(pen)
    paths = _grid_paths(g, light)
    tapers = []
    for i, ramp in enumerate(ramps):
        paths += _label(g, 1 + i, font.number(ramp), light)
    paths.append(_wave(g.x(1), g.y(0.5), length, d0, d1, periods))
    for i, ramp in enumerate(ramps):
        y = g.y(1 + i + 0.5)
        x = g.x(1)
        pts = [[x, y, 0.0], [x + ramp, y, d1], [x + ramp + TAPER_HOLD, y, d1], [x + 2 * ramp + TAPER_HOLD, y, 0.0]]
        paths.append(PenPath(np.array(pts, dtype=np.float64)))
        tapers.append({"ramp": ramp, "depth": d1, "y": round(y, 2)})
    info = {
        "test": "wave",
        "length": length,
        "from": d0,
        "to": d1,
        "periods": [round(p, 1) for p in periods],
        "tapers": tapers,
        "grid": g.info(),
        "box": _box(g),
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

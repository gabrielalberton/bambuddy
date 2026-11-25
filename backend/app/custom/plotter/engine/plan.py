"""Desenho (px) + posição + papel + caneta -> caminhos da caneta em mm, com aperto em cada ponto.

Saída: lista de ``PenPath`` com pontos (X, Y, aperto) no sistema da mesa, já recortados à área útil,
ordenados para andar pouco e com a variação de aperto limitada ao que o eixo Z acompanha.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from . import simplify
from .profile import Machine, Paper, PenProfile, Placement, drawable_area
from .strokes import Drawing

# quanto o aperto pode variar por mm de traço (o Z é lento; acima disso a máquina freia o XY)
MAX_DEPTH_SLOPE = 0.6
GCODE_EPS_XY = 0.03  # mm
GCODE_EPS_DEPTH = 0.015  # mm
MAX_PATHS = 60_000
MAX_POINTS = 600_000


class PlanError(ValueError):
    """Não dá para gerar o plot com estes dados."""


@dataclass
class PlanOptions:
    pressure: str = "variable"  # "variable" | "constant"
    width_mode: str = "fit"  # "fit": espalha as larguras do desenho na faixa da caneta | "physical": largura real
    width_gain: float = 1.0  # multiplica a largura (modo "physical")
    constant_depth: float | None = None  # aperto no modo constante (None = o mais leve que risca)
    optimize: bool = True
    exclude: list[int] = field(default_factory=list)  # índices de traços que o usuário apagou

    @classmethod
    def from_dict(cls, data: dict | None) -> PlanOptions:
        data = data or {}
        o = cls()
        o.pressure = "constant" if data.get("pressure") == "constant" else "variable"
        o.width_mode = "physical" if data.get("width_mode") == "physical" else "fit"
        try:
            o.width_gain = float(min(10.0, max(0.1, float(data.get("width_gain", 1.0)))))
        except (TypeError, ValueError):
            o.width_gain = 1.0
        cd = data.get("constant_depth")
        o.constant_depth = None if cd in (None, "") else float(cd)
        o.optimize = bool(data.get("optimize", True))
        o.exclude = [int(i) for i in (data.get("exclude") or []) if isinstance(i, (int, float))][:100_000]
        return o


@dataclass
class PenPath:
    pts: np.ndarray  # (n, 3) float64: X, Y da ponta da caneta (mm da mesa) e aperto (mm)

    @property
    def is_dot(self) -> bool:
        return len(self.pts) == 1


@dataclass
class Issue:
    level: str  # "error" | "warning" | "info"
    code: str
    text: str
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"level": self.level, "code": self.code, "text": self.text, "data": self.data}


@dataclass
class PlanPaths:
    paths: list[PenPath]
    issues: list[Issue]
    stats: dict


def transform_matrix(drawing_w: float, drawing_h: float, placement: Placement) -> tuple[np.ndarray, float]:
    """(matriz 2x3 de px da imagem -> mm da mesa, mm por px). O Y da imagem cresce para baixo; o da mesa, para o fundo."""
    s = placement.width / drawing_w
    th = math.radians(placement.rotation)
    c, sn = math.cos(th), math.sin(th)
    # local: lx = (u - W/2)·s ; ly = (H/2 - v)·s ; mesa = centro + R(θ)·local
    a = np.array([[c * s, sn * s], [sn * s, -c * s]], dtype=np.float64)
    off = np.array(
        [
            placement.cx - c * s * drawing_w / 2.0 - sn * s * drawing_h / 2.0,
            placement.cy - sn * s * drawing_w / 2.0 + c * s * drawing_h / 2.0,
        ]
    )
    return np.concatenate([a, off[:, None]], axis=1), s


def placement_corners(drawing_w: float, drawing_h: float, placement: Placement) -> np.ndarray:
    """Os 4 cantos da imagem na mesa (mm), na ordem cima-esq, cima-dir, baixo-dir, baixo-esq da imagem."""
    m, _ = transform_matrix(drawing_w, drawing_h, placement)
    corners = np.array([[0, 0, 1], [drawing_w, 0, 1], [drawing_w, drawing_h, 1], [0, drawing_h, 1]], dtype=np.float64)
    return corners @ m.T


def clip_polyline(pts: np.ndarray, rect: tuple[float, float, float, float]) -> list[np.ndarray]:
    """Recorta uma polilinha (x, y, atributo) a um retângulo; devolve os pedaços que ficam dentro."""
    x0, y0, x1, y1 = rect
    xs, ys = pts[:, 0], pts[:, 1]
    if xs.min() >= x0 and xs.max() <= x1 and ys.min() >= y0 and ys.max() <= y1:
        return [pts]
    if xs.max() < x0 or xs.min() > x1 or ys.max() < y0 or ys.min() > y1:
        return []
    if len(pts) == 1:
        return []
    out: list[np.ndarray] = []
    cur: list[np.ndarray] = []
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        dx, dy = float(b[0] - a[0]), float(b[1] - a[1])
        t0, t1, inside = 0.0, 1.0, True
        for p, q in ((-dx, a[0] - x0), (dx, x1 - a[0]), (-dy, a[1] - y0), (dy, y1 - a[1])):
            if abs(p) < 1e-12:
                if q < 0:
                    inside = False
                    break
                continue
            r = q / p
            if p < 0:
                if r > t1:
                    inside = False
                    break
                t0 = max(t0, r)
            else:
                if r < t0:
                    inside = False
                    break
                t1 = min(t1, r)
        if not inside or t1 - t0 < 1e-12:
            if len(cur) > 1:
                out.append(np.array(cur))
            cur = []
            continue
        pa, pb = a + t0 * (b - a), a + t1 * (b - a)
        if t0 > 0.0 and cur:
            if len(cur) > 1:
                out.append(np.array(cur))
            cur = []
        if not cur:
            cur = [pa]
        cur.append(pb)
        if t1 < 1.0:
            if len(cur) > 1:
                out.append(np.array(cur))
            cur = []
    if len(cur) > 1:
        out.append(np.array(cur))
    return out


def limit_slope(pts: np.ndarray, max_slope: float = MAX_DEPTH_SLOPE) -> np.ndarray:
    """Limita |Δaperto| por mm andado. Só alivia (nunca aperta mais do que foi pedido)."""
    if len(pts) < 2:
        return pts
    out = pts.copy()
    seg = np.hypot(np.diff(out[:, 0]), np.diff(out[:, 1]))
    d = out[:, 2]
    for i in range(1, len(d)):
        d[i] = min(d[i], d[i - 1] + max_slope * seg[i - 1])
    for i in range(len(d) - 2, -1, -1):
        d[i] = min(d[i], d[i + 1] + max_slope * seg[i])
    return out


def order_paths(paths: list[PenPath], start: tuple[float, float]) -> list[PenPath]:
    """Vizinho mais próximo, podendo inverter o traço. Em desenho enorme, em faixas (serpentina)."""
    n = len(paths)
    if n < 2:
        return paths
    if n > 6000:
        return _order_bands(paths, start)
    starts = np.array([p.pts[0, :2] for p in paths])
    ends = np.array([p.pts[-1, :2] for p in paths])
    return _greedy(paths, starts, ends, np.array(start, dtype=np.float64))[0]


def _greedy(paths, starts, ends, cur):
    n = len(paths)
    left = np.ones(n, dtype=bool)
    out: list[PenPath] = []
    big = 1e18
    for _ in range(n):
        ds = ((starts - cur) ** 2).sum(axis=1)
        de = ((ends - cur) ** 2).sum(axis=1)
        ds[~left] = big
        de[~left] = big
        i, j = int(np.argmin(ds)), int(np.argmin(de))
        if ds[i] <= de[j]:
            out.append(paths[i])
            cur = ends[i]
            left[i] = False
        else:
            out.append(PenPath(paths[j].pts[::-1].copy()))
            cur = starts[j]
            left[j] = False
    return out, cur


def _order_bands(paths: list[PenPath], start: tuple[float, float], band: float = 12.0) -> list[PenPath]:
    mids = np.array([p.pts[len(p.pts) // 2, :2] for p in paths])
    rows = np.floor(mids[:, 1] / band).astype(int)
    out: list[PenPath] = []
    cur = np.array(start, dtype=np.float64)
    for k, row in enumerate(sorted(set(rows.tolist()))):
        idx = np.nonzero(rows == row)[0]
        idx = idx[np.argsort(mids[idx, 0])]
        if k % 2:
            idx = idx[::-1]
        for chunk in np.array_split(idx, max(1, len(idx) // 2000)):
            sub = [paths[i] for i in chunk]
            starts = np.array([p.pts[0, :2] for p in sub])
            ends = np.array([p.pts[-1, :2] for p in sub])
            ordered, cur = _greedy(sub, starts, ends, cur)
            out.extend(ordered)
    return out


def build_paths(
    drawing: Drawing,
    placement: Placement,
    paper: Paper,
    pen: PenProfile,
    machine: Machine,
    opts: PlanOptions | None = None,
) -> PlanPaths:
    opts = opts or PlanOptions()
    issues: list[Issue] = []
    area = drawable_area(machine, pen, paper)
    if area is None:
        raise PlanError("o papel não tem área útil dentro do alcance da caneta (confira posição, margem e offset)")
    if not drawing.strokes:
        raise PlanError("o desenho não tem traços")
    variable = opts.pressure == "variable"
    if variable and not pen.pressure_calibrated:
        variable = False
        issues.append(
            Issue(
                "warning",
                "pressure_uncalibrated",
                "Sem tabela de pressão calibrada: plotando com pressão constante.",
            )
        )
    matrix, mm_per_px = transform_matrix(drawing.width, drawing.height, placement)
    skip = set(opts.exclude)
    strokes = [s for i, s in enumerate(drawing.strokes) if i not in skip]
    if not strokes:
        raise PlanError("todos os traços foram removidos")

    # largura física (mm) de cada ponto e a função largura -> aperto
    pen_lo, pen_hi = pen.width_range()
    all_w = np.concatenate([s.pts[:, 2] for s in strokes]).astype(np.float64) * mm_per_px
    # "fit" é relativo: o mais fino do desenho vira o mais fino da caneta, o mais grosso vira o mais grosso.
    # Desenho de largura uniforme não tem o que espalhar: usa a largura real, limitada à faixa, sem avisos.
    fit_mode = variable and opts.width_mode == "fit"
    fit = None
    if fit_mode:
        w_lo, w_hi = float(np.percentile(all_w, 5)), float(np.percentile(all_w, 95))
        if w_hi > 1e-9 and (w_hi - w_lo) / w_hi >= 0.15:
            fit = (w_lo, w_hi)
    const_depth = pen.depth_min if opts.constant_depth is None else float(opts.constant_depth)
    const_depth = min(pen.depth_max, max(0.0, const_depth))
    table_w = np.array([r[1] for r in pen.table], dtype=np.float64)
    table_d = np.array([r[0] for r in pen.table], dtype=np.float64)

    def depths_for(width_mm: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(aperto, fora da faixa: -1 fino demais, +1 grosso demais, 0 ok)."""
        if not variable:
            return np.full(len(width_mm), const_depth), np.zeros(len(width_mm), dtype=np.int8)
        if fit is not None:
            t = np.clip((width_mm - fit[0]) / (fit[1] - fit[0]), 0.0, 1.0)
            target = pen_lo + t * (pen_hi - pen_lo)
            flag = np.zeros(len(width_mm), dtype=np.int8)
        elif fit_mode:
            target = width_mm
            flag = np.zeros(len(width_mm), dtype=np.int8)
        else:
            target = width_mm * opts.width_gain
            flag = np.where(target < pen_lo * 0.85, -1, np.where(target > pen_hi * 1.15, 1, 0)).astype(np.int8)
        depth = np.interp(np.clip(target, pen_lo, pen_hi), table_w, table_d)
        return np.clip(depth, pen.depth_min, pen.depth_max), flag

    paths: list[PenPath] = []
    total_len = kept_len = thin_len = thick_len = 0.0
    dots_total = dots_kept = 0
    for s in strokes:
        src = s.path().astype(np.float64)
        xy = src[:, :2] @ matrix[:, :2].T + matrix[:, 2]
        depth, flag = depths_for(src[:, 2] * mm_per_px)
        pts = np.concatenate([xy, depth[:, None]], axis=1)
        if len(pts) == 1:
            dots_total += 1
            x, y = pts[0, 0], pts[0, 1]
            if area[0] <= x <= area[2] and area[1] <= y <= area[3]:
                dots_kept += 1
                paths.append(PenPath(pts))
            continue
        seg = np.hypot(np.diff(xy[:, 0]), np.diff(xy[:, 1]))
        length = float(seg.sum())
        total_len += length
        if flag.any():
            seg_flag = np.maximum(np.abs(flag[:-1]), np.abs(flag[1:])) * np.sign(flag[:-1] + flag[1:] + 0.0)
            thin_len += float(seg[seg_flag < 0].sum())
            thick_len += float(seg[seg_flag > 0].sum())
        for piece in clip_polyline(pts, area):
            piece = simplify.simplify_xyv(piece, GCODE_EPS_XY, GCODE_EPS_DEPTH)
            piece = _drop_tiny(piece)
            if len(piece) < 2:
                continue
            piece = limit_slope(piece)
            kept_len += float(np.hypot(np.diff(piece[:, 0]), np.diff(piece[:, 1])).sum())
            paths.append(PenPath(piece))

    if not paths:
        raise PlanError("nada do desenho cai dentro da área útil do papel")
    if len(paths) > MAX_PATHS or sum(len(p.pts) for p in paths) > MAX_POINTS:
        raise PlanError("desenho grande demais para um plot só (traços demais); simplifique ou reduza a imagem")
    clipped = 0.0 if total_len <= 0 else max(0.0, 1.0 - kept_len / total_len)
    if clipped > 0.002 or dots_kept < dots_total:
        issues.append(
            Issue(
                "warning",
                "clipped",
                f"{clipped * 100:.0f}% do traçado fica fora da área útil do papel e não será desenhado.",
                {"fraction": round(clipped, 4), "dots_dropped": dots_total - dots_kept},
            )
        )
    if total_len > 0 and thin_len / total_len > 0.02:
        issues.append(
            Issue(
                "warning",
                "too_thin",
                f"{thin_len / total_len * 100:.0f}% do traçado pede linha mais fina que a caneta faz "
                f"({pen_lo:.2f} mm); sai na largura mínima.",
                {"fraction": round(thin_len / total_len, 4)},
            )
        )
    if total_len > 0 and thick_len / total_len > 0.02:
        issues.append(
            Issue(
                "warning",
                "too_thick",
                f"{thick_len / total_len * 100:.0f}% do traçado pede linha mais grossa que a caneta faz "
                f"({pen_hi:.2f} mm); sai na largura máxima.",
                {"fraction": round(thick_len / total_len, 4)},
            )
        )
    if opts.optimize:
        paths = order_paths(paths, (area[0], area[1]))
    depths = np.concatenate([p.pts[:, 2] for p in paths])
    allxy = np.concatenate([p.pts[:, :2] for p in paths])
    stats = {
        "paths": len(paths),
        "dots": sum(1 for p in paths if p.is_dot),
        "points": int(sum(len(p.pts) for p in paths)),
        "draw_mm": round(kept_len, 1),
        "clipped_fraction": round(clipped, 4),
        "pressure": "variable" if variable else "constant",
        "width_mode": ("fit" if fit_mode else "physical") if variable else "constant",
        "width_fit": [round(fit[0], 3), round(fit[1], 3)] if fit is not None else None,
        "depth_min": round(float(depths.min()), 3),
        "depth_max": round(float(depths.max()), 3),
        "width_min": round(pen.width_for_depth(float(depths.min())), 3),
        "width_max": round(pen.width_for_depth(float(depths.max())), 3),
        "mm_per_px": round(mm_per_px, 5),
        "bounds": [round(float(v), 2) for v in (*allxy.min(axis=0), *allxy.max(axis=0))],
        "area": [round(float(v), 2) for v in area],
    }
    return PlanPaths(paths, issues, stats)


def _drop_tiny(pts: np.ndarray, min_step: float = 0.02) -> np.ndarray:
    if len(pts) < 3:
        return pts
    keep = [0]
    for i in range(1, len(pts) - 1):
        if math.hypot(pts[i, 0] - pts[keep[-1], 0], pts[i, 1] - pts[keep[-1], 1]) >= min_step:
            keep.append(i)
    keep.append(len(pts) - 1)
    return pts[keep]

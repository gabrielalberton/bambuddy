"""Imagem -> ``Drawing`` (traços de linha central com largura em cada ponto).

Não é vetorização de contorno: cada traço da imagem vira UMA linha pelo eixo, com a largura local medida
pela transformada de distância. É essa largura que depois vira pressão (profundidade em Z) na caneta.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass

import cv2
import numpy as np

from . import raster, simplify, skeleton
from .graph import RawStroke, TraceOptions, trace_skeleton
from .strokes import Drawing, Stroke

# Abaixo desta largura (px) o traço é fino demais para medir espessura direito: amplia antes de afinar.
_MIN_WORK_STROKE_PX = 3.2
_MAX_WORK_PIXELS = 9_000_000


@dataclass
class VectorizeOptions:
    ink: str = "luma"
    invert: str = "auto"
    threshold: float | None = None
    background: bool = True
    despeckle: float = 1.0  # multiplicador da limpeza automática de sujeira (0 = não limpa)
    smooth: float = 1.5  # suavização do eixo, em px de trabalho
    prune: float = 0.9  # rebarbas: 0 = mantém tudo, maior = poda mais
    simplify: float = 0.35  # erro máximo da simplificação, em px de trabalho
    max_deviation_deg: float = 45.0  # continuidade nos cruzamentos
    max_pixels: int = raster.MAX_PIXELS_DEFAULT

    @classmethod
    def from_dict(cls, data: dict | None) -> VectorizeOptions:
        out = cls()
        for key, value in (data or {}).items():
            if hasattr(out, key) and value is not None:
                setattr(out, key, value)
        out.despeckle = float(min(20.0, max(0.0, out.despeckle)))
        out.smooth = float(min(6.0, max(0.0, out.smooth)))
        out.prune = float(min(3.0, max(0.0, out.prune)))
        out.simplify = float(min(3.0, max(0.05, out.simplify)))
        out.max_deviation_deg = float(min(80.0, max(5.0, out.max_deviation_deg)))
        return out

    def raster(self) -> raster.RasterOptions:
        return raster.RasterOptions.from_dict(
            {
                "ink": self.ink,
                "invert": self.invert,
                "threshold": self.threshold,
                "background": self.background,
                "max_pixels": self.max_pixels,
            }
        )


def vectorize_image(data: bytes, options: VectorizeOptions | dict | None = None) -> Drawing:
    opts = options if isinstance(options, VectorizeOptions) else VectorizeOptions.from_dict(options)
    return vectorize(raster.decode_image(data, opts.raster().max_pixels), opts)


def vectorize(rgb: np.ndarray, options: VectorizeOptions | dict | None = None) -> Drawing:
    opts = options if isinstance(options, VectorizeOptions) else VectorizeOptions.from_dict(options)
    ropts = opts.raster()
    t0 = time.time()
    h, w = rgb.shape[:2]
    dark = raster.darkness(rgb, ropts)
    speck = max(4.0, 2.5e-6 * h * w) * opts.despeckle
    mask, core, threshold = _masks(dark, ropts, speck)
    coverage = float(mask.mean())
    if coverage <= 0.0:
        raise raster.ImageError("não achei traço na imagem (tente ajustar o limiar)")
    dt = skeleton.distance(core)
    typical = raster.typical_stroke_px(core, dt)

    factor = 1
    if typical < _MIN_WORK_STROKE_PX:
        factor = 3 if typical < 1.6 else 2
        while factor > 1 and h * w * factor * factor > _MAX_WORK_PIXELS:
            factor -= 1
    if factor > 1:
        big = cv2.resize(dark, (w * factor, h * factor), interpolation=cv2.INTER_CUBIC)
        fixed = raster.RasterOptions.from_dict({**asdict(ropts), "threshold": threshold})
        mask, core, _ = _masks(big, fixed, speck * factor * factor)
        del big
        dt = skeleton.distance(core)
    del dark, core

    skel = skeleton.thin(mask)
    raw = trace_skeleton(
        skel,
        dt,
        TraceOptions(prune_ratio=opts.prune, max_deviation_deg=opts.max_deviation_deg),
    )
    strokes = [s for s in (_refine(r, opts, 1.0 / factor) for r in raw) if s is not None]
    drawing = Drawing(float(w), float(h), strokes)
    drawing.meta = {
        "threshold": round(threshold, 3),
        "coverage": round(coverage, 4),
        "typical_stroke_px": round(typical, 2),
        "work_scale": factor,
        "seconds": round(time.time() - t0, 2),
        "options": asdict(opts),
        **drawing.stats(),
    }
    return drawing


def _masks(dark: np.ndarray, ropts: raster.RasterOptions, speck: float) -> tuple[np.ndarray, np.ndarray, float]:
    """(máscara limpa para a topologia, miolo para medir largura, limiar)."""
    mask, core, threshold = raster.binarize(dark, ropts)
    if speck > 0:
        cleaned = raster.clean(mask, speck)
        core = ((core | (cleaned & (1 - mask))) & cleaned).astype(np.uint8)  # furinho fechado conta como tinta
        mask = cleaned
    else:
        core = (core & mask).astype(np.uint8)
    return mask, core, threshold


def _refine(raw: RawStroke, opts: VectorizeOptions, scale: float) -> Stroke | None:
    """Traço cru do esqueleto (px de trabalho) -> traço suave e enxuto (px da imagem)."""
    if raw.is_dot:
        width = float(skeleton.width_from_distance(float(raw.rad[0])))
        return Stroke(np.array([[raw.pts[0, 0] * scale, raw.pts[0, 1] * scale, width * scale]], dtype=np.float32))
    pts, rad = simplify.resample(raw.pts, raw.rad, 1.0, raw.closed)
    if len(pts) < 2:
        return None
    x = simplify.gaussian_smooth(pts[:, 0], opts.smooth, raw.closed)
    y = simplify.gaussian_smooth(pts[:, 1], opts.smooth, raw.closed)
    # a largura oscila mais que o eixo (ruído de borda): suaviza um pouco mais, sem extrapolar nas pontas
    r = simplify.gaussian_smooth(rad, 2.0 * opts.smooth + 1.0, raw.closed, pin_ends=False)
    width = skeleton.width_from_distance(np.asarray(r, dtype=np.float64))
    xyz = np.stack([x, y, width], axis=1)
    out = simplify.simplify_xyv(xyz, opts.simplify, max(0.25, opts.simplify * 1.5), raw.closed)
    closed = raw.closed and len(out) >= 3
    return Stroke((out * scale).astype(np.float32), closed)


def render_preview(drawing: Drawing, max_side: int = 1400, background: int = 255) -> np.ndarray:
    """Rasteriza os traços com a largura variável (imagem cinza uint8), para conferência e miniaturas."""
    scale = min(1.0, max_side / max(drawing.width, drawing.height))
    shift = 4  # subpixel do OpenCV
    f = scale * (1 << shift)
    canvas = np.full(
        (max(1, round(drawing.height * scale)), max(1, round(drawing.width * scale))), background, np.uint8
    )
    ink = 0 if background > 127 else 255
    for s in drawing.strokes:
        p = s.path()
        if len(p) == 1:
            c = (int(round(p[0, 0] * f)), int(round(p[0, 1] * f)))
            cv2.circle(canvas, c, max(1, int(round(p[0, 2] * 0.5 * f))), ink, -1, cv2.LINE_AA, shift)
            continue
        for a, b in zip(p[:-1], p[1:]):
            thick = max(1, int(round(0.5 * (a[2] + b[2]) * scale)))
            pa = (int(round(a[0] * f)), int(round(a[1] * f)))
            pb = (int(round(b[0] * f)), int(round(b[1] * f)))
            cv2.line(canvas, pa, pb, ink, thick, cv2.LINE_AA, shift)
    return canvas

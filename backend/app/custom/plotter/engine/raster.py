"""Imagem -> mapa de tinta (0..1) -> máscara binária limpa.

O alvo são desenhos a traço, caligrafia e fotos/scans de papel: fundo claro (ou escuro, detectado), tinta
contrastante. Tudo aqui trabalha em pixels; a escala física entra só no posicionamento.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import cv2
import numpy as np

# Acima disto a imagem é reduzida: não melhora o traço e o processo de vetorização tem teto de memória.
MAX_PIXELS_DEFAULT = 4_000_000
# Teto absoluto do que aceitamos decodificar (bomba de descompressão).
DECODE_PIXEL_LIMIT = 120_000_000
# PNG e outros formatos precisam passar pela resolução original antes do resize.
FULL_DECODE_PIXEL_LIMIT = 24_000_000


class ImageError(ValueError):
    """Imagem inválida, grande demais ou sem traço aproveitável."""


@dataclass
class RasterOptions:
    ink: str = "luma"  # "luma" (tinta escura) | "min" (tinta colorida sobre papel claro)
    invert: str = "auto"  # "auto" | "yes" | "no"  (traço claro sobre fundo escuro)
    threshold: float | None = None  # 0..1 sobre a escuridão normalizada; None = Otsu
    hysteresis: float = 0.7  # limiar fraco = forte * hysteresis (recupera pontas claras do traço)
    background: bool = True  # compensa iluminação desigual (foto de papel)
    min_speck_px: float | None = None  # área mínima de um componente; None = automático
    max_pixels: int = MAX_PIXELS_DEFAULT

    @classmethod
    def from_dict(cls, data: dict | None) -> RasterOptions:
        out = cls()
        for key, value in (data or {}).items():
            if hasattr(out, key) and value is not None:
                setattr(out, key, value)
        if out.ink not in ("luma", "min"):
            out.ink = "luma"
        if out.invert not in ("auto", "yes", "no"):
            out.invert = "auto"
        if out.threshold is not None:
            out.threshold = float(min(0.97, max(0.03, out.threshold)))
        out.hysteresis = float(min(1.0, max(0.3, out.hysteresis)))
        out.max_pixels = int(min(MAX_PIXELS_DEFAULT, max(50_000, out.max_pixels)))
        return out


def decode_image(data: bytes, max_pixels: int = MAX_PIXELS_DEFAULT) -> np.ndarray:
    """Bytes de imagem -> RGB uint8 (HxWx3), orientação EXIF aplicada, transparência sobre branco."""
    from PIL import Image, ImageOps

    Image.MAX_IMAGE_PIXELS = DECODE_PIXEL_LIMIT
    try:
        im = Image.open(io.BytesIO(data))
        pixels = im.width * im.height
        limit = DECODE_PIXEL_LIMIT if im.format == "JPEG" else FULL_DECODE_PIXEL_LIMIT
        if pixels > limit:
            raise ImageError(f"imagem grande demais: reduza para até {limit // 1_000_000} megapixels")
        # JPEG: decodifica já reduzido (economiza muita RAM em foto de celular)
        if im.format == "JPEG" and pixels > max_pixels * 2:
            scale = (pixels / max_pixels) ** 0.5
            im.draft("RGB", (max(1, int(im.width / scale)), max(1, int(im.height / scale))))
        im = ImageOps.exif_transpose(im)
        if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
            rgba = im.convert("RGBA")
            white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
            im = Image.alpha_composite(white, rgba).convert("RGB")
        else:
            im = im.convert("RGB")
        if im.width * im.height > max_pixels:
            scale = (max_pixels / (im.width * im.height)) ** 0.5
            im = im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))), Image.LANCZOS)
        arr = np.asarray(im, dtype=np.uint8)
    except ImageError:
        raise
    except Exception as exc:  # noqa: BLE001 - Pillow levanta de tudo um pouco
        raise ImageError(f"não consegui abrir a imagem ({type(exc).__name__})") from exc
    if arr.ndim != 3 or arr.shape[0] < 4 or arr.shape[1] < 4:
        raise ImageError("imagem pequena demais")
    return np.ascontiguousarray(arr)


def darkness(rgb: np.ndarray, opts: RasterOptions) -> np.ndarray:
    """Mapa float32 em 0..1: 1 = tinta, 0 = papel."""
    if opts.ink == "min":
        gray = rgb.min(axis=2)
    else:
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    invert = opts.invert == "yes" or (opts.invert == "auto" and float(np.median(gray)) < 110.0)
    if invert:
        gray = 255 - gray
    g = gray.astype(np.float32)
    if opts.background:
        g = g / _paper_level(gray)
    else:
        g = g / max(1.0, float(np.percentile(gray, 99)))
    return 1.0 - np.clip(g, 0.0, 1.0)


def _paper_level(gray: np.ndarray) -> np.ndarray:
    """Brilho do papel em cada ponto (float32), para dividir a imagem e achatar sombras/gradientes."""
    h, w = gray.shape
    scale = min(1.0, 384.0 / max(h, w))
    small = cv2.resize(gray, (max(8, round(w * scale)), max(8, round(h * scale))), interpolation=cv2.INTER_AREA)
    k = max(5, (min(small.shape) // 9) | 1)
    closed = cv2.morphologyEx(small, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    closed = cv2.GaussianBlur(closed, (0, 0), k / 2.0)
    bg = cv2.resize(closed, (w, h), interpolation=cv2.INTER_LINEAR).astype(np.float32)
    # Área preenchida maior que o kernel faria o "papel" local ficar escuro e a tinta sumir: piso global.
    floor = 0.55 * float(np.percentile(gray, 97))
    return np.maximum(bg, max(1.0, floor))


def binarize(dark: np.ndarray, opts: RasterOptions) -> tuple[np.ndarray, np.ndarray, float]:
    """(máscara, miolo, limiar): máscaras uint8 0/1.

    A máscara usa histerese (pixel fraco só entra se estiver ligado a um forte) e define a topologia: não
    perde a ponta clara de um traço. O miolo é só o que passa do limiar forte e serve para medir a largura,
    senão a franja de antisserrilhado engordaria todo traço (e trecho apagado sai fino, como deve).
    """
    d8 = np.clip(dark * 255.0 + 0.5, 0, 255).astype(np.uint8)
    if opts.threshold is None:
        otsu, _ = cv2.threshold(d8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        t_high = float(min(0.85, max(0.16, otsu / 255.0)))
    else:
        t_high = opts.threshold
    strong = d8 > round(t_high * 255)
    weak = (d8 > round(t_high * opts.hysteresis * 255)).astype(np.uint8)
    n, labels = cv2.connectedComponents(weak, connectivity=8)
    if n <= 1:
        return np.zeros_like(d8), np.zeros_like(d8), t_high
    keep = np.zeros(n, dtype=bool)
    keep[np.unique(labels[strong])] = True
    keep[0] = False
    return keep[labels].astype(np.uint8), strong.astype(np.uint8), t_high


def clean(mask: np.ndarray, min_speck_px: float | None = None) -> np.ndarray:
    """Tira sujeira (componentes minúsculos) e fecha furinhos dentro do traço."""
    h, w = mask.shape
    area_min = float(min_speck_px) if min_speck_px is not None else max(4.0, 2.5e-6 * h * w)
    out = mask.copy()
    n, labels, stats, _ = cv2.connectedComponentsWithStats(out, connectivity=8)
    if n > 1:
        small = stats[:, cv2.CC_STAT_AREA] < area_min
        small[0] = False
        if small.any():
            out[small[labels]] = 0
    inv = (1 - out).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(inv, connectivity=4)
    if n > 1:
        hole = stats[:, cv2.CC_STAT_AREA] < area_min
        # o fundo de verdade toca a borda; furo é o que não toca
        border = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
        hole[border] = False
        if hole.any():
            out[hole[labels]] = 1
    return out


def typical_stroke_px(mask: np.ndarray, dt: np.ndarray | None = None) -> float:
    """Largura típica do traço em px (0 se a máscara estiver vazia)."""
    if dt is None:
        dt = cv2.distanceTransform(mask, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    vals = dt[mask > 0]
    if vals.size == 0:
        return 0.0
    # perfil triangular: a média da distância dentro de um traço de W pixels é ~(W + 2) / 4
    return max(1.0, 4.0 * float(vals.mean()) - 2.0)

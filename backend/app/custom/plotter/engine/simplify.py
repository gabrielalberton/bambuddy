"""Reamostragem, suavização e simplificação de polilinhas com atributo (largura / profundidade)."""

from __future__ import annotations

import numpy as np


def cumulative_length(pts: np.ndarray) -> np.ndarray:
    if len(pts) < 2:
        return np.zeros(len(pts), dtype=np.float64)
    d = np.diff(pts[:, :2].astype(np.float64), axis=0)
    return np.concatenate([[0.0], np.cumsum(np.hypot(d[:, 0], d[:, 1]))])


def resample(pts: np.ndarray, vals: np.ndarray, step: float, closed: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """Pontos igualmente espaçados (≈ ``step``) ao longo da polilinha; ``vals`` interpolado junto."""
    if len(pts) < 2:
        return pts.astype(np.float64), vals.astype(np.float64)
    if closed:
        pts = np.concatenate([pts, pts[:1]])
        vals = np.concatenate([vals, vals[:1]])
    s = cumulative_length(pts)
    total = float(s[-1])
    if total < 1e-9:
        return pts[:1].astype(np.float64), vals[:1].astype(np.float64)
    n = max(2, int(round(total / step)) + 1)
    t = np.linspace(0.0, total, n)
    out = np.stack([np.interp(t, s, pts[:, 0]), np.interp(t, s, pts[:, 1])], axis=1)
    v = np.interp(t, s, vals)
    if closed:
        out, v = out[:-1], v[:-1]
    return out, v


def gaussian_smooth(v: np.ndarray, sigma: float, closed: bool = False, pin_ends: bool = True) -> np.ndarray:
    """Suaviza uma sequência. ``pin_ends``: reflexão ímpar, a ponta fica exatamente onde estava."""
    n = len(v)
    if sigma <= 0 or n < 3:
        return v
    r = max(1, int(3.0 * sigma + 0.5))
    x = np.arange(-r, r + 1, dtype=np.float64)
    k = np.exp(-0.5 * (x / sigma) ** 2)
    k /= k.sum()
    if closed:
        padded = np.pad(v, r, mode="wrap")
    elif pin_ends:
        padded = np.pad(v, r, mode="reflect", reflect_type="odd")
    else:
        padded = np.pad(v, r, mode="reflect")
    return np.convolve(padded, k, mode="valid")


def rdp_indices(points: np.ndarray, eps: float) -> np.ndarray:
    """Ramer-Douglas-Peucker em N dimensões; devolve os índices que ficam."""
    n = len(points)
    if n <= 2 or eps <= 0:
        return np.arange(n)
    pts = points.astype(np.float64)
    keep = np.zeros(n, dtype=bool)
    keep[0] = keep[-1] = True
    eps2 = eps * eps
    stack = [(0, n - 1)]
    while stack:
        i0, i1 = stack.pop()
        if i1 - i0 < 2:
            continue
        a = pts[i0]
        seg = pts[i1] - a
        rel = pts[i0 + 1 : i1] - a
        seg2 = float(seg @ seg)
        if seg2 < 1e-18:
            d2 = (rel * rel).sum(axis=1)
        else:
            t = np.clip(rel @ seg / seg2, 0.0, 1.0)
            diff = rel - t[:, None] * seg
            d2 = (diff * diff).sum(axis=1)
        k = int(np.argmax(d2))
        if d2[k] > eps2:
            m = i0 + 1 + k
            keep[m] = True
            stack.append((i0, m))
            stack.append((m, i1))
    return np.nonzero(keep)[0]


def simplify_xyv(pts: np.ndarray, eps_xy: float, eps_v: float, closed: bool = False) -> np.ndarray:
    """Simplifica pontos (x, y, v): erro máximo ``eps_xy`` no plano e ``eps_v`` no atributo."""
    if len(pts) <= 2:
        return pts
    work = pts.astype(np.float64).copy()
    if closed:
        work = np.concatenate([work, work[:1]])
    scaled = work.copy()
    scaled[:, 2] *= eps_xy / max(eps_v, 1e-9)
    idx = rdp_indices(scaled, eps_xy)
    out = work[idx]
    if closed:
        out = out[:-1]
        if len(out) < 3:  # laço que virou segmento: devolve aberto, quem chama decide
            return out
    return out

"""Afinamento (esqueleto de 1 px) e transformada de distância.

Sem ``cv2.ximgproc`` nem scikit-image na imagem de produção: o afinamento Guo-Hall é feito aqui com uma
tabela de 256 entradas (código dos 8 vizinhos) aplicada por ``cv2.filter2D`` + ``cv2.LUT``, que é rápido o
bastante mesmo em 4 MP.

Depois do Guo-Hall sobra "escada" (pixels redundantes em cantos); uma passada extra remove todo ponto
simples que não é ponta, em 4 subcampos (nunca dois vizinhos ao mesmo tempo, então a topologia se mantém).
O resultado é um esqueleto em que grau de vizinhança = grau no grafo, que é o que ``graph.py`` assume.
"""

from __future__ import annotations

import cv2
import numpy as np

# Bit de cada vizinho, no sentido horário a partir do norte: N NE E SE S SW W NW
_KERNEL = np.array([[128, 1, 2], [64, 0, 4], [32, 16, 8]], dtype=np.float32)
# vizinhança-8 entre posições do anel (consecutivas + os pares de vizinhos-4 em diagonal entre si)
_RING_8 = [(i, (i + 1) % 8) for i in range(8)] + [(0, 2), (2, 4), (4, 6), (6, 0)]
_RING_4 = [(i, (i + 1) % 8) for i in range(8)]


def _bits(code: int) -> list[int]:
    return [(code >> b) & 1 for b in range(8)]


def _components(members: list[int], adjacency: list[tuple[int, int]]) -> list[set[int]]:
    parent = {m: m for m in members}

    def find(a: int) -> int:
        while parent[a] != a:
            a = parent[a]
        return a

    for a, b in adjacency:
        if a in parent and b in parent:
            parent[find(a)] = find(b)
    groups: dict[int, set[int]] = {}
    for m in members:
        groups.setdefault(find(m), set()).add(m)
    return list(groups.values())


def _guo_hall_luts() -> np.ndarray:
    luts = np.zeros((2, 256), dtype=np.uint8)
    for code in range(256):
        p2, p3, p4, p5, p6, p7, p8, p9 = _bits(code)
        c = (
            int((not p2) and (p3 or p4))
            + int((not p4) and (p5 or p6))
            + int((not p6) and (p7 or p8))
            + int((not p8) and (p9 or p2))
        )
        n1 = int(p9 or p2) + int(p3 or p4) + int(p5 or p6) + int(p7 or p8)
        n2 = int(p2 or p3) + int(p4 or p5) + int(p6 or p7) + int(p8 or p9)
        if c == 1 and 2 <= min(n1, n2) <= 3:
            if not ((p6 or p7 or (not p9)) and p8):
                luts[0, code] = 1
            if not ((p2 or p3 or (not p5)) and p4):
                luts[1, code] = 1
    return luts


def _redundant_lut() -> np.ndarray:
    """1 onde o pixel central é ponto simples (conectividade 8 no traço, 4 no fundo) e não é ponta."""
    lut = np.zeros(256, dtype=np.uint8)
    for code in range(256):
        bits = _bits(code)
        fg = [i for i in range(8) if bits[i]]
        bg = [i for i in range(8) if not bits[i]]
        if len(fg) < 2:
            continue  # ponta ou pixel isolado: fica
        if len(_components(fg, _RING_8)) != 1:
            continue
        touching = [comp for comp in _components(bg, _RING_4) if comp & {0, 2, 4, 6}]
        if len(touching) == 1:
            lut[code] = 1
    return lut


_GUO_HALL = _guo_hall_luts()
_REDUNDANT = _redundant_lut()


def neighbor_code(img: np.ndarray) -> np.ndarray:
    return cv2.filter2D(img, -1, _KERNEL, borderType=cv2.BORDER_CONSTANT)


def thin(mask: np.ndarray, max_iterations: int = 4000) -> np.ndarray:
    """Máscara 0/1 -> esqueleto 0/1 de 1 px, mesma forma."""
    out = np.zeros_like(mask, dtype=np.uint8)
    ys, xs = np.nonzero(mask)
    if ys.size == 0:
        return out
    y0, y1, x0, x1 = int(ys.min()), int(ys.max()) + 1, int(xs.min()), int(xs.max()) + 1
    img = np.ascontiguousarray((mask[y0:y1, x0:x1] > 0).astype(np.uint8))
    for _ in range(max_iterations):
        changed = False
        for lut in _GUO_HALL:
            drop = cv2.LUT(neighbor_code(img), lut)
            drop &= img
            if cv2.countNonZero(drop):
                img ^= drop
                changed = True
        if not changed:
            break
    _remove_redundant(img)
    out[y0:y1, x0:x1] = img
    return out


def _remove_redundant(img: np.ndarray) -> None:
    for _ in range(8):
        changed = False
        for ry in (0, 1):
            for rx in (0, 1):
                drop = cv2.LUT(neighbor_code(img), _REDUNDANT)
                drop &= img
                sub = drop[ry::2, rx::2]
                if cv2.countNonZero(sub):
                    img[ry::2, rx::2] ^= sub
                    changed = True
        if not changed:
            return


def distance(mask: np.ndarray) -> np.ndarray:
    """Distância (px, float32) de cada pixel de traço até o fundo mais próximo."""
    return cv2.distanceTransform((mask > 0).astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE)


def width_from_distance(dt: np.ndarray | float) -> np.ndarray | float:
    """Largura do traço (px) a partir da distância no eixo: 2·d − 0,5 (correção do centro em pixel par/ímpar)."""
    return np.maximum(1.0, 2.0 * dt - 0.5) if isinstance(dt, np.ndarray) else max(1.0, 2.0 * dt - 0.5)

"""Fonte de traço único para os números impressos nos testes (0-9, vírgula, ponto, sinal e espaço).

Desenho no estilo de display de 7 segmentos: poucas descidas da caneta e legível com traço de 0,3 mm a
3 mm de altura. Unidades da fonte: altura 1, dígito com 0,6 de largura, Y para o fundo da mesa (lido de
frente para a impressora).
"""

from __future__ import annotations

import numpy as np

_W = 0.6
_GAP = 0.3
GLYPHS: dict[str, list[list[tuple[float, float]]]] = {
    "0": [[(0, 0), (_W, 0), (_W, 1), (0, 1), (0, 0)]],
    "1": [[(0.1, 0.8), (0.3, 1), (0.3, 0)]],
    "2": [[(0, 1), (_W, 1), (_W, 0.5), (0, 0.5), (0, 0), (_W, 0)]],
    "3": [[(0, 1), (_W, 1), (_W, 0), (0, 0)], [(0.1, 0.5), (_W, 0.5)]],
    "4": [[(0, 1), (0, 0.5), (_W, 0.5)], [(_W, 1), (_W, 0)]],
    "5": [[(_W, 1), (0, 1), (0, 0.5), (_W, 0.5), (_W, 0), (0, 0)]],
    "6": [[(_W, 1), (0, 1), (0, 0), (_W, 0), (_W, 0.5), (0, 0.5)]],
    "7": [[(0, 1), (_W, 1), (0.2, 0)]],
    "8": [[(0, 0.5), (0, 0), (_W, 0), (_W, 1), (0, 1), (0, 0.5), (_W, 0.5)]],
    "9": [[(_W, 0.5), (0, 0.5), (0, 1), (_W, 1), (_W, 0), (0, 0)]],
    ",": [[(0.1, 0.15), (0.1, 0), (0, -0.2)]],
    ".": [[(0.05, 0), (0.05, 0.1)]],
    "-": [[(0, 0.5), (0.4, 0.5)]],
    " ": [],
}
_ADVANCE = {",": 0.1 + _GAP, ".": 0.1 + _GAP, "-": 0.4 + _GAP, " ": _W}


def number(value: float) -> str:
    """0,35 / 1 / 0,05: vírgula decimal e sem zeros sobrando."""
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return ("0" if text in ("-0", "") else text).replace(".", ",")


def _advance(char: str) -> float:
    return _ADVANCE.get(char, _W + _GAP)


def width(text: str, height: float) -> float:
    if not text:
        return 0.0
    return (sum(_advance(c) for c in text) - _GAP) * height


def polylines(text: str, x: float, y: float, height: float, align: str = "left") -> list[np.ndarray]:
    """Traços (N x 2, mm da mesa) do texto com a linha de base em ``y``; ``align`` = left, right ou center."""
    if any(c not in GLYPHS for c in text):
        raise ValueError(f"caractere sem desenho na fonte: {text!r}")
    total = width(text, height)
    cursor = x - (total if align == "right" else total / 2.0 if align == "center" else 0.0)
    out: list[np.ndarray] = []
    for char in text:
        for line in GLYPHS[char]:
            pts = np.array(line, dtype=np.float64) * height
            out.append(pts + (cursor, y))
        cursor += _advance(char) * height
    return out

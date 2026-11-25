"""Modelo do desenho vetorizado: traços com largura em cada ponto.

Um traço é uma polilinha de pontos (x, y, largura). Entre dois pontos tudo varia linearmente, que é
exatamente o que o G-code faz (``G1 X Y Z``). Um traço de um ponto só é um "ponto" (toque da caneta).
As unidades são as da imagem de origem (px); a conversão para mm acontece no posicionamento.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class Stroke:
    pts: np.ndarray  # (n, 3) float32: x, y, largura
    closed: bool = False

    @property
    def is_dot(self) -> bool:
        return len(self.pts) == 1

    def length(self) -> float:
        if len(self.pts) < 2:
            return 0.0
        d = np.diff(self.pts[:, :2], axis=0)
        total = float(np.hypot(d[:, 0], d[:, 1]).sum())
        if self.closed:
            total += float(np.hypot(*(self.pts[0, :2] - self.pts[-1, :2])))
        return total

    def path(self) -> np.ndarray:
        """Pontos na ordem de desenho; traço fechado repete o primeiro ponto no fim."""
        if self.closed and len(self.pts) > 1:
            return np.concatenate([self.pts, self.pts[:1]])
        return self.pts


@dataclass
class Drawing:
    width: float
    height: float
    strokes: list[Stroke] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    def stats(self) -> dict:
        n_pts = sum(len(s.pts) for s in self.strokes)
        widths = np.concatenate([s.pts[:, 2] for s in self.strokes]) if self.strokes else np.zeros(0)
        return {
            "strokes": len(self.strokes),
            "dots": sum(1 for s in self.strokes if s.is_dot),
            "points": n_pts,
            "length": round(sum(s.length() for s in self.strokes), 1),
            "width_min": round(float(widths.min()), 2) if widths.size else 0.0,
            "width_max": round(float(widths.max()), 2) if widths.size else 0.0,
            "width_p05": round(float(np.percentile(widths, 5)), 2) if widths.size else 0.0,
            "width_p50": round(float(np.percentile(widths, 50)), 2) if widths.size else 0.0,
            "width_p95": round(float(np.percentile(widths, 95)), 2) if widths.size else 0.0,
        }

    def bounds(self) -> tuple[float, float, float, float] | None:
        """(x0, y0, x1, y1) da tinta, contando a largura do traço."""
        if not self.strokes:
            return None
        allp = np.concatenate([s.pts for s in self.strokes])
        half = allp[:, 2] * 0.5
        return (
            float((allp[:, 0] - half).min()),
            float((allp[:, 1] - half).min()),
            float((allp[:, 0] + half).max()),
            float((allp[:, 1] + half).max()),
        )

    def to_json(self) -> dict:
        return {
            "width": self.width,
            "height": self.height,
            "strokes": [
                {"p": np.round(s.pts.astype(np.float64), 2).reshape(-1).tolist(), "c": 1 if s.closed else 0}
                for s in self.strokes
            ],
            "meta": self.meta,
        }

    @classmethod
    def from_json(cls, data: dict) -> Drawing:
        strokes = []
        for item in data.get("strokes", []):
            flat = np.asarray(item.get("p", []), dtype=np.float32)
            if flat.size < 3 or flat.size % 3:
                continue
            strokes.append(Stroke(flat.reshape(-1, 3), bool(item.get("c"))))
        return cls(float(data["width"]), float(data["height"]), strokes, dict(data.get("meta") or {}))

"""Imagens sintéticas para os testes do plotter (traço preto em fundo branco, RGB uint8)."""

from __future__ import annotations

import cv2
import numpy as np


def canvas(h: int = 600, w: int = 600) -> np.ndarray:
    return np.full((h, w), 255, np.uint8)


def rgb(gray: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)


def cross(angle_px: int = 250) -> np.ndarray:
    a = canvas()
    cv2.line(a, (50, 300), (550, 300), 0, 11, cv2.LINE_AA)
    cv2.line(a, (300, 300 - angle_px), (300, 300 + angle_px), 0, 11, cv2.LINE_AA)
    return rgb(a)


def tee() -> np.ndarray:
    a = canvas()
    cv2.line(a, (50, 100), (550, 100), 0, 11, cv2.LINE_AA)
    cv2.line(a, (300, 100), (300, 500), 0, 11, cv2.LINE_AA)
    return rgb(a)


def wedge() -> np.ndarray:
    """Um traço só, em senoide, com a largura indo de ~3 a ~29 px e voltando."""
    a = canvas(500, 900)
    for t in np.linspace(0, 1, 900):
        x = 60 + 780 * t
        y = 250 + 120 * np.sin(t * 2 * np.pi * 1.5)
        r = 1.5 + 13 * abs(np.sin(t * np.pi * 2))
        cv2.circle(a, (int(x), int(y)), int(round(r)), 0, -1, cv2.LINE_AA)
    return rgb(a)


def circle_and_dots() -> np.ndarray:
    a = canvas()
    cv2.circle(a, (300, 300), 150, 0, 9, cv2.LINE_AA)
    cv2.circle(a, (300, 300), 8, 0, -1, cv2.LINE_AA)
    cv2.circle(a, (100, 80), 4, 0, -1, cv2.LINE_AA)
    return rgb(a)


def png_bytes(image: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", cv2.cvtColor(image, cv2.COLOR_RGB2BGR))
    assert ok
    return buf.tobytes()

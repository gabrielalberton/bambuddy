"""G-codes reais do Gabriel (fora do git). Sem eles, os testes que dependem deles são pulados."""

import os
import pathlib

import pytest

REPO = pathlib.Path(os.environ.get("TWIN_GCODE_REPO", "/home/gabriel/projects/3d-printing"))
FILES = {
    "stackmatrix": REPO / "work/kromacut/stackmatrix/final/stack-matrix-256.a1.gcode.3mf",
    "teste1024": REPO / "work/kromacut/teste1024/teste1024.a1.gcode.3mf",
    "fit_coupon": REPO / "work/print3d/fit_coupon/slice/fit_coupon.gcode.3mf",
    "earth": REPO / "work/ditherforge/earth-experimentos/earth-saida-scripts/earth.a1.gcode.3mf",
}


def need(name):
    p = FILES[name]
    if not p.exists():
        pytest.skip(f"{p} ausente (G-codes reais não são versionados)")
    return p

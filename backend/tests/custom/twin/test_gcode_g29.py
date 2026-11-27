"""G29 e esperas medidos na A1 real (micro 2026-11-26, vídeo em tela cheia)."""

import numpy as np

from backend.app.custom.twin.gcode import interpret


def test_g29_probes_7x7_grid_16mm_inside_the_area():
    prog = interpret(["G90", "G29 A1 X3.99999 Y4 I248 J248", "M400"])
    x, y, z = (np.frombuffer(a, dtype="f4") for a in (prog.x, prog.y, prog.z))
    touch = z == 0.0
    cols = sorted({round(float(v), 1) for v in x[touch]})
    rows = sorted({round(float(v), 1) for v in y[touch]})
    assert len(cols) == 7 and len(rows) == 7
    assert cols[0] == 20.0 and cols[-1] == 236.0  # 4 + 16 e 4 + 248 - 16
    assert 35.5 < cols[1] - cols[0] < 36.5  # passo ~36 mm medido


def test_g29_serpentine_alternates_direction():
    prog = interpret(["G90", "G29 A1 X4 Y4 I248 J248"])
    x, y, z = (np.frombuffer(a, dtype="f4") for a in (prog.x, prog.y, prog.z))
    points = [(float(a), float(b)) for a, b, c in zip(x, y, z, strict=True) if c == 0.0]
    points = [p for i, p in enumerate(points) if i == 0 or p != points[i - 1]]  # a espera repete o registro
    first_row, second_row = [p[0] for p in points[:7]], [p[0] for p in points[7:14]]
    assert first_row == sorted(first_row) and second_row == sorted(second_row, reverse=True)

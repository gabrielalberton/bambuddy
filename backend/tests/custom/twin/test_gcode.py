"""Parser/planejador contra G-code real: tempo previsto vs. estimativa do fatiador (cabeçalho e linhas M73 R)."""

import functools

import numpy as np
import pytest

from backend.app.custom.twin import gcode
from backend.tests.custom.twin.conftest import need


@functools.cache
def prog_of(name):
    return gcode.interpret(gcode.open_plate_lines(str(need(name))))


def slicer_curve(p):
    m = [e for e in p.events if e.kind == "m73"]
    r0 = m[0].b
    return [(e.t, (r0 - e.b) * 60.0) for e in m]


# O fatiador soma os blocos condicionais (calibração de extrusão, nivelamento) que o firmware pula quando as flags valem 0; por isso o planejador fica alguns % abaixo.
@pytest.mark.parametrize("name,tol", [("stackmatrix", 0.07), ("teste1024", 0.10), ("fit_coupon", 0.12)])
def test_total_time_vs_slicer_header(name, tol):
    p = prog_of(name)
    est = p.meta["header_total_time_s"]
    err = (p.total_time - est) / est
    print(f"{name}: planejador {p.total_time / 60:.1f} min vs fatiador {est / 60:.1f} min ({err:+.1%})")
    assert abs(err) < tol


@pytest.mark.parametrize("name", ["stackmatrix", "teste1024"])
def test_m73_timeline_tracks_slicer(name):
    """Ao longo do arquivo, o tempo do planejador nas linhas `M73 P R` fica a ~1 min (< 3%) da curva do próprio fatiador."""
    p = prog_of(name)
    # a pré-impressão (aquecimento/calibrações condicionais) o fatiador estima à parte; compara a partir da 1ª camada
    t1 = p.layers[0]["t"]
    curve = [(m, s) for m, s in slicer_curve(p) if m >= t1]
    off0 = curve[0][0] - curve[0][1]
    worst = max(abs((mine - sl) - off0) for mine, sl in curve)
    print(f"{name}: desvio máximo do planejador vs. curva M73 do fatiador após a 1ª camada: {worst:.0f} s")
    assert worst < 0.03 * p.meta["header_total_time_s"] + 45


def test_monotonic_and_sane():
    p = prog_of("stackmatrix")
    t = np.frombuffer(p.t, dtype="f8")
    assert np.all(np.diff(t) >= -1e-9)
    x, y, z = (np.frombuffer(a, dtype="f4") for a in (p.x, p.y, p.z))
    assert x.min() > -60 and x.max() < 280 and y.min() > -10 and y.max() < 275 and z.min() >= -0.5 and z.max() < 300
    # 11 camadas, 30 trocas de AMS (+ a inicial)
    assert len(p.layers) == 11 and p.meta["total_layers"] == 11
    assert sum(1 for e in p.events if e.kind == "tool") == 31


def test_events_have_anchors():
    p = prog_of("stackmatrix")
    kinds = {e.kind for e in p.events}
    assert {"m73", "layer", "claim", "tool", "hold", "layer_start", "temp"} <= kinds
    m = [e for e in p.events if e.kind == "m73"]
    assert m[0].a == 0 and m[-1].a == 100


@pytest.mark.slow
def test_earth_stress():
    import resource
    import time

    t0 = time.time()
    p = gcode.interpret(gcode.open_plate_lines(str(need("earth"))))
    dt = time.time() - t0
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
    print(
        f"earth: {len(p.t)} registros, {dt:.1f}s, rss {rss} MB, total {p.total_time / 3600:.2f} h vs {p.meta['header_total_time_s'] / 3600:.2f} h"
    )
    assert abs(p.total_time - p.meta["header_total_time_s"]) / p.meta["header_total_time_s"] < 0.03
    assert rss < 600

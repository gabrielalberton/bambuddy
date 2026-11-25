"""custom(plotter): os dois modos do suporte, com mola e sem mola (caneta travada)."""

import numpy as np
import pytest

from backend.app.custom.plotter import engine as E
from backend.app.custom.plotter.engine import plan as PL
from backend.app.custom.plotter.engine.strokes import Drawing, Stroke


def rigid(**over):
    base = {"mount": "rigid", "z_contact": 4.0, "table": [[0.05, 0.4], [0.2, 0.9], [0.4, 1.6]]}
    return E.PenProfile.from_dict({**base, **over})


def spring(**over):
    base = {"z_contact": 4.0, "table": [[0.1, 0.3], [0.6, 0.8], [1.2, 1.6]]}
    return E.PenProfile.from_dict({**base, **over})


def wavy_drawing():
    """Traço de 100 px cuja largura salta de fino para grosso no meio (pede mudança brusca de aperto)."""
    xs = np.linspace(10, 90, 41)
    widths = np.where(xs < 50, 1.0, 12.0)
    pts = np.stack([xs, np.full_like(xs, 50.0), widths], axis=1).astype(np.float32)
    return Drawing(100.0, 100.0, [Stroke(pts)])


def code_lines(text):
    """Comandos sem comentário e sem as linhas de progresso (M73), que se intercalam entre os movimentos."""
    out = [ln.split(";", 1)[0].strip() for ln in text.splitlines()]
    return [ln for ln in out if ln and not ln.startswith("M73")]


def test_perfil_antigo_sem_modo_e_com_mola():
    pen = E.PenProfile.from_dict({"z_contact": 4.0})
    assert pen.mount == "spring" and pen.max_compression == 3.0 and pen.depth_max == 1.2


def test_perfil_novo_de_cada_modo_vem_com_os_valores_do_modo():
    r = E.PenProfile.from_dict({"mount": "rigid"})
    assert (r.depth_min, r.depth_max, r.max_compression, r.z_speed) == (0.05, 0.4, 0.6, 5.0)
    assert r.name == "Caneta sem mola" and r.use_mesh
    s = E.PenProfile.for_mount("spring")
    assert (s.depth_min, s.depth_max, s.max_compression) == (0.2, 1.2, 3.0)


def test_sem_mola_limita_o_aperto_e_obriga_a_malha():
    with pytest.raises(E.ProfileError, match="max_compression"):
        E.PenProfile.from_dict({"mount": "rigid", "max_compression": 2.5})
    with pytest.raises(E.ProfileError, match="depth_max"):
        E.PenProfile.from_dict({"mount": "rigid", "depth_max": 2.2, "max_compression": 2.0})
    assert E.PenProfile.from_dict({"mount": "rigid", "use_mesh": False}).use_mesh is True
    assert E.PenProfile.from_dict({"use_mesh": False}).use_mesh is False  # com mola continua opcional
    with pytest.raises(E.ProfileError, match="mount"):
        E.PenProfile.from_dict({"mount": "elastico"})


def test_escala_de_pressao_sem_mola_tem_passos_finos():
    assert E.calibration.default_ladder_depths(rigid()) == [0.0, 0.05, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5]
    spring_steps = E.calibration.default_ladder_depths(spring())
    assert spring_steps[0] == 0.0 and spring_steps[-1] == 1.5 and min(np.diff(spring_steps)) >= 0.1 - 1e-9


def test_sem_mola_suaviza_mais_a_mudanca_de_aperto():
    paper, place = E.Paper(), E.Placement(cx=128, cy=110, width=100)
    opts = E.PlanOptions(pressure="variable", width_mode="fit")
    slopes = {}
    for name, pen in (("spring", spring()), ("rigid", rigid())):
        planned = PL.build_paths(wavy_drawing(), place, paper, pen, E.A1, opts)
        pts = planned.paths[0].pts
        seg = np.hypot(np.diff(pts[:, 0]), np.diff(pts[:, 1]))
        slopes[name] = float(np.max(np.abs(np.diff(pts[:, 2])) / np.maximum(seg, 1e-9)))
    assert slopes["rigid"] <= E.MOUNTS["rigid"].max_slope + 1e-6
    assert slopes["spring"] <= E.MOUNTS["spring"].max_slope + 1e-6


def test_sem_mola_desce_rapido_ate_perto_do_papel_e_encosta_devagar():
    pen = rigid()
    paths, _ = E.calibration.frame(E.drawable_area(E.A1, pen, E.Paper()), pen)
    res = E.build_gcode(paths, pen, E.Paper(), E.A1)
    lines = code_lines(res.text)
    assert "; pen_mount = rigid" in res.text
    i = lines.index("G1 Z4.3 F300")  # contato 4.0 + 0.3 de folga, na velocidade de Z do perfil (5 mm/s)
    nxt = lines[i + 1].split()  # 2 mm/s da folga até o aperto (abaixo do contato)
    assert nxt[0] == "G1" and float(nxt[1][1:]) < 4.0 and nxt[2] == "F120"
    assert "G29.2 S1" in lines
    assert E.validate(res.text, E.A1, pen, E.Paper()).ok


def test_com_mola_desce_direto():
    pen = spring()
    paths, _ = E.calibration.frame(E.drawable_area(E.A1, pen, E.Paper()), pen)
    lines = code_lines(E.build_gcode(paths, pen, E.Paper(), E.A1).text)
    downs = [ln for ln in lines if ln.startswith("G1 Z3.") and "X" not in ln]
    assert downs and all(ln.endswith("F600") for ln in downs)


@pytest.mark.parametrize(
    "old,new,code",
    [
        ("G29.2 S1", "G29.2 S0", "mesh_required"),
        (" F120\n", " F300\n", "fast_contact"),
    ],
)
def test_validador_recusa_gcode_sem_mola_adulterado(old, new, code):
    pen = rigid()
    paths, _ = E.calibration.frame(E.drawable_area(E.A1, pen, E.Paper()), pen)
    text = E.build_gcode(paths, pen, E.Paper(), E.A1).text
    assert old in text
    report = E.validate(text.replace(old, new), E.A1, pen, E.Paper())
    assert not report.ok and code in {e["code"] for e in report.errors}


def test_plano_sem_mola_avisa_da_folha_plana():
    plot = E.make_plot(wavy_drawing(), E.Placement(cx=128, cy=110, width=100), E.Paper(), rigid())
    assert plot.ok and "rigid_flatness" in {i.code for i in plot.issues}
    plot = E.make_plot(wavy_drawing(), E.Placement(cx=128, cy=110, width=100), E.Paper(), spring())
    assert "rigid_flatness" not in {i.code for i in plot.issues}


def test_escala_de_pressao_sem_mola_tambem_avisa_da_folha_plana():
    pen = rigid()
    paths, _ = E.calibration.pressure_ladder(E.drawable_area(E.A1, pen, E.Paper()), pen)
    plot = E.plot_paths(paths, pen, E.Paper())
    assert plot.ok and [i.code for i in plot.issues] == ["rigid_flatness"]

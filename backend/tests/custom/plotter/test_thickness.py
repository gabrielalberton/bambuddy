"""custom(plotter): tipos de caneta (BIC é o padrão) e os três testes de espessura com números impressos."""

import numpy as np
import pytest

from backend.app.custom.plotter import engine as E, store
from backend.app.custom.plotter.engine import font


def calibrated(mount="spring", pen_type="bic", **over):
    return E.PenProfile.from_dict({"mount": mount, "pen_type": pen_type, "z_contact": 4.0, **over})


def a4_area(pen):
    return E.drawable_area(E.A1, pen, E.Paper())


# ---------------------------------------------------------------- tipos de caneta
def test_bic_e_a_caneta_padrao_nos_dois_modos():
    doc = store.default_settings()
    assert {p["pen_type"] for p in doc["pens"].values()} == {"bic"}
    spring = E.PenProfile.from_dict(doc["pens"]["padrao"])
    rigid = E.PenProfile.from_dict(doc["pens"]["sem-mola"])
    assert spring.name == "Caneta BIC com mola" and rigid.name == "Caneta BIC sem mola"
    # esferográfica precisa de força com mola; travada, a ponta dura aguenta pouco
    assert (spring.depth_min, spring.depth_max, spring.max_compression) == (1.4, 2.5, 3.0)
    assert (rigid.depth_min, rigid.depth_max, rigid.max_compression) == (0.05, 0.2, 0.3)
    assert spring.line_width == rigid.line_width == 0.4


@pytest.mark.parametrize("mount", ["spring", "rigid"])
def test_todo_tipo_de_caneta_cabe_nos_limites_do_modo(mount):
    spec = E.MOUNTS[mount]
    for key, pen_type in E.PEN_TYPES.items():
        pen = E.PenProfile.for_mount(mount, key)
        assert pen.pen_type == key and pen.mount == mount
        assert 0 <= pen.depth_min < pen.depth_max <= pen.max_compression <= spec.compression_limit
        assert pen.depth_max <= spec.depth_limit
        assert E.PenProfile.from_dict(pen.to_dict()) == pen  # passa na validação
        info = E.pen_type_info(pen_type)
        assert info["defaults"][mount]["max_compression"] == pen.max_compression


def test_tipo_desconhecido_e_recusado_e_perfil_antigo_vira_generico():
    with pytest.raises(E.ProfileError, match="pen_type"):
        E.PenProfile.from_dict({"pen_type": "giz"})
    old = E.PenProfile.from_dict({"z_contact": 4.0})  # gravado antes dos tipos: valores genéricos
    assert old.pen_type == "outra" and (old.depth_min, old.depth_max) == (0.2, 1.2)


# ---------------------------------------------------------------- fonte
def test_numeros_saem_com_virgula_e_alinhados_a_direita():
    assert [font.number(v) for v in (0.0, 0.35, 1.0, 0.05, 1.25)] == ["0", "0,35", "1", "0,05", "1,25"]
    lines = font.polylines("0,35", 50.0, 10.0, 2.5, "right")
    xs = np.concatenate([ln[:, 0] for ln in lines])
    ys = np.concatenate([ln[:, 1] for ln in lines])
    assert xs.max() == pytest.approx(50.0) and xs.min() == pytest.approx(50.0 - font.width("0,35", 2.5))
    assert ys.max() == pytest.approx(12.5) and ys.min() < 10.0  # a vírgula desce abaixo da linha de base
    with pytest.raises(ValueError):
        font.polylines("mm", 0, 0, 2.5)


# ---------------------------------------------------------------- teste 2: pente


# ---------------------------------------------------------------- teste de altura (Z 5 -> 8 mm)
def sweep(pen=None, paper=None, **kw):
    pen = pen or calibrated(z_contact=6.0)
    paper = paper or E.Paper()
    area = E.drawable_area(E.A1, pen, paper)
    touch = E.z_levels(pen, paper, E.A1)["touch"]
    return E.calibration.z_sweep(area, pen, touch, paper.w, **kw), pen, paper


def test_linhas_do_teste_cobrem_2_mm_abaixo_e_acima_do_contato_da_esquerda_para_a_direita():
    (paths, info), pen, paper = sweep()
    touch = info["touch"]
    tests = [q for q in paths if len(q.pts) == 2 and q.pts[0, 2] != q.pts[1, 2]]
    assert len(tests) == 5 and info["rows"] == [round(float(q.pts[0, 1]), 2) for q in tests]
    assert (info["z_from"], info["z_to"]) == (touch - 2.0, touch + 2.0)
    for q in tests:
        assert touch - q.pts[0, 2] == pytest.approx(touch - 2.0) and touch - q.pts[1, 2] == pytest.approx(touch + 2.0)
        assert q.pts[1, 0] - q.pts[0, 0] == pytest.approx(info["length"])
    assert info["length"] == pytest.approx(0.8 * paper.w)
    ids = {id(q) for q in tests}
    order = [id(q) in ids for q in paths]
    assert order == sorted(order)  # régua, verticais e números antes das linhas do teste


def test_verticais_numeradas_marcam_o_z_de_cada_posicao():
    (paths, info), _, _ = sweep()
    marks = {m["z"]: m["x"] for m in info["marks"]}
    assert list(marks) == [4.0, 4.5, 5.0, 5.5, 6.0, 6.5, 7.0, 7.5, 8.0]  # contato em 6: de 4 a 8
    assert marks[4.0] == pytest.approx(info["left"]) and marks[8.0] == pytest.approx(info["left"] + info["length"])
    assert marks[6.0] == pytest.approx(info["left"] + info["length"] / 2.0)
    depths = {round(float(d), 3) for q in paths if not (len(q.pts) == 2 and q.pts[0, 2] != q.pts[1, 2]) for d in q.pts[:, 2]}
    assert len(depths) == 1  # verticais, régua e números saem leves e iguais: só as linhas do teste variam
    assert max(info["rows"]) < info["top"] and info["bottom"] < min(info["rows"])


def test_faixa_acompanha_o_contato_e_pode_ser_escolhida():
    pen = calibrated(z_contact=7.0)
    (_, info), _, _ = sweep(pen)
    assert (info["z_from"], info["z_to"]) == (5.0, 9.0) and info["marks"][0]["z"] == 5.0
    (_, info), _, _ = sweep(pen, z_from=5.0, z_to=8.0)
    assert (info["z_from"], info["z_to"]) == (5.0, 8.0) and [m["z"] for m in info["marks"]][-1] == 8.0


def test_velocidades_alternadas_e_ordem_invertida():
    pen = calibrated(z_contact=6.0)
    (paths, info), _, paper = sweep(pen, lines=6, speeds=[1.0, 0.4])
    tests = [q for q in paths if len(q.pts) == 2 and q.pts[0, 2] != q.pts[1, 2]]
    assert [q.speed for q in tests] == [60.0, 24.0, 60.0, 24.0, 60.0, 24.0] and info["speeds"] == [q.speed for q in tests]
    plot = E.plot_paths(paths, pen, paper)
    assert plot.ok, plot.report.errors
    feeds = {ln.split(" F")[-1] for ln in plot.gcode.splitlines() if ln.startswith("G1 X") and " Z" in ln and " F" in ln}
    assert {"3600", "1440"} <= feeds  # 60 e 24 mm/s
    (paths, info), _, _ = sweep(pen, reverse=True)
    tests = [q for q in paths if len(q.pts) == 2 and q.pts[0, 2] != q.pts[1, 2]]
    assert [round(float(q.pts[0, 1]), 2) for q in tests] == info["rows"][::-1] and info["order"] == [4, 3, 2, 1, 0]
    assert all(q.speed is None for q in tests)


def test_teste_tem_uns_50_mm_de_altura_e_80_por_cento_da_largura_do_papel():
    (paths, info), _, paper = sweep()
    x0, y0, x1, y1 = info["box"]
    assert x1 - x0 == pytest.approx(0.8 * paper.w)
    assert 45.0 <= y1 - y0 <= 55.0


@pytest.mark.parametrize("mount", ["spring", "rigid"])
def test_teste_de_altura_passa_na_validacao_com_o_bico_acima_do_contato(mount):
    pen = calibrated(mount=mount, z_contact=6.0)
    kw = {} if mount == "spring" else {"z_from": 5.8, "z_to": 6.5}  # sem mola o suporte aguenta só 0,6 mm
    (paths, info), pen, paper = sweep(pen, **kw)
    plot = E.plot_paths(paths, pen, paper, title="altura")
    assert plot.ok, plot.report.errors
    assert plot.report.stats["z_max"] >= info["touch"]  # a linha sobe até ficar acima do papel


def test_teste_recusa_aperto_alem_do_suporte_e_papel_pequeno():
    pen = calibrated(z_contact=6.0)
    area = E.drawable_area(E.A1, pen, E.Paper())
    with pytest.raises(E.PlanError, match="limite do suporte"):
        E.calibration.z_sweep(area, pen, 6.0, 210.0, z_from=1.0, z_to=8.0)
    with pytest.raises(E.PlanError):
        E.calibration.z_sweep(area, pen, 6.0, 210.0, z_from=8.0, z_to=5.0)
    with pytest.raises(E.PlanError):
        E.calibration.z_sweep((0, 0, 40, 30), pen, 6.0, 210.0)


def test_bic_vai_mais_rapido_que_antes():
    pen = E.PenProfile.for_mount("spring", "bic")
    assert (pen.draw_speed, pen.travel_speed, pen.z_speed) == (60.0, 200.0, 20.0)


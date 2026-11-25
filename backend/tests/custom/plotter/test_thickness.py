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
    assert (spring.depth_min, spring.depth_max, spring.max_compression) == (0.4, 1.5, 3.0)
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
@pytest.mark.parametrize("mount", ["spring", "rigid"])
def test_pente_tem_uma_celula_por_espacamento_em_cada_aperto(mount):
    pen = calibrated(mount)
    paths, info = E.calibration.spacing_comb(a4_area(pen), pen)
    depths = [r["depth"] for r in info["rows"]]
    assert depths == E.calibration.comb_depths(pen) and depths[0] == pen.depth_min and depths[-1] == pen.depth_max
    spacings = info["spacings"]
    assert len(spacings) == 8 and spacings == sorted(spacings)
    assert spacings[0] <= pen.line_width <= spacings[-1]  # a largura nominal fica dentro do pente
    cells = [q for q in paths if len(q.pts) > 4 and np.ptp(q.pts[:, 2]) == 0 and q.pts[0, 2] in depths]
    cells = [q for q in cells if np.ptp(q.pts[:, 0]) == pytest.approx(E.calibration.COMB_CELL)]
    assert len(cells) == len(depths) * len(spacings)
    first = cells[0]  # linhas da primeira célula ficam a exatamente um espaçamento umas das outras
    ys = sorted(set(np.round(first.pts[:, 1], 4)), reverse=True)
    assert np.allclose(-np.diff(ys), spacings[0])
    plot = E.plot_paths(paths, pen, E.Paper(), title="pente")
    assert plot.ok, plot.report.errors


def test_pente_de_marcador_nao_passa_da_celula():
    pen = calibrated(pen_type="marcador")
    spacings = E.calibration.comb_spacings(pen)
    assert spacings[-1] <= 0.6 * E.calibration.COMB_CELL and spacings[0] < pen.line_width
    with pytest.raises(E.PlanError):
        E.calibration.spacing_comb(a4_area(pen), pen, spacings=[0.3, 6.0])


# ---------------------------------------------------------------- teste 3: cunha com régua
@pytest.mark.parametrize("mount", ["spring", "rigid"])
def test_cunha_vai_subindo_e_volta_descendo_sobre_a_regua(mount):
    pen = calibrated(mount)
    paths, info = E.calibration.ruler_wedge(a4_area(pen), pen)
    top = E.calibration.default_ladder_depths(pen)[-1]
    assert (info["from"], info["to"], info["length"], info["marks"]) == (0.0, top, 100.0, 10)
    forward, back = paths[-2].pts, paths[-1].pts
    assert forward[0, 2] == 0.0 and forward[-1, 2] == top and forward[-1, 0] - forward[0, 0] == 100.0
    # a volta corre da direita para a esquerda com o mesmo aperto da ida em cada ponto da régua
    assert back[0, 0] == forward[-1, 0] and back[0, 2] == top and back[-1, 2] == 0.0
    assert info["return_y"] < info["forward_y"]
    grid = info["grid"]  # a grade numerada é a régua: coluna 0 no começo da ida, 10 no fim
    assert grid["zero_x"] == forward[0, 0] and grid["zero_x"] + grid["pitch"] * info["marks"] == forward[-1, 0]
    plot = E.plot_paths(paths, pen, E.Paper(), title="cunha")
    assert plot.ok, plot.report.errors


def test_cunha_encurta_em_papel_pequeno_e_recusa_o_que_nao_cabe():
    pen = calibrated()
    _, info = E.calibration.ruler_wedge(E.drawable_area(E.A1, pen, E.Paper(w=105, h=148)), pen)
    assert info["length"] == 70.0 and info["marks"] == 7
    with pytest.raises(E.PlanError):
        E.calibration.ruler_wedge((0, 0, 40, 40), pen)
    with pytest.raises(E.PlanError):
        E.calibration.ruler_wedge(a4_area(pen), pen, top_depth=9.0)


def test_layouts_dos_testes_seguem_o_perfil():
    rigid = calibrated("rigid")
    out = E.calibration.thickness_layouts(rigid, a4_area(rigid))
    assert out["ladder"]["depths"] == [0.0, 0.05, 0.1, 0.15, 0.2, 0.3]
    assert out["comb"]["depths"] == [0.05, 0.1, 0.15, 0.2]
    assert out["wedge"] == {"from": 0.0, "to": 0.3, "length": 100.0}
    assert out["wave"] == {"length": 150.0, "from": 0.05, "to": 0.2, "ramps": [5.0, 10.0, 20.0, 40.0]}


# ---------------------------------------------------------------- teste 4: onda e pontas
@pytest.mark.parametrize("mount", ["spring", "rigid"])
def test_onda_varia_do_minimo_ao_maximo_e_as_pontas_somem(mount):
    pen = calibrated(mount)
    paths, info = E.calibration.wave_tapers(a4_area(pen), pen)
    ramps = [t["ramp"] for t in info["tapers"]]
    assert ramps == [5.0, 10.0, 20.0, 40.0] and info["length"] == 150.0
    wave = paths[-1 - len(ramps)].pts
    assert wave[0, 2] == pytest.approx(pen.depth_min) and np.ptp(wave[:, 0]) == pytest.approx(150.0)
    assert wave[:, 2].min() >= pen.depth_min - 1e-9 and wave[:, 2].max() == pytest.approx(pen.depth_max, abs=0.01)
    peaks = np.flatnonzero((wave[1:-1, 2] > wave[:-2, 2]) & (wave[1:-1, 2] >= wave[2:, 2]))
    assert len(peaks) >= 5 and np.diff(wave[peaks + 1, 0])[-1] < np.diff(wave[peaks + 1, 0])[0]  # ondas encurtam
    for taper, ramp in zip(paths[-len(ramps) :], ramps, strict=True):
        pts = taper.pts
        assert pts[0, 2] == 0.0 and pts[-1, 2] == 0.0 and pts[:, 2].max() == pen.depth_max  # some nas duas pontas
        assert pts[1, 0] - pts[0, 0] == ramp and pts[-1, 0] - pts[-2, 0] == ramp
    plot = E.plot_paths(paths, pen, E.Paper(), title="onda")
    assert plot.ok, plot.report.errors


def test_pontas_alongam_para_respeitar_a_variacao_de_aperto_do_modo():
    pen = calibrated(depth_max=3.0, max_compression=3.0)  # 3 mm em 5 mm passaria de 0,6 mm por mm
    ramps = E.calibration.taper_ramps(pen)
    assert ramps[0] >= 3.0 / (0.9 * E.MOUNTS["spring"].max_slope) and ramps[0] % 5 == 0


@pytest.mark.parametrize("make", ["pressure_ladder", "spacing_comb", "ruler_wedge", "wave_tapers"])
@pytest.mark.parametrize("mount", ["spring", "rigid"])
def test_todo_teste_sai_numa_grade_de_10_mm_e_respeita_o_modo(make, mount):
    pen = calibrated(mount, "pincel")
    paths, info = getattr(E.calibration, make)(a4_area(pen), pen)
    grid = info["grid"]
    vertical = paths[0].pts
    xs = sorted(set(np.round(vertical[:, 0], 6)))
    assert len(xs) == grid["cols"] + 1 and np.allclose(np.diff(xs), 10.0)
    assert np.ptp(vertical[:, 1]) == pytest.approx(10.0 * grid["rows"])
    # variação de aperto por mm dentro do limite do modo em todos os traços
    slope = pen.mount_spec.max_slope
    for q in paths:
        seg = np.hypot(*np.diff(q.pts[:, :2], axis=0).T)
        dd = np.abs(np.diff(q.pts[:, 2]))
        assert np.all(dd <= slope * seg + 1e-9)
    box = info["box"]
    for q in paths:  # tudo dentro da caixa informada (grade + números embaixo)
        assert q.pts[:, 0].min() >= box[0] - 1e-6 and q.pts[:, 0].max() <= box[2] + 1e-6
        assert q.pts[:, 1].min() >= box[1] - 0.6 and q.pts[:, 1].max() <= box[3] + 1e-6


def test_celulas_do_pente_nao_encostam_na_grade():
    pen = calibrated()
    paths, info = E.calibration.spacing_comb(a4_area(pen), pen)
    zero, top = info["grid"]["zero_x"], info["grid"]["top"]
    cells = [q for q in paths if np.ptp(q.pts[:, 0]) == pytest.approx(5.0) and len(q.pts) > 4]
    for q in cells:
        cx = (q.pts[:, 0].min() - zero) % 10.0
        cy = (top - q.pts[:, 1].max()) % 10.0
        assert cx == pytest.approx(2.5) and cy == pytest.approx(2.5)

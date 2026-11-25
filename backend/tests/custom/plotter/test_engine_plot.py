"""custom(plotter): posicionamento, pressão -> Z, G-code da A1, validador e pacote .gcode.3mf."""

import hashlib
import io
import zipfile

import numpy as np
import pytest

from backend.app.custom.plotter import engine as E
from backend.app.custom.plotter.engine import gcode as G, plan as PL
from backend.app.custom.plotter.engine.strokes import Drawing, Stroke

from . import shapes

TABLE = [[0.1, 0.3], [0.6, 0.8], [1.2, 1.6]]


def pen(**over):
    return E.PenProfile.from_dict({"z_contact": 4.0, "table": TABLE, **over})


def line_drawing(widths=(4.0, 4.0)):
    """Imagem de 100x100 px com um traço horizontal no meio, de x=10 a x=90."""
    pts = np.array([[10, 50, widths[0]], [90, 50, widths[1]]], np.float32)
    return Drawing(100.0, 100.0, [Stroke(pts)])


def code_lines(text):
    return [ln.split(";", 1)[0].strip() for ln in text.splitlines() if ln.split(";", 1)[0].strip()]


# ---------------------------------------------------------------- geometria
def test_posicionamento_inverte_o_y_e_gira_anti_horario():
    m, s = PL.transform_matrix(100, 100, E.Placement(cx=128, cy=100, width=50, rotation=0))
    assert s == pytest.approx(0.5)
    top_left = np.array([0, 0, 1]) @ m.T
    assert top_left == pytest.approx([103, 125])  # topo da imagem fica para o fundo da mesa
    corners = PL.placement_corners(100, 100, E.Placement(cx=128, cy=100, width=50, rotation=90))
    assert corners[0] == pytest.approx([103, 75])  # girou 90° anti-horário: o canto de cima-esquerda foi para baixo


def test_area_util_e_papel_menos_margem_dentro_do_alcance_da_caneta():
    area = E.drawable_area(E.A1, pen(), E.Paper())
    # A4 em pé a 23 mm da esquerda: a caneta (32 mm à frente do bico) não alcança o fundo da mesa
    assert area == pytest.approx((28.0, 5.0, 228.0, 222.0))
    assert E.drawable_area(E.A1, pen(), E.Paper(x=400)) is None
    assert E.pen_reach(E.A1, pen(offset_x=2.0)) == pytest.approx((2.0, -32.0, 258.0, 222.0))


def test_home_do_z_fica_na_borda_da_frente_fora_do_papel_quando_da():
    assert E.home_point(E.A1, E.Paper()) == (11.5, 3.0, False)  # faixa livre à esquerda do A4
    assert E.home_point(E.A1, E.Paper(x=0, w=240)) == (248.0, 3.0, False)  # só sobra faixa à direita
    assert E.home_point(E.A1, E.Paper(x=0, w=256)) == (128.0, 3.0, True)  # papel cobre a borda: toca o papel
    assert E.home_point(E.A1, E.Paper(y=20)) == (128.0, 3.0, False)  # papel recuado: borda livre


def test_recorte_parte_o_traco_e_interpola_o_atributo():
    pts = np.array([[-10.0, 5.0, 0.0], [30.0, 5.0, 4.0]])
    pieces = PL.clip_polyline(pts, (0.0, 0.0, 20.0, 10.0))
    assert len(pieces) == 1
    assert pieces[0][0] == pytest.approx([0.0, 5.0, 1.0])
    assert pieces[0][-1] == pytest.approx([20.0, 5.0, 3.0])
    zig = np.array([[5.0, 5.0, 1.0], [5.0, 50.0, 1.0], [15.0, 50.0, 1.0], [15.0, 5.0, 1.0]])
    assert len(PL.clip_polyline(zig, (0.0, 0.0, 20.0, 10.0))) == 2
    assert PL.clip_polyline(pts + [0, 100, 0], (0.0, 0.0, 20.0, 10.0)) == []


def test_limite_de_inclinacao_so_alivia_o_aperto():
    pts = np.array([[0.0, 0.0, 0.2], [0.5, 0.0, 1.2], [10.0, 0.0, 1.2]])
    out = PL.limit_slope(pts, 0.6)
    assert out[1, 2] == pytest.approx(0.5)  # 0,2 + 0,6 mm/mm × 0,5 mm
    assert np.all(out[:, 2] <= pts[:, 2] + 1e-12)


# ---------------------------------------------------------------- pressão
def test_tabela_de_pressao_converte_largura_em_aperto():
    p = pen()
    assert p.pressure_calibrated and p.width_range() == pytest.approx((0.4, 1.6))
    assert p.depth_for_width(0.8) == (pytest.approx(0.6), 0)
    assert p.depth_for_width(0.05)[1] == -1 and p.depth_for_width(5.0)[1] == 1
    assert p.width_for_depth(0.9) == pytest.approx(1.2)
    with pytest.raises(E.ProfileError):
        pen(table=[[0.1, 0.9], [0.5, 0.4]])  # mais aperto não pode afinar
    with pytest.raises(E.ProfileError):
        pen(depth_max=4.0)  # além do que o suporte aguenta


def test_largura_real_vira_aperto_e_fora_da_faixa_avisa():
    d = line_drawing((1.0, 3.0))  # 0,5 mm/px -> 0,5 mm e 1,5 mm
    place = E.Placement(cx=128, cy=100, width=50)
    out = E.build_paths(d, place, E.Paper(), pen(), E.A1, E.PlanOptions(width_mode="physical"))
    depths = out.paths[0].pts[:, 2]
    assert depths.min() == pytest.approx(0.3, abs=0.01) and depths.max() == pytest.approx(1.125, abs=0.01)
    assert not out.issues
    thick = E.build_paths(line_drawing((8.0, 8.0)), place, E.Paper(), pen(), E.A1, E.PlanOptions(width_mode="physical"))
    assert [i.code for i in thick.issues] == ["too_thick"]
    assert thick.paths[0].pts[:, 2].max() == pytest.approx(1.2)


def test_modo_ajustar_espalha_as_larguras_do_desenho_na_faixa_da_caneta():
    d = Drawing(100.0, 100.0, [Stroke(np.array([[10, 30, 40.0], [90, 30, 40.0]], np.float32)),
                               Stroke(np.array([[10, 70, 400.0], [90, 70, 400.0]], np.float32))])
    out = E.build_paths(d, E.Placement(cx=128, cy=100, width=50), E.Paper(), pen(), E.A1)
    depths = sorted(float(p.pts[0, 2]) for p in out.paths)
    assert depths == pytest.approx([0.2, 1.2])  # o mais fino no aperto mínimo, o mais grosso no máximo
    assert out.stats["width_mode"] == "fit"


def test_sem_tabela_so_pressao_constante():
    p = E.PenProfile.from_dict({"z_contact": 4.0})
    out = E.build_paths(line_drawing((1.0, 9.0)), E.Placement(cx=128, cy=100, width=50), E.Paper(), p, E.A1)
    assert [i.code for i in out.issues] == ["pressure_uncalibrated"]
    assert np.allclose(out.paths[0].pts[:, 2], p.depth_min)
    assert out.stats["pressure"] == "constant"


def test_fora_do_papel_e_recortado_com_aviso_e_tudo_fora_e_erro():
    half = E.build_paths(line_drawing(), E.Placement(cx=28, cy=100, width=100), E.Paper(), pen(), E.A1)
    assert [i.code for i in half.issues] == ["clipped"]
    assert half.paths[0].pts[:, 0].min() == pytest.approx(28.0)
    with pytest.raises(E.PlanError):
        E.build_paths(line_drawing(), E.Placement(cx=128, cy=250, width=50), E.Paper(), pen(), E.A1)


def test_tracos_apagados_pelo_usuario_ficam_de_fora():
    d = Drawing(100.0, 100.0, [line_drawing().strokes[0], Stroke(np.array([[10, 20, 4.0], [90, 20, 4.0]], np.float32))])
    out = E.build_paths(d, E.Placement(cx=128, cy=100, width=50), E.Paper(), pen(), E.A1, E.PlanOptions(exclude=[0]))
    assert len(out.paths) == 1 and out.paths[0].pts[0, 1] == pytest.approx(115.0)


def test_ordem_anda_pouco_e_pode_inverter_traco():
    def seg(x0, x1, y):
        return E.PenPath(np.array([[x0, y, 0.2], [x1, y, 0.2]]))

    ordered = PL.order_paths([seg(100, 200, 50), seg(0, 90, 10), seg(200, 100, 12)], (0.0, 0.0))
    assert [float(p.pts[0, 0]) for p in ordered] == [0.0, 100.0, 200.0]  # o terceiro foi invertido


# ---------------------------------------------------------------- G-code
def make(**over):
    d = E.vectorize(shapes.wedge())
    return E.make_plot(d, E.Placement(cx=128, cy=110, width=160), over.pop("paper", E.Paper()), pen(**over), title="cunha")


def test_gcode_varia_o_z_dentro_do_traco_e_nao_aquece_nem_extruda():
    plot = make()
    assert plot.ok, plot.report.errors
    lines = code_lines(plot.gcode)
    draws = [ln for ln in lines if ln.startswith("G1 X")]
    zs = [float(part[1:]) for ln in draws for part in ln.split() if part.startswith("Z")]
    assert len(draws) == len(zs) > 50  # todo movimento de traço leva Z
    assert min(zs) == pytest.approx(2.8, abs=0.01) and max(zs) == pytest.approx(3.8, abs=0.01)  # contato 4,0 − aperto
    assert len({round(z, 2) for z in zs}) > 20  # variação contínua, não dois níveis
    tokens = {ln.split()[0] for ln in lines}
    assert not tokens & {"M109", "M190", "G2", "G3", "M620", "M621", "M620.1", "G92"}
    assert not any(tok.startswith("T") for tok in tokens)
    assert not any(part.startswith("E") for ln in lines if ln.startswith(("G0", "G1")) for part in ln.split()[1:])
    assert [ln for ln in lines if ln.startswith(("M104", "M140"))] == ["M104 S0", "M140 S0", "M104 S0", "M140 S0"]
    assert plot.report.stats["z_min"] >= plot.report.stats["z_floor"]


def test_inicio_faz_home_com_a_caneta_fora_da_mesa_e_sem_calibracoes():
    lines = code_lines(make().gcode)
    i_home_xy, i_home_z = lines.index("G28 X"), lines.index("G28 Z P0 T140")
    assert lines.index("G380 S2 Z40 F1200") < i_home_xy < i_home_z
    between = lines[i_home_xy:i_home_z]
    assert "G0 X11.5 F18000" in between and "G0 Y3 F3000" in between  # borda da frente; caneta em Y=-29
    # nada de nivelamento, medição de vibração, calibração de fluxo ou detecção de placa
    assert not {ln.split()[0] for ln in lines} & {"G29", "G39.4", "M970", "M970.3", "M974", "M983", "M984", "M975"}
    assert lines[i_home_z + 1] == "G29.2 S1"
    lines = [ln for ln in lines if not ln.startswith("M73")]
    first_draw = next(i for i, ln in enumerate(lines) if ln.startswith("G1 X"))
    assert lines[first_draw - 2].startswith("G0 X") and lines[first_draw - 1].startswith("G1 Z3.")
    assert code_lines(make().gcode)[-1] == "M73 P100 R0"


def test_home_sobre_o_papel_desconta_a_espessura():
    covered = E.Paper(x=0, w=256, thickness=0.15)
    assert G.z_levels(pen(), covered, E.A1)["touch"] == pytest.approx(3.85)
    assert G.z_levels(pen(), E.Paper(), E.A1)["touch"] == pytest.approx(4.0)


def test_sem_altura_de_contato_nao_gera_e_piso_do_bico_e_respeitado():
    with pytest.raises(E.PlanError):
        E.make_plot(line_drawing(), E.Placement(cx=128, cy=100, width=50), E.Paper(), E.PenProfile())
    low = E.PenProfile.from_dict({"z_contact": 1.2, "depth_min": 0.2, "depth_max": 1.0, "max_compression": 3.0})
    with pytest.raises(E.PlanError, match="limite seguro"):
        E.make_plot(line_drawing(), E.Placement(cx=128, cy=100, width=50), E.Paper(), low,
                    options=E.PlanOptions(pressure="constant", constant_depth=1.0))


def test_tempo_do_gerador_bate_com_o_do_validador():
    plot = make()
    assert plot.report.stats["time_s"] == pytest.approx(plot.stats["gcode"]["time_s"], rel=0.02)
    assert plot.report.stats["draw_mm"] == pytest.approx(plot.stats["gcode"]["draw_mm"], rel=0.01)
    assert plot.report.stats["pen_downs"] == plot.stats["gcode"]["pen_downs"] == 1
    assert plot.report.sim and plot.report.sim[-1][3] <= plot.report.stats["time_s"]


@pytest.mark.parametrize(
    ("inject", "code"),
    [
        ("M104 S220", "not_allowed"),
        ("M140 S60", "not_allowed"),
        ("M109 S200", "not_allowed"),
        ("G1 X100 Y100 E5", "move_words"),
        ("G1 X300 Y100", "x_range"),
        ("G1 X100 Y-5", "y_range"),
        ("G1 Z0.1 F300", "z_floor"),
        ("G1 Z90 F300", "z_ceiling"),
        ("G2 X1 Y1 I1 J0", "not_allowed"),
        ("T0", "not_allowed"),
        ("M620 S0A", "not_allowed"),
        ("M1002 gcode_claim_action : 2", "syntax"),
        ("G91", "relative_after_home"),
        ("G0 X5 Y100 F6000\nG1 Z3.9 F300", "pen_off_paper"),  # caneta em X=5: fora do A4 que começa em 23
        ("G0 X128 Y100 F6000\nG1 Z3.9 F300\nG0 X140 Y100 F6000", "rapid_pen_down"),
        ("G0 X128 Y100 F6000\nG1 Z3.9 F300\nG1 X140 Y100 F9000", "draw_feed"),
        ("G0 X128 Y100 F6000\nG1 Z3.9 F300", "ends_low"),
    ],
)
def test_validador_recusa_gcode_adulterado(inject, code):
    plot = make()
    marker = ";===== fim"
    if code == "ends_low":
        tampered = plot.gcode.split(marker)[0] + inject + "\n; EXECUTABLE_BLOCK_END\n"
    else:
        tampered = plot.gcode.replace(marker, inject + "\n" + marker)
    report = E.validate(tampered, E.A1, pen(), E.Paper(), keep_sim=False)
    assert not report.ok
    assert code in [e["code"] for e in report.errors]


def test_validador_recusa_arquivo_sem_home_truncado_ou_com_home_no_meio_da_mesa():
    plot = make()
    assert "no_home" in [e["code"] for e in E.validate(plot.gcode.replace("G28 Z P0 T140\n", ""), E.A1, pen(), E.Paper()).errors]
    cut = plot.gcode.rsplit("; EXECUTABLE_BLOCK_END", 1)[0]
    assert "truncated" in [e["code"] for e in E.validate(cut, E.A1, pen(), E.Paper()).errors]
    moved = plot.gcode.replace("G0 Y3 F3000", "G0 Y128 F3000")
    assert "z_home_place" in [e["code"] for e in E.validate(moved, E.A1, pen(), E.Paper()).errors]
    hot = plot.gcode.replace("M104 S0 ; bico desligado\n", "")
    assert E.validate(hot, E.A1, pen(), E.Paper()).ok  # o M104 S0 do fim ainda garante o desligamento
    none = plot.gcode.replace("M104 S0", "M400")
    assert "heater_not_off" in [e["code"] for e in E.validate(none, E.A1, pen(), E.Paper()).errors]


def test_validador_usa_o_perfil_atual_e_nao_o_do_arquivo():
    plot = make()
    shifted = pen(z_contact=6.0)  # caneta recalibrada mais alta: o arquivo antigo arrastaria a ponta no deslocamento
    report = E.validate(plot.gcode, E.A1, shifted, E.Paper())
    assert not report.ok


# ---------------------------------------------------------------- pacote
def test_pacote_3mf_tem_o_gcode_o_md5_e_as_miniaturas():
    plot = make()
    data = plot.package()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = set(z.namelist())
        assert {
            "[Content_Types].xml",
            "_rels/.rels",
            "3D/3dmodel.model",
            "Metadata/plate_1.gcode",
            "Metadata/plate_1.gcode.md5",
            "Metadata/plate_1.png",
            "Metadata/plate_1_small.png",
            "Metadata/slice_info.config",
            "Metadata/model_settings.config",
            "Metadata/_rels/model_settings.config.rels",
            "Metadata/project_settings.config",
        } <= names
        body = z.read("Metadata/plate_1.gcode")
        assert z.read("Metadata/plate_1.gcode.md5").decode() == hashlib.md5(body).hexdigest().upper()
        assert b'key="weight" value="0.00"' in z.read("Metadata/slice_info.config")
        assert z.read("Metadata/plate_1.png")[:8] == b"\x89PNG\r\n\x1a\n"
    assert E.package.read_gcode(data) == plot.gcode


def test_plot_recusado_nao_empacota():
    plot = make()
    plot.report.ok = False
    with pytest.raises(E.PlanError):
        plot.package()


# ---------------------------------------------------------------- calibração
def test_escada_tem_uma_linha_por_aperto_com_o_aperto_escrito_ao_lado():
    p = E.PenProfile.from_dict({"z_contact": 4.0})
    area = E.drawable_area(E.A1, p, E.Paper())
    paths, info = E.calibration.pressure_ladder(area, p, [0.0, 0.3, 0.6, 1.0])
    assert [r["depth"] for r in info["rows"]] == [0.0, 0.3, 0.6, 1.0]
    lines = [q for q in paths if len(q.pts) == 2 and abs(q.pts[1, 0] - q.pts[0, 0]) == E.calibration.LADDER_LINE]
    assert [float(q.pts[0, 2]) for q in lines] == [0.0, 0.3, 0.6, 1.0]
    assert [round(float(q.pts[0, 1]), 2) for q in lines] == [r["y"] for r in info["rows"]]
    line_ids = {id(q) for q in lines}
    order = [id(q) in line_ids for q in paths]
    assert order == sorted(order)  # grade e números antes das linhas
    zero = info["grid"]["zero_x"]
    assert all(q.pts[0, 0] in (zero, zero + 50.0) for q in lines)
    labels = [q for q in paths if id(q) not in line_ids and q.pts[:, 1].min() > info["grid"]["top"] - 80]
    labels = [q for q in labels if np.ptp(q.pts[:, 0]) < 3 and q.pts[:, 0].max() < zero]
    assert labels  # aperto escrito na coluna da esquerda
    plot = E.plot_paths(paths, p, E.Paper(), title="folha")
    assert plot.ok, plot.report.errors
    with pytest.raises(E.PlanError):
        E.calibration.pressure_ladder(area, p, [0.0, 9.0])
    with pytest.raises(E.PlanError):
        E.calibration.pressure_ladder((0, 0, 30, 30), p)


def test_cruz_corrige_o_offset_da_caneta():
    p = pen()
    area = E.drawable_area(E.A1, p, E.Paper())
    paths, info = E.calibration.offset_cross(area, p, (100.0, 100.0))
    assert info["target"] == [100.0, 100.0] and E.plot_paths(paths, p, E.Paper()).ok
    # a cruz saiu 1,5 mm à direita e 2 mm para a frente do esperado
    assert E.calibration.corrected_offset(p, (100.0, 100.0), (101.5, 98.0)) == (1.5, -34.0)
    with pytest.raises(E.PlanError):
        E.calibration.offset_cross(area, p, (30.0, 100.0))


def test_contorno_da_area_util_passa_no_validador():
    p = pen()
    paths, _ = E.calibration.frame(E.drawable_area(E.A1, p, E.Paper()), p)
    plot = E.plot_paths(paths, p, E.Paper())
    assert plot.ok and plot.report.stats["bounds"] == pytest.approx([28.0, 5.0, 228.0, 222.0])

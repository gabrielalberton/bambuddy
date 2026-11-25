"""custom(plotter): vetorização de linha central com largura (imagem -> traços)."""

import cv2
import numpy as np
import pytest

from backend.app.custom.plotter import engine as E
from backend.app.custom.plotter.engine import raster, skeleton

from . import shapes


def _lines(drawing):
    return [s for s in drawing.strokes if not s.is_dot]


def test_esqueleto_preserva_topologia_e_fica_com_1px():
    a = np.zeros((300, 300), np.uint8)
    cv2.line(a, (20, 150), (280, 150), 1, 9)
    cv2.circle(a, (150, 150), 80, 1, 7)
    skel = skeleton.thin(a)
    assert cv2.connectedComponents(skel, connectivity=8)[0] == cv2.connectedComponents(a, connectivity=8)[0]
    # nenhum bloco 2x2 cheio: o esqueleto tem 1 px de espessura
    full = skel[:-1, :-1] & skel[1:, :-1] & skel[:-1, 1:] & skel[1:, 1:]
    assert not full.any()
    # pontas da linha continuam lá (não encolheu até sumir)
    ys, xs = np.nonzero(skel)
    assert xs.min() < 30 and xs.max() > 270


def test_cruz_vira_dois_tracos_retos_com_a_largura_certa():
    d = E.vectorize(shapes.cross())
    lines = _lines(d)
    assert len(lines) == 2 and not d.meta["dots"]
    for s in lines:
        assert s.length() == pytest.approx(500, abs=12)
        # cv2.line com espessura 11 e antisserrilhado tem ~13 px
        assert np.all(np.abs(s.pts[:, 2] - 13.2) < 1.2)
    spans = sorted((np.ptp(s.pts[:, 0]), np.ptp(s.pts[:, 1])) for s in lines)
    assert spans[0][0] < 3 and spans[1][1] < 3  # um vertical, um horizontal: passaram direto pelo cruzamento


def test_t_tem_a_barra_inteira_e_a_haste_terminando_nela():
    d = E.vectorize(shapes.tee())
    lines = sorted(_lines(d), key=lambda s: -s.length())
    assert len(lines) == 2
    bar, stem = lines
    assert bar.length() == pytest.approx(500, abs=12)
    assert stem.length() == pytest.approx(400, abs=12)
    # a haste termina dentro da tinta da barra (o nó do esqueleto fica um pouco para o lado da haste)
    assert min(abs(stem.pts[0, 1] - 100.5), abs(stem.pts[-1, 1] - 100.5)) < 6.5


def test_largura_varia_ao_longo_do_traco():
    d = E.vectorize(shapes.wedge())
    assert len(d.strokes) == 1
    widths = d.strokes[0].pts[:, 2]
    assert widths.min() < 6 and widths.max() > 26
    # duas "barrigas": a largura sobe, desce e sobe de novo dentro do mesmo traço
    wide = widths > 20
    assert int(np.sum(wide[1:] & ~wide[:-1])) == 2


def test_pontos_viram_toque_de_caneta_e_circulo_fica_fechado():
    d = E.vectorize(shapes.circle_and_dots())
    dots = sorted((s for s in d.strokes if s.is_dot), key=lambda s: s.pts[0, 2])
    assert len(dots) == 2
    assert dots[0].pts[0, 2] == pytest.approx(8.5, abs=2.0)
    assert dots[1].pts[0, 2] == pytest.approx(16.5, abs=2.0)
    assert np.allclose(dots[1].pts[0, :2], (300.5, 300.5), atol=1.5)
    ring = [s for s in d.strokes if not s.is_dot]
    assert len(ring) == 1 and ring[0].closed
    assert ring[0].length() == pytest.approx(2 * np.pi * 150, rel=0.03)


def test_traco_fino_e_ampliado_antes_de_medir():
    a = shapes.canvas(200, 600)
    cv2.line(a, (20, 100), (580, 100), 0, 1, cv2.LINE_AA)
    d = E.vectorize(shapes.rgb(a))
    assert d.meta["work_scale"] > 1
    assert len(d.strokes) == 1
    s = d.strokes[0]
    assert s.length() == pytest.approx(560, abs=8)
    assert 0.8 <= float(np.median(s.pts[:, 2])) <= 3.0  # em px da imagem original
    assert np.all(np.abs(s.pts[:, 1] - 100.5) < 1.0)


def test_fundo_escuro_e_detectado_e_tinta_colorida_funciona():
    inverted = 255 - shapes.cross()
    assert len(_lines(E.vectorize(inverted))) == 2
    red = shapes.cross().copy()
    red[..., 0] = 255  # traço vermelho puro: luma alta, canal mínimo baixo
    assert len(_lines(E.vectorize(red, {"ink": "min"}))) == 2


def test_sombra_na_foto_nao_vira_traco():
    a = shapes.canvas().astype(np.float32)
    cv2.line(a, (60, 300), (540, 300), 60, 9, cv2.LINE_AA)
    ramp = np.linspace(1.0, 0.55, 600, dtype=np.float32)[None, :]  # metade direita na sombra
    photo = shapes.rgb(np.clip(a * ramp, 0, 255).astype(np.uint8))
    d = E.vectorize(photo)
    assert len(d.strokes) == 1
    assert d.strokes[0].length() == pytest.approx(480, abs=15)


def test_imagem_em_branco_ou_invalida_da_erro_claro():
    with pytest.raises(E.ImageError):
        E.vectorize(shapes.rgb(shapes.canvas()))
    with pytest.raises(E.ImageError):
        E.vectorize_image(b"isto nao e uma imagem")


def test_decodifica_png_com_transparencia_sobre_branco_e_limita_o_tamanho():
    rgba = np.zeros((400, 400, 4), np.uint8)
    cv2.line(rgba, (40, 200), (360, 200), (0, 0, 0, 255), 9)
    ok, buf = cv2.imencode(".png", rgba)
    assert ok
    arr = raster.decode_image(buf.tobytes())
    assert arr.shape == (400, 400, 3) and arr[10, 10].tolist() == [255, 255, 255] and arr[200, 200].tolist() == [0, 0, 0]
    small = raster.decode_image(buf.tobytes(), max_pixels=40_000)
    assert small.shape[0] * small.shape[1] <= 41_000


def test_rebarba_do_canto_reto_e_podada():
    a = shapes.canvas()
    cv2.rectangle(a, (100, 100), (500, 140), 0, -1)
    cv2.rectangle(a, (100, 100), (140, 500), 0, -1)
    d = E.vectorize(shapes.rgb(a))
    assert len(d.strokes) == 1  # um "L" só, sem ramos para os cantos


def test_json_ida_e_volta():
    d = E.vectorize(shapes.circle_and_dots())
    again = E.Drawing.from_json(d.to_json())
    assert len(again.strokes) == len(d.strokes)
    assert [s.closed for s in again.strokes] == [s.closed for s in d.strokes]
    assert np.allclose(again.strokes[0].pts, d.strokes[0].pts, atol=0.01)

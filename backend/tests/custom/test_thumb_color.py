"""custom(thumb-color): cor da miniatura a partir do próprio 3MF."""

import io
import json
import zipfile

from backend.app.custom import thumb_color


def _zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_fatiado_usa_filamento_com_mais_gramas():
    info = '<config><plate><filament id="1" color="#4DAFDA" used_g="2.0" /><filament id="3" color="#DA1884FF" used_g="7.5" /></plate></config>'
    assert thumb_color.model_color(_zip({"Metadata/slice_info.config": info})) == "#DA1884"


def test_projeto_usa_extrusor_mais_usado():
    ps = json.dumps({"filament_colour": ["#FFFFFF", "#F95D73"]})
    ms = (
        '<config><object id="1"><metadata key="extruder" value="2"/></object>'
        '<object id="2"><metadata key="extruder" value="2"/></object>'
        '<object id="3"><metadata key="extruder" value="1"/></object></config>'
    )
    data = _zip({"Metadata/project_settings.config": ps, "Metadata/model_settings.config": ms})
    assert thumb_color.model_color(data) == "#F95D73"


def test_sem_cor_e_cor_escura():
    assert thumb_color.model_color(_zip({"3D/3dmodel.model": "<model/>"})) == thumb_color.NEUTRAL
    ps = json.dumps({"filament_colour": ["#000000"]})
    assert thumb_color.model_color(_zip({"Metadata/project_settings.config": ps})) == thumb_color.DARK_FLOOR
    assert thumb_color.model_color(b"nao e zip") == thumb_color.NEUTRAL


def test_install_troca_a_cor_do_renderizador():
    from backend.app.services import plate_thumbnail, stl_thumbnail

    thumb_color.install()
    assert stl_thumbnail.BAMBU_GREEN == thumb_color.NEUTRAL
    seen = {}

    class FakePoly:
        def __init__(self, *a, **kw):
            seen.update(kw)

    thumb_color._local.color = "#DA1884"
    try:
        try:
            plate_thumbnail._render_at_size([], 64, FakePoly, {})
        except Exception:  # noqa: BLE001 - só interessa a cor que chegou ao polígono
            pass
    finally:
        thumb_color._local.color = None
    assert seen.get("facecolors") == "#DA1884"

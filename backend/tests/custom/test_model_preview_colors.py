import zipfile

import numpy as np
import trimesh
from lxml import etree

from backend.app.custom.model_preview import render


def test_bambu_filament_codes():
    assert [render.paint_slot(code) for code in ("", "4", "8", "0C", "1C")] == [0, 1, 2, 3, 4]


def test_split_paint_picks_dominant_leaf_and_broken_data_is_unpainted():
    assert render.paint_slot("4482") == 1
    assert render.paint_slot("C") == 0
    assert render.paint_slot("GG") == 0


def test_decimation_keeps_coincident_sides_of_a_3mf_seam_connected(tmp_path, monkeypatch):
    sphere = trimesh.creation.icosphere(subdivisions=3, radius=10)
    faces = sphere.faces.copy()
    # Both sides touch at the same positions but use different vertex IDs.
    faces[sphere.triangles_center[:, 2] > 0] += len(sphere.vertices)
    vertices = np.vstack((sphere.vertices, sphere.vertices))
    root = etree.Element("model", unit="millimeter")
    resources = etree.SubElement(root, "resources")
    obj = etree.SubElement(resources, "object", id="1", type="model")
    part = etree.SubElement(obj, "mesh")
    points = etree.SubElement(part, "vertices")
    for x, y, z in vertices:
        etree.SubElement(points, "vertex", x=str(x), y=str(y), z=str(z))
    triangles = etree.SubElement(part, "triangles")
    for a, b, c in faces:
        etree.SubElement(triangles, "triangle", v1=str(a), v2=str(b), v3=str(c))
    build = etree.SubElement(root, "build")
    etree.SubElement(build, "item", objectid="1")
    source, glb, png = (tmp_path / name for name in ("split.3mf", "preview.glb", "thumbnail.png"))
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("3D/3dmodel.model", etree.tostring(root))
        archive.writestr("Metadata/project_settings.config", '{"filament_colour":["#FFFFFFFF"]}')

    monkeypatch.setattr(render, "FACE_BUDGET", 320)
    render.render(source, glb, png)

    preview = trimesh.load_scene(glb, process=False)
    (mesh,) = preview.geometry.values()
    assert len(mesh.faces) < len(sphere.faces) / 2
    assert mesh.is_watertight
    np.testing.assert_array_equal(mesh.visual.material.main_color, [255, 255, 255, 255])
    assert png.read_bytes().startswith(b"\x89PNG")

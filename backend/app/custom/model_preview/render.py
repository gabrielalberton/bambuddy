"""Render a small, colored preview of a 3MF package in a separate process."""
from __future__ import annotations

import json
import re
import sys
import zipfile
from array import array
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

if __name__ == "__main__":
    import resource

    # A single malformed or oversized project must not OOM the API process.
    memory_budget = 768 * 1024**2
    resource.setrlimit(resource.RLIMIT_AS, (memory_budget, memory_budget))

import numpy as np
from lxml import etree

from backend.app.services.plate_thumbnail import _MODEL_ROOT, _local, _render_at_size, _transform

FACE_BUDGET = 70_000
MAX_MODEL_BYTES = 384 * 1024**2
FALLBACK = "#00AE42"
_HEX = re.compile(r"#[0-9a-f]{6}([0-9a-f]{2})?", re.I)
_PAINT = re.compile(r"[0-9a-f]+", re.I)


@lru_cache(maxsize=4096)
def paint_slot(code: str) -> int:
    """Read the Bambu triangle selector. For split faces use the dominant leaf."""
    if not _PAINT.fullmatch(code):
        return 0
    digits = iter(int(c, 16) for c in reversed(code))
    weights = Counter()
    pending = [1.0]
    try:
        while pending:
            weight = pending.pop()
            value = next(digits)
            children = value & 3
            if children:
                pending.extend([weight / (children + 1)] * (children + 1))
                continue
            slot = value >> 2
            if slot == 3:
                extra = next(digits)
                slot = next(digits) + 18 if extra == 15 else extra + 3
            weights[slot] += weight
    except StopIteration:
        return 0
    return weights.most_common(1)[0][0]


def _settings(zf):
    names = zf.namelist()
    palette = []
    settings = "Metadata/project_settings.config"
    if settings in names:
        settings_data = json.loads(zf.read(settings))
        colors = settings_data.get("filament_colour", [])
        if isinstance(colors, list):
            palette = [c[:7] if isinstance(c, str) and _HEX.fullmatch(c) else FALLBACK for c in colors]
    objects, parts = {}, {}
    settings = "Metadata/model_settings.config"
    if settings in names:
        parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
        root = etree.fromstring(zf.read(settings), parser)
        for obj in root.findall("object"):
            obj_id = obj.get("id")
            value = obj.find("metadata[@key='extruder']")
            if value is not None and (slot := value.get("value", "")).isdigit():
                objects[obj_id] = int(slot)
            for part in obj.findall("part"):
                value = part.find("metadata[@key='extruder']")
                if value is not None and (slot := value.get("value", "")).isdigit():
                    parts[(obj_id, part.get("id"))] = int(slot)
    return palette, objects, parts


def _read_model(zf, path):
    objects, build = {}, []
    vertices, triangles, slots = array("f"), array("i"), array("B")
    components = []
    with zf.open(path) as stream:
        parse = etree.iterparse(stream, events=("end",), resolve_entities=False, no_network=True, load_dtd=False)
        for _, element in parse:
            tag = _local(element.tag) if isinstance(element.tag, str) else ""
            if tag == "vertex":
                vertices.extend(float(element.get(axis)) for axis in "xyz")
            elif tag == "triangle":
                triangles.extend(int(element.get(key)) for key in ("v1", "v2", "v3"))
                slots.append(paint_slot(element.get("paint_color", "")))
            elif tag in ("component", "item"):
                ref = next((val.lstrip("/") for key, val in element.attrib.items() if _local(key) == "path"), path)
                record = ref, element.get("objectid"), _transform(element.get("transform"))
                (build if tag == "item" else components).append(record)
            elif tag == "object":
                points = np.frombuffer(vertices, dtype=np.float32).reshape(-1, 3)
                faces = np.frombuffer(triangles, dtype=np.int32).reshape(-1, 3)
                face_slots = np.frombuffer(slots, dtype=np.uint8)
                valid = ((faces >= 0) & (faces < len(points))).all(axis=1)
                objects[element.get("id")] = points, faces[valid], face_slots[valid], components
                vertices, triangles, slots = array("f"), array("i"), array("B")
                components = []
            element.clear()
            while element.getprevious() is not None:
                del element.getparent()[0]
    return objects, build


def _placed_meshes(zf, object_slots, part_slots):
    models = {}
    # Re-use geometry across instances and group placements by their default color.
    placements = defaultdict(list)
    visited = 0
    model_names = {x.filename for x in zf.infolist() if x.filename.lower().endswith(".model")}
    if sum(zf.getinfo(name).file_size for name in model_names) > MAX_MODEL_BYTES:
        raise ValueError("3MF model data exceeds preview budget")
    if not model_names:
        return
    root_path = _MODEL_ROOT if _MODEL_ROOT in model_names else sorted(model_names)[0]
    root, build = _read_model(zf, root_path)
    models[root_path] = root

    def place(path, object_id, transform, default_slot, root_id, parents):
        nonlocal visited
        visited += 1
        if visited > 12000:
            raise ValueError("3MF has too many component instances")
        key = (path, object_id)
        if path not in model_names or key in parents or len(parents) >= 16:
            return
        if path not in models:
            models[path] = _read_model(zf, path)[0]
        record = models[path].get(object_id)
        if record is None:
            return
        _, faces, _, children = record
        slot = part_slots.get((root_id, object_id), default_slot)
        if len(faces):
            placements[(path, object_id, slot)].append(transform)
        for ref, child, local in children:
            place(ref, child, transform @ local, slot, root_id, parents | {key})

    for path, object_id, matrix in build or [(root_path, obj_id, np.eye(4)) for obj_id, obj in root.items() if len(obj[1])]:
        place(path, object_id, matrix, object_slots.get(object_id, 1), object_id, set())

    total = sum(len(models[path][obj][1]) * len(matrices) for (path, obj, _), matrices in placements.items())
    if not total:
        return
    if sum(map(len, placements.values())) > 2048:
        raise ValueError("3MF has too many model placements")
    yield models, placements, min(1.0, FACE_BUDGET / total)


def _weld_mesh(points: np.ndarray, faces: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Connect exactly coincident vertices of this part and filament before decimation."""
    ids, compact = np.unique(faces, return_inverse=True)
    vertices, welded = np.unique(points[ids], axis=0, return_inverse=True)
    indices = welded[compact].reshape(-1, 3).astype(np.int32)
    a, b, c = indices.T
    # A face that named a vertex twice by two different indices collapses.
    valid = (a != b) & (b != c) & (a != c)
    return vertices, indices[valid]


def _cluster_large_mesh(vertices, faces, target):
    """Collapse nearby vertices before quadric simplification of a huge mesh."""
    lower = vertices.min(axis=0)
    extent = float((vertices.max(axis=0) - lower).max())
    if extent <= 0:
        return vertices[:0], faces[:0]
    normalized = (vertices - lower) / extent
    resolution = 128
    while True:
        cells = np.floor(normalized * resolution).astype(np.int64)
        width = resolution + 1
        packed = cells[:, 0] + width * (cells[:, 1] + width * cells[:, 2])
        _, representative, groups = np.unique(packed, return_index=True, return_inverse=True)
        clustered = groups[faces]
        a, b, c = clustered.T
        clustered = clustered[(a != b) & (a != c) & (b != c)]
        distinct = np.unique(np.sort(clustered, axis=1), axis=0, return_index=True)[1]
        if len(distinct) <= max(2000, target * 2) or resolution <= 12:
            return vertices[representative], clustered[distinct].astype(np.int32)
        resolution = max(12, min(resolution - 1, int(resolution * (target / len(distinct)) ** 0.5)))


def render(source: Path, glb: Path, png: Path):
    import fast_simplification
    import trimesh
    from matplotlib.colors import LightSource, to_rgba
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    from backend.app.services.stl_thumbnail import _shade_kwargs

    scene = trimesh.Scene()
    surfaces = []
    rgba_values = []
    with zipfile.ZipFile(source) as zf:
        palette, object_slots, part_slots = _settings(zf)
        for models, placements, ratio in _placed_meshes(zf, object_slots, part_slots):
            for (path, object_id, default_slot), matrices in placements.items():
                points, faces, painted, _ = models[path][object_id]
                slots = np.where(painted, painted, default_slot)
                for slot in np.unique(slots):
                    # A 3MF can repeat identical positions along seams. If
                    # the simplifier moves each side separately, gaps appear.
                    vertices, indices = _weld_mesh(points, faces[slots == slot])
                    target = max(32, int(len(indices) * ratio))
                    if len(indices) > 900_000:
                        vertices, indices = _cluster_large_mesh(vertices, indices, target)
                    if target < len(indices):
                        vertices, indices = fast_simplification.simplify(vertices, indices, target_count=target)
                    if not len(indices):
                        continue
                    color = palette[slot - 1] if 0 < slot <= len(palette) else FALLBACK
                    rgba = to_rgba(color)
                    linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in rgba[:3]]
                    for matrix in matrices:
                        placed = vertices @ matrix[:3, :3].T + matrix[:3, 3]
                        winding = indices[:, ::-1] if np.linalg.det(matrix[:3, :3]) < 0 else indices
                        mesh = trimesh.Trimesh(vertices=placed, faces=winding, process=False)
                        mesh.visual = trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(
                            baseColorFactor=[*linear, rgba[3]], metallicFactor=0.0, roughnessFactor=0.62,
                        ))
                        scene.add_geometry(mesh)
                        surfaces.append(placed[winding])
                        rgba_values.append(np.repeat([rgba], len(winding), axis=0))

    if not surfaces:
        raise ValueError("3MF contains no previewable geometry")
    polygons = np.concatenate(surfaces)
    colors = np.concatenate(rgba_values)
    lower, upper = polygons.min(axis=(0, 1)), polygons.max(axis=(0, 1))
    normalized = (polygons - (lower + upper) / 2) / max(float((upper - lower).max()), 1e-6)
    png.write_bytes(_render_at_size(normalized, 512, Poly3DCollection, _shade_kwargs(normalized, LightSource), facecolors=colors))
    glb.write_bytes(scene.export(file_type="glb"))


if __name__ == "__main__":
    render(*(Path(arg) for arg in sys.argv[1:]))

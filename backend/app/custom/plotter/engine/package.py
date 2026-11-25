"""Empacota o G-code num ``.gcode.3mf`` no formato que a A1 aceita em ``project_file``.

Espelha os membros de um arquivo fatiado pelo Bambu Studio (o G-code em ``Metadata/plate_1.gcode``, o MD5
ao lado, as relações OPC e as miniaturas), com metadados mínimos e honestos: zero filamento, uma camada.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import io
import json
import zipfile
from xml.sax.saxutils import escape

import cv2
import numpy as np

from .gcode import clean_title
from .plan import PenPath
from .profile import Machine, Paper, PenProfile

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
 <Default Extension="png" ContentType="image/png"/>
 <Default Extension="gcode" ContentType="text/x.gcode"/>
</Types>
"""

_RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
 <Relationship Target="/Metadata/plate_1.png" Id="rel-2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/thumbnail"/>
 <Relationship Target="/Metadata/plate_1.png" Id="rel-4" Type="http://schemas.bambulab.com/package/2021/cover-thumbnail-middle"/>
 <Relationship Target="/Metadata/plate_1_small.png" Id="rel-5" Type="http://schemas.bambulab.com/package/2021/cover-thumbnail-small"/>
</Relationships>
"""

_SETTINGS_RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Target="/Metadata/plate_1.gcode" Id="rel-1" Type="http://schemas.bambulab.com/package/2021/gcode"/>
</Relationships>
"""

_MODEL = """<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" xmlns:BambuStudio="http://schemas.bambulab.com/package/2021">
 <metadata name="Application">BambuStudio-02.09.01.70</metadata>
 <metadata name="BambuStudio:3mfVersion">1</metadata>
 <metadata name="CreationDate">{date}</metadata>
 <metadata name="ModificationDate">{date}</metadata>
 <metadata name="Title">{title}</metadata>
 <resources>
 </resources>
 <build/>
</model>
"""

_MODEL_SETTINGS = """<?xml version="1.0" encoding="UTF-8"?>
<config>
  <plate>
    <metadata key="plater_id" value="1"/>
    <metadata key="plater_name" value="{title}"/>
    <metadata key="locked" value="false"/>
    <metadata key="gcode_file" value="Metadata/plate_1.gcode"/>
    <metadata key="thumbnail_file" value="Metadata/plate_1.png"/>
  </plate>
</config>
"""

_SLICE_INFO = """<?xml version="1.0" encoding="UTF-8"?>
<config>
  <header>
    <header_item key="X-BBL-Client-Type" value="slicer"/>
    <header_item key="X-BBL-Client-Version" value="02.09.01.70"/>
  </header>
  <plate>
    <metadata key="index" value="1"/>
    <metadata key="extruder_type" value="0"/>
    <metadata key="nozzle_volume_type" value="0"/>
    <metadata key="printer_model_id" value=""/>
    <metadata key="nozzle_diameters" value="0.4"/>
    <metadata key="timelapse_type" value="0"/>
    <metadata key="prediction" value="{seconds}"/>
    <metadata key="weight" value="0.00"/>
    <metadata key="outside" value="false"/>
    <metadata key="support_used" value="false"/>
    <metadata key="label_object_enabled" value="false"/>
    <object identify_id="1" name="{title}" skipped="false" />
    <filament id="1" tray_info_idx="GFL99" type="PLA" color="#161616" used_m="0.00" used_g="0.00" />
  </plate>
</config>
"""


def render_thumbnail(
    paths: list[PenPath], pen: PenProfile, paper: Paper, machine: Machine, size: int = 512
) -> np.ndarray:
    """Vista de cima da placa: papel branco e o traçado previsto, com a largura estimada (BGR uint8)."""
    shift = 4
    scale = size / machine.plate_w
    f = scale * (1 << shift)
    img = np.full((size, size, 3), (58, 54, 50), np.uint8)

    def to_px(x: float, y: float) -> tuple[int, int]:
        return (int(round(x * f)), int(round((machine.plate_h - y) * f)))

    cv2.rectangle(img, to_px(paper.x, paper.y + paper.h), to_px(paper.x + paper.w, paper.y), (250, 250, 250), -1, cv2.LINE_AA, shift)
    for p in paths:
        pts = p.pts
        if len(pts) == 1:
            r = max(1, int(round(pen.width_for_depth(float(pts[0, 2])) * 0.5 * f)))
            cv2.circle(img, to_px(pts[0, 0], pts[0, 1]), r, (30, 30, 30), -1, cv2.LINE_AA, shift)
            continue
        for a, b in zip(pts[:-1], pts[1:]):
            width = pen.width_for_depth(0.5 * float(a[2] + b[2]))
            cv2.line(img, to_px(a[0], a[1]), to_px(b[0], b[1]), (30, 30, 30), max(1, int(round(width * scale))), cv2.LINE_AA, shift)
    return img


def _png(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("falha ao gerar a miniatura")
    return buf.tobytes()


def build_3mf(gcode: str, title: str, seconds: float, thumbnail: np.ndarray | None = None) -> bytes:
    """Bytes do ``.gcode.3mf``. ``thumbnail``: imagem BGR quadrada (ou None para uma em branco)."""
    name = escape(clean_title(title), {'"': "&quot;"})
    today = _dt.date.today().isoformat()
    if thumbnail is None:
        thumbnail = np.full((512, 512, 3), 245, np.uint8)
    small = cv2.resize(thumbnail, (128, 128), interpolation=cv2.INTER_AREA)
    data = gcode.encode("utf-8")
    md5 = hashlib.md5(data).hexdigest().upper()  # noqa: S324 - formato do arquivo, não é segurança
    plate = {
        "bbox_all": [0, 0, 0, 0],
        "bbox_objects": [],
        "bed_type": "textured_plate",
        "filament_colors": ["#161616"],
        "filament_ids": [0],
        "first_extruder": 0,
        "is_seq_print": False,
        "nozzle_diameter": 0.4,
        "version": 2,
    }
    project = {
        "printer_model": "Bambu Lab A1",
        "printer_settings_id": "Bambu Lab A1 0.4 nozzle",
        "curr_bed_type": "Textured PEI Plate",
        "nozzle_diameter": ["0.4"],
        "filament_type": ["PLA"],
        "filament_colour": ["#161616"],
        "pen_plotter": "1",
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("3D/3dmodel.model", _MODEL.format(date=today, title=name))
        z.writestr("Metadata/plate_1.gcode", data)
        z.writestr("Metadata/plate_1.gcode.md5", md5)
        z.writestr("Metadata/plate_1.json", json.dumps(plate))
        z.writestr("Metadata/plate_1.png", _png(thumbnail))
        z.writestr("Metadata/plate_1_small.png", _png(small))
        z.writestr("Metadata/slice_info.config", _SLICE_INFO.format(seconds=int(round(seconds)), title=name))
        z.writestr("Metadata/model_settings.config", _MODEL_SETTINGS.format(title=name))
        z.writestr("Metadata/_rels/model_settings.config.rels", _SETTINGS_RELS)
        z.writestr("Metadata/project_settings.config", json.dumps(project, indent=1))
    return buf.getvalue()


def read_gcode(data: bytes) -> str:
    """G-code de dentro de um pacote gerado por ``build_3mf`` (confere o MD5)."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        gcode = z.read("Metadata/plate_1.gcode")
        md5 = z.read("Metadata/plate_1.gcode.md5").decode().strip()
    if hashlib.md5(gcode).hexdigest().upper() != md5:  # noqa: S324
        raise ValueError("MD5 do G-code não confere")
    return gcode.decode("utf-8")

"""Fixtures pequenas compartilhadas pelos testes do catálogo (fork gabriel)."""

import io
import struct
import zipfile


def valid_stl() -> bytes:
    return b"\0" * 80 + struct.pack("<I", 1) + b"\0" * 50


def valid_3mf() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(
            "3D/3dmodel.model", '<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"/>'
        )
        archive.writestr("Metadata/project_settings.config", '{"filament_colour":["#FF0000","#00FF00"]}')
    return output.getvalue()

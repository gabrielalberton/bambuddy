"""custom(thumb-color): miniaturas renderizadas pelo Bambuddy com a cor real do filamento, não verde fixo.

O upstream pinta toda miniatura que ele mesmo renderiza (STL, 3MF sem PNG embutido, fatiado sem PNG)
de verde Bambu. Aqui, sem editar o upstream:

- 3MF/fatiado: a cor do filamento principal do próprio arquivo. Em fatiado, o filamento com mais gramas
  no ``slice_info.config``; senão, o extrusor mais usado pelos objetos (``model_settings.config``) mapeado
  em ``filament_colour`` do ``project_settings.config``.
- STL (sem cor): cinza claro neutro.

Multicolor fica com a cor principal: pintar por objeto exigiria reescrever o carregador de geometria.
"""

from __future__ import annotations

import io
import json
import logging
import re
import threading
import zipfile
from collections import Counter

log = logging.getLogger("custom.thumb_color")

NEUTRAL = "#D4D4D4"
_HEX = re.compile(r"^#?([0-9a-fA-F]{6})([0-9a-fA-F]{2})?$")
_local = threading.local()


DARK_FLOOR = "#4A4A4A"  # o fundo da miniatura é quase preto: filamento preto sumiria


def _norm(color: str | None) -> str | None:
    if not color:
        return None
    m = _HEX.match(color.strip())
    if not m:
        return None
    hex6 = m.group(1).upper()
    r, g, b = (int(hex6[i : i + 2], 16) / 255 for i in (0, 2, 4))
    if 0.2126 * r + 0.7152 * g + 0.0722 * b < 0.12:
        return DARK_FLOOR
    return f"#{hex6}"


def model_color(threemf_bytes: bytes) -> str:
    try:
        zf = zipfile.ZipFile(io.BytesIO(threemf_bytes))
    except zipfile.BadZipFile:
        return NEUTRAL
    with zf:
        names = set(zf.namelist())
        # fatiado: o filamento que mais pesa
        if "Metadata/slice_info.config" in names:
            text = zf.read("Metadata/slice_info.config").decode("utf-8", "ignore")
            best = None
            for m in re.finditer(r"<filament\b([^>]*)/?>", text):
                attrs = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
                try:
                    grams = float(attrs.get("used_g") or 0)
                except ValueError:
                    grams = 0
                color = _norm(attrs.get("color"))
                if color and (best is None or grams > best[0]):
                    best = (grams, color)
            if best:
                return best[1]
        colours: list[str] = []
        if "Metadata/project_settings.config" in names:
            try:
                ps = json.loads(zf.read("Metadata/project_settings.config"))
                colours = [c for c in (ps.get("filament_colour") or []) if isinstance(c, str)]
            except ValueError:
                colours = []
        if not colours:
            return NEUTRAL
        extruders: Counter[int] = Counter()
        if "Metadata/model_settings.config" in names:
            text = zf.read("Metadata/model_settings.config").decode("utf-8", "ignore")
            for obj in re.finditer(r"<object\b.*?</object>", text, re.S):
                m = re.search(r'<metadata key="extruder" value="(\d+)"', obj.group(0))
                if m:
                    extruders[int(m.group(1))] += 1
        idx = (extruders.most_common(1)[0][0] if extruders else 1) - 1
        return _norm(colours[idx] if 0 <= idx < len(colours) else colours[0]) or NEUTRAL


def current_color() -> str | None:
    return getattr(_local, "color", None)


_originals: dict = {}


def uninstall() -> None:
    """Volta os renderizadores do upstream ao original (testes)."""
    from backend.app.services import plate_thumbnail, stl_thumbnail

    if not getattr(plate_thumbnail, "_custom_thumb_color", False):
        return
    stl_thumbnail.BAMBU_GREEN = _originals["stl_green"]
    plate_thumbnail._render_model_thumbnails = _originals["models"]
    plate_thumbnail._render_at_size = _originals["size"]
    plate_thumbnail._custom_thumb_color = False


def install() -> None:
    """Liga as cores nos renderizadores do upstream (idempotente)."""
    from backend.app.services import plate_thumbnail, stl_thumbnail

    if getattr(plate_thumbnail, "_custom_thumb_color", False):
        return
    _originals.update(
        stl_green=stl_thumbnail.BAMBU_GREEN,
        models=plate_thumbnail._render_model_thumbnails,
        size=plate_thumbnail._render_at_size,
    )
    stl_thumbnail.BAMBU_GREEN = NEUTRAL  # STL não tem cor

    orig_models = plate_thumbnail._render_model_thumbnails
    orig_size = plate_thumbnail._render_at_size

    def render_model_thumbnails(threemf_bytes: bytes):
        _local.color = model_color(threemf_bytes)
        try:
            return orig_models(threemf_bytes)
        finally:
            _local.color = None

    def render_at_size(poly3d, size, Poly3DCollection, shade_kw):  # noqa: N803 - mesma assinatura do upstream
        color = current_color()
        if color is None:
            return orig_size(poly3d, size, Poly3DCollection, shade_kw)

        def colored(*args, **kwargs):
            kwargs["facecolors"] = color
            kwargs["edgecolors"] = color
            return Poly3DCollection(*args, **kwargs)

        return orig_size(poly3d, size, colored, shade_kw)

    plate_thumbnail._render_model_thumbnails = render_model_thumbnails
    plate_thumbnail._render_at_size = render_at_size
    plate_thumbnail._custom_thumb_color = True

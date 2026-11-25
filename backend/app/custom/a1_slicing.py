"""Keep slicing on the A1 for installations that enable the lock."""

from __future__ import annotations

import json
import os
import re
import zipfile
from dataclasses import dataclass
from io import BytesIO
from typing import TYPE_CHECKING

from fastapi import HTTPException

from backend.app.custom.printer_prefs.router import NOZZLE_OPTIONS
from backend.app.schemas.slicer import PresetRef, SliceRequest
from backend.app.utils.printer_models import normalize_printer_model, normalize_printer_model_id
from backend.app.utils.slicer_strings import first_slicer_string

if TYPE_CHECKING:
    from backend.app.schemas.slicer_presets import UnifiedPreset

_PROJECT_SETTINGS = "Metadata/project_settings.config"
_PLATE_GCODE = re.compile(r"Metadata/plate_\d+\.gcode", re.IGNORECASE)
_GCODE_SETTING = re.compile(rb"^;[ \t]*(printer_model|nozzle_diameter)[ \t]*=[ \t]*([^\r\n]+)", re.MULTILINE)
_GCODE_SCAN_BYTES = 128 * 1024
# Bambu names every system preset for the machine it was made for: "... @BBL A1" is the
# 0.4 nozzle, "... @BBL A1 0.2 nozzle" the 0.2 one. Measured 2026-11-25 against the
# sidecar's 233 process / 1928 filament presets: the name and `compatible_printers`
# agree on every A1 0.2 / 0.4 preset.
_A1_PRESET_NAME = re.compile(r"@BBL A1(?: (?P<nozzle>\d\.\d) nozzle)?$")


def enabled() -> bool:
    return os.environ.get("BAMBUDDY_CUSTOM_A1_SLICING") == "1"


def is_a1(model: str | None) -> bool:
    return normalize_printer_model_id(normalize_printer_model(model)) == "A1"


def _nozzle_diameter(raw: object) -> str | None:
    value = raw[0] if isinstance(raw, list) and raw else raw
    if isinstance(value, (str, int, float)):
        try:
            diameter = float(value)
        except ValueError:
            return None
        if diameter in (0.2, 0.4, 0.6, 0.8):
            return f"{diameter:.1f}"
    return None


def _project_settings(archive: zipfile.ZipFile) -> dict:
    with archive.open(_PROJECT_SETTINGS) as source:
        parsed = json.loads(source.read(4 * 1024 * 1024))
    return parsed if isinstance(parsed, dict) else {}


def _gcode_settings(samples: tuple[bytes, ...]) -> dict[str, str]:
    return {
        key.decode(): value.decode("utf-8", errors="replace").strip()
        for sample in samples
        for key, value in _GCODE_SETTING.findall(sample)
    }


@dataclass(frozen=True)
class A1SliceTarget:
    diameter: str

    @property
    def preset(self) -> PresetRef:
        return PresetRef(source="standard", id=f"Bambu Lab A1 {self.diameter} nozzle")

    def matches(self, settings: dict) -> bool:
        return is_a1(first_slicer_string(settings.get("printer_model"))) and (
            _nozzle_diameter(settings.get("nozzle_diameter")) == self.diameter
        )

    def can_use_embedded(self, content: bytes, filename: str) -> bool:
        if not filename.lower().endswith(".3mf"):
            return False
        try:
            with zipfile.ZipFile(BytesIO(content)) as archive:
                return self.matches(_project_settings(archive))
        except (zipfile.BadZipFile, KeyError, OSError, ValueError):
            return False

    def check_presets(self, request: SliceRequest) -> None:
        """Refuse a bundled process / filament preset made for another printer or nozzle."""
        refs = [request.process_preset, *request.filament_presets]
        wrong = [
            ref.id
            for ref in refs
            if ref is not None and ref.source == "standard" and not _named_for_a1(ref.id, (self.diameter,))
        ]
        if wrong:
            raise HTTPException(
                422,
                f"Perfil que não é da Bambu Lab A1 com bico de {self.diameter} mm: {', '.join(wrong)}. "
                "Escolha um perfil da A1.",
            )

    def apply(self, request: SliceRequest, can_use_embedded: bool) -> SliceRequest:
        self.check_presets(request)
        return request.model_copy(
            update={
                "printer_preset": self.preset,
                "use_embedded_settings": request.use_embedded_settings and can_use_embedded,
            }
        )

    def validate_output(self, content: bytes, *, export_3mf: bool) -> None:
        if not export_3mf:
            if self.matches(_gcode_settings((content[:_GCODE_SCAN_BYTES], content[-_GCODE_SCAN_BYTES:]))):
                return
        else:
            try:
                with zipfile.ZipFile(BytesIO(content)) as archive:
                    plates = [name for name in archive.namelist() if _PLATE_GCODE.fullmatch(name)]
                    if (
                        plates
                        and self.matches(_project_settings(archive))
                        and all(self._matches_plate(archive, name) for name in plates)
                    ):
                        return
            except (zipfile.BadZipFile, KeyError, OSError, ValueError):
                pass
        raise HTTPException(
            502,
            f"O fatiador não confirmou a Bambu Lab A1 com bico de {self.diameter} mm. O arquivo não foi salvo.",
        )

    def _matches_plate(self, archive: zipfile.ZipFile, name: str) -> bool:
        with archive.open(name) as plate:
            head = plate.read(_GCODE_SCAN_BYTES)
        if not head:
            return False
        # Some slicers put the configuration at the end of the G-code. The
        # generated 3MF already confirmed the target. Reject contradictory
        # per-plate settings whenever the slicer includes them in the header.
        fields = _gcode_settings((head,))
        return ("printer_model" not in fields or is_a1(fields["printer_model"])) and (
            "nozzle_diameter" not in fields or _nozzle_diameter(fields["nozzle_diameter"]) == self.diameter
        )


def a1_printer_names(diameters: tuple[str, ...] = NOZZLE_OPTIONS) -> set[str]:
    return {f"Bambu Lab A1 {diameter} nozzle" for diameter in diameters}


def _named_for_a1(name: str | None, diameters: tuple[str, ...]) -> bool:
    match = _A1_PRESET_NAME.search((name or "").strip())
    return match is not None and (match.group("nozzle") or "0.4") in diameters


def preset_fits_a1(preset: UnifiedPreset, slot: str, diameters: tuple[str, ...] = NOZZLE_OPTIONS) -> bool:
    """Whether a preset is the A1's own, for one of its nozzles (0.2 / 0.4 by default)."""
    printers = a1_printer_names(diameters)
    if slot == "printer":
        return preset.name in printers or (preset.inherits or "") in printers
    if preset.compatible_printers:
        return any(name in printers for name in preset.compatible_printers)
    return _named_for_a1(preset.name, diameters) or _named_for_a1(preset.inherits, diameters)


def only_a1_presets(tier: dict[str, list[UnifiedPreset]]) -> dict[str, list[UnifiedPreset]]:
    """Drop every preset made for another printer (or for an A1 nozzle not owned here).

    The A1 is the only printer in this installation. Listing other machines' presets
    (1928 filaments, 233 processes, 70 printers) only offered wrong choices.
    """
    if not enabled():
        return tier
    return {slot: [preset for preset in presets if preset_fits_a1(preset, slot)] for slot, presets in tier.items()}


def fixed_a1_presets() -> dict[str, PresetRef] | None:
    if not enabled():
        return None
    return {diameter: A1SliceTarget(diameter).preset for diameter in NOZZLE_OPTIONS}


def fixed_a1_target(diameter: str | None) -> A1SliceTarget | None:
    if not enabled():
        return None
    if diameter is None or diameter not in NOZZLE_OPTIONS:
        options = " ou ".join(f"{size.replace('.', ',')} mm" for size in NOZZLE_OPTIONS)
        raise HTTPException(422, f"Escolha o bico de {options} da Bambu Lab A1 para fatiar.")
    return A1SliceTarget(diameter)

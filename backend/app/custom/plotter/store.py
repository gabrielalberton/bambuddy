"""Persistência do plotter em JSON/arquivos sob ``<dados>/custom/plotter`` (nada em tabela do upstream).

- ``settings.json``: por impressora, as canetas (perfis), a caneta ativa, o papel e a última posição;
- ``drawings/<id>/``: imagem enviada, prévia e traços vetorizados;
- ``plans/<id>/``: o ``.gcode.3mf`` validado e o resumo do plano.

Desenhos e planos são descartáveis: só os mais recentes ficam.
"""

from __future__ import annotations

import json
import pathlib
import re
import secrets
import shutil
import time

from .engine import MOUNTS, Paper, PenProfile, Placement, ProfileError

KEEP_DRAWINGS = 12
KEEP_PLANS = 12
_ID = re.compile(r"^[a-f0-9]{12}$")
_PEN_ID = re.compile(r"^[a-z0-9_-]{1,32}$")
MAX_PENS = 12


def base_dir() -> pathlib.Path:
    from backend.app.core.config import settings

    return pathlib.Path(settings.base_dir) / "custom" / "plotter"


def new_id() -> str:
    return secrets.token_hex(6)


def _write_json(path: pathlib.Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False))
    tmp.replace(path)


def _read_json(path: pathlib.Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- ajustes por impressora
# um perfil inicial por modo do suporte; cada um guarda a própria calibração (o contato e a curva de pressão
# com mola não valem sem mola: a caneta muda de altura ao ser travada e a ponta passa a ser a única "mola")
DEFAULT_PEN_IDS = {"spring": "padrao", "rigid": "sem-mola"}


def default_settings() -> dict:
    return {
        "pens": {pen_id: PenProfile.for_mount(mount).to_dict() for mount, pen_id in DEFAULT_PEN_IDS.items()},
        "active_pen": DEFAULT_PEN_IDS["spring"],
        "paper": Paper().to_dict(),
        "placement": None,
    }


def normalize_settings(doc: dict | None) -> dict:
    """Valida e completa o documento; levanta ``ProfileError`` com o motivo."""
    doc = doc if isinstance(doc, dict) else {}
    pens_in = doc.get("pens")
    if not isinstance(pens_in, dict) or not pens_in:
        pens_in = default_settings()["pens"]
    if len(pens_in) > MAX_PENS:
        raise ProfileError(f"no máximo {MAX_PENS} canetas")
    pens: dict[str, dict] = {}
    for pen_id, raw in pens_in.items():
        if not isinstance(pen_id, str) or not _PEN_ID.match(pen_id):
            raise ProfileError("identificador de caneta inválido")
        pens[pen_id] = PenProfile.from_dict(raw if isinstance(raw, dict) else {}).to_dict()
    for mount, pen_id in DEFAULT_PEN_IDS.items():  # garante um perfil de cada modo (ajustes antigos só tinham um)
        if mount in MOUNTS and not any(p["mount"] == mount for p in pens.values()) and pen_id not in pens:
            if len(pens) < MAX_PENS:
                pens[pen_id] = PenProfile.for_mount(mount).to_dict()
    active = doc.get("active_pen")
    if active not in pens:
        active = next(iter(pens))
    placement = doc.get("placement")
    return {
        "pens": pens,
        "active_pen": active,
        "paper": Paper.from_dict(doc.get("paper") if isinstance(doc.get("paper"), dict) else None).to_dict(),
        "placement": Placement.from_dict(placement).to_dict() if isinstance(placement, dict) else None,
    }


def load_settings(printer_id: int) -> dict:
    data = _read_json(base_dir() / "settings.json") or {}
    try:
        return normalize_settings(data.get(str(printer_id)))
    except ProfileError:
        return default_settings()


def save_settings(printer_id: int, doc: dict) -> dict:
    clean = normalize_settings(doc)
    path = base_dir() / "settings.json"
    data = _read_json(path) or {}
    data[str(printer_id)] = clean
    _write_json(path, data)
    return clean


def get_pen(printer_id: int, pen_id: str | None = None) -> tuple[str, PenProfile]:
    doc = load_settings(printer_id)
    pid = pen_id if pen_id in doc["pens"] else doc["active_pen"]
    return pid, PenProfile.from_dict(doc["pens"][pid])


def update_pen(printer_id: int, pen_id: str, changes: dict) -> dict:
    doc = load_settings(printer_id)
    if pen_id not in doc["pens"]:
        raise ProfileError("caneta não encontrada")
    doc["pens"][pen_id] = {**doc["pens"][pen_id], **changes}
    return save_settings(printer_id, doc)


# ---------------------------------------------------------------- desenhos e planos
def _item_dir(kind: str, item_id: str) -> pathlib.Path:
    if not _ID.match(item_id or ""):
        raise KeyError(item_id)
    return base_dir() / kind / item_id


def _prune(kind: str, keep: int) -> None:
    root = base_dir() / kind
    try:
        dirs = sorted((d for d in root.iterdir() if d.is_dir()), key=lambda d: d.stat().st_mtime, reverse=True)
    except OSError:
        return
    for old in dirs[keep:]:
        shutil.rmtree(old, ignore_errors=True)


def save_drawing(item_id: str, drawing: dict, source: bytes | None = None, preview: bytes | None = None) -> None:
    folder = _item_dir("drawings", item_id)
    folder.mkdir(parents=True, exist_ok=True)
    if source is not None:
        (folder / "source.bin").write_bytes(source)
    if preview is not None:
        (folder / "preview.jpg").write_bytes(preview)
    _write_json(folder / "drawing.json", drawing)
    folder.touch()
    _prune("drawings", KEEP_DRAWINGS)


def load_drawing(item_id: str) -> dict | None:
    try:
        return _read_json(_item_dir("drawings", item_id) / "drawing.json")
    except KeyError:
        return None


def drawing_file(item_id: str, name: str) -> pathlib.Path | None:
    try:
        path = _item_dir("drawings", item_id) / name
    except KeyError:
        return None
    return path if path.is_file() else None


def save_plan(item_id: str, summary: dict, package: bytes | None) -> None:
    folder = _item_dir("plans", item_id)
    folder.mkdir(parents=True, exist_ok=True)
    if package is not None:
        (folder / "plot.gcode.3mf").write_bytes(package)
    _write_json(folder / "plan.json", {**summary, "saved_at": time.time()})
    _prune("plans", KEEP_PLANS)


def load_plan(item_id: str) -> dict | None:
    try:
        return _read_json(_item_dir("plans", item_id) / "plan.json")
    except KeyError:
        return None


def plan_package(item_id: str) -> pathlib.Path | None:
    try:
        path = _item_dir("plans", item_id) / "plot.gcode.3mf"
    except KeyError:
        return None
    return path if path.is_file() else None

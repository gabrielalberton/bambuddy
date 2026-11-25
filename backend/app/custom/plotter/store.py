"""Persistência do plotter em JSON/arquivos sob ``<dados>/custom/plotter`` (nada em tabela do upstream).

- ``settings.json``: por impressora, as canetas (perfis), a caneta ativa, o papel e a última posição;
- ``drawings/<id>/``: imagem enviada, prévia, miniatura, traços vetorizados e ``info.json`` (nome, datas,
  opções de vetorização), que alimenta o histórico de envios;
- ``plans/<id>/``: o ``.gcode.3mf`` validado e o resumo do plano.

Desenhos e planos são descartáveis: só os mais recentes ficam (os desenhos também têm teto de disco).
"""

from __future__ import annotations

import base64
import json
import pathlib
import re
import secrets
import shutil
import time

from .engine import MOUNTS, Paper, PenProfile, Placement, ProfileError

KEEP_DRAWINGS = 30
KEEP_DRAWINGS_BYTES = 300 * 1024 * 1024  # imagens originais somadas; o resto do histórico é pequeno
KEEP_PLANS = 12
THUMB_SIDE = 160
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
    # BIC é a caneta padrão nos dois modos (PenProfile.for_mount usa DEFAULT_PEN_TYPE)
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


def _prune(kind: str, keep: int, max_bytes: int | None = None) -> None:
    """Mantém os ``keep`` mais recentes; com ``max_bytes``, apaga também os mais antigos acima do teto."""
    root = base_dir() / kind
    try:
        dirs = sorted((d for d in root.iterdir() if d.is_dir()), key=lambda d: d.stat().st_mtime, reverse=True)
    except OSError:
        return
    total = 0
    for index, folder in enumerate(dirs):
        if max_bytes is not None:
            total += sum(f.stat().st_size for f in folder.iterdir() if f.is_file())
        if index >= keep or (max_bytes is not None and index > 0 and total > max_bytes):
            shutil.rmtree(folder, ignore_errors=True)


def save_drawing(
    item_id: str,
    drawing: dict,
    source: bytes | None = None,
    preview: bytes | None = None,
    thumb: bytes | None = None,
    options: dict | None = None,
) -> None:
    folder = _item_dir("drawings", item_id)
    folder.mkdir(parents=True, exist_ok=True)
    if source is not None:
        (folder / "source.bin").write_bytes(source)
    if preview is not None:
        (folder / "preview.jpg").write_bytes(preview)
    if thumb:
        (folder / "thumb.jpg").write_bytes(thumb)
    _write_json(folder / "drawing.json", drawing)
    old = _read_json(folder / "info.json") or {}
    now = time.time()
    _write_json(
        folder / "info.json",
        {
            **_info_from(drawing, old.get("created_at") or now),
            "updated_at": now,
            "options": options if options is not None else old.get("options") or {},
        },
    )
    folder.touch()
    _prune("drawings", KEEP_DRAWINGS, KEEP_DRAWINGS_BYTES)


def _info_from(drawing: dict, created_at: float) -> dict:
    meta = drawing.get("meta") or {}
    return {
        "name": str(meta.get("name") or "desenho"),
        "created_at": created_at,
        "strokes": len(drawing.get("strokes") or []),
        "width": drawing.get("width"),
        "height": drawing.get("height"),
    }


def make_thumb(image: bytes) -> bytes | None:
    """Miniatura JPEG (lado maior ``THUMB_SIDE``) de uma prévia; None se não der para ler."""
    import cv2
    import numpy as np

    img = cv2.imdecode(np.frombuffer(image, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return None
    h, w = img.shape[:2]
    scale = min(1.0, THUMB_SIDE / max(h, w))
    if scale < 1.0:
        img = cv2.resize(img, (max(1, round(w * scale)), max(1, round(h * scale))), interpolation=cv2.INTER_AREA)
    ok, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 72])
    return jpg.tobytes() if ok else None


def list_drawings() -> list[dict]:
    """Histórico de envios, do mais recente ao mais antigo, com miniatura embutida (data URL).

    Desenhos de antes do histórico ganham ``info.json`` e miniatura na primeira listagem.
    """
    root = base_dir() / "drawings"
    try:
        folders = [d for d in root.iterdir() if d.is_dir() and _ID.match(d.name)]
    except OSError:
        return []
    items = []
    for folder in folders:
        info = _read_json(folder / "info.json")
        if not isinstance(info, dict):
            drawing = _read_json(folder / "drawing.json")
            if not isinstance(drawing, dict):
                continue
            stamp = folder.stat().st_mtime
            info = {**_info_from(drawing, stamp), "updated_at": stamp, "options": {}}
            _write_json(folder / "info.json", info)
        thumb = folder / "thumb.jpg"
        preview = folder / "preview.jpg"
        if not thumb.is_file() and preview.is_file():
            data = make_thumb(preview.read_bytes())
            if data:
                thumb.write_bytes(data)
        items.append(
            {
                "id": folder.name,
                **info,
                "can_revectorize": (folder / "source.bin").is_file(),
                "thumb": "data:image/jpeg;base64," + base64.b64encode(thumb.read_bytes()).decode()
                if thumb.is_file()
                else None,
            }
        )
    items.sort(key=lambda item: item.get("updated_at") or 0, reverse=True)
    return items


def delete_drawing(item_id: str) -> bool:
    try:
        folder = _item_dir("drawings", item_id)
    except KeyError:
        return False
    if not folder.is_dir():
        return False
    shutil.rmtree(folder, ignore_errors=True)
    return True


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

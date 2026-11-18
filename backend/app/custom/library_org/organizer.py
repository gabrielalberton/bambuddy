"""custom(library-org): organiza a biblioteca por modelo, sem perder nada.

Regras (custom/docs/biblioteca-organizacao.md):

- Só mexe em arquivo que está **solto**: na raiz ou direto numa pasta de importação de topo
  ("MakerWorld", "Printables"). Arquivo que o dono pôs numa pasta dele não é tocado.
- Mexer = mudar ``folder_id`` e, em fatiados com nome genérico, o ``filename`` exibido. Os bytes ficam
  onde estão (``file_path`` é um hash), nada é apagado.
- MakerWorld/Printables: uma pasta por modelo, ``<Fonte>/<título do modelo>``. O título vem do
  ``Title`` do 3MF; sem ele, do nome do arquivo. Perfis diferentes do mesmo modelo caem na mesma pasta.
- Fatiado (``sliced_from_library_file_id``): vai para a pasta da origem, com nome que diz o que é:
  ``<origem> - A1 0.4mm 0.20mm PLA 2h16m.gcode.3mf``.
- Arquivo próprio solto na raiz (sem fonte): ``Meus modelos/<família>``, família = maior prefixo comum
  de nome entre os arquivos (``Calib-fluxo3-...-rosa.stl``, ``...-rosa.gcode.3mf``,
  ``...-rosa-frente-dir-pronto.gcode.3mf`` → ``Calib-fluxo3-...-rosa``).
- A pasta de cada modelo fica gravada no estado (``data/custom/library_org.json``), então se o dono
  renomear ou mover a pasta, os próximos arquivos do modelo continuam indo para ela.
"""

from __future__ import annotations

import json
import logging
import pathlib
import re
import zipfile
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("custom.library_org")

IMPORT_FOLDERS = {"makerworld": "MakerWorld", "printables": "Printables"}
OWN_FOLDER = "Meus modelos"
MAX_NAME = 120


def state_path() -> pathlib.Path:
    from backend.app.core.config import settings

    return pathlib.Path(settings.base_dir) / "custom" / "library_org.json"


def load_state() -> dict[str, Any]:
    try:
        return json.loads(state_path().read_text())
    except (OSError, ValueError):
        return {}


def save_state(state: dict[str, Any]) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True, ensure_ascii=False))
    tmp.replace(path)


# ----- nomes -----

_EXT_RE = re.compile(r"(\.gcode)?\.(3mf|stl|step|stp|obj)$", re.I)


def stem(filename: str) -> str:
    return _EXT_RE.sub("", filename).strip()


def family_stem(filename: str) -> str:
    s = stem(filename)
    return re.sub(r"-pronto$", "", s, flags=re.I)


def clean_folder_name(name: str) -> str:
    name = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", " ", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:MAX_NAME].rstrip() or "Sem nome"


def source_key(source_type: str | None, source_url: str | None) -> tuple[str, str] | None:
    """(fonte, id do modelo) de um arquivo importado."""
    if not source_type or not source_url:
        return None
    st = source_type.lower()
    if st == "makerworld":
        m = re.search(r"/models/(\d+)", source_url)
    elif st == "printables":
        m = re.search(r"/model/(\d+)", source_url)
    else:
        return None
    return (st, m.group(1)) if m else None


def model_title_from_3mf(path: pathlib.Path | None) -> str | None:
    if path is None or not path.exists() or path.suffix.lower() != ".3mf":
        return None
    try:
        with zipfile.ZipFile(path) as zf, zf.open("3D/3dmodel.model") as fh:
            head = fh.read(200_000).decode("utf-8", "ignore")
    except (OSError, KeyError, zipfile.BadZipFile):
        return None
    m = re.search(r'<metadata name="Title">([^<]+)</metadata>', head)
    if not m:
        return None
    import html

    title = html.unescape(m.group(1)).strip()
    return title or None


def _fmt_time(seconds: Any) -> str:
    try:
        s = int(float(seconds))
    except (TypeError, ValueError):
        return ""
    h, m = divmod(s // 60, 60)
    return f"{h}h{m:02d}m" if h else f"{m}m"


def slice_label(meta: dict[str, Any]) -> str:
    parts = []
    if meta.get("sliced_for_model"):
        parts.append(str(meta["sliced_for_model"]))
    if meta.get("nozzle_diameter"):
        parts.append(f"{meta['nozzle_diameter']}mm")
    if meta.get("layer_height"):
        try:
            parts.append(f"{float(meta['layer_height']):.2f}mm")
        except (TypeError, ValueError):
            pass
    if meta.get("filament_type"):
        parts.append(str(meta["filament_type"]).split(";")[0])
    t = _fmt_time(meta.get("print_time_seconds"))
    if t:
        parts.append(t)
    return " ".join(parts)


def sliced_name(source_filename: str, meta: dict[str, Any]) -> str:
    label = slice_label(meta)
    base = stem(source_filename)
    return f"{base} - {label}.gcode.3mf" if label else f"{base}.gcode.3mf"


def is_generic_slice_name(filename: str, source_filename: str) -> bool:
    """Nome que o fatiador deu (igual ao da origem): pode trocar sem apagar nada que o dono escreveu."""
    return stem(filename).lower() == stem(source_filename).lower()


# ----- plano -----


@dataclass
class Move:
    file_id: int
    filename: str
    to_path: list[str]  # pasta destino, do topo para baixo
    new_filename: str | None = None
    reason: str = ""
    model_key: str | None = None


@dataclass
class Plan:
    moves: list[Move] = field(default_factory=list)
    skipped: list[tuple[int, str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "moves": [m.__dict__ for m in self.moves],
            "skipped": [{"file_id": i, "filename": n, "why": w} for i, n, w in self.skipped],
        }


@dataclass
class FileRow:
    id: int
    filename: str
    folder_id: int | None
    source_type: str | None
    source_url: str | None
    meta: dict[str, Any]
    is_external: bool
    disk_path: pathlib.Path | None = None


@dataclass
class FolderRow:
    id: int
    name: str
    parent_id: int | None
    is_external: bool
    project_id: int | None
    archive_id: int | None


def build_plan(
    files: list[FileRow],
    folders: dict[int, FolderRow],
    state: dict[str, Any],
    title_of=model_title_from_3mf,
) -> Plan:
    plan = Plan()
    by_id = {f.id: f for f in files}
    top_import = {
        fid: key
        for key, name in IMPORT_FOLDERS.items()
        for fid, fo in folders.items()
        if fo.parent_id is None and fo.name == name and not fo.is_external
    }

    def loose(f: FileRow) -> bool:
        if f.is_external:
            return False
        return f.folder_id is None or f.folder_id in top_import

    # 1) arquivos importados: uma pasta por modelo
    dest_of: dict[int, list[str]] = {}
    for f in files:
        key = source_key(f.source_type, f.source_url)
        if not key:
            continue
        mk = f"{key[0]}:{key[1]}"
        known = state.get("models", {}).get(mk) or {}
        # a pasta já criada para o modelo vale mesmo se o dono renomeou ou moveu
        path = _path_of(known.get("folder_id"), folders) if known.get("folder_id") in folders else None
        if path is None:
            folder_name = known.get("name")
            if not folder_name:
                folder_name = clean_folder_name(title_of(f.disk_path) or stem(f.filename))
                state.setdefault("models", {}).setdefault(mk, {})["name"] = folder_name
            path = [IMPORT_FOLDERS[key[0]], folder_name]
        dest_of[f.id] = path
        if loose(f):
            plan.moves.append(Move(f.id, f.filename, path, reason="modelo importado", model_key=mk))

    # 2) arquivos próprios soltos na raiz: famílias por prefixo
    own = [
        f
        for f in files
        if f.folder_id is None
        and not f.is_external
        and not source_key(f.source_type, f.source_url)
        and not f.meta.get("sliced_from_library_file_id")
    ]
    stems = sorted({family_stem(f.filename) for f in own}, key=len)
    root_of: dict[str, str] = {}
    for s in stems:
        parent = next((r for r in stems if r != s and len(r) < len(s) and s.startswith(r + "-")), None)
        root_of[s] = root_of.get(parent, parent) if parent else s
    fam_of = {f.id: root_of.get(family_stem(f.filename), family_stem(f.filename)) for f in own}
    # fatiados contam como membros da família da origem (uma família de 1 arquivo + 1 fatiado já vira pasta)
    fam_size: dict[str, int] = {}
    for f in own:
        fam_size[fam_of[f.id]] = fam_size.get(fam_of[f.id], 0) + 1
    for f in files:
        sid = f.meta.get("sliced_from_library_file_id")
        try:
            src_fam = fam_of.get(int(sid)) if sid is not None else None
        except (TypeError, ValueError):
            src_fam = None
        if src_fam:
            fam_size[src_fam] += 1
    for f in own:
        fam = fam_of[f.id]
        path = [OWN_FOLDER, clean_folder_name(fam)] if fam_size[fam] > 1 else [OWN_FOLDER]
        dest_of[f.id] = path
        plan.moves.append(Move(f.id, f.filename, path, reason="arquivo próprio"))

    # 3) fatiados: junto da origem, com nome que diz o que é
    def source_of(f: FileRow) -> FileRow | None:
        sid = f.meta.get("sliced_from_library_file_id")
        try:
            return by_id.get(int(sid)) if sid is not None else None
        except (TypeError, ValueError):
            return None

    for f in files:
        src = source_of(f)
        if src is None:
            continue
        # origem fatiada de outra fatiada: sobe até a raiz da linhagem
        seen = {f.id}
        while (up := source_of(src)) is not None and up.id not in seen:
            seen.add(src.id)
            src = up
        new_name = None
        if is_generic_slice_name(f.filename, src.filename):
            candidate = sliced_name(src.filename, f.meta)
            if candidate != f.filename:
                new_name = candidate
        target = dest_of.get(src.id)
        if target is None:
            # origem está numa pasta do dono: o fatiado vai para lá também, se estiver solto
            target = _path_of(src.folder_id, folders) if src.folder_id else None
        if not loose(f):
            if new_name:
                plan.moves.append(Move(f.id, f.filename, [], new_filename=new_name, reason="só renomear"))
            continue
        if target is None:
            plan.skipped.append((f.id, f.filename, "origem sem pasta definida"))
            continue
        plan.moves.append(Move(f.id, f.filename, target, new_filename=new_name, reason=f"fatiado de #{src.id}"))
    return plan


def _path_of(folder_id: int | None, folders: dict[int, FolderRow]) -> list[str] | None:
    path: list[str] = []
    seen = set()
    while folder_id is not None and folder_id in folders and folder_id not in seen:
        seen.add(folder_id)
        fo = folders[folder_id]
        path.insert(0, fo.name)
        folder_id = fo.parent_id
    return path or None


def dedupe_names(plan: Plan, existing: dict[tuple[str, ...], set[str]]) -> None:
    """Nomes repetidos na mesma pasta ganham " (2)", " (3)"... na ordem dos ids."""
    for mv in sorted(plan.moves, key=lambda m: m.file_id):
        name = mv.new_filename or mv.filename
        key = tuple(mv.to_path)
        taken = existing.setdefault(key, set())
        if name.lower() in taken:
            base, ext = (
                (name[: -len(".gcode.3mf")], ".gcode.3mf")
                if name.lower().endswith(".gcode.3mf")
                else (
                    pathlib.Path(name).stem,
                    pathlib.Path(name).suffix,
                )
            )
            n = 2
            while f"{base} ({n}){ext}".lower() in taken:
                n += 1
            name = f"{base} ({n}){ext}"
            mv.new_filename = name
        taken.add(name.lower())

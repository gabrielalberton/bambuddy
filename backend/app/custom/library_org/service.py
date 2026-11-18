"""custom(library-org): aplica o plano do ``organizer`` no banco (só ``folder_id``/``filename``)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy import select

from .organizer import (
    FileRow,
    FolderRow,
    build_plan,
    dedupe_names,
    load_state,
    save_state,
)

log = logging.getLogger("custom.library_org")

AUTO_SECONDS = 120
_task: asyncio.Task | None = None
_lock = asyncio.Lock()


async def _load(db) -> tuple[list[FileRow], dict[int, FolderRow], dict[int, Any], dict[int, Any]]:
    from backend.app.api.routes.library import to_absolute_path
    from backend.app.models.library import LibraryFile, LibraryFolder

    folder_objs = {f.id: f for f in (await db.execute(select(LibraryFolder))).scalars().all()}
    folders = {
        f.id: FolderRow(f.id, f.name, f.parent_id, bool(f.is_external), f.project_id, f.archive_id)
        for f in folder_objs.values()
    }
    file_objs = {f.id: f for f in (await db.execute(LibraryFile.active())).scalars().all()}
    files = []
    for f in file_objs.values():
        disk = None
        if not f.is_external and f.filename.lower().endswith(".3mf"):
            try:
                disk = to_absolute_path(f.file_path)
            except Exception:  # noqa: BLE001 - só serve para ler o título
                disk = None
        files.append(
            FileRow(
                f.id,
                f.filename,
                f.folder_id,
                f.source_type,
                f.source_url,
                dict(f.file_metadata or {}),
                bool(f.is_external),
                disk,
            )
        )
    files.sort(key=lambda r: r.id)
    return files, folders, folder_objs, file_objs


async def run(apply: bool = False) -> dict[str, Any]:
    from backend.app.core.database import async_session
    from backend.app.models.library import LibraryFolder

    async with _lock, async_session() as db:
        state = load_state()
        files, folders, folder_objs, file_objs = await _load(db)
        plan = build_plan(files, folders, state)

        # nomes já ocupados em cada pasta (por arquivos que não vão sair dela)
        moving = {m.file_id for m in plan.moves if m.to_path}
        path_cache: dict[int | None, tuple[str, ...]] = {}

        def path_tuple(folder_id: int | None) -> tuple[str, ...]:
            if folder_id in path_cache:
                return path_cache[folder_id]
            parts: list[str] = []
            fid = folder_id
            while fid is not None and fid in folders:
                parts.insert(0, folders[fid].name)
                fid = folders[fid].parent_id
            path_cache[folder_id] = tuple(parts)
            return path_cache[folder_id]

        existing: dict[tuple[str, ...], set[str]] = {}
        for f in files:
            if f.id not in moving:
                existing.setdefault(path_tuple(f.folder_id), set()).add(f.filename.lower())
        for mv in plan.moves:
            if not mv.to_path:
                mv.to_path = list(path_tuple(file_objs[mv.file_id].folder_id))
        # sem mudança real (já está no lugar e com o nome certo) sai do plano
        plan.moves = [
            m
            for m in plan.moves
            if tuple(m.to_path) != path_tuple(file_objs[m.file_id].folder_id)
            or (m.new_filename and m.new_filename != m.filename)
        ]
        for m in plan.moves:
            if tuple(m.to_path) == path_tuple(file_objs[m.file_id].folder_id):
                existing.setdefault(tuple(m.to_path), set()).discard(m.filename.lower())
        dedupe_names(plan, existing)

        result = plan.as_dict()
        result["applied"] = False
        if not apply or not plan.moves:
            if apply:
                save_state(state)
            return result

        by_path: dict[tuple[str, ...], int | None] = {(): None}
        for fid in folders:
            by_path.setdefault(path_tuple(fid), fid)

        async def ensure(path: list[str]) -> int | None:
            parent: int | None = None
            for i in range(len(path)):
                key = tuple(path[: i + 1])
                if key in by_path and by_path[key] is not None and not folders[by_path[key]].is_external:
                    parent = by_path[key]
                    continue
                parent_obj = folder_objs.get(parent) if parent else None
                new = LibraryFolder(
                    name=path[i],
                    parent_id=parent,
                    created_by_id=parent_obj.created_by_id if parent_obj else None,
                    shared=parent_obj.shared if parent_obj else True,
                )
                db.add(new)
                await db.flush()
                folder_objs[new.id] = new
                folders[new.id] = FolderRow(new.id, new.name, parent, False, None, None)
                by_path[key] = new.id
                path_cache.clear()
                parent = new.id
            return parent

        for mv in plan.moves:
            target = await ensure(mv.to_path)
            obj = file_objs[mv.file_id]
            obj.folder_id = target
            if mv.new_filename:
                obj.filename = mv.new_filename
            if mv.model_key and target is not None:
                state.setdefault("models", {}).setdefault(mv.model_key, {})["folder_id"] = target
        await db.commit()
        save_state(state)
        result["applied"] = True
        log.info("biblioteca organizada: %d arquivo(s)", len(plan.moves))
        return result


async def _auto_loop() -> None:
    while True:
        await asyncio.sleep(AUTO_SECONDS)
        try:
            if load_state().get("auto"):
                await run(apply=True)
        except Exception:  # noqa: BLE001 - a rodada automática nunca pode morrer
            log.exception("organização automática falhou")


def ensure_auto() -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.get_running_loop().create_task(_auto_loop())

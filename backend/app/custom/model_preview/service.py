"""Queue 3MF preview renders and publish thumbnails without changing the upload."""
from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

from sqlalchemy import update

from backend.app.core import database
from backend.app.core.config import settings
from backend.app.core.tasks import spawn_background_task
from backend.app.core.websocket import ws_manager
from backend.app.models.archive import PrintArchive
from backend.app.models.library import LibraryFile

_render_lock = asyncio.Lock()
_jobs: dict[str, asyncio.Task] = {}


def enabled() -> bool:
    return os.environ.get("BAMBUDDY_CUSTOM_MODEL_PREVIEW") == "1"


def _digest(source: Path) -> str:
    with source.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


async def _generate(source: Path, destination: Path) -> None:
    async with _render_lock:
        if (destination / "preview.glb").is_file():
            return
        with tempfile.TemporaryDirectory(dir=destination.parent) as scratch:
            temp = Path(scratch)
            child = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "backend.app.custom.model_preview.render",
                str(source), str(temp / "preview.glb"), str(temp / "thumbnail.png"),
                env={**os.environ, "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"},
                stdout=asyncio.subprocess.DEVNULL,
            )
            try:
                try:
                    status = await asyncio.wait_for(child.wait(), timeout=120)
                except TimeoutError as exc:
                    raise ValueError("3MF preview render timed out") from exc
            finally:
                if child.returncode is None:
                    child.kill()
                    await child.wait()
            if status != 0 or not (temp / "preview.glb").is_file():
                raise ValueError("3MF preview could not be rendered")
            destination.mkdir(exist_ok=True)
            (temp / "thumbnail.png").replace(destination / "thumbnail.png")
            (temp / "preview.glb").replace(destination / "preview.glb")


async def preview_artifacts(source: Path) -> Path:
    digest = await asyncio.to_thread(_digest, source)
    root = settings.base_dir / "custom" / "model-previews-v1"
    root.mkdir(parents=True, exist_ok=True)
    destination = root / digest
    if (destination / "preview.glb").is_file():
        return destination
    task = _jobs.get(digest)
    if task is None:
        task = spawn_background_task(_generate(source, destination), name="render-3mf-preview")
        _jobs[digest] = task
        def retire(done: asyncio.Task) -> None:
            if done.cancelled() or done.exception() is None:
                _jobs.pop(digest, None)
            else:
                # Let polling viewers receive the error before permitting another render.
                asyncio.get_running_loop().call_later(60, _jobs.pop, digest, None)

        task.add_done_callback(retire)
    await asyncio.shield(task)
    return destination


async def publish_thumbnail(
    model, row_id: int, stored_source: str, source: Path, *, replace: bool = False, artifacts: Path | None = None
) -> None:
    if artifacts is None:
        artifacts = await preview_artifacts(source)
    parent = source.parent if model is PrintArchive else settings.archive_dir / "library" / "thumbnails"
    parent.mkdir(parents=True, exist_ok=True)
    dest = parent / f"model-preview-{uuid4().hex}.png"
    predicates = [model.id == row_id, model.file_path == stored_source, model.deleted_at.is_(None)]
    if not replace:
        predicates.append(model.thumbnail_path.is_(None))
    async with database.async_session() as db:
        row_updated = False
        try:
            shutil.copyfile(artifacts / "thumbnail.png", dest)
            result = await db.execute(update(model).where(*predicates).values(thumbnail_path=str(dest.relative_to(settings.base_dir))))
            row_updated = result.rowcount == 1
            await db.commit()
        finally:
            if not row_updated:
                dest.unlink(missing_ok=True)
    if row_updated:
        if model is PrintArchive:
            await ws_manager.send_archive_updated({"id": row_id})
        else:
            # Only a cache invalidation hint; carries no file IDs or metadata.
            await ws_manager.broadcast({"type": "library_thumbnails_changed"})


def queue_model_thumbnail(row: LibraryFile | PrintArchive, source: Path) -> None:
    if enabled() and source.suffix.lower() == ".3mf" and not row.thumbnail_path:
        spawn_background_task(
            publish_thumbnail(type(row), row.id, row.file_path, source), name="publish-3mf-thumbnail",
        )

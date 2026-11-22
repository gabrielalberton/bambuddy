"""Serve the derived 3D geometry under the same permissions as its source."""
import asyncio

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.routes.archives import _ensure_archive_visible
from backend.app.api.routes.library import _ensure_library_file_visible, to_absolute_path
from backend.app.core.auth import RequestPrinterScope, require_ownership_permission
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.core.printer_scope import PrinterScope
from backend.app.models.archive import PrintArchive
from backend.app.models.library import LibraryFile

from .service import enabled, preview_artifacts

router = APIRouter(prefix="/custom/model-preview", tags=["custom-model-preview"])


async def _send(stored_path: str):
    path = to_absolute_path(stored_path)
    if not enabled() or not path or path.suffix.lower() != ".3mf" or not path.is_file():
        raise HTTPException(404, "Model preview is unavailable")
    try:
        artifacts = await asyncio.wait_for(preview_artifacts(path), timeout=2)
    except asyncio.TimeoutError:
        return Response(status_code=202, headers={"Retry-After": "2", "Cache-Control": "no-store"})
    except (OSError, ValueError) as exc:
        raise HTTPException(422, "Could not generate the model preview") from exc
    return FileResponse(artifacts / "preview.glb", media_type="model/gltf-binary", headers={"Cache-Control": "private, no-store"})


@router.get("/archives/{archive_id}")
async def archive_preview(
    archive_id: int,
    db: AsyncSession = Depends(get_db, scope="function"),
    auth=Depends(require_ownership_permission(Permission.ARCHIVES_READ_ALL, Permission.ARCHIVES_READ_OWN)),
    printer_scope: PrinterScope = RequestPrinterScope,
):
    archive = await _ensure_archive_visible(await db.get(PrintArchive, archive_id), *auth, printer_scope)
    stored_path = archive.source_3mf_path or archive.file_path
    await db.close()
    return await _send(stored_path)


@router.get("/library/{file_id}")
async def library_preview(
    file_id: int,
    db: AsyncSession = Depends(get_db, scope="function"),
    auth=Depends(require_ownership_permission(Permission.LIBRARY_READ_ALL, Permission.LIBRARY_READ_OWN)),
):
    entry = _ensure_library_file_visible(await db.get(LibraryFile, file_id), *auth)
    stored_path = entry.file_path
    await db.close()
    return await _send(stored_path)

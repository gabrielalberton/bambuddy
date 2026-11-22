"""Read the print log and the queue outcomes it does not represent as one page."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, case, func, literal, null, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.routes.archives import _visible_archive_clauses
from backend.app.api.routes.print_log import _SORTABLE_COLUMNS
from backend.app.api.routes.print_queue import _QUEUE_ITEM_LOADS, _enrich_response, _history_conditions
from backend.app.core.auth import ApiKeyActor, RequestActor, RequestPrinterScope, require_ownership_permission
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.core.printer_scope import PrinterScope
from backend.app.models.archive import PrintArchive
from backend.app.models.library import LibraryFile
from backend.app.models.print_log import RUN_OPEN, PrintLogEntry
from backend.app.models.print_queue import PrintQueueItem, PrintQueueVariant
from backend.app.models.printer import Printer
from backend.app.models.user import User
from backend.app.schemas.print_log import PrintLogEntrySchema
from backend.app.schemas.print_queue import PrintQueueItemResponse
from backend.app.utils.local_time import to_naive_utc

router = APIRouter(prefix="/custom/print-history", tags=["print-history"])


class HistoryEntry(PrintLogEntrySchema):
    queue_only: bool = False
    queue_item: PrintQueueItemResponse | None = None
    archive_available: bool = False
    archive_has_thumbnail: bool = False
    library_file_available: bool = False


class HistoryResponse(BaseModel):
    items: list[HistoryEntry]
    total: int


def _event_at(model):
    return func.coalesce(model.completed_at, model.started_at, model.created_at)


def _queue_rows(queue_conditions, run_conditions):
    q, run = PrintQueueItem, PrintLogEntry
    # Only suppress a queue row when its run is visible to this caller. Match
    # stored identities before applying any search, date, or status filter.
    represented = (
        select(run.id)
        .where(
            *run_conditions,
            or_(
                run.queue_item_id == q.id,
                and_(run.queue_item_id.is_(None), run.billing_run_id == q.billing_run_id),
            ),
        )
        .correlate(q)
        .exists()
    )
    first_variant = (
        select(LibraryFile.filename)
        .join(PrintQueueVariant, PrintQueueVariant.library_file_id == LibraryFile.id)
        .where(PrintQueueVariant.queue_item_id == q.id, LibraryFile.deleted_at.is_(None))
        .order_by(PrintQueueVariant.position, PrintQueueVariant.id)
        .limit(1)
        .correlate(q)
        .scalar_subquery()
    )
    name = func.coalesce(
        func.nullif(PrintArchive.print_name, ""),
        PrintArchive.filename,
        func.nullif(LibraryFile.file_metadata["print_name"].as_string(), ""),
        LibraryFile.filename,
        first_variant,
    )
    columns = {
        "date": _event_at(q),
        "print_name": name,
        "printer": Printer.name,
        "user": User.username,
        "status": q.status,
        "completed_at": q.completed_at,
    }
    return (
        select(
            literal("queue").label("source"),
            q.id.label("row_id"),
            q.printer_id.label("printer_id"),
            *(columns.get(key, null()).label(key) for key in _SORTABLE_COLUMNS),
        )
        .select_from(q)
        .outerjoin(PrintArchive, and_(PrintArchive.id == q.archive_id, PrintArchive.deleted_at.is_(None)))
        .outerjoin(LibraryFile, and_(LibraryFile.id == q.library_file_id, LibraryFile.deleted_at.is_(None)))
        .outerjoin(Printer, Printer.id == q.printer_id)
        .outerjoin(User, User.id == q.created_by_id)
        .where(*queue_conditions, ~represented)
    )


@router.get("", response_model=HistoryResponse)
async def get_history(
    search: str | None = None,
    printer_id: int | None = None,
    created_by_username: str | None = None,
    status: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(default=25, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    sort_by: str = Query(default="date"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    db: AsyncSession = Depends(get_db, scope="function"),
    auth_result: tuple[User | ApiKeyActor | None, bool] = Depends(
        require_ownership_permission(Permission.ARCHIVES_READ_ALL, Permission.ARCHIVES_READ_OWN)
    ),
    actor: User | ApiKeyActor | None = RequestActor,
    printer_scope: PrinterScope = RequestPrinterScope,
):
    if sort_by not in _SORTABLE_COLUMNS:
        raise HTTPException(400, f"Cannot sort by {sort_by!r}")

    user, can_read_all = auth_result
    run_conditions = [PrintLogEntry.status != RUN_OPEN]
    if not can_read_all:
        run_conditions.append(PrintLogEntry.created_by_id == user.id if user else literal(False))
    if (scope := printer_scope.where(PrintLogEntry.printer_id)) is not None:
        run_conditions.append(scope)
    run_columns = {**_SORTABLE_COLUMNS, "date": _event_at(PrintLogEntry)}
    runs = select(
        literal("run").label("source"),
        PrintLogEntry.id.label("row_id"),
        PrintLogEntry.printer_id.label("printer_id"),
        *(value.label(key) for key, value in run_columns.items()),
    ).where(*run_conditions)
    queue_read_all = actor is None or actor.has_permission(Permission.QUEUE_READ_ALL.value)
    queue_read = queue_read_all or (
        actor is not None and actor.id is not None and actor.has_permission(Permission.QUEUE_READ_OWN.value)
    )
    if queue_read:
        queue_conditions = _history_conditions(actor, queue_read_all, printer_scope, None, None, None)
        rows = union_all(runs, _queue_rows(queue_conditions, run_conditions)).subquery()
    else:
        rows = runs.subquery()

    conditions = []
    if printer_id is not None:
        conditions.append(rows.c.printer_id == printer_id)
    if created_by_username:
        conditions.append(rows.c.user == created_by_username)
    if status:
        statuses = ("aborted", "cancelled") if status == "cancelled" else (status,)
        conditions.append(rows.c.status.in_(statuses))
    if search:
        conditions.append(rows.c.print_name.ilike(f"%{search}%"))
    if (start := to_naive_utc(date_from)) is not None:
        conditions.append(rows.c.date >= start)
    if (end := to_naive_utc(date_to)) is not None:
        conditions.append(rows.c.date <= end)

    sort = rows.c[sort_by]
    if sort_by in {"print_name", "printer", "user"}:
        sort = func.lower(sort)
    elif sort_by == "status":
        sort = case((sort == "aborted", "cancelled"), else_=sort)
    order = sort.asc() if sort_dir == "asc" else sort.desc()
    total = await db.scalar(select(func.count()).select_from(rows).where(*conditions))
    page = (
        await db.execute(
            select(rows.c.source, rows.c.row_id, rows.c.print_name)
            .where(*conditions)
            .order_by(order.nulls_last(), rows.c.source, rows.c.row_id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    run_ids = [row.row_id for row in page if row.source == "run"]
    queue_ids = [row.row_id for row in page if row.source == "queue"]
    log_rows = (
        {run.id: run for run in await db.scalars(select(PrintLogEntry).where(PrintLogEntry.id.in_(run_ids)))}
        if run_ids
        else {}
    )
    queue_items = (
        {
            item.id: item
            for item in await db.scalars(
                select(PrintQueueItem).options(*_QUEUE_ITEM_LOADS).where(PrintQueueItem.id.in_(queue_ids))
            )
        }
        if queue_ids
        else {}
    )
    archive_ids = {
        item.archive_id for item in [*log_rows.values(), *queue_items.values()] if item.archive_id is not None
    }
    available = (
        dict(
            (
                await db.execute(
                    select(PrintArchive.id, PrintArchive.thumbnail_path).where(
                        PrintArchive.id.in_(archive_ids),
                        PrintArchive.deleted_at.is_(None),
                        *_visible_archive_clauses(user, can_read_all, printer_scope),
                    )
                )
            ).all()
        )
        if archive_ids
        else {}
    )
    library_read_all = actor is None or actor.has_permission(Permission.LIBRARY_READ_ALL.value)
    library_owner_id = (
        actor.id if actor is not None and actor.has_permission(Permission.LIBRARY_READ_OWN.value) else None
    )
    items = []
    for row in page:
        if row.source == "run" and (run := log_rows.get(row.row_id)) is not None:
            entry = HistoryEntry.model_validate(run)
            entry.archive_available = entry.archive_id in available
            entry.archive_has_thumbnail = entry.archive_id is not None and bool(available.get(entry.archive_id))
            items.append(entry)
        elif row.source == "queue" and (queued := queue_items.get(row.row_id)) is not None:
            item = _enrich_response(queued)
            library_file = queued.library_file
            library_available = (
                library_file is not None
                and library_file.deleted_at is None
                and (
                    library_read_all
                    or (library_owner_id is not None and library_file.created_by_id == library_owner_id)
                )
            )
            items.append(
                HistoryEntry(
                    id=item.id,
                    archive_id=item.archive_id,
                    archive_available=item.archive_id in available,
                    library_file_available=library_available,
                    print_name=row.print_name,
                    plate_id=item.plate_id,
                    printer_name=item.printer_name,
                    printer_id=item.printer_id,
                    status=item.status,
                    started_at=item.started_at,
                    completed_at=item.completed_at,
                    filament_type=item.filament_type,
                    filament_color=item.filament_color,
                    created_by_id=item.created_by_id,
                    created_by_username=item.created_by_username,
                    created_at=item.created_at,
                    queue_only=True,
                    queue_item=item,
                )
            )
    return HistoryResponse(items=items, total=total or 0)

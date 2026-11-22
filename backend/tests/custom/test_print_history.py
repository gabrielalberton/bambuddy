from datetime import datetime, timedelta

from backend.app.models.print_log import RUN_OPEN, PrintLogEntry
from backend.app.models.print_queue import PrintQueueItem
from backend.tests.integration.test_queue_history_api import _admin_token, _auth, _user

URL = "/api/v1/custom/print-history"
BASE = datetime(2026, 11, 22, 20)


async def _history(client, *, headers=None, **params):
    response = await client.get(URL, headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _row_ids(page):
    return [(row["queue_only"], row["id"]) for row in page["items"]]


async def test_history_uses_logged_runs_and_keeps_other_terminal_jobs(
    async_client, db_session, printer_factory, archive_factory
):
    printer = await printer_factory()
    archive = await archive_factory(printer.id, print_name="Archived part", with_run=False)
    removed = await archive_factory(printer.id, deleted_at=BASE, with_run=False)
    await archive_factory(printer.id, status="archived", with_run=False)
    paired = PrintQueueItem(archive_id=archive.id, printer_id=printer.id, status="completed")
    by_billing = PrintQueueItem(archive_id=archive.id, status="cancelled", billing_run_id="old-dispatch")
    cancelled = PrintQueueItem(
        archive_id=archive.id, printer_id=printer.id, status="cancelled", completed_at=BASE + timedelta(minutes=30)
    )
    pending = PrintQueueItem(archive_id=archive.id, status="pending")
    db_session.add_all([paired, by_billing, cancelled, pending])
    await db_session.flush()

    first = PrintLogEntry(
        archive_id=archive.id, print_name="First print", status="completed", completed_at=BASE, queue_item_id=paired.id
    )
    second = PrintLogEntry(
        archive_id=archive.id, print_name="Second print", status="aborted", completed_at=BASE + timedelta(hours=1)
    )
    legacy = PrintLogEntry(
        archive_id=removed.id,
        print_name="Legacy print",
        status="failed",
        completed_at=BASE - timedelta(hours=1),
        billing_run_id="old-dispatch",
    )
    open_run = PrintLogEntry(archive_id=archive.id, status=RUN_OPEN, started_at=BASE)
    db_session.add_all([first, second, legacy, open_run])
    await db_session.commit()

    page = await _history(async_client, limit=2)
    assert page["total"] == 4
    assert _row_ids(page) == [(False, second.id), (True, cancelled.id)]
    assert page["items"][0]["archive_available"] is True
    assert page["items"][1]["queue_item"]["id"] == cancelled.id
    assert page["items"][1]["duration_seconds"] is None
    assert page["items"][1]["filament_used_grams"] is None
    next_page = await _history(async_client, limit=2, offset=2)
    assert _row_ids(next_page) == [(False, first.id), (False, legacy.id)]
    assert next_page["items"][1]["archive_available"] is False

    # The same archive can be printed repeatedly or cancelled. Filters act
    # after deduplication and cannot revive a queue copy with differing data.
    assert _row_ids(await _history(async_client, status="cancelled")) == [(False, second.id), (True, cancelled.id)]
    assert _row_ids(await _history(async_client, search="archived")) == [(True, cancelled.id)]
    assert _row_ids(await _history(async_client, date_from="2026-11-22T17:30:00-03:00")) == [
        (False, second.id),
        (True, cancelled.id),
    ]
    assert _row_ids(await _history(async_client, sort_by="print_name", sort_dir="asc")) == [
        (True, cancelled.id),
        (False, first.id),
        (False, legacy.id),
        (False, second.id),
    ]


async def test_history_respects_both_resources_ownership_and_printer_scope(
    async_client, db_session, printer_factory, archive_factory
):
    a, b = await printer_factory(), await printer_factory()
    admin = await _admin_token(async_client)
    scoped_token, user = await _user(
        async_client, admin, "scoped", ["archives:read_own", "queue:read_own"], printer_ids=[a.id]
    )
    archive_token, _ = await _user(async_client, admin, "archive", ["archives:read_all"], printer_ids=[a.id])
    queue_token, _ = await _user(async_client, admin, "queue-only", ["queue:read_all"])
    source = await archive_factory(a.id, with_run=False)
    mine = PrintQueueItem(printer_id=a.id, archive_id=source.id, created_by_id=user, status="cancelled")
    other = PrintQueueItem(printer_id=a.id, archive_id=source.id, status="failed")
    outside = PrintQueueItem(printer_id=b.id, archive_id=source.id, status="cancelled", created_by_id=user)
    db_session.add_all([mine, other, outside])
    await db_session.flush()
    own_run = PrintLogEntry(archive_id=source.id, printer_id=a.id, status="completed", created_by_id=user)
    others_run = PrintLogEntry(archive_id=source.id, printer_id=a.id, status="completed", queue_item_id=mine.id)
    outside_run = PrintLogEntry(archive_id=source.id, printer_id=b.id, status="completed", created_by_id=user)
    db_session.add_all([own_run, others_run, outside_run])
    await db_session.commit()

    own_history = await _history(async_client, headers=_auth(scoped_token))
    assert set(_row_ids(own_history)) == {(False, own_run.id), (True, mine.id)}
    assert not any(row["archive_available"] for row in own_history["items"])
    archived_history = await _history(async_client, headers=_auth(archive_token))
    assert set(_row_ids(archived_history)) == {(False, own_run.id), (False, others_run.id)}
    assert all(row["archive_available"] for row in archived_history["items"])
    assert (await async_client.get(URL, headers=_auth(queue_token))).status_code == 403

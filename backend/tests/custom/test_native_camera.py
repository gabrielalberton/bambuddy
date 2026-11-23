import asyncio
from contextlib import aclosing
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.app.api.routes import camera
from backend.app.core.auth import StreamOpener
from backend.app.models.printer import Printer


@pytest.mark.asyncio
async def test_native_view_does_not_replace_external_frames(async_client, db_session, monkeypatch):
    printer = Printer(
        name="A1",
        model="A1",
        serial_number="TEST-NATIVE",
        ip_address="192.0.2.71",
        access_code="test",
        external_camera_enabled=True,
        external_camera_url="/dev/video0",
        external_camera_type="usb",
    )
    db_session.add(printer)
    await db_session.commit()
    printer_id = printer.id

    async def external(*args, on_frame, **kwargs):
        on_frame(b"external")
        yield b"external"
        await asyncio.Event().wait()

    async def native(**kwargs):
        assert kwargs["printer_id"] is None
        assert kwargs["stream_id"] is None
        yield b"native"
        await asyncio.Event().wait()

    monkeypatch.setattr("backend.app.services.external_camera.generate_mjpeg_stream", external)
    monkeypatch.setattr(camera, "generate_chamber_mjpeg_stream", native)
    request = MagicMock(is_disconnected=AsyncMock(return_value=False))
    opener = StreamOpener(auth_on=False)
    try:
        default = await camera.camera_stream(printer_id, request, opener=opener)
        async with aclosing(default.body_iterator) as external_body:
            assert await asyncio.wait_for(anext(external_body), 2) == b"external"
            selected = await camera.camera_stream(printer_id, request, opener=opener, native=True)
            async with aclosing(selected.body_iterator) as native_body:
                assert await asyncio.wait_for(anext(native_body), 2) == b"native"
                assert camera.get_buffered_frame(printer_id) == b"external"
    finally:
        await camera.forget_printer(printer_id)

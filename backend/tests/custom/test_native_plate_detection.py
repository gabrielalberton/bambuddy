import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.app.api.routes import camera
from backend.app.core.config import settings
from backend.app.custom import native_plate_detection as native
from backend.app.services import camera_light, plate_detection
from backend.app.services.camera_fanout import get_or_create_broadcaster


class Light:
    def __init__(self, on=False):
        self.state = SimpleNamespace(connected=True, chamber_light=on, chamber_light_report_at=time.monotonic())
        self.calls = []

    def set_chamber_light(self, on):
        self.calls.append(on)
        self.state.chamber_light = on
        self.state.chamber_light_report_at = time.monotonic()
        return True


def _chunk(jpeg):
    return b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"


@pytest.fixture(autouse=True)
def native_capture(monkeypatch, tmp_path):
    monkeypatch.setenv("BAMBUDDY_CUSTOM_NATIVE_PLATE_DETECTION", "1")
    monkeypatch.setattr(settings, "plate_calibration_dir", tmp_path)
    monkeypatch.setattr(camera_light, "_light_settings", AsyncMock(return_value=("off", 4.0)))
    monkeypatch.setattr(camera_light, "_holders", {})
    monkeypatch.setattr(camera_light, "_lit_at", {})
    monkeypatch.setattr(camera_light, "_flash_owned", set())
    monkeypatch.setattr(camera_light, "_flash_off_at", {})
    monkeypatch.setattr(camera_light, "_off_tasks", {})


@pytest.fixture
def jpeg():
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    image = np.random.default_rng(42).integers(50, 155, (128, 192, 3), dtype=np.uint8)
    ok, data = cv2.imencode(".jpg", image)
    assert ok
    return data.tobytes()


@pytest.fixture
def dark_jpeg():
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    ok, data = cv2.imencode(".jpg", np.zeros((128, 192, 3), dtype=np.uint8))
    assert ok
    return data.tobytes()


async def test_capture_and_check_share_native_references_and_flash(
    async_client, printer_factory, monkeypatch, jpeg, dark_jpeg
):
    printer = await printer_factory(
        model="A1",
        external_camera_enabled=True,
        external_camera_url="http://example.invalid/camera",
        external_camera_type="mjpeg",
    )
    legacy = settings.plate_calibration_dir / f"printer_{printer.id}_ref_0.jpg"
    legacy.write_bytes(b"old external image")
    legacy_roi = (0.1, 0.1, 0.3, 0.3)
    assert native.native_plate_roi(printer.id, legacy_roi) == native.DEFAULT_NATIVE_PLATE_ROI
    assert native.save_native_plate_roi(printer.id, {"x": 0.2, "y": 0.3, "w": 0.6, "h": 0.6})

    light = Light()
    monkeypatch.setattr(camera_light, "_get_client", lambda _: light)
    external = AsyncMock()
    monkeypatch.setattr("backend.app.services.external_camera.capture_frame", external)

    async def generate(**kwargs):
        assert kwargs["printer_id"] is None
        assert kwargs["model"] == "A1"
        while not kwargs["disconnect_event"].is_set():
            await asyncio.sleep(0.01)
            yield _chunk(jpeg if light.state.chamber_light else dark_jpeg)

    monkeypatch.setattr(camera, "generate_chamber_mjpeg_stream", generate)
    url = f"/api/v1/printers/{printer.id}/camera"
    try:
        before = (await async_client.get(f"{url}/check-plate?use_external=true&include_debug_image=true")).json()
        assert before["needs_calibration"]
        assert before["reference_count"] == 0
        assert before["debug_image_url"].startswith("data:image/jpeg;base64,")
        assert before["roi"] == {"x": 0.2, "y": 0.3, "w": 0.6, "h": 0.6}
        assert light.calls == [True, False]

        saved = (await async_client.post(f"{url}/plate-detection/calibrate?use_external=true&label=Empty")).json()
        assert saved["success"]
        assert "câmera nativa" in saved["message"]
        assert light.calls == [True, False] * 2

        light.state.chamber_light = True  # user switched it on
        camera_light.hand_back(printer.id)
        checked = (await async_client.get(f"{url}/check-plate")).json()
        assert checked["is_empty"] and not checked["failure_reason"]
        assert not checked["needs_calibration"]
        assert checked["reference_count"] == 1
        assert light.state.chamber_light
        assert light.calls == [True, False] * 2
        assert legacy.read_bytes() == b"old external image"
        external.assert_not_awaited()
    finally:
        await camera.forget_printer(printer.id)


async def test_waits_for_the_first_illuminated_frame_on_an_open_stream(monkeypatch, jpeg, dark_jpeg):
    printer_id = 55
    light = Light()
    monkeypatch.setattr(camera_light, "_get_client", lambda _: light)
    sent_unlit_after_switch = False
    sent_lit = 0

    async def upstream(_event):
        nonlocal sent_unlit_after_switch, sent_lit
        yield _chunk(jpeg)  # a cached frame left over from a previous flash
        while True:
            await asyncio.sleep(0.005)
            if light.state.chamber_light and sent_unlit_after_switch:
                sent_lit += 1
                yield _chunk(jpeg)
            else:
                sent_unlit_after_switch |= light.state.chamber_light
                yield _chunk(dark_jpeg)

    broadcaster = await get_or_create_broadcaster(f"printer-{printer_id}", upstream)
    viewer = await broadcaster.subscribe()
    try:
        assert await asyncio.wait_for(viewer.get(), 2) == _chunk(jpeg)
        frame = await native.capture_native_plate(printer_id, "192.0.2.1", "test", "A1", True)
        assert frame == jpeg
        assert sent_unlit_after_switch
        assert sent_lit == 1
        assert light.calls == [True, False]
        assert broadcaster.subscriber_count == 1
    finally:
        await broadcaster.unsubscribe(viewer)
        await camera.forget_printer(printer_id)


@pytest.mark.parametrize("cancelled", [False, True])
async def test_light_is_restored_on_capture_failure_or_cancellation(monkeypatch, cancelled, dark_jpeg):
    printer_id = 56
    light = Light()
    monkeypatch.setattr(camera_light, "_get_client", lambda _: light)
    ready = asyncio.Event()

    async def failed(**_kwargs):
        yield _chunk(dark_jpeg)
        while not light.state.chamber_light:
            await asyncio.sleep(0.005)
        ready.set()
        if cancelled:
            await asyncio.Event().wait()
        yield b"--frame\r\nContent-Type: text/plain\r\n\r\nCamera offline\r\n"

    monkeypatch.setattr(camera, "generate_chamber_mjpeg_stream", failed)
    capture = asyncio.create_task(native.capture_native_plate(printer_id, "192.0.2.1", "test", "A1", True))
    try:
        await asyncio.wait_for(ready.wait(), 2)
        if cancelled:
            capture.cancel()
            with pytest.raises(asyncio.CancelledError):
                await capture
        else:
            assert await capture is None
        assert light.calls == [True, False]
    finally:
        await camera.forget_printer(printer_id)


async def test_two_overlapping_flashes_release_when_the_last_capture_ends(monkeypatch):
    light = Light()
    monkeypatch.setattr(camera_light, "_get_client", lambda _: light)
    printer = SimpleNamespace(id=57)
    first = camera_light.camera_light(printer, any_mode=True, settle=0, flash=True)
    second = camera_light.camera_light(printer, any_mode=True, settle=0, flash=True)
    assert await first.__aenter__()
    async with second:
        await first.__aexit__(None, None, None)
        assert light.calls == [True]
    assert light.calls == [True, False]


async def test_consecutive_checks_wait_for_a_fresh_off_report(monkeypatch, jpeg, dark_jpeg):
    printer_id = 58

    class DelayedLight(Light):
        physical_light = False

        def set_chamber_light(self, on):
            self.calls.append(on)
            self.physical_light = on
            asyncio.get_running_loop().call_later(0.030 if on else 0.060, self.report, on)
            return True

        def report(self, on):
            self.state.chamber_light = on
            self.state.chamber_light_report_at = time.monotonic()

    light = DelayedLight()
    monkeypatch.setattr(camera_light, "_get_client", lambda _: light)

    async def generate(**kwargs):
        while not kwargs["disconnect_event"].is_set():
            await asyncio.sleep(0.005)
            yield _chunk(jpeg if light.physical_light else dark_jpeg)

    monkeypatch.setattr(camera, "generate_chamber_mjpeg_stream", generate)
    try:
        args = (printer_id, "192.0.2.1", "test", "A1", True)
        assert await native.capture_native_plate(*args) == jpeg
        assert not light.state.chamber_light  # even the on report is still pending
        assert await native.capture_native_plate(*args) == jpeg
        assert light.calls == [True, False, True, False]
        assert await camera_light.wait_for_previous_flash(printer_id)
    finally:
        await camera.forget_printer(printer_id)


def test_switching_back_recovers_previous_references_and_roi(monkeypatch, jpeg):
    printer_id = 1
    old_file = settings.plate_calibration_dir / f"printer_{printer_id}_ref_0.jpg"
    old_file.write_bytes(jpeg)
    detector = plate_detection.PlateDetector()
    assert detector.get_calibration_count(printer_id) == 0
    assert detector.calibrate(jpeg, printer_id)[0]
    new_file = native.native_plate_reference_dir(settings.plate_calibration_dir) / old_file.name
    assert new_file.exists()

    monkeypatch.delenv("BAMBUDDY_CUSTOM_NATIVE_PLATE_DETECTION")
    assert detector.get_reference_thumbnail(printer_id, 0)
    assert detector.get_calibration_count(printer_id) == 1
    assert native.native_plate_roi(printer_id, (0.1, 0.2, 0.3, 0.4)) == (0.1, 0.2, 0.3, 0.4)
    plate_detection.remove_printer_references(printer_id)
    assert not old_file.exists()
    assert not new_file.exists()

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import cv2
import numpy as np
import pytest

from backend.app.core.config import settings
from backend.app.custom import plate_clear_samples as samples


def _jpeg(value=120):
    ok, data = cv2.imencode(".jpg", np.full((32, 48, 3), value, np.uint8))
    assert ok
    return data.tobytes()


@pytest.fixture
def printer():
    return SimpleNamespace(
        id=1, ip_address="10.0.0.2", access_code="x", model="A1", external_camera_enabled=True,
    )


@pytest.fixture(autouse=True)
def dataset_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "base_dir", tmp_path)
    monkeypatch.setenv("BAMBUDDY_CUSTOM_PLATE_CLEAR_DATASET", "1")
    return tmp_path / "custom" / "plate-clear-dataset"


def _entries(root):
    return sorted(p for p in (root / "1").iterdir() if not p.name.startswith("."))


@pytest.mark.asyncio
async def test_saves_both_cameras_with_clean_label(monkeypatch, dataset_dir, printer):
    monkeypatch.setattr(samples, "capture_native_plate", AsyncMock(return_value=_jpeg(100)))
    monkeypatch.setattr(samples, "_external", AsyncMock(return_value=_jpeg(200)))

    await samples.capture_confirmation(printer, lambda: "IDLE")

    (entry,) = _entries(dataset_dir)
    meta = json.loads((entry / "metadata.json").read_text())
    assert meta["label"] == "clean"
    assert meta["printer_state"] == "IDLE"
    assert meta["cameras"]["native"]["status"] == "captured"
    assert meta["cameras"]["external"]["status"] == "captured"
    assert (entry / "native.jpg").read_bytes().startswith(b"\xff\xd8")
    assert (entry / "external.jpg").exists()
    # A captura nativa não pode acender a luz da câmara (light=False).
    assert samples.capture_native_plate.call_args.kwargs["light"] is False


@pytest.mark.asyncio
async def test_one_camera_failing_still_records_the_other(monkeypatch, dataset_dir, printer):
    monkeypatch.setattr(samples, "capture_native_plate", AsyncMock(side_effect=RuntimeError("boom")))
    monkeypatch.setattr(samples, "_external", AsyncMock(return_value=_jpeg()))

    await samples.capture_confirmation(printer, lambda: "FINISH")

    (entry,) = _entries(dataset_dir)
    meta = json.loads((entry / "metadata.json").read_text())
    assert meta["cameras"]["native"]["status"] == "error"
    assert meta["cameras"]["external"]["status"] == "captured"
    assert not (entry / "native.jpg").exists()


@pytest.mark.asyncio
async def test_disabled_by_default(monkeypatch, dataset_dir, printer):
    monkeypatch.delenv("BAMBUDDY_CUSTOM_PLATE_CLEAR_DATASET")
    native = AsyncMock(return_value=_jpeg())
    monkeypatch.setattr(samples, "capture_native_plate", native)

    await samples.capture_confirmation(printer, lambda: "IDLE")

    native.assert_not_called()
    assert not dataset_dir.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["RUNNING", "PAUSE", "PREPARE"])
async def test_skips_when_printer_is_active(monkeypatch, dataset_dir, printer, state):
    native = AsyncMock(return_value=_jpeg())
    monkeypatch.setattr(samples, "capture_native_plate", native)

    await samples.capture_confirmation(printer, lambda: state)

    native.assert_not_called()
    assert not dataset_dir.exists()


@pytest.mark.asyncio
async def test_discards_sample_if_print_starts_during_capture(monkeypatch, dataset_dir, printer):
    monkeypatch.setattr(samples, "capture_native_plate", AsyncMock(return_value=_jpeg()))
    monkeypatch.setattr(samples, "_external", AsyncMock(return_value=_jpeg()))
    states = iter(["IDLE", "RUNNING"])

    await samples.capture_confirmation(printer, lambda: next(states))

    assert not dataset_dir.exists()


def test_invalid_jpeg_is_not_stored(dataset_dir):
    samples._save(
        dataset_dir, 1, datetime.now(UTC), "IDLE",
        {"native": ("captured", b"not-a-jpeg", "t"), "external": ("unavailable", None, None)},
    )
    (entry,) = _entries(dataset_dir)
    meta = json.loads((entry / "metadata.json").read_text())
    assert meta["cameras"]["native"]["status"] == "invalid_jpeg"
    assert not (entry / "native.jpg").exists()

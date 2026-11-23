"""Área de detecção em quadrilátero: migração do retângulo, gravação nos dois modos e máscara poligonal."""

import json

import pytest

from backend.app.core.config import settings
from backend.app.custom import native_plate_detection as native, plate_roi_quad as quad

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

TRAPEZOID = [[0.35, 0.4], [0.65, 0.4], [0.9, 0.9], [0.1, 0.9]]


@pytest.fixture(autouse=True)
def calibration_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "plate_calibration_dir", tmp_path)
    monkeypatch.delenv("BAMBUDDY_CUSTOM_PLATE_QUAD", raising=False)
    return tmp_path


@pytest.fixture
def native_mode(monkeypatch):
    monkeypatch.setenv("BAMBUDDY_CUSTOM_NATIVE_PLATE_DETECTION", "1")


@pytest.fixture
def external_mode(monkeypatch):
    monkeypatch.delenv("BAMBUDDY_CUSTOM_NATIVE_PLATE_DETECTION", raising=False)


def test_saved_rectangle_reads_as_its_four_corners(native_mode, calibration_dir):
    path = calibration_dir / "native-camera" / "printer_7_roi.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"x": 0.1, "y": 0.2, "w": 0.5, "h": 0.4}))

    roi = native.native_plate_roi(7, None)

    assert roi == (0.1, 0.2, 0.5, 0.4)
    assert roi.points == ((0.1, 0.2), (0.6, 0.2), (0.6, pytest.approx(0.6)), (0.1, pytest.approx(0.6)))
    assert roi.is_rectangle
    assert json.loads(path.read_text()) == {"x": 0.1, "y": 0.2, "w": 0.5, "h": 0.4}  # leitura não regrava


def test_native_quad_is_saved_with_its_bounding_rectangle(native_mode, calibration_dir):
    body = {"x": 0, "y": 0, "w": 1, "h": 1, "points": TRAPEZOID}
    assert native.save_native_plate_roi(3, body)

    stored = json.loads((calibration_dir / "native-camera" / "printer_3_roi.json").read_text())
    assert stored["points"] == TRAPEZOID
    assert stored["x"] == pytest.approx(0.1) and stored["w"] == pytest.approx(0.8)
    roi = native.native_plate_roi(3, None)
    assert not roi.is_rectangle
    assert roi.as_dict()["points"] == TRAPEZOID


def test_external_quad_follows_the_upstream_columns(external_mode, calibration_dir):
    body = {"x": 0, "y": 0, "w": 1, "h": 1, "points": TRAPEZOID}
    assert not native.save_native_plate_roi(5, body)  # o upstream grava as colunas
    assert body["x"] == pytest.approx(0.1) and body["h"] == pytest.approx(0.5)  # envolvente, no mesmo dict
    columns = (body["x"], body["y"], body["w"], body["h"])

    assert native.native_plate_roi(5, columns).points == tuple(map(tuple, TRAPEZOID))
    # Colunas mudadas por outro caminho: o arquivo deixa de valer.
    assert native.native_plate_roi(5, (0.2, 0.2, 0.5, 0.5)).is_rectangle
    assert native.native_plate_roi(5, None) is None
    # Desligado: volta ao retângulo envolvente.
    import os

    os.environ["BAMBUDDY_CUSTOM_PLATE_QUAD"] = "0"
    try:
        assert native.native_plate_roi(5, columns).is_rectangle
    finally:
        del os.environ["BAMBUDDY_CUSTOM_PLATE_QUAD"]
    # Retângulo puro sem points apaga os cantos.
    assert not native.save_native_plate_roi(5, {"x": 0.1, "y": 0.4, "w": 0.8, "h": 0.5})
    assert not (calibration_dir / "printer_5_roi.json").exists()


def _frame(blob_at=None):
    image = np.full((240, 320, 3), 120, np.uint8)
    image[::8, :] = 135  # textura leve
    if blob_at is not None:
        x, y = blob_at
        cv2.circle(image, (x, y), 18, (255, 255, 255), -1)
    ok, data = cv2.imencode(".jpg", image)
    assert ok
    return data.tobytes()


def _calibrated(printer_id, roi):
    from backend.app.services.plate_detection import PlateDetector

    assert PlateDetector().calibrate(_frame(), printer_id)[0]
    return quad.make_plate_detector(roi)


def test_polygon_mask_ignores_objects_outside_the_plate(external_mode):
    rect = quad.PlateROI((0.1, 0.4, 0.8, 0.5))
    trapezoid = quad.PlateROI(quad.bounding_rect(TRAPEZOID), tuple(map(tuple, TRAPEZOID)))
    # Canto superior esquerdo do retângulo envolvente: fora do trapézio.
    outside = _frame(blob_at=(50, 115))
    inside = _frame(blob_at=(160, 180))

    assert not _calibrated(1, rect).analyze_frame(outside, 1).is_empty
    detector = _calibrated(1, trapezoid)
    result = detector.analyze_frame(outside, 1, include_debug_image=True)
    assert result.is_empty, result.message
    assert result.debug_image
    assert detector.roi_mask is not None and not detector.roi_mask.all()

    assert not detector.analyze_frame(inside, 1).is_empty


def test_mean_counts_only_pixels_inside_the_polygon():
    from types import SimpleNamespace

    diff = np.zeros((4, 4), np.uint8)
    diff[0, 0] = 200  # fora
    diff[2, 2] = 100  # dentro
    mask = np.zeros((4, 4), bool)
    mask[2:, 2:] = True
    assert quad.roi_mean(SimpleNamespace(roi_mask=mask), diff) == 25.0
    assert quad.roi_mean(SimpleNamespace(roi_mask=None), diff) == pytest.approx(300 / 16)


def test_rectangle_keeps_the_upstream_comparison(external_mode):
    from backend.app.services.plate_detection import PlateDetector

    roi = quad.PlateROI((0.1, 0.4, 0.8, 0.5))
    detector = _calibrated(2, roi)
    upstream = PlateDetector(roi=tuple(roi))
    frame = _frame(blob_at=(160, 180))
    assert detector.analyze_frame(frame, 2).difference_percent == pytest.approx(
        upstream.analyze_frame(frame, 2).difference_percent
    )
    assert detector.roi_mask is None


async def test_patch_and_check_return_the_quad(async_client, printer_factory, external_mode, monkeypatch):
    printer = await printer_factory()
    resp = await async_client.patch(
        f"/api/v1/printers/{printer.id}",
        json={"plate_detection_roi": {"x": 0, "y": 0, "w": 1, "h": 1, "points": TRAPEZOID}},
    )
    assert resp.status_code == 200, resp.text
    assert native.native_plate_roi(printer.id, (0.1, 0.4, 0.8, 0.5)).points == tuple(map(tuple, TRAPEZOID))

    bad = await async_client.patch(
        f"/api/v1/printers/{printer.id}",
        json={"plate_detection_roi": {"x": 0, "y": 0, "w": 1, "h": 1, "points": [[0, 0], [2, 0], [1, 1], [0, 1]]}},
    )
    assert bad.status_code == 422

    from backend.app.services import plate_detection

    async def capture(*args, **kwargs):
        return _frame(), "test"

    monkeypatch.setattr(plate_detection, "capture_camera_image", capture)
    _calibrated(printer.id, None)
    checked = (await async_client.get(f"/api/v1/printers/{printer.id}/camera/check-plate")).json()
    assert checked["roi"]["points"] == TRAPEZOID
    assert checked["is_empty"]


async def test_backdrop_is_the_newest_reference(async_client, printer_factory, external_mode):
    printer = await printer_factory()
    url = f"/api/v1/custom/plate-roi/{printer.id}/backdrop.jpg"
    assert (await async_client.get(url)).status_code == 404
    _calibrated(printer.id, None)
    resp = await async_client.get(url)
    assert resp.status_code == 200
    assert resp.content.startswith(b"\xff\xd8")

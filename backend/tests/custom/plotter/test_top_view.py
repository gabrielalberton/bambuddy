"""Aerial plate view: lens + perspective removed, plate X right / plate Y up."""

import cv2
import numpy as np
import pytest

from backend.app.custom.plotter.vision import PLATE_MM, PlateTracker

SIZE = (640, 360)
FRONT = 40.0  # world Y of the plate front edge, as reported by locate()


def _tracker(plane_scale: float = 1.0) -> PlateTracker:
    """A fisheye camera looking straight down at the middle of the plate."""
    t = PlateTracker.__new__(PlateTracker)
    t.profile = {"usable_left": 10.0, "plane_scale": plane_scale}
    t.size = SIZE
    t.k = np.array([[300.0, 0, 320], [0, 300.0, 180], [0, 0, 1]])
    t.d = np.zeros(4)
    t.rotation = None
    t.z = 0.0
    centre = np.array([10.0 + 128 * plane_scale, FRONT + 128 * plane_scale, 320.0])
    t.r = cv2.Rodrigues(np.diag([1.0, -1, -1]))[0].ravel()  # x right, image y down = plate y down
    t.t = np.diag([1.0, -1, -1]) @ -centre
    t.active = t
    return t


def _frame(tracker: PlateTracker, x0, x1, y0, y1, plane_scale=1.0):
    frame = np.zeros((SIZE[1], SIZE[0], 3), np.uint8)
    xs = np.array([x0, x1, x1, x0]) * plane_scale + 10.0
    ys = np.array([y0, y0, y1, y1]) * plane_scale + FRONT
    pts = tracker.project(xs, ys).round().astype(np.int32)
    cv2.fillConvexPoly(frame, pts, (255, 255, 255))
    return frame


@pytest.mark.parametrize("plane_scale", [1.0, 0.95])
def test_marker_lands_at_plate_coordinates(plane_scale):
    tracker = _tracker(plane_scale)
    frame = _frame(tracker, 100, 120, 50, 70, plane_scale)  # plate mm: x 100-120, y 50-70
    top = tracker.top_view(frame, FRONT, margin_mm=30, px_per_mm=3)

    assert top.shape == (round((PLATE_MM + 60) * 3),) * 2 + (3,)
    ys, xs = np.nonzero(top[:, :, 0] > 128)
    # x grows to the right, y grows upward (image row = (256 + margin - y) * ppm)
    assert xs.mean() == pytest.approx((110 + 30) * 3, abs=3)
    assert ys.mean() == pytest.approx((256 + 30 - 60) * 3, abs=3)
    assert xs.max() - xs.min() == pytest.approx(20 * 3, abs=8)  # edges are soft after the 3x resample


def test_margin_is_dimmed_and_off_camera_is_black():
    tracker = _tracker()
    frame = np.full((SIZE[1], SIZE[0], 3), 200, np.uint8)
    top = tracker.top_view(frame, FRONT, margin_mm=30, px_per_mm=3)
    centre = top[top.shape[0] // 2, top.shape[1] // 2, 0]
    border = top[top.shape[0] // 2, 15, 0]  # inside the 30 mm margin
    assert centre == pytest.approx(200, abs=2)
    assert border < centre * 0.6


def test_rejects_a_frame_with_another_aspect_ratio():
    with pytest.raises(ValueError):
        _tracker().top_view(np.zeros((500, 500, 3), np.uint8), FRONT)


def _fit_profile(front_range=(-120, 40)):
    centre = np.array([10.0 + 128, -40.0 + 128, 320.0])  # above the plate when its front is at -40
    r = cv2.Rodrigues(np.diag([1.0, -1, -1]))[0].ravel()
    t = np.diag([1.0, -1, -1]) @ -centre
    lens = {
        "f": 300.0, "cx": 320.0, "cy": 180.0, "k1": 0.0, "k2": 0.0, "k3": 0.0, "k4": 0.0,
        "rx": r[0], "ry": r[1], "rz": r[2], "tx": t[0], "ty": t[1], "tz": t[2],
    }
    return {
        "view_id": "fit", "mode": "plane_fit", "frame_size": list(SIZE), "rectified_size": [1, 1],
        "rectified_origin": [0, 0, 0.0], "usable_left": 10.0, "plane_scale": 1.0, "axis": [-1.0, 0.0],
        "lens": lens, "templates": [], "fit": {"front_range": list(front_range), "min_score": 15},
    }


def _scene(tracker, front, *, plate=20, ground=150):
    frame = np.full((SIZE[1], SIZE[0], 3), ground, np.uint8)
    xs = np.array([10.0, 266.0, 266.0, 10.0])
    ys = np.array([front, front, front + 256.0, front + 256.0])
    cv2.fillConvexPoly(frame, tracker.project(xs, ys).round().astype(np.int32), (plate,) * 3)
    return frame


@pytest.mark.parametrize("front", [-80.0, -40.0, 0.0])
def test_plane_fit_follows_the_plate_along_y(front):
    tracker = PlateTracker.from_profile(_fit_profile())
    result = tracker.locate(_scene(tracker, front))

    assert result["found"] and result["camera_view"] == "fit"
    assert result["front_plane_mm"] == pytest.approx(front, abs=3)
    assert result["y_mm"] == pytest.approx(-front, abs=3)
    assert len(result["outline"]) == 32


def test_plane_fit_then_top_view_is_a_flat_plate():
    tracker = PlateTracker.from_profile(_fit_profile())
    frame = _scene(tracker, -40.0)
    result = tracker.locate(frame)
    top = tracker.top_view(frame, result["front_plane_mm"], margin_mm=30, px_per_mm=3)
    dark = (top[:, :, 0] > 8) & (top[:, :, 0] < 45)  # the plate, not the black off-camera area or dimmed margin
    ys, xs = np.nonzero(dark)
    assert xs.min() == pytest.approx(30 * 3, abs=9) and xs.max() == pytest.approx((256 + 30) * 3, abs=9)
    assert ys.min() == pytest.approx(30 * 3, abs=9) and ys.max() == pytest.approx((256 + 30) * 3, abs=9)


def test_plane_fit_reports_no_match_on_an_empty_scene():
    tracker = PlateTracker.from_profile(_fit_profile())
    frame = np.full((SIZE[1], SIZE[0], 3), 120, np.uint8)
    result = tracker.locate(frame)
    assert result["found"] is False

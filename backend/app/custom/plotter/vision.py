"""Track the A1 plate along its single moving axis in a calibrated fisheye image."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import cv2
import numpy as np


class PlateTracker:
    def __init__(self, path: Path):
        self.profile = json.loads(path.read_text())
        lens = self.profile["lens"]
        self.size = tuple(self.profile["frame_size"])
        self.shape = tuple(self.profile["rectified_size"])
        self.k = np.array([[lens["f"], 0, lens["cx"]], [0, lens["f"], lens["cy"]], [0, 0, 1.]])
        self.d = np.array([lens[f"k{i}"] for i in range(1, 5)])
        self.r = np.array([lens[f"r{i}"] for i in "xyz"])
        self.t = np.array([lens[f"t{i}"] for i in "xyz"])
        self.x0, self.y0, self.z = self.profile["rectified_origin"]
        self.last: tuple[float, float] | None = None
        self.maps: dict[tuple[int, int], tuple[np.ndarray, np.ndarray]] = {}
        self.anchors = [
            (ref["x"], ref["y"], np.frombuffer(base64.b64decode(ref["pixels"]), np.uint8).reshape(ref["shape"]))
            for ref in self.profile.get("anchors", [])
        ]
        self.templates = []
        for ref in self.profile["templates"]:
            patch = np.frombuffer(base64.b64decode(ref["pixels"]), np.uint8).reshape(ref["shape"])
            self.templates.append((ref["x"], ref["front_offset"], ref["feature"], self.features(patch)))

    @staticmethod
    def features(gray: np.ndarray) -> np.ndarray:
        smooth = cv2.GaussianBlur(gray, (3, 3), 0.7)
        return cv2.Sobel(smooth, cv2.CV_32F, 0, 1, ksize=3)

    def project(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        world = np.stack([x, y, np.full_like(x, self.z)], axis=-1).reshape(-1, 1, 3).astype(float)
        return cv2.fisheye.projectPoints(world, self.r, self.t, self.k, self.d)[0].reshape(*x.shape, 2)

    def rectify(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        if abs(w / h - self.size[0] / self.size[1]) > 0.02:
            raise ValueError("Enquadramento da câmera diferente do perfil.")
        size = w, h
        if size not in self.maps:
            width, height = self.shape
            x, y = np.meshgrid(self.x0 + np.arange(width), self.y0 - np.arange(height))
            projected = self.project(x, y) * (w / self.size[0], h / self.size[1])
            if len(self.maps) >= 3:
                self.maps.clear()
            self.maps[size] = cv2.convertMaps(
                projected[:, :, 0].astype("float32"), projected[:, :, 1].astype("float32"), cv2.CV_16SC2
            )
        return cv2.remap(frame, *self.maps[size], cv2.INTER_LINEAR)

    def camera_aligned(self, frame: np.ndarray) -> bool:
        if not self.anchors:
            return True
        gray = cv2.cvtColor(cv2.resize(frame, (640, 360), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
        for x, y, patch in self.anchors:
            h, w = patch.shape
            window = gray[y - 6:y + h + 6, x - 6:x + w + 6]
            result = cv2.matchTemplate(window, patch, cv2.TM_CCOEFF_NORMED)
            _, score, _, (dx, dy) = cv2.minMaxLoc(result)
            if score >= 0.72 and abs(dx - 6) <= 2 and abs(dy - 6) <= 2:
                return True
        return False

    def _score(self, rectified: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        gray = cv2.cvtColor(rectified, cv2.COLOR_BGR2GRAY)
        gradient = self.features(gray)
        start, end = self.profile["front_search"]
        candidate_count = end - start + 1
        scores: dict[str, dict[int, np.ndarray]] = {"rim": {}, "logo": {}, "notch": {}}
        for x, offset, feature, patch in self.templates:
            h, w = patch.shape
            patch_start = start + offset
            patch_end = end + offset + h
            a = max(0, patch_start)
            b = min(gray.shape[0], patch_end)
            scan = gradient[a:b, x:x + w]
            values = cv2.matchTemplate(scan, patch, cv2.TM_CCOEFF_NORMED).ravel()
            valid = cv2.matchTemplate((gray[a:b, x:x + w] > 0).astype("float32"),
                                      np.ones((h, w), "float32"), cv2.TM_CCORR).ravel()
            values[valid < 0.98 * h * w] = 0
            series = np.zeros(candidate_count, dtype=np.float32)
            i = a - patch_start
            series[i:i + len(values)] = values
            prior = scores[feature].get(x)
            scores[feature][x] = series if prior is None else np.maximum(prior, series)

        rim = np.sort(list(scores["rim"].values()) + list(scores["notch"].values()), axis=0)
        edge = np.mean(rim[-min(3, len(rim)):], axis=0)
        logo = np.max(list(scores["logo"].values()), axis=0)
        # The machine base presents its own straight lip. The notch in the
        # plate profile carries more evidence than another straight segment.
        notch = np.maximum(np.max(list(scores["notch"].values()), axis=0), 0)
        profile = 0.8 * edge + 0.2 * notch
        return profile, edge, logo

    def background_scores(self, frame: np.ndarray) -> np.ndarray:
        profile, _, _ = self._score(self.rectify(frame))
        return profile

    def _front_row(self, rectified: np.ndarray, prior: float) -> float:
        """Refine the front of the square body against the thin, dark PEI rim."""
        stripe = self.profile.get("front_edge_stripe")
        if stripe is None:
            return prior
        x0, x1 = stripe
        lo = max(2, int(prior) - 15)
        hi = min(rectified.shape[0] - 4, int(prior) + 7)
        ys = np.arange(lo, hi + 1)
        if not ys.size:
            return prior
        patch = cv2.cvtColor(rectified[lo - 2:hi + 4, x0:x1], cv2.COLOR_BGR2GRAY)
        gradient = np.median(self.features(patch), axis=1)
        i = ys - lo + 2
        fall = np.maximum(-gradient[i - 1], -gradient[i])
        rise = np.maximum(gradient[i + 1], gradient[i + 2])
        contrast = np.minimum(fall, rise)
        score = contrast - 1.4 * np.abs(ys - prior)
        peak = int(np.argmax(score))
        # Dim or occluded rims keep the estimate from the template search.
        if contrast[peak] < 19 or score[peak] < 11:
            return prior
        return float(ys[peak])

    def locate(self, frame: np.ndarray, *, at: float | None = None, diagnostics: bool = False) -> dict:
        if not self.camera_aligned(frame):
            return {"found": False, "reason": "camera_alignment"}
        rectified = self.rectify(frame)
        profile, edge, logo = self._score(rectified)
        start, end = self.profile["front_search"]
        candidates = np.arange(start, end + 1)
        background = np.asarray(self.profile.get("background", 0))
        score = profile + 0.60 * np.maximum(logo, 0) - np.maximum(background - 0.32, 0)
        if at is not None and self.last is not None:
            previous_time, previous_row = self.last
            elapsed = at - previous_time
            if 0 <= elapsed < 0.65:
                allowed = np.abs(candidates - previous_row) <= 12 + 180 * elapsed
                score = np.where(allowed, score, -np.inf)
        index = int(np.argmax(score))
        far = abs(candidates - candidates[index]) > 12
        margin = float(score[index] - np.max(score[far]))
        found = (edge[index] >= 0.37 or (edge[index] >= 0.20 and logo[index] >= 0.34)) and margin >= 0.05
        result = {"found": bool(found), "confidence": round(float(score[index]) / 1.6, 3)}
        if diagnostics:
            result.update(best_row=int(candidates[index]), edge=float(edge[index]), logo=float(logo[index]), profile=float(profile[index]), margin=margin if np.isfinite(margin) else 1.6)
        if not found:
            return result
        row = float(candidates[index])
        if 0 < index < len(score) - 1:
            left, mid, right = (float(v) for v in score[index - 1:index + 2])
            if np.isfinite(left + right) and left + right < 2 * mid:
                row += 0.5 * (left - right) / (left + right - 2 * mid)
        if at is not None:
            self.last = at, row
        front_row = self._front_row(rectified, row - self.profile["usable_front_offset"])
        front = self.y0 - front_row
        x_left = self.profile["usable_left"]
        size = 256 * self.profile.get("plane_scale", 1.0)
        x = np.array([x_left, x_left + size, x_left + size, x_left])
        y = np.array([front, front, front + size, front + size])
        corners = self.project(x, y) / self.size
        phase = np.arange(8) / 8
        outline_x = (x[:, None] + (np.roll(x, -1) - x)[:, None] * phase).ravel()
        outline_y = (y[:, None] + (np.roll(y, -1) - y)[:, None] * phase).ravel()
        outline = self.project(outline_x, outline_y) / self.size
        result.update(
            corners=corners.round(6).tolist(),
            outline=outline.round(6).tolist(),
            front_plane_mm=round(front, 2),
        )
        if "axis" in self.profile:
            slope, zero = self.profile["axis"]
            result["y_mm"] = round((front - zero) / slope, 2)
        return result

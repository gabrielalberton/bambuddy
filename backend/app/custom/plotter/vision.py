"""Track the A1 plate along its single moving axis in a calibrated fisheye image."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import cv2
import numpy as np

from .vision_edges import PlateEdges
from .vision_pose import CameraReference


BLUR_LENGTHS = (1, 5, 9, 17, 25)
PLATE_MM = 256.0


class PlateTracker:
    def __init__(self, path: Path):
        self._load(json.loads(path.read_text()))

    @classmethod
    def from_profile(cls, profile: dict) -> PlateTracker:
        tracker = cls.__new__(cls)
        tracker._load(profile)
        return tracker

    def _load(self, profile: dict):
        self.profile = profile
        lens = self.profile["lens"]
        self.size = tuple(self.profile["frame_size"])
        self.shape = tuple(self.profile["rectified_size"])
        self.k = np.array([[lens["f"], 0, lens["cx"]], [0, lens["f"], lens["cy"]], [0, 0, 1.]])
        self.d = np.array([lens[f"k{i}"] for i in range(1, 5)])
        self.r = np.array([lens[f"r{i}"] for i in "xyz"])
        self.t = np.array([lens[f"t{i}"] for i in "xyz"])
        self.x0, self.y0, self.z = self.profile["rectified_origin"]
        self.rotation = None
        self.reference = (
            CameraReference(profile["registration"], self.k, self.d, self.size)
            if "registration" in profile else None
        )
        self.views = [self.from_profile(view) for view in profile.get("views", [])]
        self.active = self
        self.edges = PlateEdges(profile["edge_references"], self.features) if "edge_references" in profile else None
        self.last: tuple[float, float] | None = None
        self.maps: dict[tuple[int, int], tuple[np.ndarray, np.ndarray]] = {}
        self.anchors = [
            (ref["x"], ref["y"], np.frombuffer(base64.b64decode(ref["pixels"]), np.uint8).reshape(ref["shape"]))
            for ref in self.profile.get("anchors", [])
        ]
        self.templates = []
        for ref in self.profile["templates"]:
            patch = np.frombuffer(base64.b64decode(ref["pixels"]), np.uint8).reshape(ref["shape"])
            gradient = self.features(patch)
            variants = [gradient]
            for length in BLUR_LENGTHS[1:]:
                variants.append(cv2.blur(gradient, (1, length), borderType=cv2.BORDER_CONSTANT))
            self.templates.append((ref["x"], ref["front_offset"], ref["feature"], variants))

    @staticmethod
    def features(gray: np.ndarray) -> np.ndarray:
        smooth = cv2.GaussianBlur(gray, (3, 3), 0.7)
        return cv2.Sobel(smooth, cv2.CV_32F, 0, 1, ksize=3)

    def project(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        world = np.stack([x, y, np.full_like(x, self.z)], axis=-1).reshape(-1, 1, 3).astype(float)
        r, t = self.r, self.t
        if self.rotation is not None:
            r = cv2.Rodrigues(self.rotation @ cv2.Rodrigues(r)[0])[0].ravel()
            t = self.rotation @ t
        return cv2.fisheye.projectPoints(world, r, t, self.k, self.d)[0].reshape(*x.shape, 2)

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

    def _score(
        self, gray: np.ndarray, gradient: np.ndarray, *, motion_blur: bool = False
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        valid_pixels = cv2.integral((gray > 0).astype(np.uint8))
        start, end = self.profile["front_search"]
        candidate_count = end - start + 1
        scores: dict[str, dict[int, np.ndarray]] = {"rim": {}, "logo": {}, "notch": {}}
        for x, offset, feature, variants in self.templates:
            h, w = variants[0].shape
            patch_start = start + offset
            patch_end = end + offset + h
            a = max(0, patch_start)
            b = min(gray.shape[0], patch_end)
            scan = gradient[a:b, x:x + w]
            values = cv2.matchTemplate(scan, variants[0], cv2.TM_CCOEFF_NORMED).ravel()
            if motion_blur:
                for patch, length in zip(variants[1:], BLUR_LENGTHS[1:]):
                    blurred = cv2.matchTemplate(scan, patch, cv2.TM_CCOEFF_NORMED).ravel()
                    values = np.maximum(values, blurred * (1.0 - 0.007 * length))
            top = np.arange(a, a + len(values))
            bottom = top + h
            valid = valid_pixels[bottom, x + w] - valid_pixels[bottom, x]
            valid -= valid_pixels[top, x + w] - valid_pixels[top, x]
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
        gray = cv2.cvtColor(self.rectify(frame), cv2.COLOR_BGR2GRAY)
        profile, _, _ = self._score(gray, self.features(gray))
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

    def _bright_surface_end(self, gray: np.ndarray, candidates: np.ndarray) -> np.ndarray:
        """Suppress a broad light-to-dark boundary inside the plate, such as white paper."""
        stripe = self.profile.get("front_edge_stripe")
        if stripe is None:
            return np.zeros(candidates.size, dtype=bool)
        row = np.clip(candidates - round(self.profile["usable_front_offset"]), 20, len(gray) - 25)
        x0, _ = stripe
        line = np.median(gray[:, x0 - 70:x0 + 20], axis=1).astype(np.float32)
        light = cv2.blur(line[:, None], (1, 15)).ravel()
        before, after = light[row - 13], light[row + 22]
        return (before - after > 26) & (before > after * 1.36)

    def _set_rotation(self, rotation: np.ndarray | None):
        if self.rotation is rotation:
            return
        if rotation is not None and self.rotation is not None and np.linalg.norm(rotation - self.rotation) < 0.003:
            return
        self.rotation = rotation
        self.maps.clear()

    def locate(self, frame: np.ndarray, *, at: float | None = None, diagnostics: bool = False) -> dict:
        views = (self, *self.views)
        if self.active is not self:
            views = (self.active, *(view for view in views if view is not self.active))
        for view in views:
            if view.camera_aligned(frame):
                view._set_rotation(None)
                return self._locate_in_view(view, frame, at=at, diagnostics=diagnostics)
        estimates = []
        for view in views:
            if view.reference is not None:
                estimated = view.reference.estimate(frame)
                if estimated is not None:
                    rotation, count = estimated
                    estimates.append((count, view, rotation))
        if not estimates:
            self.active.last = None
            return {"found": False, "reason": "camera_alignment"}
        _, view, rotation = max(estimates, key=lambda item: item[0])
        view._set_rotation(rotation)
        return self._locate_in_view(view, frame, at=at, diagnostics=diagnostics)

    def _locate_in_view(self, view, frame, *, at, diagnostics):
        if self.active is not view:
            view.last = None
            self.active = view
        rectified = view.rectify(frame)
        if "contrast_strips" in view.profile:
            result = view._locate_contrast(rectified, diagnostics)
        else:
            result = view._locate_templates(rectified, at=at, diagnostics=diagnostics)
        if view.profile.get("view_id"):
            result["camera_view"] = view.profile["view_id"]
        if view.rotation is not None:
            result["camera_reoriented"] = True
            if diagnostics:
                result["camera_rotation_delta"] = view.rotation.tolist()
        return result

    def _locate_templates(self, rectified: np.ndarray, *, at: float | None, diagnostics: bool) -> dict:
        gray = cv2.cvtColor(rectified, cv2.COLOR_BGR2GRAY)
        gradient = self.features(gray)
        start, end = self.profile["front_search"]
        candidates = np.arange(start, end + 1)
        background = np.maximum(np.asarray(self.profile.get("background", 0)) - 0.32, 0)
        inside = self._bright_surface_end(gray, candidates)
        previous = None
        if at is not None and self.last is not None:
            previous_time, previous_row = self.last
            elapsed = at - previous_time
            if 0 < elapsed < 0.65:
                previous = previous_row, elapsed

        def peak(profile, logo, limit):
            score = profile + 0.60 * np.maximum(logo, 0) - background
            score = np.where(inside & (logo < 0.30), score - 0.30, score)
            if previous is not None:
                prev_row, dt = previous
                allowed = np.abs(candidates - prev_row) <= 12 + limit * dt
                score = np.where(allowed, score, -np.inf)
            index = int(np.argmax(score))
            far = np.abs(candidates - candidates[index]) > 12
            return score, index, float(score[index] - np.max(score[far]))

        profile, edge, logo = self._score(gray, gradient)
        score, index, margin = peak(profile, logo, 180)
        found = (edge[index] >= 0.37 or (edge[index] >= 0.20 and logo[index] >= 0.34)) and margin >= 0.05
        strong = found and (edge[index] >= 0.56 or logo[index] >= 0.34)
        used_blur = False
        if not strong:
            broad_profile, broad_edge, broad_logo = self._score(gray, gradient, motion_blur=True)
            broad_score, broad_index, broad_margin = peak(broad_profile, broad_logo, 400)
            close = abs(broad_index - index) <= 15
            landmark = broad_logo[broad_index] >= 0.32
            two_matches = close and edge[index] >= 0.35 and broad_edge[broad_index] >= 0.46
            enough_margin = broad_margin >= (0.018 if two_matches else 0.05)
            if enough_margin and (two_matches or (landmark and broad_edge[broad_index] >= 0.30)):
                profile, edge, logo = broad_profile, broad_edge, broad_logo
                score, index, margin = broad_score, broad_index, broad_margin
                found = used_blur = True
            elif not close and edge[index] < 0.50 and logo[index] < 0.23 and previous is None:
                found = False
        result = {"found": bool(found), "confidence": round(float(np.clip(score[index] / 1.6, 0, 1)), 3)}
        evidence = None
        source = None
        if self.edges is not None:
            # During fast moves the front bevel may disappear into the printer base.
            # The rear edge is visible toward the front of travel and the revealed
            # stationary base is useful once the plate has receded past it.
            rear = self.edges.measure_rear(gradient) if not strong else None
            front = self.edges.measure_front(rectified) if rear is None and not strong else None
            if rear is not None:
                evidence, source = rear, "rear_edge"
            elif front is not None:
                agrees = abs(front[0] + self.profile["usable_front_offset"] - candidates[index]) < 22
                if not found or agrees or front[1] > 0.58:
                    evidence, source = front, "revealed_base"
        if evidence is not None:
            front_row, confidence = evidence
            if at is not None:
                self.last = at, front_row + self.profile["usable_front_offset"]
            result.update(found=True, confidence=round(confidence, 3))
            if diagnostics:
                result.update(edge_source=source, best_row=round(front_row + self.profile["usable_front_offset"]))
            return self._project_result(result, front_row)
        if diagnostics:
            result.update(
                best_row=int(candidates[index]), edge=float(edge[index]), logo=float(logo[index]),
                profile=float(profile[index]), margin=margin if np.isfinite(margin) else 1.6,
                used_blur=used_blur,
            )
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
        return self._project_result(result, front_row)

    def _locate_contrast(self, rectified: np.ndarray, diagnostics: bool) -> dict:
        gray = cv2.cvtColor(rectified, cv2.COLOR_BGR2GRAY)
        gradient = self.features(gray)
        start, end = self.profile["front_search"]
        rows = np.arange(start, end + 1)
        similarities = {}
        for x, offset, _, variants in self.templates:
            h, w = variants[0].shape
            scan = gradient[start + offset:end + offset + h, x:x + w]
            scores = [cv2.matchTemplate(scan, p, cv2.TM_CCOEFF_NORMED).ravel() * (1 - 0.006 * blur)
                      for p, blur in zip(variants, BLUR_LENGTHS)]
            similarities[x] = np.maximum(similarities.get(x, -1), np.maximum.reduce(scores))

        contrast = []
        for x0, x1, offset in self.profile["contrast_strips"]:
            line = np.median(gray[:, x0:x1], axis=1).astype(np.float32)
            at = rows + offset
            bands = []
            for sigma, gap in ((1.5, 4), (3, 7), (5, 11)):
                smooth = cv2.GaussianBlur(line[:, None], (1, 0), sigma, sigmaY=sigma).ravel()
                inside, outside = smooth[at - gap], smooth[at + gap]
                evidence = np.tanh((outside - inside) / np.maximum(9, (outside + inside) * 0.17))
                evidence[(line[at - gap] < 2) | (line[at + gap] < 3)] = 0
                bands.append(evidence)
            contrast.append(np.maximum.reduce(bands))

        rim = np.maximum(np.sort(contrast, axis=0)[-3:], 0).mean(axis=0)
        similarity = np.sort(list(similarities.values()), axis=0)[-3:].mean(axis=0)
        score = similarity + 0.5 * rim
        i = int(np.argmax(score))
        far = np.abs(rows - rows[i]) > 16
        margin = float(score[i] - np.max(score[far]))
        threshold = self.profile.get("contrast_min_similarity", 0.42)
        found = bool(similarity[i] >= threshold and rim[i] >= 0.46 and margin >= 0.08)
        result = {"found": found, "confidence": round(float(np.clip(score[i] / 1.5, 0, 1)), 3)}
        if diagnostics:
            result.update(best_row=int(rows[i]), margin=margin, rim=float(rim[i]), edge=float(similarity[i]))
        if not found:
            return result
        return self._project_result(result, float(rows[i]))

    def top_view(
        self, frame: np.ndarray, front_mm: float, *, margin_mm: float = 30.0, px_per_mm: float = 3.0, dim: float = 0.45,
    ) -> np.ndarray:
        """Aerial view of the 256 mm plate, undistorted, with a dimmed ``margin_mm`` border.

        Uses the view that just located the plate (rotation included), sampling the
        fisheye frame directly so lens distortion and perspective are removed in one step.
        Image x grows to the right (plate X) and image y grows toward the back (plate Y up).
        """
        view = self.active
        h, w = frame.shape[:2]
        if abs(w / h - view.size[0] / view.size[1]) > 0.02:
            raise ValueError("Enquadramento da câmera diferente do perfil.")
        scale = view.profile.get("plane_scale", 1.0)
        span = PLATE_MM + 2 * margin_mm
        count = round(span * px_per_mm)
        real = -margin_mm + (np.arange(count) + 0.5) / px_per_mm
        x_real, y_real = np.meshgrid(real, real[::-1])
        x = view.profile["usable_left"] + x_real * scale
        y = front_mm + y_real * scale
        projected = view.project(x, y) * (w / view.size[0], h / view.size[1])
        out = cv2.remap(
            frame, projected[:, :, 0].astype("float32"), projected[:, :, 1].astype("float32"),
            cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
        )
        outside = (x_real < 0) | (x_real > PLATE_MM) | (y_real < 0) | (y_real > PLATE_MM)
        shade = np.where(outside, dim, 1.0).astype("float32")
        shade = cv2.GaussianBlur(shade, (0, 0), px_per_mm * 0.8)
        return np.clip(out * shade[:, :, None], 0, 255).astype(np.uint8)

    def _project_result(self, result: dict, front_row: float) -> dict:
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

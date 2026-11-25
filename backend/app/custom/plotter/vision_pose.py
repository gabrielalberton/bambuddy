"""Recover camera rotation from fixed scene features and calibrated fisheye rays."""

from __future__ import annotations

import base64

import cv2
import numpy as np


class CameraReference:
    def __init__(self, config: dict, k: np.ndarray, distortion: np.ndarray, size: tuple[int, int]):
        encoded = np.frombuffer(base64.b64decode(config["image"]), np.uint8)
        reference = cv2.imdecode(encoded, cv2.IMREAD_GRAYSCALE)
        self.k = k * np.array([[reference.shape[1] / size[0]], [reference.shape[0] / size[1]], [1]])
        self.d = distortion
        self.shape = reference.shape
        self.sift = cv2.SIFT_create(nfeatures=500, contrastThreshold=0.017)
        mask = np.zeros(self.shape, np.uint8)
        for x, y, w, h in config["static_regions"]:
            mask[y:y + h, x:x + w] = 255
        points, self.descriptors = self._features(reference, mask)
        self.rays = self._rays(points)
        self.match = cv2.BFMatcher(cv2.NORM_L2)

    def _features(self, gray: np.ndarray, mask=None):
        equalized = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 6)).apply(gray)
        points, desc = self.sift.detectAndCompute(equalized, mask)
        return np.array([p.pt for p in points], dtype=np.float64).reshape(-1, 2), desc

    def _rays(self, points: np.ndarray) -> np.ndarray:
        if len(points) == 0:
            return np.empty((0, 3))
        xy = cv2.fisheye.undistortPoints(points.reshape(-1, 1, 2), self.k, self.d).reshape(-1, 2)
        rays = np.column_stack((xy, np.ones(len(xy))))
        return rays / np.linalg.norm(rays, axis=1, keepdims=True)

    @staticmethod
    def _rotation(a: np.ndarray, b: np.ndarray) -> np.ndarray:
        u, _, vt = np.linalg.svd(b.T @ a)
        u[:, -1] *= np.linalg.det(u @ vt)
        return u @ vt

    def estimate(self, frame: np.ndarray) -> tuple[np.ndarray, int] | None:
        gray = cv2.cvtColor(cv2.resize(frame, self.shape[::-1], interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
        points, desc = self._features(gray)
        if self.descriptors is None or desc is None or len(desc) < 2:
            return None
        pairs = self.match.knnMatch(self.descriptors, desc, k=2)
        matches = {m.trainIdx: m.queryIdx for m, n in pairs if m.distance < 0.72 * n.distance}
        if len(matches) < 12:
            return None
        a = self.rays[list(matches.values())]
        b = self._rays(points[list(matches)])
        # Test a rotation, with rays spanning the image. This rejects translation
        # with visible parallax and matches concentrated in a small patch.
        rng = np.random.default_rng(13)
        best = np.zeros(len(a), dtype=bool)
        for _ in range(96):
            indices = rng.choice(len(a), 3, replace=False)
            rotation = self._rotation(a[indices], b[indices])
            inliers = np.linalg.norm(a @ rotation.T - b, axis=1) < 0.007
            if inliers.sum() > best.sum():
                best = inliers
        count = int(best.sum())
        if count < max(12, 0.65 * len(a)):
            return None
        if cv2.contourArea(cv2.convexHull(points[list(matches)][best].astype(np.float32))) < 0.025 * gray.size:
            return None
        rotation = self._rotation(a[best], b[best])
        if np.linalg.norm(cv2.Rodrigues(rotation)[0]) > 0.55:
            return None
        return rotation, count

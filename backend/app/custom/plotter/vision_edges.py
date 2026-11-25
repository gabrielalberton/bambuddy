"""Independent edge evidence for the calibrated camera view."""

from __future__ import annotations

import base64

import cv2
import numpy as np


class PlateEdges:
    def __init__(self, config: dict, features):
        self.rear = []
        self.blurs = (1, 5, 9, 17, 25)
        for patch in config["rear"]:
            pixels = self._decode(patch)
            edge = features(pixels)
            variants = [edge] + [cv2.blur(edge, (1, n), borderType=cv2.BORDER_CONSTANT) for n in self.blurs[1:]]
            self.rear.append((patch["x"], variants))
        self.background = self._decode(config["background"]).astype(np.float32)
        self.height = config["rear_to_front"]
        self.rear_start = config["rear_patch_before"]

    @staticmethod
    def _decode(patch: dict) -> np.ndarray:
        return np.frombuffer(base64.b64decode(patch["pixels"]), np.uint8).reshape(patch["shape"])

    def measure_rear(self, gradient: np.ndarray) -> tuple[float, float] | None:
        scores = {}
        for x, variants in self.rear:
            _, w = variants[0].shape
            strip = gradient[:137, x:x + w]
            similarity = np.maximum.reduce([
                cv2.matchTemplate(strip, patch, cv2.TM_CCOEFF_NORMED).ravel() * (1 - 0.004 * blur)
                for patch, blur in zip(variants, self.blurs)
            ])
            scores[x] = np.maximum(scores.get(x, -1), similarity)
        evidence = np.sort(list(scores.values()), axis=0)[-3:].mean(axis=0)
        peak = int(np.argmax(evidence))
        far = abs(np.arange(len(evidence)) - peak) > 12
        if evidence[peak] < 0.40 or evidence[peak] - np.max(evidence[far]) < 0.13:
            return None
        return float(peak + self.height + self.rear_start), float(evidence[peak])

    def measure_front(self, frame: np.ndarray) -> tuple[float, float] | None:
        # The exposed fixed printer base is the background where the plate ends.
        measured = frame.astype(np.float32)
        static = np.s_[389:421, 198:250]
        gain = np.median(measured[static], axis=(0, 1)) / np.maximum(np.median(self.background[static], axis=(0, 1)), 10)
        if np.any((gain < 0.5) | (gain > 1.7)):
            return None
        base = self.background * gain
        difference = np.abs(measured - base).mean(axis=2)
        valid = (base.mean(axis=2) > 2) & (measured.mean(axis=2) > 2)
        rows = np.arange(145, 313)
        bands = []
        for left, right, offset in ((82, 110, 4), (120, 150, 4), (159, 183, 4), (198, 221, -3), (225, 242, -3)):
            coverage = valid[:, left:right].mean(axis=1)
            distance = np.mean(np.minimum(difference[:, left:right], 55) * valid[:, left:right], axis=1)
            signal = cv2.blur((distance / np.maximum(coverage, 0.01))[:, None], (1, 11)).ravel()
            sample = rows + offset
            score = signal[sample - 7] - signal[sample + 11]
            score[(coverage[sample - 8] < 0.85) | (coverage[sample + 11] < 0.85)] = 0
            bands.append(score)
        evidence = np.sort(bands, axis=0)[-3:].mean(axis=0)
        peak = int(np.argmax(evidence))
        far = np.abs(rows - rows[peak]) > 12
        if evidence[peak] < 22 or evidence[peak] - np.max(evidence[far]) < 6:
            return None
        return float(rows[peak] + 6), float(evidence[peak] / 55)

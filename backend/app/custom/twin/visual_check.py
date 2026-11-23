#!/usr/bin/env python3
"""Compare the A1 camera and a stationary twin pose near a visual reference.

Uses native features on the machine. Requires opencv-python-headless and numpy.
Does not query or control the printer. The caller supplies a current camera frame.
"""

import argparse
import json
from pathlib import Path

import cv2 as cv
import numpy as np

PARTS = ("base", "head", "bed")


def image_features(frame, size):
    if frame.shape[1] * size[1] != frame.shape[0] * size[0]:
        raise ValueError("proporção da câmera diferente da referência")
    gray = cv.cvtColor(cv.resize(frame, size, interpolation=cv.INTER_AREA), cv.COLOR_BGR2GRAY)
    smooth = cv.GaussianBlur(gray, (3, 3), 0.6)
    return smooth.astype("float32") - cv.GaussianBlur(smooth, (0, 0), 2.5).astype("float32")


def crop(image, box):
    x, y, w, h = box
    tile = image[y:y + h, x:x + w]
    if min(x, y) < 0 or min(w, h) < 1 or tile.shape != (h, w):
        raise ValueError("região fora da imagem")
    return tile


def detect(features, template, region, scales):
    x, y, _, _ = region
    source = crop(features, region)
    h, w = template.shape
    strongest = None
    for scale in scales:
        patch = cv.resize(template, (round(w * scale), round(h * scale)))
        ph, pw = patch.shape
        if ph > source.shape[0] or pw > source.shape[1] or patch.std() < 0.5:
            continue
        scores = cv.matchTemplate(source, patch, cv.TM_CCOEFF_NORMED)
        _, value, _, (u, v) = cv.minMaxLoc(scores)
        scores[max(0, v - 12):v + 13, max(0, u - 12):u + 13] = -1
        if strongest is None or value > strongest[0]:
            strongest = value, value - float(scores.max()), (x + u + pw / 2, y + v + ph / 2)
    return strongest


def locate(features, templates, config):
    proposals = []
    for template, spec in templates:
        result = detect(features, template, spec["region"], spec.get("scales", [1]))
        if result is None:
            continue
        score, margin, point = result
        if score >= spec["min_score"] and margin >= spec["min_margin"]:
            proposals.append((score, point))
    if not proposals:
        return None
    _, best = max(proposals, key=lambda match: match[0])
    conflicting = any(np.linalg.norm(np.subtract(best, point)) > config["max_template_disagreement_px"]
                      for _, point in proposals)
    return None if conflicting else best


class VisualReference:
    def __init__(self, path):
        self.config = json.loads(path.read_text())
        self.size = tuple(self.config["size"])
        self.templates = {}
        decoded = {}
        for part in PARTS:
            self.templates[part] = []
            for spec in self.config["parts"][part]["templates"]:
                name = spec["image"]
                if name not in decoded:
                    frame = cv.imread(str(path.parent / name))
                    if frame is None:
                        raise ValueError(f"imagem de referência indisponível: {name}")
                    decoded[name] = image_features(frame, self.size)
                self.templates[part].append((crop(decoded[name], spec["box"]), spec))

    def observe(self, frame):
        features = image_features(frame, self.size)
        observed = {part: locate(features, self.templates[part], self.config) for part in PARTS}
        distances = {}
        for part, point in observed.items():
            if point is not None:
                origin = self.config["parts"][part]["center"]
                distances[part] = round(float(np.linalg.norm(np.subtract(point, origin))), 1)
        if distances.get("base", float("inf")) > self.config["max_base_drift_px"]:
            return "unknown", distances, observed
        moving = [self.config["parts"][part] for part in ("head", "bed")]
        offsets = [distances.get(part) for part in ("head", "bed")]
        if any(offset is not None and offset >= part["far_px"] for part, offset in zip(moving, offsets, strict=True)):
            return "away", distances, observed
        if all(offset is not None and offset <= part["close_px"] for part, offset in zip(moving, offsets, strict=True)):
            return "near", distances, observed
        return "unknown", distances, observed

    def compare(self, frame, twin):
        visual, distances, observed = self.observe(frame)
        delta = np.abs(np.subtract(self.config["reference_xyz_mm"], twin))
        reference_near = np.all(delta <= self.config["twin_close_mm"])
        reference_far = np.any(delta >= self.config["twin_far_mm"])
        if visual == "near" and reference_near:
            comparison = "visually_close"
        elif (visual == "near" and reference_far) or (visual == "away" and reference_near):
            comparison = "divergent"
        else:
            comparison = "unknown"
        return {"comparison": comparison, "camera_reference": visual, "offsets_px": distances, "locations_px": observed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", type=Path)
    parser.add_argument("image", type=Path)
    parser.add_argument("--twin", nargs=3, type=float, required=True, metavar=("X", "Y", "Z"))
    args = parser.parse_args()
    try:
        if not np.isfinite(args.twin).all():
            raise ValueError("pose do twin inválida")
        frame = cv.imread(str(args.image))
        if frame is None:
            raise ValueError("imagem da câmera indisponível")
        result = VisualReference(args.profile).compare(frame, args.twin)
    except (OSError, ValueError, KeyError, cv.error) as error:
        result = {"comparison": "unknown", "reason": str(error)}
    print(json.dumps(result, ensure_ascii=False))
    return 2 if result["comparison"] == "unknown" else 0


if __name__ == "__main__":
    raise SystemExit(main())

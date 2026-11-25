"""Recebe XYZ públicos do rastreador local por socket Unix."""
from __future__ import annotations

import asyncio
import json
import math
import time

BOUNDS = {"x": (-53, 272), "y": (-5, 267), "z": (-5, 261)}
MAX_AGE = 0.85


def public_pose(raw, now: float) -> dict | None:
    if not isinstance(raw, dict):
        return None
    stamp = raw.get("at")
    if type(stamp) not in (int, float) or not math.isfinite(stamp) or not -0.05 <= now - stamp <= MAX_AGE:
        return None
    pose = {}
    for axis, (lo, hi) in BOUNDS.items():
        v = raw.get(axis)
        if type(v) in (int, float) and lo <= v <= hi:
            pose[axis] = v
    return {"at": stamp, **pose} if pose else None


async def read_pose(socket: str) -> dict | None:
    async def receive():
        reader, writer = await asyncio.open_unix_connection(socket, limit=1024)
        try:
            return json.loads(await reader.readline())
        finally:
            writer.close()
            await writer.wait_closed()

    try:
        raw = await asyncio.wait_for(receive(), timeout=0.35)
    except (OSError, ValueError, TimeoutError):
        return None
    return public_pose(raw, time.time())

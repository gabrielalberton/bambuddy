"""Empacota um `Program` em binário compacto para o navegador.

Layout (little-endian):  "A1TW" | u32 versão | u32 tamanho do JSON | JSON (utf-8, padding a 4 bytes) |
  xyz  Int16[N*3] (centésimos de mm, padding a 4) | t    Float32[N] (instante FINAL do registro, s)
  line Uint32[N]                           | kind Uint8[N] (padding a 4) | attr Uint16[N] (padding a 4)
O JSON leva a tabela de atributos, âncoras (M73, camadas, estágios, esperas, trocas), cores e metadados.
"""

from __future__ import annotations

import hashlib
import json
import struct

import numpy as np

from .gcode import Program

MAGIC = b"A1TW"
VERSION = 1


def _pad(b: bytes) -> bytes:
    return b + b"\0" * (-len(b) % 4)


def pack(prog: Program, colors: list[str], job: dict) -> tuple[bytes, str]:
    n = len(prog.t)
    xyz = np.empty((n, 3), dtype=np.int16)
    xyz[:, 0] = np.clip(np.rint(np.frombuffer(prog.x, dtype="f4") * 100), -32000, 32000)
    xyz[:, 1] = np.clip(np.rint(np.frombuffer(prog.y, dtype="f4") * 100), -32000, 32000)
    xyz[:, 2] = np.clip(np.rint(np.frombuffer(prog.z, dtype="f4") * 100), -32000, 32000)
    t32 = np.frombuffer(prog.t, dtype="f8").astype("f4")
    line = np.frombuffer(prog.line, dtype="u4")
    kind = np.frombuffer(prog.kind, dtype="u1")
    attr = np.frombuffer(prog.attr, dtype="u2")

    ev = {"m73": [], "layer": [], "claim": [], "tool": [], "hold": [], "swap": [], "layer_start": [], "temp": []}
    for e in prog.events:
        if e.kind == "m73":
            ev["m73"].append([e.line, round(e.t, 3), e.a, e.b])
        elif e.kind == "layer":
            ev["layer"].append([e.line, round(e.t, 3), int(e.a)])
        elif e.kind == "claim":
            ev["claim"].append([e.line, round(e.t, 3), int(e.a)])
        elif e.kind == "tool":
            ev["tool"].append([e.line, round(e.t, 3), int(e.a)])
        elif e.kind == "hold":
            ev["hold"].append([e.line, round(e.t, 3), round(e.b, 3), e.s, e.a, e.c])
        elif e.kind == "filament_swap":
            ev["swap"].append([e.line, round(e.t, 3), int(e.a), e.s])
        elif e.kind == "temp":
            ev["temp"].append([e.line, round(e.t, 3), int(e.b), e.a, round(e.c, 1)])
        elif e.kind == "layer_start":
            ev["layer_start"].append([e.line, round(e.t, 3), int(e.a), e.b])
    m = prog.meta
    header = {
        "n": n,
        "total_time": round(prog.total_time, 3),
        "lines": prog.n_lines,
        "features": prog.features,
        "attrs": [[a[0], a[1], a[2], a[3], a[4]] for a in prog.attrs],
        "events": ev,
        "colors": colors,
        "meta": {
            k: m.get(k)
            for k in (
                "header_total_time_s",
                "header_model_time_s",
                "total_layers",
                "max_z_height",
                "filament_type",
                "nozzle_diameter",
                "printer_model",
                "filaments_used",
                "curr_bed_type",
                "layer_height",
            )
            if k in m
        },
        "job": job,
    }
    hjb = json.dumps(header, separators=(",", ":")).encode()
    hj = hjb + b" " * (-len(hjb) % 4)
    parts = [
        MAGIC,
        struct.pack("<II", VERSION, len(hj)),
        hj,
        _pad(xyz.tobytes()),
        t32.tobytes(),
        line.tobytes(),
        _pad(kind.tobytes()),
        _pad(attr.tobytes()),
    ]
    blob = b"".join(parts)
    return blob, hashlib.sha1(blob).hexdigest()[:16]

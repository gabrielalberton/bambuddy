"""Identifica o próximo plot despachado para cada impressora no callback de início."""

from __future__ import annotations

import time

FILE_PREFIX = "penplot_"
_PENDING_SECONDS = 300
_pending: dict[int, tuple[str, float]] = {}


def register_plot(printer_id: int, filename: str) -> None:
    _pending[printer_id] = (filename, time.monotonic())


def forget_plot(printer_id: int) -> None:
    _pending.pop(printer_id, None)


def is_plotter_job(printer_id: int, data: dict | None) -> bool:
    """Pula a detecção de objeto só quando o início coincide com um plot recém-despachado."""
    pending = _pending.get(printer_id)
    if pending is None or not isinstance(data, dict):
        return False
    filename, sent_at = pending
    if time.monotonic() - sent_at > _PENDING_SECONDS:
        forget_plot(printer_id)
        return False
    for key in ("subtask_name", "filename", "gcode_file"):
        value = data.get(key)
        if isinstance(value, str) and value.rsplit("/", 1)[-1] in (filename, filename.removesuffix(".3mf")):
            forget_plot(printer_id)
            return True
    return False

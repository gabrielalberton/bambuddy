"""custom(printer-prefs): bico e velocidade no card da página inicial.

- ``POST /custom/printers/{id}/nozzle?diameter=0.2|0.4``: configura o bico na impressora por MQTT LAN
  (``set_accessories``). A A1 não tem sensor de bico: vale o que o dono diz que montou.
  Recusa durante uma impressão.
- ``PUT /custom/printers/{id}/speed?mode=1..4``: com impressão rodando, troca já; sempre grava como
  padrão. O padrão é aplicado a cada impressão nova a partir da camada 2 (a 1ª camada fica no modo do
  arquivo), por um vigia em segundo plano.
- ``GET /custom/printers/{id}/prefs``: padrão gravado, bico e modo atuais.
"""

from __future__ import annotations

import asyncio
import json
import logging
import pathlib
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from backend.app.core.auth import RequirePrinterPermissionIfAuthEnabled
from backend.app.core.permissions import Permission

log = logging.getLogger("custom.printer_prefs")

router = APIRouter(prefix="/custom/printers", tags=["custom"])

NOZZLE_OPTIONS = ("0.2", "0.4")
SPEED_MODES = (1, 2, 3, 4)
APPLY_FROM_LAYER = 2
POLL_SECONDS = 10
BUSY_STATES = {"RUNNING", "PAUSE", "PREPARE", "SLICING"}


def _prefs_path() -> pathlib.Path:
    from backend.app.core.config import settings

    return pathlib.Path(settings.base_dir) / "custom" / "printer_prefs.json"


def load_prefs() -> dict[str, Any]:
    try:
        return json.loads(_prefs_path().read_text())
    except (OSError, ValueError):
        return {}


def save_prefs(prefs: dict[str, Any]) -> None:
    path = _prefs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(prefs, indent=2, sort_keys=True))
    tmp.replace(path)


def _printer_prefs(printer_id: int) -> dict[str, Any]:
    return load_prefs().get(str(printer_id), {})


def _client(printer_id: int):
    from backend.app.services.printer_manager import printer_manager

    client = printer_manager.get_client(printer_id)
    if client is None or not getattr(client.state, "connected", False):
        raise HTTPException(400, "Impressora desconectada")
    return client


def _current_nozzle(client) -> str:
    nozzles = getattr(client.state, "nozzles", None) or []
    return str(getattr(nozzles[0], "nozzle_diameter", "") or "") if nozzles else ""


@router.get("/{printer_id}/prefs")
async def get_prefs(printer_id: int, _=RequirePrinterPermissionIfAuthEnabled(Permission.PRINTERS_READ)):
    ensure_applier()
    from backend.app.services.printer_manager import printer_manager

    client = printer_manager.get_client(printer_id)
    state = getattr(client, "state", None)
    return {
        "default_speed": _printer_prefs(printer_id).get("default_speed"),
        "speed_level": getattr(state, "speed_level", None),
        "nozzle_diameter": _current_nozzle(client) if client else "",
        "nozzle_options": list(NOZZLE_OPTIONS),
        "apply_from_layer": APPLY_FROM_LAYER,
    }


@router.put("/{printer_id}/speed")
async def set_speed(
    printer_id: int,
    mode: int = Query(..., ge=1, le=4),
    _=RequirePrinterPermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
):
    ensure_applier()
    prefs = load_prefs()
    prefs.setdefault(str(printer_id), {})["default_speed"] = mode
    save_prefs(prefs)
    applied_now = False
    from backend.app.services.printer_manager import printer_manager

    client = printer_manager.get_client(printer_id)
    if client is not None and getattr(client.state, "state", "") in ("RUNNING", "PAUSE"):
        applied_now = bool(client.set_print_speed(mode))
        _applied[printer_id] = _job_key(client.state)
    return {"success": True, "default_speed": mode, "applied_now": applied_now}


@router.post("/{printer_id}/nozzle")
async def set_nozzle(
    printer_id: int,
    diameter: str = Query(...),
    _=RequirePrinterPermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
):
    if diameter not in NOZZLE_OPTIONS:
        raise HTTPException(400, f"Bico deve ser um de {', '.join(NOZZLE_OPTIONS)}")
    client = _client(printer_id)
    if getattr(client.state, "state", "") in BUSY_STATES:
        raise HTTPException(409, "Não dá para trocar o bico durante uma impressão")
    nozzles = getattr(client.state, "nozzles", None) or []
    nozzle_type = (getattr(nozzles[0], "nozzle_type", "") if nozzles else "") or "stainless_steel"
    command = {
        "system": {
            "sequence_id": "0",
            "command": "set_accessories",
            "accessory_type": "nozzle",
            "nozzle_diameter": float(diameter),
            "nozzle_type": nozzle_type,
        }
    }
    if not client._client:  # noqa: SLF001 - mesmo cliente paho que o upstream usa
        raise HTTPException(400, "Impressora desconectada")
    client._client.publish(client.topic_publish, json.dumps(command), qos=1)  # noqa: SLF001
    log.info("printer %s: bico configurado para %s (%s)", printer_id, diameter, nozzle_type)
    return {"success": True, "nozzle_diameter": diameter, "nozzle_type": nozzle_type}


# ----- vigia: aplica a velocidade padrão em cada impressão nova -----

_applied: dict[int, tuple | None] = {}
_task: asyncio.Task | None = None


def _job_key(state) -> tuple:
    return (
        getattr(state, "subtask_name", None),
        getattr(state, "gcode_file", None),
        getattr(state, "subtask_id", None),
    )


def apply_once(printer_id: int, client, default_speed: int | None) -> bool:
    """Uma rodada do vigia para uma impressora. Devolve se mandou o comando."""
    state = getattr(client, "state", None)
    if state is None:
        return False
    if getattr(state, "state", "") not in ("RUNNING", "PAUSE"):
        _applied.pop(printer_id, None)
        return False
    if default_speed not in SPEED_MODES:
        return False
    key = _job_key(state)
    if _applied.get(printer_id) == key or (getattr(state, "layer_num", 0) or 0) < APPLY_FROM_LAYER:
        return False
    _applied[printer_id] = key
    if getattr(state, "speed_level", None) == default_speed:
        return False
    sent = bool(client.set_print_speed(default_speed))
    log.info("printer %s: velocidade padrão %s aplicada (camada %s)", printer_id, default_speed, state.layer_num)
    return sent


async def _applier() -> None:
    from backend.app.services.printer_manager import printer_manager

    while True:
        try:
            for pid_str, prefs in load_prefs().items():
                client = printer_manager.get_client(int(pid_str))
                if client is not None:
                    apply_once(int(pid_str), client, prefs.get("default_speed"))
        except Exception:  # noqa: BLE001 - o vigia nunca pode morrer
            log.exception("vigia de velocidade falhou")
        await asyncio.sleep(POLL_SECONDS)


def ensure_applier() -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.get_running_loop().create_task(_applier())


class StartApplierMiddleware:
    """Inicia o vigia no startup (lifespan) sem tocar no ``main.py`` do upstream."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "lifespan":
            try:
                ensure_applier()
                from backend.app.custom.library_org.service import ensure_auto

                ensure_auto()
            except RuntimeError:
                pass
        await self.app(scope, receive, send)

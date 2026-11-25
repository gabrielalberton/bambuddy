"""custom(plotter): API do plotter de caneta na A1 (custom/docs/plotter.md).

Leitura pede ``printers:read``; vetorizar e gerar plano pedem ``printers:files``; gravar perfil, mover a
impressora e iniciar o plot pedem ``printers:control`` da impressora em questão.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from backend.app.core.auth import (
    RequestPrinterScope,
    RequirePermissionIfAuthEnabled,
    RequirePrinterPermissionIfAuthEnabled,
)
from backend.app.core.permissions import Permission
from backend.app.core.printer_scope import PrinterScope

from . import engine as E, printer as P, store, vision_api, worker

log = logging.getLogger("custom.plotter")

router = APIRouter(prefix="/custom/plotter", tags=["custom-plotter"])

MAX_UPLOAD_BYTES = 30 * 1024 * 1024


def plotter_enabled() -> bool:
    return os.environ.get("BAMBUDDY_CUSTOM_PLOTTER", "on").strip().lower() not in ("off", "0", "false", "no")


def _fail(exc: Exception) -> HTTPException:
    if isinstance(exc, P.Blocked):
        return HTTPException(exc.status, detail={"message": str(exc), "reasons": exc.reasons})
    if isinstance(exc, worker.JobError):
        log.error("plotter: %s", exc)
        return HTTPException(500, detail={"message": str(exc).splitlines()[0], "reasons": []})
    return HTTPException(422, detail={"message": str(exc), "reasons": []})


class SettingsBody(BaseModel):
    pens: dict
    active_pen: str | None = None
    paper: dict | None = None
    placement: dict | None = None


class VectorizeBody(BaseModel):
    options: dict = Field(default_factory=dict)


class PlanBody(BaseModel):
    kind: Literal["drawing", "ladder", "cross", "frame"] = "drawing"
    drawing_id: str | None = None
    placement: dict | None = None
    paper: dict | None = None
    pen_id: str | None = None
    options: dict = Field(default_factory=dict)
    depths: list[float] | None = Field(default=None, max_length=24)
    target: list[float] | None = Field(default=None, min_length=2, max_length=2)
    title: str | None = Field(default=None, max_length=80)


class JogStartBody(BaseModel):
    pen_id: str | None = None
    target: list[float] | None = Field(default=None, min_length=2, max_length=2)


class JogMoveBody(BaseModel):
    z: float


class JogFinishBody(BaseModel):
    save: bool = False


# ---------------------------------------------------------------- leitura
@router.get("/config")
async def get_config(
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
    printer_scope: PrinterScope = RequestPrinterScope,
):
    return {
        "enabled": True,
        "paper_presets": [{"id": k, "w": v[0], "h": v[1]} for k, v in E.PAPER_PRESETS.items()],
        "mounts": [E.mount_info(m) for m in E.MOUNTS.values()],
        "max_upload_mb": MAX_UPLOAD_BYTES // (1024 * 1024),
        "limits": {
            "nozzle_max_temp": P.MAX_NOZZLE_TEMP,
            "bed_max_temp": P.MAX_BED_TEMP,
            "jog_max_step": P.JOG_MAX_STEP,
            "jog_max_z": P.JOG_MAX_Z,
        },
        "printers": [
            {**printer, "plate_vision": vision_api.profile_path(printer["id"]).is_file()}
            for printer in await P.list_printers(printer_scope)
        ],
    }


@router.get("/printers/{printer_id}/status")
async def get_status(printer_id: int, _=RequirePrinterPermissionIfAuthEnabled(Permission.PRINTERS_READ)):
    snap = P.snapshot(printer_id)
    return {**snap, "blockers": P.blockers(snap)}


@router.get("/printers/{printer_id}/plate-camera")
async def get_plate_camera(
    printer_id: int, topdown: bool = False, _=RequirePrinterPermissionIfAuthEnabled(Permission.PRINTERS_READ)
):
    """``topdown=true`` troca o quadro bruto pela vista aérea corrigida do prato (com margem escurecida)."""
    return await vision_api.match(printer_id, topdown)


@router.get("/printers/{printer_id}/settings")
async def get_settings(printer_id: int, _=RequirePrinterPermissionIfAuthEnabled(Permission.PRINTERS_READ)):
    return _settings_view(printer_id, store.load_settings(printer_id))


@router.put("/printers/{printer_id}/settings")
async def put_settings(
    printer_id: int, body: SettingsBody, _=RequirePrinterPermissionIfAuthEnabled(Permission.PRINTERS_CONTROL)
):
    try:
        saved = store.save_settings(printer_id, body.model_dump())
    except E.ProfileError as exc:
        raise _fail(exc) from exc
    return _settings_view(printer_id, saved)


def _settings_view(printer_id: int, doc: dict) -> dict:
    """Ajustes + o que deriva deles (área útil, alcance, ponto do home) para a tela desenhar a mesa."""
    machine = E.A1
    paper = E.Paper.from_dict(doc["paper"])
    derived = {}
    for pen_id, raw in doc["pens"].items():
        pen = E.PenProfile.from_dict(raw)
        area = E.drawable_area(machine, pen, paper)
        derived[pen_id] = {
            "reach": [round(v, 2) for v in E.pen_reach(machine, pen)],
            "area": [round(v, 2) for v in area] if area else None,
            "width_range": [round(v, 3) for v in pen.width_range()],
            "mount": pen.mount,
            "jog_steps": list(pen.mount_spec.jog_steps),
            "contact_calibrated": pen.contact_calibrated,
            "pressure_calibrated": pen.pressure_calibrated,
            "ladder_depths": E.calibration.default_ladder_depths(pen),
        }
    hx, hy, on_paper = E.home_point(machine, paper)
    return {**doc, "derived": derived, "home": [hx, hy, on_paper], "machine": P.machine_info(machine)}


# ---------------------------------------------------------------- desenhos
async def _vectorize(item_id: str, data: bytes, options: dict, name: str | None, keep_source: bool) -> dict:
    try:
        result = await worker.run("vectorize", data, options, timeout=worker.VECTORIZE_TIMEOUT)
    except (ValueError, worker.JobError) as exc:
        raise _fail(exc) from exc
    drawing = result["drawing"]
    if name:
        drawing["meta"]["name"] = name
    store.save_drawing(item_id, drawing, data if keep_source else None, result["preview"] or None)
    return {"id": item_id, **drawing}


@router.post("/drawings")
async def create_drawing(
    file: UploadFile = File(...),
    options: str = Form("{}"),
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_FILES),
):
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, detail={"message": "Imagem grande demais.", "reasons": []})
    if not data:
        raise HTTPException(422, detail={"message": "Arquivo vazio.", "reasons": []})
    try:
        opts = json.loads(options or "{}")
        if not isinstance(opts, dict):
            raise ValueError
    except ValueError as exc:
        raise HTTPException(422, detail={"message": "Opções inválidas.", "reasons": []}) from exc
    name = (file.filename or "").rsplit("/", 1)[-1].rsplit(".", 1)[0][:60] or "desenho"
    return await _vectorize(store.new_id(), data, opts, name, keep_source=True)


@router.post("/drawings/{drawing_id}/vectorize")
async def revectorize(
    drawing_id: str, body: VectorizeBody, _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_FILES)
):
    source = store.drawing_file(drawing_id, "source.bin")
    old = store.load_drawing(drawing_id)
    if source is None or old is None:
        raise HTTPException(404, detail={"message": "Desenho não encontrado: envie a imagem de novo.", "reasons": []})
    name = (old.get("meta") or {}).get("name")
    return await _vectorize(drawing_id, source.read_bytes(), body.options, name, keep_source=False)


@router.get("/drawings/{drawing_id}")
async def get_drawing(drawing_id: str, _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ)):
    drawing = store.load_drawing(drawing_id)
    if drawing is None:
        raise HTTPException(404, detail={"message": "Desenho não encontrado.", "reasons": []})
    return {"id": drawing_id, **drawing}


@router.get("/drawings/{drawing_id}/image")
async def get_drawing_image(drawing_id: str, _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ)):
    path = store.drawing_file(drawing_id, "preview.jpg")
    if path is None:
        raise HTTPException(404, detail={"message": "Imagem não encontrada.", "reasons": []})
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


# ---------------------------------------------------------------- planos
@router.post("/printers/{printer_id}/plans")
async def create_plan(
    printer_id: int, body: PlanBody, _=RequirePrinterPermissionIfAuthEnabled(Permission.PRINTERS_FILES)
):
    row = await P.printer_row(printer_id)
    machine = E.machine_for_model(getattr(row, "model", None))
    if row is None:
        raise HTTPException(404, detail={"message": "Impressora não encontrada.", "reasons": []})
    if machine is None:
        raise HTTPException(422, detail={"message": "O plotter só funciona na Bambu Lab A1.", "reasons": []})
    doc = store.load_settings(printer_id)
    pen_id = body.pen_id if body.pen_id in doc["pens"] else doc["active_pen"]
    request: dict = {
        "kind": body.kind,
        "machine": machine.key,
        "pen": doc["pens"][pen_id],
        "paper": body.paper or doc["paper"],
        "title": body.title or body.kind,
    }
    if body.kind == "drawing":
        drawing = store.load_drawing(body.drawing_id or "")
        if drawing is None:
            raise HTTPException(404, detail={"message": "Desenho não encontrado: envie a imagem de novo.", "reasons": []})
        request.update(drawing=drawing, placement=body.placement, options=body.options)
        request["title"] = body.title or (drawing.get("meta") or {}).get("name") or "desenho"
    else:
        request.update(depths=body.depths, target=body.target)
    try:
        result = await worker.run("plan", request, timeout=worker.PLAN_TIMEOUT)
    except (ValueError, worker.JobError) as exc:
        raise _fail(exc) from exc
    plan_id = store.new_id()
    summary = {**result["summary"], "id": plan_id, "printer_id": printer_id, "pen_id": pen_id}
    if body.kind == "drawing":
        summary["drawing_id"] = body.drawing_id
    stored = {k: v for k, v in summary.items() if k != "sim"}
    store.save_plan(plan_id, stored, result["package"])
    return summary


@router.get("/printers/{printer_id}/plans/{plan_id}")
async def get_plan(printer_id: int, plan_id: str, _=RequirePrinterPermissionIfAuthEnabled(Permission.PRINTERS_READ)):
    summary = store.load_plan(plan_id)
    if summary is None or summary.get("printer_id") != printer_id:
        raise HTTPException(404, detail={"message": "Plano não encontrado.", "reasons": []})
    return summary


@router.get("/printers/{printer_id}/plans/{plan_id}/download")
async def download_plan(
    printer_id: int, plan_id: str, _=RequirePrinterPermissionIfAuthEnabled(Permission.PRINTERS_READ)
):
    summary = store.load_plan(plan_id)
    path = store.plan_package(plan_id)
    if summary is None or path is None or summary.get("printer_id") != printer_id:
        raise HTTPException(404, detail={"message": "Plano não encontrado.", "reasons": []})
    name = f"{E.gcode.clean_title(summary.get('title') or 'plot').replace(' ', '_')}.gcode.3mf"
    return FileResponse(path, media_type="application/octet-stream", filename=name)


@router.post("/printers/{printer_id}/plans/{plan_id}/start")
async def start_plan(
    printer_id: int, plan_id: str, _=RequirePrinterPermissionIfAuthEnabled(Permission.PRINTERS_CONTROL)
):
    try:
        return await P.start_plan(printer_id, plan_id)
    except P.Blocked as exc:
        raise _fail(exc) from exc


# ---------------------------------------------------------------- ajuste de altura
@router.post("/printers/{printer_id}/jog/start")
async def jog_start(
    printer_id: int, body: JogStartBody, _=RequirePrinterPermissionIfAuthEnabled(Permission.PRINTERS_CONTROL)
):
    try:
        async with P.motion_lock(printer_id):
            return await P.jog_start(printer_id, body.pen_id, tuple(body.target) if body.target else None)
    except (P.Blocked, E.ProfileError) as exc:
        raise _fail(exc) from exc


@router.post("/printers/{printer_id}/jog/move")
async def jog_move(
    printer_id: int, body: JogMoveBody, _=RequirePrinterPermissionIfAuthEnabled(Permission.PRINTERS_CONTROL)
):
    try:
        async with P.motion_lock(printer_id):
            return await P.jog_move(printer_id, body.z)
    except P.Blocked as exc:
        raise _fail(exc) from exc


@router.post("/printers/{printer_id}/jog/finish")
async def jog_finish(
    printer_id: int, body: JogFinishBody, _=RequirePrinterPermissionIfAuthEnabled(Permission.PRINTERS_CONTROL)
):
    try:
        async with P.motion_lock(printer_id):
            return await P.jog_finish(printer_id, body.save)
    except (P.Blocked, E.ProfileError) as exc:
        raise _fail(exc) from exc

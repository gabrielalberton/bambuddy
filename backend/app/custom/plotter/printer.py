"""Lado da impressora: estado, bloqueios de segurança, envio do plot e sessão de ajuste de altura.

Nada aqui move a impressora por conta própria: ``start_plan`` e as funções de ``jog_*`` só são chamadas
pelas rotas que o usuário aciona, com a permissão de controle da impressora.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import engine as E, store
from .hooks import FILE_PREFIX, is_plotter_job  # noqa: F401 - reexportado

log = logging.getLogger("custom.plotter")

IDLE_STATES = {"IDLE", "FINISH", "FAILED"}
ACTIVE_STATES = {"PREPARE", "SLICING", "RUNNING", "PAUSE"}
MAX_NOZZLE_TEMP = 50.0  # °C: bico quente a poucos mm do papel pinga filamento no desenho
MAX_BED_TEMP = 45.0
JOG_START_Z = 20.0  # altura do bico ao levar a caneta para cima do papel (suporte padrão: ponta ~4 mm abaixo)
JOG_MAX_Z = 40.0
JOG_MAX_STEP = 5.0
JOG_IDLE_SECONDS = 600  # depois disso os motores podem ter desligado: a posição não vale mais
ACK_TIMEOUT = 12.0
_start_locks: dict[int, asyncio.Lock] = {}


class Blocked(Exception):
    """Operação recusada; ``reasons`` é a lista de bloqueios (código + texto)."""

    def __init__(self, reasons: list[dict], status: int = 409) -> None:
        super().__init__("; ".join(r["text"] for r in reasons))
        self.reasons = reasons
        self.status = status


def _manager():
    from backend.app.services.printer_manager import printer_manager

    return printer_manager


async def printer_row(printer_id: int):
    from sqlalchemy import select

    from backend.app.core.database import async_session
    from backend.app.models.printer import Printer

    async with async_session() as db:
        return (await db.execute(select(Printer).where(Printer.id == printer_id))).scalar_one_or_none()


async def list_printers() -> list[dict]:
    from sqlalchemy import select

    from backend.app.core.database import async_session
    from backend.app.models.printer import Printer

    async with async_session() as db:
        rows = (await db.execute(select(Printer).order_by(Printer.id))).scalars().all()
    out = []
    for row in rows:
        machine = E.machine_for_model(row.model)
        out.append(
            {
                "id": row.id,
                "name": row.name,
                "model": row.model,
                "supported": machine is not None,
                "machine": machine_info(machine) if machine else None,
            }
        )
    return out


def machine_info(machine: E.Machine) -> dict:
    return {
        "key": machine.key,
        "name": machine.name,
        "plate_w": machine.plate_w,
        "plate_h": machine.plate_h,
        "nozzle_x": list(machine.nozzle_x),
        "nozzle_y": list(machine.nozzle_y),
        "nozzle_z_min": machine.nozzle_z_min,
        "home_y": machine.home_y,
    }


def _num(value) -> float | None:
    try:
        return round(float(value), 1)
    except (TypeError, ValueError):
        return None


def snapshot(printer_id: int) -> dict:
    manager = _manager()
    client = manager.get_client(printer_id)
    state = getattr(client, "state", None)
    temps = getattr(state, "temperatures", None) or {}
    raw = getattr(state, "raw_data", None) or {}
    home_flag = raw.get("home_flag")
    subtask = getattr(state, "subtask_name", None) or ""
    gstate = str(getattr(state, "state", "unknown") or "unknown")
    return {
        "connected": bool(state is not None and getattr(state, "connected", False)),
        "state": gstate,
        "nozzle": _num(temps.get("nozzle")),
        "nozzle_target": _num(temps.get("nozzle_target")),
        "bed": _num(temps.get("bed")),
        "bed_target": _num(temps.get("bed_target")),
        "homed": type(home_flag) is int and home_flag & 7 == 7,
        "awaiting_plate_clear": bool(manager.is_awaiting_plate_clear(printer_id)),
        "subtask": subtask,
        "progress": _num(getattr(state, "progress", None)),
        "plotting": gstate in ACTIVE_STATES and subtask.startswith(FILE_PREFIX),
        "jog": jog_public(printer_id),
    }


def blockers(snap: dict, for_plot: bool = True) -> list[dict]:
    """Por que não dá para mover a impressora agora (lista vazia = pode)."""
    out: list[dict] = []
    if not snap["connected"]:
        return [{"code": "offline", "text": "Impressora desconectada."}]
    if snap["state"] not in IDLE_STATES:
        out.append({"code": "busy", "text": f"A impressora está ocupada ({snap['state']})."})
    if (snap["nozzle_target"] or 0) > 0 or (snap["nozzle"] or 0) > MAX_NOZZLE_TEMP:
        out.append(
            {
                "code": "nozzle_hot",
                "text": f"Bico quente ou aquecendo ({snap['nozzle']} °C). Espere esfriar abaixo de "
                f"{MAX_NOZZLE_TEMP:.0f} °C.",
            }
        )
    if (snap["bed_target"] or 0) > 0 or (snap["bed"] or 0) > MAX_BED_TEMP:
        out.append({"code": "bed_hot", "text": f"Mesa quente ou aquecendo ({snap['bed']} °C)."})
    if for_plot and snap["awaiting_plate_clear"]:
        out.append(
            {
                "code": "plate_not_cleared",
                "text": "O Bambuddy está esperando a confirmação de mesa liberada do trabalho anterior.",
            }
        )
    return out


def _check(printer_id: int, for_plot: bool = True) -> dict:
    snap = snapshot(printer_id)
    reasons = blockers(snap, for_plot)
    if reasons:
        raise Blocked(reasons)
    return snap


# ---------------------------------------------------------------- envio do plot
async def start_plan(printer_id: int, plan_id: str) -> dict:
    """Confere tudo de novo, envia o ``.gcode.3mf`` por FTPS e manda imprimir, sem nenhuma calibração."""
    lock = _start_locks.setdefault(printer_id, asyncio.Lock())
    if lock.locked():
        raise Blocked([{"code": "starting", "text": "Já existe um envio em andamento."}])
    async with lock:
        summary = store.load_plan(plan_id)
        package_path = store.plan_package(plan_id)
        if not summary or package_path is None or not summary.get("ok"):
            raise Blocked([{"code": "no_plan", "text": "Plano não encontrado ou recusado: gere de novo."}], 404)
        if summary.get("printer_id") != printer_id:
            raise Blocked([{"code": "wrong_printer", "text": "Este plano foi gerado para outra impressora."}])
        row = await printer_row(printer_id)
        machine = E.machine_for_model(getattr(row, "model", None))
        if row is None or machine is None:
            raise Blocked([{"code": "unsupported", "text": "O plotter só funciona na Bambu Lab A1."}])
        # O plano vale para a caneta e o papel com que foi gerado: se a calibração mudou, não serve mais.
        pen_id, pen_now = store.get_pen(printer_id, summary.get("pen_id"))
        if pen_id != summary.get("pen_id") or pen_now.to_dict() != summary.get("pen"):
            raise Blocked([{"code": "stale", "text": "A caneta mudou depois que o plano foi gerado: gere de novo."}])
        pen = E.PenProfile.from_dict(summary["pen"])
        paper = E.Paper.from_dict(summary["paper"])
        gcode = await asyncio.to_thread(lambda: E.package.read_gcode(package_path.read_bytes()))
        report = await asyncio.to_thread(E.validate, gcode, machine, pen, paper, False)
        if not report.ok:
            raise Blocked([{"code": "invalid", "text": "O G-code não passou na validação: gere de novo."}])
        _check(printer_id)
        jog_drop(printer_id)

        from backend.app.services.bambu_ftp import (
            FtpFailureReport,
            delete_file_async,
            describe_upload_failure,
            get_ftp_retry_settings,
            upload_file_async,
            with_ftp_retry,
        )

        remote_name = f"{FILE_PREFIX}{plan_id}.3mf"
        remote_path = f"/{remote_name}"
        retry_on, retry_count, retry_delay, ftp_timeout = await get_ftp_retry_settings()
        failure = FtpFailureReport()
        kwargs = {
            "socket_timeout": ftp_timeout,
            "printer_model": row.model,
            "respect_handshake_cooloff": False,
            "failure": failure,
        }
        try:
            if retry_on:
                uploaded = await with_ftp_retry(
                    upload_file_async,
                    row.ip_address,
                    row.access_code,
                    Path(package_path),
                    remote_path,
                    max_retries=retry_count,
                    retry_delay=retry_delay,
                    operation_name=f"Upload plot to {row.name}",
                    **kwargs,
                )
            else:
                uploaded = await upload_file_async(
                    row.ip_address, row.access_code, Path(package_path), remote_path, **kwargs
                )
        except Exception as exc:  # noqa: BLE001 - qualquer falha de rede vira "não enviou"
            log.warning("plotter: upload falhou: %s", exc)
            uploaded = False
        if not uploaded:
            raise Blocked([{"code": "upload_failed", "text": describe_upload_failure(failure.failure)}], 502)
        # O envio pode levar alguns segundos: confere o estado de novo antes do comando.
        started = False
        try:
            _check(printer_id)
            started = bool(
                _manager().start_print(
                    printer_id,
                    remote_name,
                    plate_id=1,
                    ams_mapping=None,
                    bed_levelling="off",
                    flow_cali="off",
                    vibration_cali=False,
                    layer_inspect=False,
                    timelapse=False,
                    use_ams=False,
                    nozzle_offset_cali="off",
                )
            )
        finally:
            if not started:
                # arquivo que ficou na raiz do SD sem ser impresso vira impressão fantasma ao religar a A1
                try:
                    await delete_file_async(row.ip_address, row.access_code, remote_path, printer_model=row.model)
                except Exception as exc:  # noqa: BLE001
                    log.warning("plotter: não consegui apagar %s do SD: %s", remote_path, exc)
        if not started:
            raise Blocked([{"code": "start_refused", "text": "A impressora não aceitou o início do plot."}], 502)
        log.info("plotter: plano %s enviado para a impressora %s como %s", plan_id, printer_id, remote_name)
        return {"started": True, "file": remote_name, "time_s": summary.get("stats", {}).get("time_s")}


# ---------------------------------------------------------------- ajuste de altura (jog)
@dataclass
class JogSession:
    printer_id: int
    pen_id: str
    z: float  # Z do bico comandado
    target: tuple[float, float]  # ponta da caneta, mm da mesa
    home_on_paper: bool
    paper_thickness: float
    floor: float
    updated: float = field(default_factory=time.time)
    moving_until: float = 0.0


_jog: dict[int, JogSession] = {}


def jog_drop(printer_id: int) -> None:
    _jog.pop(printer_id, None)


def jog_public(printer_id: int) -> dict | None:
    s = _jog.get(printer_id)
    if s is None:
        return None
    if time.time() - s.updated > JOG_IDLE_SECONDS:
        jog_drop(printer_id)
        return None
    return {
        "pen_id": s.pen_id,
        "z": round(s.z, 2),
        "target": [round(s.target[0], 2), round(s.target[1], 2)],
        "floor": s.floor,
        "max": JOG_MAX_Z,
        "settling": max(0.0, round(s.moving_until - time.time(), 1)),
        "home_on_paper": s.home_on_paper,
    }


SEND_CHUNK = 10  # linhas por mensagem MQTT


async def _send(printer_id: int, lines: list[str]) -> None:
    """Manda G-code por MQTT, em blocos, esperando o aceite da impressora a cada bloco."""
    for i in range(0, len(lines), SEND_CHUNK):
        await _send_block(printer_id, "\n".join(lines[i : i + SEND_CHUNK]))


async def _send_block(printer_id: int, gcode: str) -> None:
    client = _manager().get_client(printer_id)
    if client is None or not client.state.connected:
        raise Blocked([{"code": "offline", "text": "Impressora desconectada."}])
    loop = asyncio.get_running_loop()
    ack: asyncio.Future = loop.create_future()
    sent_seq: list[str] = []

    def process(report: dict) -> None:
        if report.get("command") != "gcode_line" or "result" not in report or ack.done():
            return
        same_seq = bool(sent_seq) and str(report.get("sequence_id", "")) == sent_seq[0]
        if same_seq or str(report.get("param", "")).strip() == gcode:
            ack.set_result(str(report["result"]).lower() == "success")

    def on_report(topic, payload) -> None:
        if topic != client.topic_subscribe:
            return
        try:
            message = json.loads(payload)
        except (ValueError, UnicodeError):
            return
        report = message.get("print") if isinstance(message, dict) else None
        if isinstance(report, dict):
            loop.call_soon_threadsafe(process, report)

    client.register_raw_message_handler(on_report)
    try:
        if not client.send_gcode(gcode):
            raise Blocked([{"code": "send_failed", "text": "Não consegui enviar o comando para a impressora."}], 502)
        sent_seq.append(str(getattr(client, "_sequence_id", "")))
        try:
            accepted = await asyncio.wait_for(ack, ACK_TIMEOUT)
        except TimeoutError as exc:
            raise Blocked([{"code": "no_ack", "text": "A impressora não confirmou o comando."}], 504) from exc
        if not accepted:
            raise Blocked([{"code": "rejected", "text": "A impressora recusou o comando."}], 502)
    finally:
        client.unregister_raw_message_handler(on_report)


def _command_lines(lines: list[str]) -> list[str]:
    """Tira comentários e o que só faz sentido dentro de um job (progresso, estágio)."""
    out = []
    for line in lines:
        code = line.split(";", 1)[0].strip()
        if code and not code.startswith(("M73", "M1002")):
            out.append(code)
    return out


async def jog_start(printer_id: int, pen_id: str | None = None, target: tuple[float, float] | None = None) -> dict:
    """Faz o home (com a caneta fora da mesa) e leva a caneta para cima do papel, alta."""
    _check(printer_id, for_plot=False)
    row = await printer_row(printer_id)
    machine = E.machine_for_model(getattr(row, "model", None))
    if machine is None:
        raise Blocked([{"code": "unsupported", "text": "O plotter só funciona na Bambu Lab A1."}])
    pid, pen = store.get_pen(printer_id, pen_id)
    paper = E.Paper.from_dict(store.load_settings(printer_id)["paper"])
    area = E.drawable_area(machine, pen, paper)
    if area is None:
        raise Blocked([{"code": "no_area", "text": "O papel não tem área útil dentro do alcance da caneta."}])
    tx, ty = target if target else ((area[0] + area[2]) / 2.0, (area[1] + area[3]) / 2.0)
    if not (area[0] <= tx <= area[2] and area[1] <= ty <= area[3]):
        raise Blocked([{"code": "target_off", "text": "O ponto escolhido está fora da área útil do papel."}])
    home = E.home_point(machine, paper)
    lines = _command_lines(E.gcode.start_lines(machine, pen, home, JOG_START_Z))
    lines += [f"G0 X{E.gcode.fmt(tx - pen.offset_x)} Y{E.gcode.fmt(ty - pen.offset_y)} F6000", "M400"]
    await _send(printer_id, lines)
    _jog[printer_id] = JogSession(
        printer_id=printer_id,
        pen_id=pid,
        z=JOG_START_Z,
        target=(tx, ty),
        home_on_paper=home[2],
        paper_thickness=paper.thickness,
        floor=machine.nozzle_z_min,
        moving_until=time.time() + 45.0,
    )
    return jog_public(printer_id) or {}


async def jog_move(printer_id: int, z: float) -> dict:
    s = _jog.get(printer_id)
    if s is None or jog_public(printer_id) is None:
        raise Blocked([{"code": "no_session", "text": "Sessão de ajuste expirada: refaça o home."}])
    _check(printer_id, for_plot=False)
    z = round(float(z), 2)
    if not (s.floor <= z <= JOG_MAX_Z):
        raise Blocked([{"code": "z_range", "text": f"Altura fora da faixa permitida ({s.floor}..{JOG_MAX_Z} mm)."}], 400)
    if abs(z - s.z) > JOG_MAX_STEP + 1e-9:
        raise Blocked([{"code": "step", "text": f"Passo grande demais (máximo {JOG_MAX_STEP:g} mm por vez)."}], 400)
    await _send(printer_id, ["G90", f"G1 Z{E.gcode.fmt(z)} F300", "M400"])
    s.moving_until = time.time() + abs(z - s.z) / 5.0 + 0.3
    s.z = z
    s.updated = time.time()
    return jog_public(printer_id) or {}


async def jog_finish(printer_id: int, save: bool) -> dict:
    """Levanta a caneta e traz a mesa para a frente. Com ``save``, grava a altura atual como contato."""
    s = _jog.get(printer_id)
    if s is None or jog_public(printer_id) is None:
        raise Blocked([{"code": "no_session", "text": "Sessão de ajuste expirada: refaça o home."}])
    _check(printer_id, for_plot=False)
    saved = None
    if save:
        saved = round(s.z + (s.paper_thickness if s.home_on_paper else 0.0), 2)
        store.update_pen(printer_id, s.pen_id, {"z_contact": saved})
    up = min(JOG_MAX_Z, s.z + 20.0)
    try:
        await _send(printer_id, ["G90", f"G1 Z{E.gcode.fmt(up)} F600", "G0 X128 Y254 F6000", "M400"])
    finally:
        jog_drop(printer_id)
    return {"saved_z_contact": saved, "pen_id": s.pen_id}

"""Movimento explícito para o ponto de referência manual da A1."""

from __future__ import annotations

import asyncio
import json

from fastapi import HTTPException

A1_MODELS = {"A1", "N2S", "A11"}
IDLE_STATES = {"IDLE", "FINISH", "FAILED"}
POSITION = {"x": 128, "y": 128, "z": 20}
# A A1 recebe uma sequência única. M400 mantém a ordem dentro da fila do firmware.
GCODE = f"G28\nM400\nG90\nG1 Z{POSITION['z']} F1200\nG1 X{POSITION['x']} Y{POSITION['y']} F6000\nM400"
# O ACK é de aceitação. Reservar tempo para homing e até o curso inteiro de Z a 20 mm/s.
SETTLE_SECONDS = 30
REPORT_TIMEOUT = 12
_in_progress: set[int] = set()


async def move_to_reference(manager, printer_id: int):
    if printer_id in _in_progress:
        raise HTTPException(409, "Reference movement already in progress")
    client = manager.get_client(printer_id)
    if client is None or not client.state.connected:
        raise HTTPException(409, "Printer is not connected")
    if client.state.state not in IDLE_STATES:
        raise HTTPException(409, "Printer must be idle")

    loop = asyncio.get_running_loop()
    ack = loop.create_future()
    fresh_home = asyncio.Event()
    home_flag = client.state.raw_data.get("home_flag")
    settled = loop.time() + SETTLE_SECONDS
    initial_print_error = client.state.raw_data.get("print_error") or 0
    interrupted = False

    def process(report):
        nonlocal home_flag, interrupted
        if report.get("command") == "gcode_line":
            if not ack.done() and str(report.get("param", "")).strip() == GCODE and "result" in report:
                ack.set_result(report["result"] == "success")
        elif report.get("command") == "push_status":
            if report.get("gcode_state", "IDLE") not in IDLE_STATES or report.get("print_error", initial_print_error) != initial_print_error:
                interrupted = True
            home_flag = report.get("home_flag", home_flag)
            if loop.time() >= settled and type(home_flag) is int and home_flag & 7 == 7:
                fresh_home.set()

    def on_report(topic, payload):
        if topic != client.topic_subscribe:
            return
        try:
            message = json.loads(payload)
        except (ValueError, UnicodeError):
            return
        report = message.get("print") if isinstance(message, dict) else None
        if isinstance(report, dict):
            loop.call_soon_threadsafe(process, report)

    _in_progress.add(printer_id)
    client.register_raw_message_handler(on_report)
    try:
        if not client.send_gcode(GCODE):
            raise HTTPException(502, "Could not send the reference movement")
        try:
            accepted = await asyncio.wait_for(ack, REPORT_TIMEOUT)
            if not accepted:
                raise HTTPException(502, "Printer rejected the reference movement")
            await asyncio.sleep(max(0, settled - loop.time()))
            await asyncio.wait_for(fresh_home.wait(), REPORT_TIMEOUT)
        except TimeoutError as error:
            raise HTTPException(504, "Printer did not report a usable reference") from error
        if (
            interrupted
            or manager.get_client(printer_id) is not client
            or not client.state.connected
            or client.state.state not in IDLE_STATES
            or (client.state.raw_data.get("print_error") or 0) != initial_print_error
            or type(home_flag) is not int
            or home_flag & 7 != 7
        ):
            raise HTTPException(409, "Printer state changed during reference movement")
        return POSITION.copy()
    finally:
        client.unregister_raw_message_handler(on_report)
        _in_progress.discard(printer_id)

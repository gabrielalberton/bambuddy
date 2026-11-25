"""Caminhos da caneta -> G-code da A1.

Regras do arquivo gerado:

- nada de aquecer, extrudar, purgar, cortar filamento ou mexer no AMS: bico e mesa ficam desligados;
- o home do Z é feito com o bico na borda da frente da placa, onde a caneta (à frente do bico) fica
  pendurada fora da mesa: não risca o papel nem aperta a mola;
- o Z muda DURANTE o traço (``G1 X Y Z``): é assim que o aperto, e com ele a largura, varia;
- tudo em coordenadas absolutas depois do home; quem confere limites é ``validate.py``, que relê o texto.

A sequência de início segue o G-code de fábrica da A1 (perfil de 2026-05-13) só nas partes mecânicas:
sair do fim de curso do Z, ``G28 X`` (que na A1 refaz X e Y) e ``G28 Z P0`` na posição atual.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from .plan import PenPath, PlanError
from .profile import Machine, Paper, PenProfile, home_point

ACCEL_XY = 3000.0  # mm/s²: abaixo do padrão da A1 (6000) para a caneta não balançar no suporte
ACCEL_Z = 500.0
JOIN_TOLERANCE = 0.2  # mm: traço seguinte começando aqui perto não levanta a caneta
HOMING_SECONDS = 40.0
DOT_DWELL_MS = 60
END_RAISE = 25.0  # mm acima do contato ao terminar
GENERATOR = "Bambuddy pen plotter"


@dataclass
class GcodeResult:
    text: str
    stats: dict


def fmt(value: float, digits: int = 3) -> str:
    text = f"{value:.{digits}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def _move_time(dist: float, speed: float, accel: float) -> float:
    """Tempo de um movimento que parte e chega parado (perfil trapezoidal)."""
    if dist <= 0:
        return 0.0
    ramp = speed * speed / accel
    if dist >= ramp:
        return dist / speed + speed / accel
    return 2.0 * math.sqrt(dist / accel)


def clean_title(title: str) -> str:
    return re.sub(r"[^A-Za-z0-9 _.,()+-]", "_", title or "plot")[:80].strip() or "plot"


def z_levels(pen: PenProfile, paper: Paper, machine: Machine) -> dict:
    """Alturas do BICO usadas no plot (já compensando o home sobre o papel, quando for o caso)."""
    if pen.z_contact is None:
        raise PlanError("altura de contato da caneta não calibrada")
    hx, hy, on_paper = home_point(machine, paper)
    touch = pen.z_contact - (paper.thickness if on_paper else 0.0)
    return {
        "home": (hx, hy, on_paper),
        "touch": touch,
        "travel": touch + pen.lift,
        "floor": max(machine.nozzle_z_min, touch - pen.max_compression),
        "end": min(machine.nozzle_z_max, touch + pen.lift + END_RAISE),
    }


def start_lines(machine: Machine, pen: PenProfile, home: tuple[float, float, bool], z_travel: float) -> list[str]:
    hx, hy, on_paper = home
    where = "sobre o papel" if on_paper else "fora do papel"
    lines = [
        ";===== plotter de caneta: sem aquecer, sem extrusao, sem AMS =====",
        "G392 S0 ; sem deteccao de entupimento (nao ha extrusao)",
        "M104 S0 ; bico desligado",
        "M140 S0 ; mesa desligada",
        "M106 S0",
        "M106 P2 S0",
        "M1002 gcode_claim_action : 13",
        ";===== sai de perto do fim de curso do Z (igual ao G-code de fabrica) =====",
        "G91",
        "G380 S2 Z40 F1200",
        "G380 S3 Z-15 F1200",
        "G90",
        f"M204 S{fmt(ACCEL_XY, 0)}",
        "M17 X0.65 Y1.2 Z0.6 ; correntes padrao dos motores",
        "M220 S100",
        "M73.2 R1.0",
        "M982.2 S1 ; reducao de ruido",
        ";===== home de X e Y =====",
        "G28 X",
        "G91",
        "G1 Z5 F1200",
        "G90",
        f";===== home do Z na borda da frente ({where}); a caneta fica fora da mesa =====",
        f"G0 X{fmt(hx)} F18000",
        f"G0 Y{fmt(hy)} F3000",
        "G91",
        "G1 Z-5 F1200",
        "G90",
        "G28 Z P0 T140",
        "G29.2 S1 ; malha de nivelamento salva" if pen.use_mesh else "G29.2 S0 ; sem malha de nivelamento",
        "G90",
        f"G1 Z{fmt(z_travel)} F{fmt(pen.z_speed * 60, 0)}",
        "M400",
        "M1002 gcode_claim_action : 0",
        ";===== desenho =====",
    ]
    return lines


def end_lines(machine: Machine, pen: PenProfile, z_end: float) -> list[str]:
    return [
        ";===== fim: levanta a caneta e traz a mesa para a frente =====",
        f"G1 Z{fmt(z_end)} F{fmt(pen.z_speed * 60, 0)}",
        f"G0 X{fmt(machine.plate_w / 2)} Y{fmt(machine.nozzle_y[1])} F{fmt(pen.travel_speed * 60, 0)}",
        "M400",
        "M104 S0",
        "M140 S0",
        "M220 S100",
        "M73.2 R1.0",
        "M1002 set_gcode_claim_speed_level : 0",
        "M400",
    ]


def build_gcode(
    paths: list[PenPath], pen: PenProfile, paper: Paper, machine: Machine, title: str = "plot"
) -> GcodeResult:
    if not paths:
        raise PlanError("nada para desenhar")
    z = z_levels(pen, paper, machine)
    touch, z_travel, floor = z["touch"], z["travel"], z["floor"]
    ox, oy = pen.offset_x, pen.offset_y
    f_draw, f_travel, f_z = pen.draw_speed * 60.0, pen.travel_speed * 60.0, pen.z_speed * 60.0

    deepest = max(float(p.pts[:, 2].max()) for p in paths)
    if touch - deepest < floor - 1e-9:
        raise PlanError(
            f"o aperto de {deepest:.2f} mm levaria o bico a Z={touch - deepest:.2f}, abaixo do limite seguro "
            f"de {floor:.2f} mm"
        )

    # operações: (texto, segundos)
    ops: list[tuple[str, float]] = []
    cur: tuple[float, float] | None = None  # ponta da caneta
    cur_z = z_travel
    pen_down = False
    draw_mm = travel_mm = 0.0
    pen_downs = 0
    last_f = None

    def check(nx: float, ny: float) -> None:
        if not (machine.nozzle_x[0] - 1e-6 <= nx <= machine.nozzle_x[1] + 1e-6) or not (
            machine.nozzle_y[0] - 1e-6 <= ny <= machine.nozzle_y[1] + 1e-6
        ):
            raise PlanError(f"ponto fora do alcance do bico: X{nx:.2f} Y{ny:.2f}")

    hx, hy, _ = z["home"]
    nozzle = (hx, hy)
    for path in paths:
        pts = path.pts
        x0, y0, d0 = float(pts[0, 0]), float(pts[0, 1]), float(pts[0, 2])
        nx, ny = x0 - ox, y0 - oy
        check(nx, ny)
        joined = pen_down and cur is not None and math.hypot(x0 - cur[0], y0 - cur[1]) <= JOIN_TOLERANCE
        if joined:
            dist = math.hypot(nx - nozzle[0], ny - nozzle[1])
            ops.append((f"G1 X{fmt(nx)} Y{fmt(ny)} Z{fmt(touch - d0)} F{fmt(f_draw, 0)}", dist / pen.draw_speed))
            draw_mm += dist
        else:
            if pen_down:
                ops.append((f"G1 Z{fmt(z_travel)} F{fmt(f_z, 0)}", _move_time(z_travel - cur_z, pen.z_speed, ACCEL_Z)))
            dist = math.hypot(nx - nozzle[0], ny - nozzle[1])
            ops.append((f"G0 X{fmt(nx)} Y{fmt(ny)} F{fmt(f_travel, 0)}", _move_time(dist, pen.travel_speed, ACCEL_XY)))
            travel_mm += dist
            ops.append(
                (f"G1 Z{fmt(touch - d0)} F{fmt(f_z, 0)}", _move_time(z_travel - (touch - d0), pen.z_speed, ACCEL_Z))
            )
            pen_downs += 1
            dwell = max(pen.dwell_ms, DOT_DWELL_MS) if path.is_dot else pen.dwell_ms
            if dwell > 0:
                ops.append((f"G4 P{int(dwell)}", dwell / 1000.0))
            last_f = None
        nozzle = (nx, ny)
        cur_z = touch - d0
        stroke_len = 0.0
        for q in pts[1:]:
            qx, qy = float(q[0]) - ox, float(q[1]) - oy
            check(qx, qy)
            dist = math.hypot(qx - nozzle[0], qy - nozzle[1])
            cur_z = touch - float(q[2])
            word_f = "" if last_f == f_draw else f" F{fmt(f_draw, 0)}"
            last_f = f_draw
            ops.append((f"G1 X{fmt(qx)} Y{fmt(qy)} Z{fmt(cur_z)}{word_f}", dist / pen.draw_speed))
            stroke_len += dist
            nozzle = (qx, qy)
        if stroke_len > 0:
            ops.append(("", pen.draw_speed / ACCEL_XY))  # acelera e freia uma vez por traço
        draw_mm += stroke_len
        pen_down = True
        cur = (float(pts[-1, 0]), float(pts[-1, 1]))
    ops.append((f"G1 Z{fmt(z_travel)} F{fmt(f_z, 0)}", _move_time(z_travel - cur_z, pen.z_speed, ACCEL_Z)))

    end = end_lines(machine, pen, z["end"])
    end_secs = _move_time(z["end"] - z_travel, pen.z_speed, ACCEL_Z) + _move_time(
        math.hypot(machine.plate_w / 2 - nozzle[0], machine.nozzle_y[1] - nozzle[1]), pen.travel_speed, ACCEL_XY
    )
    body_secs = sum(t for _, t in ops) * 1.05
    total = HOMING_SECONDS + body_secs + end_secs
    minutes = max(1, math.ceil(total / 60.0))

    out: list[str] = []
    out += [
        "; HEADER_BLOCK_START",
        f"; {GENERATOR}",
        f"; model printing time: {_hms(body_secs)}; total estimated time: {_hms(total)}",
        "; total layer number: 1",
        "; total filament length [mm] : 0.00",
        "; total filament volume [cm^3] : 0.00",
        "; total filament weight [g] : 0.00",
        f"; max_z_height: {fmt(z['end'], 2)}",
        "; filament: 1",
        "; HEADER_BLOCK_END",
        "",
        "; CONFIG_BLOCK_START",
        "; pen_plotter = 1",
        f"; plot_title = {clean_title(title)}",
        "; printer_model = Bambu Lab A1",
        f"; pen_offset = {fmt(ox)},{fmt(oy)}",
        f"; pen_z_contact = {fmt(pen.z_contact or 0)}",
        f"; pen_z_touch = {fmt(touch)}",
        f"; pen_z_travel = {fmt(z_travel)}",
        f"; pen_z_floor = {fmt(floor)}",
        f"; paper = {fmt(paper.x)},{fmt(paper.y)},{fmt(paper.w)},{fmt(paper.h)}",
        f"; home = {fmt(hx)},{fmt(hy)},{'paper' if z['home'][2] else 'plate'}",
        "; CONFIG_BLOCK_END",
        "",
        "; EXECUTABLE_BLOCK_START",
        f"M73 P0 R{minutes}",
    ]
    out += start_lines(machine, pen, z["home"], z_travel)
    out += ["; layer num/total_layer_count: 1/1", "M73 L1"]
    elapsed = HOMING_SECONDS
    last_pct = 0
    for text, secs in ops:
        if text:
            out.append(text)
        elapsed += secs * 1.05
        pct = min(99, int(elapsed / total * 100))
        if pct > last_pct:
            last_pct = pct
            out.append(f"M73 P{pct} R{max(0, math.ceil((total - elapsed) / 60.0))}")
    out += end
    out += ["M73 P100 R0", "; EXECUTABLE_BLOCK_END", ""]
    stats = {
        "time_s": round(total, 1),
        "draw_mm": round(draw_mm, 1),
        "travel_mm": round(travel_mm, 1),
        "pen_downs": pen_downs,
        "lines": len(out),
        "z_touch": round(touch, 3),
        "z_travel": round(z_travel, 3),
        "z_min": round(touch - deepest, 3),
        "z_floor": round(floor, 3),
        "home": [round(hx, 2), round(hy, 2), bool(z["home"][2])],
    }
    return GcodeResult("\n".join(out), stats)


def _hms(seconds: float) -> str:
    s = int(round(seconds))
    h, m, sec = s // 3600, (s % 3600) // 60, s % 60
    return f"{h}h {m}m {sec}s" if h else f"{m}m {sec}s"

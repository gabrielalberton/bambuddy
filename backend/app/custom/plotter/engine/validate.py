"""Validador do G-code final: relê o TEXTO que vai para a impressora, sem confiar em quem gerou.

Passa só o que está numa lista fechada de comandos. Simula posição e modo e recusa o arquivo se:

- houver aquecimento, extrusão, troca de ferramenta, arco (G2/G3) ou qualquer comando fora da lista;
- o bico sair da faixa permitida em X/Y, descer abaixo do piso ou subir além do teto;
- a caneta baixar, ou andar baixa, com a ponta fora do papel ou da placa;
- houver deslocamento rápido (G0) com a caneta baixa, ou movimento absoluto antes do home.

Também devolve a simulação (segmentos com tempo acumulado) usada pela pré-visualização.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from .gcode import ACCEL_XY, ACCEL_Z, HOMING_SECONDS, _move_time, z_levels
from .profile import Machine, Paper, PenProfile, intersect

MAX_FEED = 30000.0  # mm/min
MAX_Z_FEED = 1500.0
MAX_DWELL_MS = 3000
EPS = 1e-6

_WORD = re.compile(r"([A-Za-z])\s*(-?\d+(?:\.\d*)?|-?\.\d+)?")
# comandos sem movimento aceitos exatamente nestas formas
_FIXED = {
    "G392 S0",
    "M104 S0",
    "M140 S0",
    "M106 S0",
    "M106 P2 S0",
    "M106 P3 S0",
    "M17 X0.65 Y1.2 Z0.6",
    "M220 S100",
    "M73.2 R1.0",
    "M982.2 S1",
    "M400",
    "G29.2 S0",
    "G29.2 S1",
    "M1002 gcode_claim_action : 13",
    "M1002 gcode_claim_action : 0",
    "M1002 set_gcode_claim_speed_level : 0",
}


@dataclass
class Report:
    ok: bool = True
    errors: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    sim: list[list[float]] = field(default_factory=list)  # [x, y (ponta), aperto (<0 = no ar), t acumulado]

    def error(self, code: str, text: str, line: int = 0) -> None:
        """Um registro por tipo de erro (com a primeira linha e a contagem), para nenhum tipo sumir da lista."""
        self.ok = False
        for item in self.errors:
            if item["code"] == code:
                item["data"]["count"] += 1
                return
        self.errors.append({"level": "error", "code": code, "text": text, "data": {"line": line, "count": 1}})

    def warn(self, code: str, text: str, line: int = 0) -> None:
        if not any(item["code"] == code for item in self.warnings):
            self.warnings.append({"level": "warning", "code": code, "text": text, "data": {"line": line}})

    def to_dict(self, with_sim: bool = True) -> dict:
        out = {"ok": self.ok, "errors": self.errors, "warnings": self.warnings, "stats": self.stats}
        if with_sim:
            out["sim"] = self.sim
        return out


def _words(body: str) -> dict[str, float | None] | None:
    out: dict[str, float | None] = {}
    rest = body
    for m in _WORD.finditer(body):
        letter = m.group(1).upper()
        if letter in out:
            return None
        out[letter] = float(m.group(2)) if m.group(2) is not None else None
        rest = rest.replace(m.group(0), "", 1)
    return out if not rest.strip() else None


def validate(text: str, machine: Machine, pen: PenProfile, paper: Paper, keep_sim: bool = True) -> Report:
    rep = Report()
    try:
        z = z_levels(pen, paper, machine)
    except ValueError as exc:
        rep.error("uncalibrated", str(exc))
        return rep
    touch, floor = z["touch"], z["floor"]
    z_clear = touch + min(1.0, pen.lift * 0.5)  # abaixo disto a caneta está "baixa"
    approach = pen.mount_spec.approach_speed if (pen.mount_spec.approach_speed or 0) < pen.z_speed else None
    ox, oy = pen.offset_x, pen.offset_y
    sheet = intersect(paper.rect(), (0.0, 0.0, machine.plate_w, machine.plate_h))
    if sheet is None:
        rep.error("paper_off_plate", "o papel está inteiro fora da placa")
        return rep

    absolute = True
    xy_homed = z_homed = False
    x = y = None  # bico
    zpos: float | None = None
    rel_z = 0.0  # soma dos movimentos relativos de Z antes do home
    feed = 0.0
    seen_off = {"M104 S0": False, "M140 S0": False}
    in_exec = False
    ended = False
    t = HOMING_SECONDS
    draw_mm = travel_mm = 0.0
    pen_downs = 0
    z_min_seen = math.inf
    z_max_seen = -math.inf
    bounds = [math.inf, math.inf, -math.inf, -math.inf]
    stroke_open = False

    def on_sheet(px: float, py: float) -> bool:
        return sheet[0] - EPS <= px <= sheet[2] + EPS and sheet[1] - EPS <= py <= sheet[3] + EPS

    for n, raw in enumerate(text.splitlines(), start=1):
        if raw.startswith("; EXECUTABLE_BLOCK_START"):
            in_exec = True
            continue
        if raw.startswith("; EXECUTABLE_BLOCK_END"):
            ended = True
            in_exec = False
            continue
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        if not in_exec:
            rep.error("outside_block", f"comando fora do bloco executável: {line[:40]}", n)
            continue
        line = re.sub(r"\s+", " ", line)
        if line in _FIXED:
            if line in seen_off:
                seen_off[line] = True
            if line == "G29.2 S0" and pen.mount_spec.needs_mesh:
                rep.error("mesh_required", "sem mola, a malha de nivelamento é obrigatória", n)
            continue
        cmd, _, body = line.partition(" ")
        cmd = cmd.upper()
        words = _words(body)
        if words is None:
            rep.error("syntax", f"linha que não entendi: {line[:40]}", n)
            continue

        if cmd == "G90" and not words:
            absolute = True
        elif cmd == "G91" and not words:
            if z_homed:
                rep.error("relative_after_home", "modo relativo depois do home", n)
            absolute = False
        elif cmd == "M73" and set(words) <= {"P", "R", "L"}:
            continue
        elif cmd == "M204" and set(words) == {"S"} and 100 <= (words["S"] or 0) <= 12000:
            continue
        elif cmd == "G4" and set(words) == {"P"} and 0 <= (words["P"] or 0) <= MAX_DWELL_MS:
            t += (words["P"] or 0) / 1000.0
        elif cmd == "G380":
            ok = not absolute and not z_homed and set(words) == {"S", "Z", "F"}
            if not ok or words["S"] not in (2.0, 3.0) or abs(words["Z"] or 0) > 40 or (words["F"] or 0) > 1200:
                rep.error("g380", "G380 fora do padrão do início", n)
            else:
                rel_z += float(words["Z"] or 0)
        elif cmd == "G28":
            if set(words) == {"X"} and words["X"] is None:
                xy_homed = True
                x = y = None
            elif set(words) == {"Z", "P", "T"} and words["Z"] is None and words["P"] == 0 and (words["T"] or 0) <= 140:
                if not xy_homed or x is None or y is None:
                    rep.error("z_home_blind", "home do Z sem posicionar o bico antes", n)
                elif abs(y - machine.home_y) > 0.5:
                    rep.error("z_home_place", "home do Z fora da borda da frente (a caneta tocaria a mesa)", n)
                z_homed = True
                zpos = 0.0
            else:
                rep.error("g28", f"home não permitido: {line}", n)
        elif cmd in ("G0", "G1"):
            if not set(words) <= {"X", "Y", "Z", "F"} or any(v is None for v in words.values()):
                rep.error("move_words", f"movimento com parâmetro proibido (extrusão?): {line[:40]}", n)
                continue
            if "F" in words:
                feed = float(words["F"] or 0)
                if feed <= 0 or feed > MAX_FEED:
                    rep.error("feed", f"velocidade fora do limite: F{feed:g}", n)
            has_xy = "X" in words or "Y" in words
            has_z = "Z" in words
            if not absolute:
                if z_homed or has_xy or not has_z or abs(words["Z"] or 0) > 10:
                    rep.error("relative_move", "movimento relativo não permitido aqui", n)
                else:
                    rel_z += float(words["Z"] or 0)
                continue
            if has_xy and not xy_homed:
                rep.error("move_before_home", "movimento em X/Y antes do home", n)
                continue
            if has_z and not z_homed:
                rep.error("z_before_home", "Z absoluto antes do home do Z", n)
                continue
            nx = float(words["X"]) if "X" in words else x
            ny = float(words["Y"]) if "Y" in words else y
            nz = float(words["Z"]) if has_z else zpos
            if has_xy:
                if nx is not None and not (machine.nozzle_x[0] - EPS <= nx <= machine.nozzle_x[1] + EPS):
                    rep.error("x_range", f"bico fora da faixa em X: {nx:g}", n)
                if ny is not None and not (machine.nozzle_y[0] - EPS <= ny <= machine.nozzle_y[1] + EPS):
                    rep.error("y_range", f"bico fora da faixa em Y: {ny:g}", n)
            if not z_homed:  # posicionamento para o home do Z: sem altura conhecida ainda
                x, y = nx, ny
                continue
            if nz is None:
                rep.error("z_unknown", "movimento sem altura definida", n)
                continue
            if nz < floor - EPS:
                rep.error("z_floor", f"bico abaixo do piso seguro: Z{nz:g} < {floor:g}", n)
            if nz > machine.nozzle_z_max + EPS:
                rep.error("z_ceiling", f"bico alto demais: Z{nz:g}", n)
            if has_z and not has_xy and feed > MAX_Z_FEED + EPS:
                rep.error("z_feed", f"Z rápido demais: F{feed:g}", n)
            if (
                approach is not None
                and has_z
                and zpos is not None
                and nz < touch - EPS
                and zpos > touch + EPS
                and feed > approach * 60.0 + EPS
            ):
                # sem mola a ponta chega no papel na velocidade de aproximação, não na de Z
                rep.error("fast_contact", f"caneta sem mola encostando rápido demais: F{feed:g}", n)
            if nx is None or ny is None:
                rep.error("xy_unknown", "movimento sem posição X/Y conhecida", n)
                continue
            z0 = zpos if zpos is not None else nz
            low = min(z0, nz) < z_clear - EPS
            moved_xy = has_xy and x is not None and y is not None and (abs(nx - x) > EPS or abs(ny - y) > EPS)
            if low and moved_xy:
                # andar com a caneta baixa: só sobre o papel, devagar e nunca em deslocamento rápido
                if not (on_sheet(nx + ox, ny + oy) and on_sheet(x + ox, y + oy)):
                    rep.error("pen_off_paper", "caneta baixa fora do papel", n)
                if cmd == "G0":
                    rep.error("rapid_pen_down", "deslocamento rápido com a caneta baixa", n)
                if feed > pen.draw_speed * 60.0 * 1.01 + EPS:
                    rep.error("draw_feed", f"traço mais rápido que o perfil permite: F{feed:g}", n)
            elif nz < z_clear - EPS and nz < z0 - EPS and not on_sheet(nx + ox, ny + oy):
                # descer (subir é sempre permitido: é como a caneta sai do ponto do home)
                rep.error("pen_off_paper", "caneta baixando fora do papel", n)
            # tempo e estatística
            if moved_xy:
                dist = math.hypot(nx - x, ny - y)
                speed = max(feed, 1.0) / 60.0
                if low:
                    draw_mm += dist
                    t += dist / speed
                    if not stroke_open:
                        stroke_open = True
                        t += speed / ACCEL_XY
                    for px, py in ((x + ox, y + oy), (nx + ox, ny + oy)):
                        bounds[0], bounds[1] = min(bounds[0], px), min(bounds[1], py)
                        bounds[2], bounds[3] = max(bounds[2], px), max(bounds[3], py)
                else:
                    travel_mm += dist
                    t += _move_time(dist, speed, ACCEL_XY)
                    stroke_open = False
            elif has_z and zpos is not None:
                t += _move_time(abs(nz - zpos), max(feed, 1.0) / 60.0, ACCEL_Z)
                if nz < touch + EPS <= zpos:
                    pen_downs += 1
                if nz >= z_clear - EPS:
                    stroke_open = False
            z_min_seen, z_max_seen = min(z_min_seen, nz), max(z_max_seen, nz)
            x, y, zpos = nx, ny, nz
            if keep_sim and x is not None and y is not None:
                depth = touch - nz
                rep.sim.append([round(x + ox, 3), round(y + oy, 3), round(depth, 3), round(t, 2)])
        else:
            rep.error("not_allowed", f"comando fora da lista permitida: {line[:40]}", n)

    if not ended:
        rep.error("truncated", "arquivo sem o fim do bloco executável")
    if not z_homed:
        rep.error("no_home", "arquivo sem home do Z")
    for key, seen in seen_off.items():
        if not seen:
            rep.error("heater_not_off", f"falta {key} (aquecedor desligado)")
    if zpos is not None and zpos < z_clear - EPS:
        rep.error("ends_low", "o arquivo termina com a caneta baixa")
    if rel_z < 15.0:
        rep.error("no_initial_lift", "falta levantar o Z antes do home")
    if draw_mm <= 0 and pen_downs == 0:
        rep.error("empty", "o arquivo não desenha nada")
    rep.stats = {
        "time_s": round(t, 1),
        "draw_mm": round(draw_mm, 1),
        "travel_mm": round(travel_mm, 1),
        "pen_downs": pen_downs,
        "z_min": round(z_min_seen, 3) if z_min_seen < math.inf else None,
        "z_max": round(z_max_seen, 3) if z_max_seen > -math.inf else None,
        "z_touch": round(touch, 3),
        "z_floor": round(floor, 3),
        "max_depth": round(touch - z_min_seen, 3) if z_min_seen < math.inf else None,
        "bounds": [round(v, 2) for v in bounds] if bounds[0] < math.inf else None,
    }
    return rep


def thin_sim(sim: list[list[float]], max_points: int = 12000) -> list[list[float]]:
    """Reduz a simulação para a tela (mantém toda mudança entre caneta baixa e alta)."""
    if len(sim) <= max_points:
        return sim
    step = math.ceil(len(sim) / max_points)
    out: list[list[float]] = []
    for i, row in enumerate(sim):
        prev_down = sim[i - 1][2] >= 0 if i else False
        nxt_down = sim[i + 1][2] >= 0 if i + 1 < len(sim) else False
        down = row[2] >= 0
        if i % step == 0 or down != prev_down or down != nxt_down or i == len(sim) - 1:
            out.append(row)
    return out

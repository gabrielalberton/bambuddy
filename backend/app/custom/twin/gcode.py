# ruff: noqa: C408, F841  (portado do twin avulso; mantido próximo do original para facilitar comparação)
"""Interpretador de G-code da Bambu (A1) + planejador de movimento com aceleração e junction jerk.

Entrada: linhas de `plate_N.gcode` (em streaming). Saída: `Program`, uma linha do tempo cinemática
(posição do cabeçote no tempo "de programa") + âncoras (M73, M991, trocas de camada/filamento, estágios,
esperas) usadas para sincronizar com os relatórios MQTT da impressora.

Modelo (calibrado contra a estimativa do fatiador, veja tests/):
  - blocos lineares e arcos (G2/G3 tesselados), feed F (x M220), limites por eixo (M203) e aceleração (M204 P/R/T,
    limitada por M201), junction jerk clássico (M205), lookahead entre barreiras (M400, M109, T..., G4...);
  - esperas de aquecimento (M109/M190), troca de filamento (T<n>) e rotinas sem modelo físico viram registros
    de "espera" com duração nominal e marcados como *holds*: o cliente só os libera por evidência (temperatura,
    estágio, próxima âncora).
"""

from __future__ import annotations

import math
import re
import zipfile
from array import array
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

# ---- registros ----
K_TRAVEL, K_EXTRUDE, K_WAIT, K_RETRACT = 0, 1, 2, 3

HOME_X, HOME_Y = -2.0, 0.0  # posições tomadas como "casa" (visual; só importam até o próximo G0/G1 absoluto)
MAX_ARC_SEG = 1.2  # mm, tamanho máximo de corda de arco
ARC_TOL = 0.03  # mm, flecha máxima

# Parâmetros nominais (ajustáveis; calibrados com test_planner e depois com gravações reais)
DEFAULTS = dict(
    ams_swap_s=30.0,  # espera do AMS Lite por troca (descarga+carga fora do que o G-code move)
    nozzle_heat=4.5,  # °C/s
    nozzle_cool=1.2,
    bed_heat=0.55,
    bed_cool=0.12,
    cal_wait={  # esperas de rotinas sem modelo físico no G-code (s)
        "M983": 16.0,
        "M984": 14.0,
        "M970.3": 5.0,
        "M970.2": 3.0,
        "M974": 2.0,
        "M975": 0.0,
        "G39.4": 6.0,
        "G29.4": 1.0,
        "M9833.2": 0.5,
        "M971": 0.2,
    },
    time_scale=1.0,  # fator global (calibração)
    jerk_scale=1.0,
)

WORD = re.compile(r"([A-Za-z])\s*(-?[0-9]*\.?[0-9]+(?:e-?[0-9]+)?)")


@dataclass
class Event:
    kind: str  # m73 | layer | claim | tool | hold | filament_swap
    line: int
    t: float = 0.0
    rec: int = 0  # índice do primeiro registro posterior ao evento
    a: float = 0.0
    b: float = 0.0
    s: str = ""
    c: float = 0.0


@dataclass
class Program:
    # registros de movimento (um por pedaço); t[i] é o instante FINAL do registro i (o inicial é t[i-1])
    x: array = field(default_factory=lambda: array("f"))
    y: array = field(default_factory=lambda: array("f"))
    z: array = field(default_factory=lambda: array("f"))
    t: array = field(default_factory=lambda: array("d"))
    line: array = field(default_factory=lambda: array("I"))
    kind: array = field(default_factory=lambda: array("B"))
    attr: array = field(default_factory=lambda: array("H"))
    attrs: list[tuple] = field(default_factory=list)  # (feature_id, width, height, filament, layer)
    features: list[str] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    layers: list[dict] = field(default_factory=list)  # [{n, z, line, t}]
    meta: dict = field(default_factory=dict)
    total_time: float = 0.0
    n_lines: int = 0


def parse_header_time(s: str) -> float | None:
    m = re.search(r"(?:(\d+)d\s*)?(?:(\d+)h\s*)?(?:(\d+)m\s*)?(?:(\d+)s)?", s.strip())
    if not m or not any(m.groups()):
        return None
    d, h, mi, se = (int(g) if g else 0 for g in m.groups())
    return float(d * 86400 + h * 3600 + mi * 60 + se)


CONFIG_KEYS = {
    "filament_colour",
    "filament_type",
    "nozzle_diameter",
    "printer_model",
    "machine_load_filament_time",
    "machine_unload_filament_time",
    "machine_max_acceleration_extruding",
    "machine_max_acceleration_travel",
    "machine_max_acceleration_retracting",
    "machine_max_acceleration_x",
    "machine_max_acceleration_y",
    "machine_max_acceleration_z",
    "machine_max_acceleration_e",
    "machine_max_jerk_x",
    "machine_max_jerk_y",
    "machine_max_jerk_z",
    "machine_max_jerk_e",
    "machine_max_speed_x",
    "machine_max_speed_y",
    "machine_max_speed_z",
    "machine_max_speed_e",
    "default_acceleration",
    "curr_bed_type",
    "layer_height",
    "initial_layer_print_height",
    "printable_area",
    "printable_height",
    "wipe_tower_x",
    "wipe_tower_y",
    "prime_tower_width",
    "filament_diameter",
}


# Flags do firmware (M1002 judge_flag NOME). Medidas na A1 real (impressão de 2026-11-12): extrude_cali_flag=0 e
# g29_before_print_flag=0 (estágios 8 e 1 nunca apareceram); filament_need_cali_flag=1 (os blocos de limpeza das trocas entram no tempo:
# sem eles o planejador fica ~5% abaixo da curva M73 do fatiador e do relógio real). O resto vale 0.
DEFAULT_FLAGS = {
    "filament_need_cali_flag": 1,
    "timelapse_record_flag": 1,
}  # timelapse: desconhecido (depende do comando de início); 1 = coerente com o fatiador


class Interpreter:
    def __init__(self, params: dict | None = None) -> None:
        self.p = {**DEFAULTS, **(params or {})}
        self.prog = Program()
        P = self.prog
        # estado modal
        self.x = self.y = 0.0
        self.z = 5.0
        self.e = 0.0
        self.abs_xyz = True
        self.abs_e = False
        self.feed = 30000 / 60.0
        self.speed_pct = 100.0
        self.speed_stack: list[float] = []
        self.acc_print = 5000.0
        self.acc_travel = 5000.0
        self.acc_retract = 5000.0
        self.max_acc = [6000.0, 6000.0, 1500.0, 5000.0]
        self.max_feed = [500.0, 500.0, 30.0, 30.0]
        self.jerk = [9.0, 9.0, 3.0, 3.0]
        self.cur_fil = 0
        self.cur_layer = 0
        self.cur_feature = 0
        self.cur_width = 0.42
        self.cur_height = 0.2
        self.attr_ids: dict[tuple, int] = {}
        self.feat_ids: dict[str, int] = {}
        self.t = 0.0
        self.noz_t = 25.0
        self.noz_target = 0.0
        self.bed_t = 25.0
        self.bed_target = 0.0
        # execução corrente
        self.blocks: list[tuple] = []  # (dx,dy,dz,de, L, vnom, acc, kind, attr, line, ex,ey,ez)
        self.pend: list[tuple[int, Event]] = []
        self.in_config = False
        # blocos condicionais do firmware Bambu (M1002 judge_flag X; M622 J<n> ... M623): só executa o bloco cuja
        # condição bate. Flags desconhecidas valem 0 (confirmado na A1 real: sem calibração de extrusão e sem nivelamento,
        # os blocos J1 são pulados e os J0 executam). Pode ser sobrescrito por params["flags"].
        import json as _json
        import os as _os

        self.flags: dict[str, int] = {
            **DEFAULT_FLAGS,
            **_json.loads(_os.environ.get("TWIN_FLAGS", "{}")),
            **(params or {}).get("flags", {}),
        }
        self.cond = 0
        self.cstack: list[bool] = []
        self.skip = 0  # >0: dentro de bloco pulado (profundidade)
        self.pending_comment_total = 0
        self.lineno = 0

    # ---------- utilidades ----------
    def _attr(self) -> int:
        key = (self.cur_feature, round(self.cur_width, 3), round(self.cur_height, 3), self.cur_fil, self.cur_layer)
        i = self.attr_ids.get(key)
        if i is None:
            i = len(self.prog.attrs)
            self.prog.attrs.append(key)
            self.attr_ids[key] = i
        return i

    def _feat(self, name: str) -> int:
        i = self.feat_ids.get(name)
        if i is None:
            i = len(self.prog.features)
            self.prog.features.append(name)
            self.feat_ids[name] = i
        return i

    def _event(self, kind: str, a: float = 0.0, b: float = 0.0, s: str = "", c: float = 0.0) -> None:
        ev = Event(kind=kind, line=self.lineno, a=a, b=b, s=s, c=c)
        self.pend.append((len(self.blocks), ev))

    # ---------- emissão de blocos ----------
    def _add_block(self, nx: float, ny: float, nz: float, de: float, feed: float, kind_hint: int | None = None) -> None:
        dx, dy, dz = nx - self.x, ny - self.y, nz - self.z
        dxyz = math.sqrt(dx * dx + dy * dy + dz * dz)
        if dxyz < 1e-9 and abs(de) < 1e-9:
            return
        if dxyz < 1e-9:  # só extrusor
            L = abs(de)
            kind = K_RETRACT
            acc = self.acc_retract
            vnom = min(feed, self.max_feed[3]) if feed > 0 else self.max_feed[3]
        else:
            L = dxyz
            kind = K_EXTRUDE if de > 1e-9 else K_TRAVEL
            acc = self.acc_print if kind == K_EXTRUDE else self.acc_travel
            vnom = feed * self.speed_pct / 100.0
            ux, uy, uz = abs(dx) / L, abs(dy) / L, abs(dz) / L
            for u, lim in ((ux, self.max_feed[0]), (uy, self.max_feed[1]), (uz, self.max_feed[2])):
                if u > 1e-9:
                    vnom = min(vnom, lim / u)
                    # aceleração por eixo
            for u, lim in ((ux, self.max_acc[0]), (uy, self.max_acc[1]), (uz, self.max_acc[2])):
                if u > 1e-9:
                    acc = min(acc, lim / u)
            if abs(de) > 1e-9:
                vnom = min(vnom, self.max_feed[3] * L / abs(de))
        if kind_hint is not None:
            kind = kind_hint
        vnom = max(vnom, 1.0)
        self.blocks.append((dx, dy, dz, de, L, vnom, max(acc, 100.0), kind, self._attr(), self.lineno, nx, ny, nz))
        self.x, self.y, self.z = nx, ny, nz

    def _arc(self, cw: bool, words: dict[str, float], feed: float) -> None:
        i, j = words.get("I", 0.0), words.get("J", 0.0)
        cx, cy = self.x + i, self.y + j
        r = math.hypot(i, j)
        ex, ey, ez = self._target(words)
        a0 = math.atan2(self.y - cy, self.x - cx)
        a1 = math.atan2(ey - cy, ex - cx)
        full = "X" not in words and "Y" not in words
        if cw:
            sweep = a0 - a1
            if sweep <= 1e-9:
                sweep += 2 * math.pi
        else:
            sweep = a1 - a0
            if sweep <= 1e-9:
                sweep += 2 * math.pi
        if full:
            sweep = 2 * math.pi * max(1.0, words.get("P", 1.0))
        if r < 1e-6:
            self._linear(ex, ey, ez, words, feed)
            return
        seglen = min(MAX_ARC_SEG, max(0.25, 2 * math.sqrt(max(2 * r * ARC_TOL, 1e-9))))
        n = max(1, int(math.ceil(sweep * r / seglen)))
        de_total = self._e_delta(words)
        sx, sy, sz = self.x, self.y, self.z
        for k in range(1, n + 1):
            f = k / n
            ang = a0 + (-sweep if cw else sweep) * f
            nx = cx + r * math.cos(ang) if k < n else ex
            ny = cy + r * math.sin(ang) if k < n else ey
            nz = sz + (ez - sz) * f
            self._add_block(nx, ny, nz, de_total / n, feed)

    def _e_delta(self, words: dict[str, float]) -> float:
        if "E" not in words:
            return 0.0
        if self.abs_e:
            d = words["E"] - self.e
            self.e = words["E"]
            return d
        self.e += words["E"]
        return words["E"]

    def _linear(self, nx: float, ny: float, nz: float, words: dict[str, float], feed: float) -> None:
        self._add_block(nx, ny, nz, self._e_delta(words), feed)

    def _target(self, words: dict[str, float]) -> tuple[float, float, float]:
        if self.abs_xyz:
            return words.get("X", self.x), words.get("Y", self.y), words.get("Z", self.z)
        return self.x + words.get("X", 0.0), self.y + words.get("Y", 0.0), self.z + words.get("Z", 0.0)

    # ---------- planejador ----------
    def _flush(self) -> None:
        """Planeja os blocos acumulados (v=0 nas pontas) e emite registros + resolve eventos pendentes."""
        P = self.prog
        blocks = self.blocks
        n = len(blocks)
        starts: list[float] = []
        if n:
            L = [b[4] for b in blocks]
            vn = [b[5] for b in blocks]
            ac = [b[6] for b in blocks]
            jmax = [0.0] * (n + 1)  # velocidade máx na junção entre i-1 e i (jmax[0] e jmax[n] = 0)
            jx = self.jerk
            for i in range(1, n):
                b0, b1 = blocks[i - 1], blocks[i]
                if b0[7] == K_RETRACT or b1[7] == K_RETRACT or b0[4] < 1e-9 or b1[4] < 1e-9:
                    jmax[i] = 0.0
                    continue
                vm = min(vn[i - 1], vn[i])
                f = 1.0
                s0, s1 = vn[i - 1] / b0[4], vn[i] / b1[4]
                for a in range(3):
                    d = abs(b1[a] * s1 - b0[a] * s0)
                    lim = jx[a] * self.p["jerk_scale"]
                    if d > lim:
                        f = min(f, lim / d)
                jmax[i] = max(vm * f, 0.0)
            # passe reverso e direto
            v = jmax[:]
            for i in range(n - 1, -1, -1):
                lim = math.sqrt(v[i + 1] * v[i + 1] + 2 * ac[i] * L[i])
                if v[i] > lim:
                    v[i] = lim
            v[0] = 0.0
            for i in range(n):
                lim = math.sqrt(v[i] * v[i] + 2 * ac[i] * L[i])
                if v[i + 1] > lim:
                    v[i + 1] = lim
            # tempos + emissão
            t = self.t
            t_run0 = t
            ts = self.p["time_scale"]
            for i in range(n):
                b = blocks[i]
                Li, a = L[i], ac[i]
                vin, vout, vnm = v[i], v[i + 1], vn[i]
                vin = min(vin, vnm)
                vout = min(vout, vnm)
                # trapézio
                da = (vnm * vnm - vin * vin) / (2 * a)
                dd = (vnm * vnm - vout * vout) / (2 * a)
                if da + dd <= Li:
                    vp = vnm
                    ta, td = (vp - vin) / a, (vp - vout) / a
                    tc = (Li - da - dd) / vp
                else:
                    vp = math.sqrt(max((2 * a * Li + vin * vin + vout * vout) / 2, 1e-9))
                    ta, td = max(vp - vin, 0) / a, max(vp - vout, 0) / a
                    tc = 0.0
                dur = (ta + tc + td) * ts
                starts.append(t)
                self._emit(b, t, dur, ta * ts, tc * ts, td * ts, vin, vp, vout, a / (ts * ts) if ts else a, Li)
                t += dur
            self.t = t
            self._thermal(t - t_run0)
        # eventos
        for bi, ev in self.pend:
            ev.t = starts[bi] if bi < len(starts) else self.t
            ev.rec = self._rec_at(ev)
            P.events.append(ev)
        self.pend.clear()
        self.blocks = []

    def _rec_at(self, ev: Event) -> int:
        return len(self.prog.t)

    def _emit(
        self,
        b,
        t0: float,
        dur: float,
        ta: float,
        tc: float,
        td: float,
        vin: float,
        vp: float,
        vout: float,
        a: float,
        L: float,
    ) -> None:
        """Emite 1 registro, ou até 5 quando há rampas longas (para a posição no tempo seguir o trapézio)."""
        P = self.prog
        dx, dy, dz, de, _, _, _, kind, attr, line, ex, ey, ez = b
        sx, sy, sz = ex - dx, ey - dy, ez - dz
        nodes: list[tuple[float, float]] = []  # (tempo relativo, fração da distância)
        if kind != K_RETRACT and dur > 0.12 and L > 1.5 and (ta > 0.06 or td > 0.06):

            def dist(tt: float) -> float:
                if tt <= ta:
                    return vin * tt + 0.5 * ((vp - vin) / ta if ta > 0 else 0) * tt * tt
                d_a = (vin + vp) / 2 * ta
                if tt <= ta + tc:
                    return d_a + vp * (tt - ta)
                r = tt - ta - tc
                return d_a + vp * tc + vp * r - 0.5 * ((vp - vout) / td if td > 0 else 0) * r * r

            pts = []
            if ta > 0.06:
                pts.append(ta / 2)
                pts.append(ta)
            if td > 0.06:
                pts.append(ta + tc)
                pts.append(ta + tc + td / 2)
            for tt in sorted(set(pts)):
                if 0 < tt < dur:
                    nodes.append((tt, min(1.0, max(0.0, dist(tt) / L))))
        nodes.append((dur, 1.0))
        prev_t = 0.0
        for tt, f in nodes:
            if tt - prev_t <= 0 and len(nodes) > 1 and f < 1.0:
                continue
            P.x.append(sx + dx * f)
            P.y.append(sy + dy * f)
            P.z.append(max(0.0, sz + dz * f))  # o bico não atravessa a mesa (toques G380 vão a Z<0)
            P.t.append(t0 + tt)
            P.line.append(line)
            P.kind.append(kind)
            P.attr.append(attr)
            prev_t = tt

    def _barrier(self) -> None:
        self._flush()

    def _wait(self, secs: float, hold: str = "", a: float = 0.0, s: str = "", c: float = 0.0) -> None:
        """Registro de espera (posição constante) na linha atual."""
        self._barrier()
        P = self.prog
        secs = max(secs, 0.0)
        t0 = self.t
        if hold:
            ev = Event(kind="hold", line=self.lineno, t=t0, rec=len(P.t), a=a, b=t0 + secs, s=hold, c=c)
            P.events.append(ev)
        if secs > 0:
            P.x.append(self.x)
            P.y.append(self.y)
            P.z.append(max(0.0, self.z))
            P.t.append(t0 + secs)
            P.line.append(self.lineno)
            P.kind.append(K_WAIT)
            P.attr.append(self._attr())
            self.t = t0 + secs
        # o estado térmico relaxa durante a espera
        self._thermal(secs)

    def _thermal(self, dt: float) -> None:
        p = self.p
        if dt <= 0:
            return
        for name, tgt, up, dn in (
            ("noz_t", self.noz_target, p["nozzle_heat"], p["nozzle_cool"]),
            ("bed_t", self.bed_target, p["bed_heat"], p["bed_cool"]),
        ):
            cur = getattr(self, name)
            step = (up if tgt > cur else dn) * dt
            setattr(self, name, min(tgt, cur + step) if tgt > cur else max(tgt, cur - step))

    # ---------- comandos ----------
    def feed_line(self, raw: str) -> None:
        self.lineno += 1
        s = raw.strip()
        if not s:
            return
        if s[0] == ";":
            self._comment(s)
            return
        sc = s.find(";")
        if sc >= 0:
            s = s[:sc].strip()
            if not s:
                return
        toks = s.split(None, 1)
        cmd = toks[0].upper()
        rest = toks[1] if len(toks) > 1 else ""
        c0 = cmd[0]
        if cmd == "M622":
            m = re.search(r"[JS]\s*(\d)", rest)
            want = int(m.group(1)) if m else 1
            if self.skip or self.cond != want:
                self.skip += 1
            else:
                self.cstack.append(True)
            return
        if cmd == "M623":
            if self.skip:
                self.skip -= 1
            elif self.cstack:
                self.cstack.pop()
            return
        if self.skip:
            return
        if cmd == "M1002":
            m = re.search(r"judge_flag\s+(\w+)", rest)
            if m:
                self.cond = int(self.flags.get(m.group(1), 0))
                return
            if "judge_last_extrude_cali_success" in rest:
                self.cond = int(self.flags.get("last_extrude_cali_success", 1))
                return
            m = re.search(r"set_flag\s+(\w+)\s*=\s*(\d+)", rest)
            if m:
                self.flags[m.group(1)] = int(m.group(2))
                return
        if c0 == "G":
            self._g(cmd, rest)
        elif c0 == "M":
            self._m(cmd, rest)
        elif c0 == "T":
            self._tool(cmd)

    def _words(self, rest: str) -> dict[str, float]:
        w: dict[str, float] = {}
        for m in WORD.finditer(rest):
            try:
                w[m.group(1).upper()] = float(m.group(2))
            except ValueError:
                pass
        return w

    def _comment(self, s: str) -> None:
        P = self.prog
        if self.in_config:
            if s.startswith("; CONFIG_BLOCK_END"):
                self.in_config = False
            else:
                k, _, v = s[2:].partition(" = ")
                if k in CONFIG_KEYS:
                    P.meta[k] = v.strip()
            return
        if s.startswith("; FEATURE:"):
            self.cur_feature = self._feat(s[10:].strip())
        elif s.startswith("; LINE_WIDTH:"):
            try:
                self.cur_width = float(s[13:])
            except ValueError:
                pass
        elif s.startswith("; LAYER_HEIGHT:"):
            try:
                self.cur_height = float(s[15:])
            except ValueError:
                pass
        elif s.startswith("; CHANGE_LAYER"):
            self.cur_layer += 1
        elif s.startswith("; Z_HEIGHT:") and self.cur_layer:
            try:
                P.layers.append({"n": self.cur_layer, "z": float(s[11:]), "line": self.lineno, "t": 0.0, "rec": 0})
                self._event("layer_start", a=self.cur_layer, b=float(s[11:]))
            except ValueError:
                pass
        elif s.startswith("; CONFIG_BLOCK_START"):
            self.in_config = True
        elif s.startswith("; model printing time:"):
            m = re.search(r"model printing time:\s*([^;]+);\s*total estimated time:\s*(.+)$", s)
            if m:
                P.meta["header_model_time_s"] = parse_header_time(m.group(1))
                P.meta["header_total_time_s"] = parse_header_time(m.group(2))
        elif s.startswith("; total layer number:"):
            P.meta["total_layers"] = int(s.split(":")[1])
        elif s.startswith("; max_z_height:"):
            P.meta["max_z_height"] = float(s.split(":")[1])
        elif s.startswith("; total filament length"):
            P.meta["filament_length_mm"] = [float(x) for x in s.split(":", 1)[1].split(",")]
        elif s.startswith("; filament:"):
            P.meta["filaments_used"] = [int(x) for x in s.split(":")[1].split(",") if x.strip().isdigit()]

    def _tool(self, cmd: str) -> None:
        try:
            n = int(cmd[1:])
        except ValueError:
            return
        if n >= 255 or n >= 1000:
            return
        # T<n>: troca de filamento no AMS (a impressora espera o AMS)
        self._barrier()
        self.cur_fil = n
        self._event("tool", a=n)
        self._wait(self.p["ams_swap_s"], hold="ams", a=n)

    def _g(self, cmd: str, rest: str) -> None:
        w = self._words(rest)
        if cmd in ("G0", "G1"):
            if "F" in w:
                self.feed = w["F"] / 60.0
            nx, ny, nz = self._target(w)
            self._add_block(nx, ny, nz, self._e_delta(w), self.feed)
        elif cmd in ("G2", "G3"):
            if "F" in w:
                self.feed = w["F"] / 60.0
            self._arc(cmd == "G2", w, self.feed)
        elif cmd == "G90":
            self.abs_xyz = True
            self.abs_e = self.abs_e  # M82/M83 são independentes
        elif cmd == "G91":
            self.abs_xyz = False
        elif cmd == "G92":
            if "E" in w:
                self.e = w["E"]
            self._flush_pos_set(w)
        elif cmd == "G4":
            ms = w.get("P", 0.0) + w.get("S", 0.0) * 1000.0
            self._wait(ms / 1000.0)
        elif cmd == "G28":
            self._home(rest)
        elif cmd == "G29":
            self._g29(w)
        elif cmd == "G380":  # movimento de Z com detecção de parada (S2/S3); tratado como G1 Z
            if "F" in w:
                self.feed = w["F"] / 60.0
            nz = self.z + w.get("Z", 0.0) if not self.abs_xyz else w.get("Z", self.z)
            self._add_block(self.x, self.y, nz, 0.0, min(self.feed, 20.0))
            self._barrier()
        elif cmd in ("G39.4", "G29.4"):
            self._wait(self.p["cal_wait"].get(cmd, 0.0))

    def _flush_pos_set(self, w: dict[str, float]) -> None:
        if any(k in w for k in "XYZ"):
            self._barrier()
            self.x = w.get("X", self.x)
            self.y = w.get("Y", self.y)
            self.z = w.get("Z", self.z)

    def _home(self, rest: str) -> None:
        up = rest.upper().split()
        axes = {a[0] for a in up if a and a[0] in "XYZ"} or {"X", "Y", "Z"}
        self._barrier()
        if "Z" in axes and len(axes) == 3:
            self._add_block(self.x, self.y, max(self.z, 0) + 5, 0.0, 20)
        if "X" in axes:
            self._add_block(HOME_X, self.y, self.z, 0.0, 90)
            self._barrier()
            self._wait(0.8)
        if "Y" in axes:
            self._add_block(self.x, HOME_Y, self.z, 0.0, 60)
            self._barrier()
            self._wait(0.8)
        if "Z" in axes:
            self._add_block(self.x, self.y, 0.0, 0.0, 12)
            self._barrier()
            self._wait(1.0)

    def _g29(self, w: dict[str, float]) -> None:
        """Nivelamento da mesa (A1: toque com o bico em grade). Sintetiza uma varredura em serpentina."""
        self._barrier()
        x0, y0 = w.get("X", 0.0), w.get("Y", 0.0)
        sx, sy = w.get("I", 256.0), w.get("J", 256.0)
        if sx < 20 or sy < 20:
            sx, sy = 256.0 - x0, 256.0 - y0
        n = 6
        z_hover = 5.0
        for iy in range(n):
            yy = y0 + sy * iy / (n - 1)
            for ix in range(n):
                xx = x0 + sx * (ix if iy % 2 == 0 else n - 1 - ix) / (n - 1)
                self._add_block(xx, yy, z_hover, 0.0, 300)
                self._barrier()
                self._add_block(xx, yy, 0.0, 0.0, 12)
                self._barrier()
                self._wait(0.25)
                self._add_block(xx, yy, z_hover, 0.0, 20)
                self._barrier()

    def _m(self, cmd: str, rest: str) -> None:
        P = self.prog
        if cmd == "M73":
            w = self._words(rest)
            if "P" in w and "R" in w:
                self._event("m73", a=w["P"], b=w["R"])
            return
        if cmd == "M991":
            w = self._words(rest)
            self._event("layer", a=w.get("P", 0.0) + 1)
            return
        if cmd == "M1002":
            m = re.search(r"gcode_claim_action\s*:\s*(\d+)", rest)
            if m:
                self._event("claim", a=int(m.group(1)))
            return
        w = self._words(rest)
        if cmd == "M82":
            self.abs_e = True
        elif cmd == "M83":
            self.abs_e = False
        elif cmd == "M204":
            if "S" in w:
                self.acc_print = self.acc_travel = w["S"]
            if "P" in w:
                self.acc_print = w["P"]
            if "T" in w:
                self.acc_travel = w["T"]
            if "R" in w:
                self.acc_retract = w["R"]
        elif cmd == "M201":
            for i, k in enumerate("XYZE"):
                if k in w:
                    self.max_acc[i] = w[k]
        elif cmd == "M203":
            for i, k in enumerate("XYZE"):
                if k in w:
                    self.max_feed[i] = w[k]
        elif cmd == "M205":
            for i, k in enumerate("XYZE"):
                if k in w:
                    self.jerk[i] = w[k]
        elif cmd == "M220":
            if re.search(r"\bB\b", rest):
                self.speed_stack.append(self.speed_pct)
            elif re.search(r"\bR\b", rest):
                if self.speed_stack:
                    self.speed_pct = self.speed_stack.pop()
            elif "S" in w:
                self.speed_pct = max(w["S"], 1.0)
        elif cmd == "M400":
            self._barrier()
            secs = w.get("S", 0.0) + w.get("P", 0.0) / 1000.0
            if secs > 0:
                self._wait(secs)
        elif cmd in ("M104", "M140"):
            if "S" in w:
                self._event(
                    "temp", a=w["S"], b=0.0 if cmd == "M104" else 1.0, c=self.noz_t if cmd == "M104" else self.bed_t
                )
                if cmd == "M104":
                    self.noz_target = w["S"]
                else:
                    self.bed_target = w["S"]
        elif cmd in ("M109", "M190"):
            self._barrier()
            tgt = w.get("S", w.get("R", 0.0))
            self._event("temp", a=tgt, b=0.0 if cmd == "M109" else 1.0, c=self.noz_t if cmd == "M109" else self.bed_t)
            if cmd == "M109":
                self.noz_target = tgt
                cur, up, dn = self.noz_t, self.p["nozzle_heat"], self.p["nozzle_cool"]
            else:
                self.bed_target = tgt
                cur, up, dn = self.bed_t, self.p["bed_heat"], self.p["bed_cool"]
            d = tgt - cur
            secs = (d / up) if d > 2 else (-d / dn if d < -2 else 0.0)
            kind = "heat_n" if cmd == "M109" else "heat_b"
            self._wait(secs, hold=kind if secs > 1.5 else "", a=tgt, c=1.0 if d > 0 else -1.0)
            if cmd == "M109":
                self.noz_t = tgt
            else:
                self.bed_t = tgt
        elif cmd in self.p["cal_wait"]:
            secs = self.p["cal_wait"][cmd]
            if secs:
                self._wait(secs, hold="cal" if secs >= 3 else "", s=cmd)
        elif cmd in ("M620", "M621"):
            # M620 S<n>A = início da troca no AMS; M621 = fim
            self._event("filament_swap", a=w.get("S", -1), s=cmd)

    # ---------- finalização ----------
    def finish(self) -> Program:
        self._barrier()
        P = self.prog
        P.total_time = self.t
        P.n_lines = self.lineno
        # índice de registro e tempo das camadas
        for ev in P.events:
            if ev.kind == "layer_start":
                for L in P.layers:
                    if L["line"] == ev.line:
                        L["t"], L["rec"] = ev.t, ev.rec
        return P


def interpret(lines: Iterable[str], params: dict | None = None) -> Program:
    it = Interpreter(params)
    for ln in lines:
        it.feed_line(ln)
    return it.finish()


def open_plate_lines(path: str, plate: int = 1) -> Iterator[str]:
    """Linhas do `Metadata/plate_N.gcode` de um .gcode.3mf (ou de um .gcode simples)."""
    import io

    if str(path).endswith(".gcode"):
        with open(path, encoding="utf-8", errors="replace") as f:
            yield from f
        return
    with zipfile.ZipFile(path) as z:
        name = f"Metadata/plate_{plate}.gcode"
        with z.open(name) as raw:
            yield from io.TextIOWrapper(raw, encoding="utf-8", errors="replace")


def read_3mf_colors(path: str) -> list[str]:
    import json

    try:
        with zipfile.ZipFile(path) as z:
            data = z.read("Metadata/project_settings.config")
        cfg = json.loads(data)
        cols = cfg.get("filament_colour") or []
        return [c if c.startswith("#") else f"#{c}" for c in cols]
    except Exception:  # noqa: BLE001
        return []

# ruff: noqa: F841, E741, B007  (portado do twin avulso; só para desenvolvimento/QA)
"""Simulador de relatórios MQTT coerentes com o G-code (sem tocar na impressora).

"Verdade": o tempo de programa T avança com a velocidade real da impressora (escala, pausas, mudanças de velocidade,
esperas mais longas/curtas que o nominal). Os relatórios imitam o `push_status` da A1 (M73 -> mc_percent/mc_remaining_time,
M991 -> layer_num, M1002 -> stg_cur, linha do G-code, temperaturas, AMS) com jitter, atrasos e lacunas.
"""

from __future__ import annotations

import asyncio
import bisect
import gzip
import random
import time
from dataclasses import dataclass, field

import numpy as np

from .gcode import Program
from .jobs import program_from_3mf
from .pack import pack

SPEED = {1: 0.5, 2: 1.0, 3: 1.24, 4: 1.66}


@dataclass
class Scenario:
    seed: int = 1
    base_rate: float = 0.96  # a impressora real roda a 96% do planejado
    speed_changes: list[tuple[float, int]] = field(default_factory=list)  # (tempo real s, spd_lvl)
    pauses: list[tuple[float, float]] = field(default_factory=list)  # (tempo real s, duração s)
    hold_stretch: tuple[float, float] = (0.6, 1.7)
    report_period: tuple[float, float] = (2.0, 2.12)  # A1 real: ticks fixos de ~2,06 s (só deltas)
    latency: tuple[float, float] = (0.02, 0.12)
    gaps: list[tuple[float, float]] = field(default_factory=list)  # (tempo real s, duração s) sem relatórios
    line_fault: str = (
        ""  # "": correto; "lixo": números aleatórios; "escala": linha*0.6 (outra contagem); "congelada": sempre a mesma
    )
    with_line: bool = False  # inclui mc_print_line_number (se a A1 não trouxer, False)
    start_T: float = 0.0
    max_real: float | None = None
    dt: float = 0.02


class Simulation:
    def __init__(self, prog: Program, colors: list[str], name: str, sc: Scenario) -> None:
        self.prog, self.sc, self.name, self.colors = prog, sc, name, colors
        self.rng = random.Random(sc.seed)
        self.t = np.frombuffer(prog.t, dtype="f8")
        self.x = np.frombuffer(prog.x, dtype="f4")
        self.y = np.frombuffer(prog.y, dtype="f4")
        self.z = np.frombuffer(prog.z, dtype="f4")
        self.line = np.frombuffer(prog.line, dtype="u4")
        ev = prog.events
        self.m73 = [e for e in ev if e.kind == "m73"]
        self.layer = [e for e in ev if e.kind == "layer"]
        self.claim = [e for e in ev if e.kind == "claim"]
        self.tools = [e for e in ev if e.kind == "tool"]
        self.holds = [e for e in ev if e.kind == "hold"]
        self.m73_t = [e.t for e in self.m73]
        self.layer_t = [e.t for e in self.layer]
        self.claim_t = [e.t for e in self.claim]
        self.tool_t = [e.t for e in self.tools]
        self.hold_t0 = [e.t for e in self.holds]
        self.hold_by_line = {e.line: e for e in self.holds}
        self.temps = {
            0: [e for e in ev if e.kind == "temp" and e.b == 0.0],
            1: [e for e in ev if e.kind == "temp" and e.b == 1.0],
        }
        self.temps_t = {k: [e.t for e in v] for k, v in self.temps.items()}
        self.stretch = [self.rng.uniform(*sc.hold_stretch) for _ in self.holds]
        self._integrate()

    # ----- verdade: tempo real -> T -----
    def _integrate(self) -> None:
        sc = self.sc
        T = sc.start_T
        real = 0.0
        total = self.prog.total_time
        reals, Ts, lvls, paused = [0.0], [T], [], []
        lvl = 2
        sch = sorted(sc.speed_changes)
        si = 0
        while total > T and (sc.max_real is None or real < sc.max_real):
            while si < len(sch) and sch[si][0] <= real:
                lvl = sch[si][1]
                si += 1
            p = any(a <= real < a + d for a, d in sc.pauses)
            rate = 0.0 if p else SPEED[lvl] * sc.base_rate
            k = bisect.bisect_right(self.hold_t0, T) - 1
            if k >= 0 and self.holds[k].b > T:
                rate = rate / self.stretch[k] if not p else 0.0
            T += sc.dt * rate
            real += sc.dt
            reals.append(real)
            Ts.append(min(T, total))
        self.real = np.array(reals)
        self.T = np.array(Ts)
        self.end_real = real

    def T_at(self, real: float) -> float:
        return float(np.interp(real, self.real, self.T))

    def lvl_at(self, real: float) -> int:
        lvl = 2
        for r, l in sorted(self.sc.speed_changes):
            if r <= real:
                lvl = l
        return lvl

    def paused_at(self, real: float) -> bool:
        return any(a <= real < a + d for a, d in self.sc.pauses)

    def pos_at_T(self, T: float) -> tuple[float, float, float]:
        i = int(np.searchsorted(self.t, T, side="left"))
        if i >= len(self.t):
            return float(self.x[-1]), float(self.y[-1]), float(self.z[-1])
        t1 = self.t[i]
        t0 = self.t[i - 1] if i > 0 else 0.0
        x0, y0, z0 = (self.x[i - 1], self.y[i - 1], self.z[i - 1]) if i > 0 else (self.x[0], self.y[0], self.z[0])
        f = 0.0 if t1 <= t0 else min(1.0, max(0.0, (T - t0) / (t1 - t0)))
        return float(x0 + (self.x[i] - x0) * f), float(y0 + (self.y[i] - y0) * f), float(z0 + (self.z[i] - z0) * f)

    # ----- conteúdo de um relatório no instante real `rt` -----
    def report(self, rt: float, full: bool) -> dict:
        T = self.T_at(rt)
        sc = self.sc
        lvl = self.lvl_at(rt)
        done = self.prog.total_time - 1e-6 <= T
        paused = self.paused_at(rt)
        r: dict = {
            "gcode_state": "FINISH" if done else ("PAUSE" if paused else "RUNNING"),
            "subtask_name": self.name,
            "gcode_file": "/data/Metadata/plate_1.gcode",
            "spd_lvl": lvl,
            "spd_mag": int(SPEED[lvl] * 100),
            "total_layer_num": self.prog.meta.get("total_layers", 0),
        }
        k = bisect.bisect_right(self.m73_t, T) - 1
        if k >= 0:
            r["mc_percent"], r["mc_remaining_time"] = int(self.m73[k].a), int(self.m73[k].b)
        else:
            r["mc_percent"], r["mc_remaining_time"] = 0, int(self.m73[0].b) if self.m73 else 0
        k = bisect.bisect_right(self.layer_t, T) - 1
        r["layer_num"] = int(self.layer[k].a) if k >= 0 else 0
        k = bisect.bisect_right(self.claim_t, T) - 1
        stg = int(self.claim[k].a) if k >= 0 else 0
        # na impressão em si o estágio é 0; durante a troca de filamento, 4
        hk = bisect.bisect_right(self.hold_t0, T) - 1
        hold = self.holds[hk] if hk >= 0 and self.holds[hk].b > T else None
        if hold and hold.s == "ams":
            stg = 4
        elif hold and hold.s == "heat_n":
            stg = 7
        r["stg_cur"] = stg if k >= 0 else 255
        for which, key, tkey, rate in (
            (0, "nozzle_temper", "nozzle_target_temper", 4.5),
            (1, "bed_temper", "bed_target_temper", 0.55),
        ):
            evs, ts = self.temps[which], self.temps_t[which]
            k2 = bisect.bisect_right(ts, T) - 1
            if k2 < 0:
                r[key], r[tkey] = 25.0, 0
                continue
            cur = evs[k2]
            prev = cur.c
            h = self.hold_by_line.get(cur.line)
            dur = (h.b - h.t) if h is not None else abs(cur.a - prev) / rate
            f = min(1.0, max(0.0, (T - cur.t) / dur)) if dur > 1e-6 else 1.0
            r[key], r[tkey] = round(prev + (cur.a - prev) * f, 2), cur.a
        tk = bisect.bisect_right(self.tool_t, T) - 1
        r["ams"] = {
            "tray_now": str(int(self.tools[tk].a)) if tk >= 0 else "255",
            "ams": [
                {
                    "id": "0",
                    "tray": [
                        {
                            "id": str(i),
                            "tray_color": (self.colors[i][1:] + "FF").upper() if i < len(self.colors) else "FFFFFFFF",
                            "tray_type": "PLA",
                        }
                        for i in range(4)
                    ],
                }
            ],
        }
        if sc.with_line:
            i = min(int(np.searchsorted(self.t, T, side="left")), len(self.line) - 1)
            ln = int(self.line[i])
            if sc.line_fault == "lixo":
                ln = self.rng.randint(1, int(self.line[-1]))
            elif sc.line_fault == "escala":
                ln = int(ln * 0.6)
            elif sc.line_fault == "congelada":
                ln = 1234
            r["mc_print_line_number"] = str(ln)
        if not full:
            keep = {
                "mc_percent",
                "mc_remaining_time",
                "layer_num",
                "stg_cur",
                "gcode_state",
                "mc_print_line_number",
                "nozzle_temper",
                "bed_temper",
            }
            r = {k2: v for k2, v in r.items() if k2 in keep}
        return r

    def schedule(self) -> list[tuple[float, float, dict]]:
        """[(tempo real de geração, tempo real de chegada, relatório)] com jitter, atraso e lacunas."""
        sc, out = self.sc, []
        rt = 0.0
        first = True
        while rt < self.end_real:
            rt += self.rng.uniform(*sc.report_period)
            if any(a <= rt < a + d for a, d in sc.gaps):
                continue
            out.append((rt, rt + self.rng.uniform(*sc.latency), self.report(rt, full=first or int(rt) % 60 == 0)))
            first = False
        out.sort(key=lambda x: x[1])
        return out


def make_sim_runner(path: str, speed: float, start_min: float):
    """Retorna a corrotina que alimenta o hub com relatórios simulados em tempo (acelerável). Só para desenvolvimento/QA
    (`BAMBUDDY_CUSTOM_TWIN_SIM=<arquivo.gcode.3mf>`): nunca toca na impressora."""

    async def run(hub) -> None:
        from .jobs import Job

        prog, colors = await asyncio.to_thread(program_from_3mf, path, 1)
        name = path.rsplit("/", 1)[-1].replace(".gcode.3mf", "")
        sim = Simulation(prog, colors, name, Scenario(start_T=start_min * 60.0, base_rate=1.0, speed_changes=[]))
        blob, jid = pack(prog, colors, {"name": name, "source": "sim", "plate": 1})
        hub.jobs.current = Job(
            key=name, name=name, status="ready", id=jid, blob_gz=gzip.compress(blob, 6), source="sim"
        )
        sched = sim.schedule()
        # fase ociosa curta antes de começar
        hub._apply({"gcode_state": "IDLE", "mc_percent": 0, "gcode_file": "", "subtask_name": ""}, time.time(), "mqtt")
        await asyncio.sleep(1.0)
        t0 = time.time()
        for gen, arr, rep in sched:
            delay = arr / speed - (time.time() - t0)
            if delay > 0:
                await asyncio.sleep(delay)
            hub._apply(rep, time.time(), "mqtt")
        while True:  # simulação terminada: mantém o estado final (FINISH)
            await asyncio.sleep(3600)

    return run

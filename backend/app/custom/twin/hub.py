"""Hub do gêmeo digital dentro do Bambuddy: estado da impressora (do cliente MQTT do PRÓPRIO Bambuddy) + job + SSE.

Fonte de estado: `BambuMQTTClient.register_raw_message_handler()` (API pública do upstream, usada pela ponte da
impressora virtual). O handler roda na thread do paho, só decodifica o JSON do tópico `device/<serial>/report` e
repassa ao event loop. **Nenhuma** chamada de publish: o twin não abre conexão própria e não manda nada à impressora
(o `pushall` que o twin avulso mandava já é feito pelo próprio Bambuddy).

Ao anexar (e a cada troca de cliente, ex. reconexão/edição da impressora), o estado é semeado a partir do
`PrinterState` do Bambuddy (campos já fundidos), porque a A1 só manda deltas.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import pathlib
import time
from typing import Any

from .jobs import JobManager, norm_name
from .recorder import Recorder
from .state import PUBLIC_KEYS, PrinterState, record_view

log = logging.getLogger("custom.twin")

MAX_CLIENTS = 24


def data_dir() -> pathlib.Path:
    from backend.app.core.config import settings

    return pathlib.Path(settings.base_dir) / "custom" / "twin"


def seed_from_state(st: Any) -> dict:
    """Relatório no formato do MQTT (`print`) a partir do `PrinterState` do Bambuddy (fundido, não delta)."""
    t = getattr(st, "temperatures", None) or {}
    raw = getattr(st, "raw_data", None) or {}
    r: dict = {
        "gcode_state": getattr(st, "state", None),
        "mc_percent": getattr(st, "progress", None),
        "mc_remaining_time": getattr(st, "remaining_time", None),
        "layer_num": getattr(st, "layer_num", None),
        "total_layer_num": getattr(st, "total_layers", None),
        "subtask_name": getattr(st, "subtask_name", None) or "",
        "gcode_file": getattr(st, "gcode_file", None) or "",
        "bed_temper": t.get("bed"),
        "bed_target_temper": t.get("bed_target"),
        "nozzle_temper": t.get("nozzle"),
        "nozzle_target_temper": t.get("nozzle_target"),
        "spd_lvl": getattr(st, "speed_level", None),
        "stg_cur": getattr(st, "stg_cur", None),
        "stg": list(getattr(st, "stg", None) or []),
        "mc_print_sub_stage": getattr(st, "mc_print_sub_stage", None),
        "ams_status": getattr(st, "ams_status", None),
        "cooling_fan_speed": getattr(st, "cooling_fan_speed", None),
        "big_fan1_speed": getattr(st, "big_fan1_speed", None),
        "big_fan2_speed": getattr(st, "big_fan2_speed", None),
        "heatbreak_fan_speed": getattr(st, "heatbreak_fan_speed", None),
    }
    # o que só existe cru (spd_mag, home_flag, nozzle_diameter...) vem do último relatório guardado pelo Bambuddy
    for k in PUBLIC_KEYS:
        if k in raw and k not in ("stg",) and r.get(k) is None:
            r[k] = raw[k]
    for k in (
        "spd_mag",
        "home_flag",
        "mc_print_line_number",
        "print_type",
        "mc_print_stage",
        "chamber_temper",
        "lights_report",
        "print_error",
        "nozzle_diameter",
    ):
        if k in raw:
            r[k] = raw[k]
    units = raw.get("ams") if isinstance(raw.get("ams"), list) else []
    r["ams"] = {"tray_now": getattr(st, "tray_now", 255), "tray_tar": getattr(st, "tray_tar", None), "ams": units}
    if not r["stg"]:
        r.pop("stg")
    return {k: v for k, v in r.items() if v is not None}


class TwinHub:
    def __init__(
        self,
        printer_id: int,
        *,
        cache_dir: pathlib.Path | None = None,
        manager: Any = None,
        resolve=None,
        record: bool | None = None,
    ) -> None:
        self.printer_id = printer_id
        self.state = PrinterState()
        self._manager = manager
        self.jobs = JobManager(cache_dir or (data_dir() / "cache"), resolve or self._resolve)
        self.clients: set[asyncio.Queue] = set()
        self.loop: asyncio.AbstractEventLoop | None = None
        self._dirty: asyncio.Event | None = None
        self._tasks: list[asyncio.Task] = []
        self._client: Any = None
        self._topic = ""
        self.rx = 0.0
        self.n_reports = 0
        self.sim = False
        self._record = (os.environ.get("BAMBUDDY_CUSTOM_TWIN_RECORD", "0") == "1") if record is None else record
        self.rec: Recorder | None = None

    # ----- ciclo de vida (preguiçoso: começa no primeiro cliente/saúde) -----
    def start(self) -> None:
        if self.loop is not None:
            return
        self.loop = asyncio.get_running_loop()
        self._dirty = asyncio.Event()
        self._tasks = [self.loop.create_task(self._broadcaster()), self.loop.create_task(self._ticker())]
        sim = os.environ.get("BAMBUDDY_CUSTOM_TWIN_SIM", "").strip()
        if sim:
            from .sim import make_sim_runner

            self.sim = True
            start = float(os.environ.get("BAMBUDDY_CUSTOM_TWIN_SIM_START", "0") or 0)
            speed = float(os.environ.get("BAMBUDDY_CUSTOM_TWIN_SIM_SPEED", "1") or 1)
            self._tasks.append(self.loop.create_task(make_sim_runner(sim, speed, start)(self)))
        else:
            self._attach()

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        self._detach()
        if self.rec:
            self.rec.close()
        self.loop = None

    @property
    def manager(self):
        if self._manager is None:
            from backend.app.services.printer_manager import printer_manager

            self._manager = printer_manager
        return self._manager

    def _attach(self) -> None:
        """(Re)registra o handler cru no cliente MQTT atual do Bambuddy. Idempotente; chamado a cada segundo."""
        client = self.manager.get_client(self.printer_id)
        if client is self._client:
            return
        self._detach()
        if client is None:
            return
        self._client = client
        self._topic = getattr(client, "topic_subscribe", "") or f"device/{getattr(client, 'serial_number', '')}/report"
        if self._record and self.rec is None:
            secrets = tuple(
                s
                for s in (getattr(client, "access_code", ""), getattr(client, "serial_number", ""))
                if s and len(s) >= 4
            )
            self.rec = Recorder(data_dir() / "recordings", secrets, max_total_mb=200)
        client.register_raw_message_handler(self._on_raw)
        try:
            self._apply(seed_from_state(client.state), time.time(), "bambuddy")
        except Exception:  # noqa: BLE001
            log.exception("twin: semente do estado falhou")
        log.info("twin: observando o MQTT do Bambuddy (impressora %s)", self.printer_id)

    def _detach(self) -> None:
        if self._client is not None:
            try:
                self._client.unregister_raw_message_handler(self._on_raw)
            except Exception:  # noqa: BLE001
                pass
        self._client = None

    # ----- entrada (thread do paho) -----
    def _on_raw(self, topic: str, payload: bytes) -> None:
        if topic != self._topic or self.loop is None:
            return
        try:
            d = json.loads(payload)
        except ValueError:
            return
        p = d.get("print") if isinstance(d, dict) else None
        if not isinstance(p, dict):
            return
        now = time.time()
        if self.rec:
            self.rec.write("mqtt", record_view(p), now)
        self.loop.call_soon_threadsafe(self._apply, p, now, "mqtt")

    def _apply(self, p: dict, t: float, source: str) -> None:
        self.state.update(p, source)
        self.rx = t
        self.n_reports += 1
        if self._dirty:
            self._dirty.set()

    # ----- G-code do job a partir dos arquivos do Bambuddy -----
    async def _resolve(self, pub: dict, name: str):
        """(caminho do 3MF, origem, placa sugerida) do job em curso: arquivo do Bambuddy, depois biblioteca por nome."""
        from sqlalchemy import select

        from backend.app.api.routes.library import to_absolute_path
        from backend.app.core import database
        from backend.app.models.archive import PrintArchive
        from backend.app.models.library import LibraryFile
        from backend.app.services.printer_manager import resolve_plate_id

        st = self._client.state if self._client is not None else None
        plate = None
        want = norm_name(name)
        async with database.async_session() as db:
            archive = None
            if st is not None:
                plate = resolve_plate_id(st)
                from backend.app.main import running_print_archive

                try:
                    archive = await running_print_archive(db, self.printer_id, st, printing_only=False, by_name=True)
                except Exception:  # noqa: BLE001
                    log.debug("twin: running_print_archive falhou", exc_info=True)
            if archive is None and want:
                rows = (
                    (
                        await db.execute(
                            select(PrintArchive)
                            .where(PrintArchive.printer_id == self.printer_id, PrintArchive.deleted_at.is_(None))
                            .order_by(PrintArchive.created_at.desc())
                            .limit(200)
                        )
                    )
                    .scalars()
                    .all()
                )
                archive = next(
                    (a for a in rows if want in (norm_name(a.print_name or ""), norm_name(a.filename or ""))), None
                )
            if archive is not None:
                p = to_absolute_path(archive.file_path)
                if p and p.is_file() and str(p).lower().endswith(".3mf"):
                    return p, f"archive:{archive.id}", plate
            if want:
                files = (await db.execute(LibraryFile.active().limit(2000))).scalars().all()
                cands = [f for f in files if norm_name(f.filename or "") == want] or [
                    f
                    for f in files
                    if (n := norm_name(f.filename or "")) and (want.startswith(n) or n.startswith(want))
                ]
                for f in cands:
                    p = to_absolute_path(f.file_path)
                    if p and p.is_file() and str(p).lower().endswith(".3mf"):
                        return p, f"library:{f.id}", plate
        return None

    # ----- saída -----
    def connected(self) -> bool:
        if self.sim:
            return True
        c = self._client
        return bool(c is not None and getattr(getattr(c, "state", None), "connected", False))

    def snapshot(self) -> dict:
        s = self.state.public()
        if self.loop is not None:
            self.jobs.observe(s)
        now = time.time()
        return {
            "ts": round(now, 3),
            "age": round(max(0.0, now - self.rx), 3) if self.rx else None,
            "src": self.state.source,
            "conn": {"mqtt": self.connected(), "bambuddy": True},
            "s": s,
            "job": self.jobs.public(),
            "since_pr": round(now - self.state.pr_at, 3) if self.state.pr_at else None,
            "plate_wait": self.plate_wait(),
        }

    def plate_wait(self) -> bool | None:
        """Bambuddy ainda espera "placa liberada"? (True = peça na mesa). Liberada (False) com a impressão
        terminada, o twin esconde a peça. None = sem informação (simulação/gerenciador ausente)."""
        if self.sim:
            return None
        try:
            return bool(self.manager.is_awaiting_plate_clear(self.printer_id))
        except Exception:  # noqa: BLE001
            return None

    def encode(self) -> str:
        return json.dumps(self.snapshot(), separators=(",", ":"))

    async def _broadcaster(self) -> None:
        assert self._dirty
        while True:
            await self._dirty.wait()
            self._dirty.clear()
            if self.clients:
                msg = self.encode()
                for q in list(self.clients):
                    if q.full():
                        try:
                            q.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                    q.put_nowait(msg)
            await asyncio.sleep(0.04)  # coalesce: no máx. ~25 msgs/s

    async def _ticker(self) -> None:
        """Reenvia o snapshot a cada segundo (idade dos dados, job) e reanexa se o Bambuddy trocou o cliente MQTT."""
        while True:
            await asyncio.sleep(1.0)
            if not self.sim:
                try:
                    self._attach()
                except Exception:  # noqa: BLE001
                    log.debug("twin: attach", exc_info=True)
            if self._dirty:
                self._dirty.set()

    def health(self) -> dict:
        j = self.jobs.current
        return {
            "ok": True,
            "mqtt": self.connected(),
            "attached": self._client is not None or self.sim,
            "sim": self.sim,
            "reports": self.n_reports,
            "clients": len(self.clients),
            "job": self.jobs.public(),
            "job_info": (j.info if j else {}),
            "job_error": (j.error if j else ""),
            "state": self.state.raw.get("gcode_state"),
            "recorder_refused": self.rec.refused if self.rec else None,
        }


_hubs: dict[int, TwinHub] = {}


def get_hub(printer_id: int) -> TwinHub:
    hub = _hubs.get(printer_id)
    if hub is None:
        hub = _hubs[printer_id] = TwinHub(printer_id)
    hub.start()
    return hub


async def reset_hubs() -> None:
    """Testes: derruba todos os hubs."""
    for h in list(_hubs.values()):
        await h.stop()
    _hubs.clear()

"""G-code do job em curso para o gêmeo digital: arquivo do Bambuddy (arquivo/biblioteca) -> interpretação -> pacote.

Diferença em relação ao twin avulso (`3d-printing/twin/server/twin_server/jobs.py`): aqui o 3MF vem direto do disco do
Bambuddy (o mesmo arquivo que o arquivamento baixou da impressora), sem API HTTP nem FTPS próprio. Não há plano B por
FTPS: se o Bambuddy não arquivou o job, é porque o próprio FTPS dele falhou, e repetir a tentativa daqui só dobraria
conexões na A1.

A interpretação roda num processo separado (spawn, um por vez, encerrado ao fim): o pico de memória do parser não fica
no processo do Bambuddy e um G-code patológico não derruba o servidor.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import gzip
import hashlib
import io
import json
import logging
import multiprocessing
import pathlib
import re
import time
import zipfile
from dataclasses import dataclass, field

from . import gcode, pack

log = logging.getLogger("custom.twin.jobs")
PARSER_VERSION = "2"
CACHE_MAX_FILES = 8
CACHE_MAX_BYTES = 200 * 1024 * 1024
ACTIVE_STATES = ("PREPARE", "RUNNING", "PAUSE", "FINISH", "FAILED")


@dataclass
class Job:
    key: str
    name: str = ""
    status: str = "loading"  # loading | ready | failed
    id: str = ""
    blob_gz: bytes = b""
    source: str = ""
    error: str = ""
    info: dict = field(default_factory=dict)
    tries: int = 0
    last_try: float = 0.0


def norm_name(s: str) -> str:
    s = (s or "").strip().lower().rsplit("/", 1)[-1]
    for suf in (".gcode.3mf", ".3mf", ".gcode"):
        if s.endswith(suf):
            s = s[: -len(suf)]
    return re.sub(r"\s+", " ", s)


def plate_of(gcode_file: str, default: int = 1) -> int:
    m = re.search(r"plate_(\d+)\.gcode", gcode_file or "")
    return int(m.group(1)) if m else default


def _open_zip(src: bytes | str | pathlib.Path) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(src) if isinstance(src, (bytes, bytearray)) else str(src))


def program_from_3mf(
    src: bytes | str | pathlib.Path, plate: int, params: dict | None = None
) -> tuple[gcode.Program, list[str]]:
    """Interpreta `Metadata/plate_N.gcode` de um .gcode.3mf (bytes ou caminho; o caminho é lido em streaming)."""
    with _open_zip(src) as z:
        name = f"Metadata/plate_{plate}.gcode"
        if name not in z.namelist():
            raise ValueError(f"{name} não existe no 3MF")
        with z.open(name) as raw:
            prog = gcode.interpret(io.TextIOWrapper(raw, encoding="utf-8", errors="replace"), params)
        colors: list[str] = []
        try:
            cfg = json.loads(z.read("Metadata/project_settings.config"))
            colors = [c if c.startswith("#") else f"#{c}" for c in (cfg.get("filament_colour") or [])]
        except Exception:  # noqa: BLE001
            pass
    return prog, colors


def build_pack_gz(path: str, plate: int, job_info: dict, params: dict | None = None) -> tuple[bytes, str, dict]:
    """(pacote gzip, id do pacote, métricas). Roda no processo filho."""
    import resource

    t0 = time.time()
    prog, colors = program_from_3mf(path, plate, params)
    blob, jid = pack.pack(prog, colors, job_info)
    gz = gzip.compress(blob, 6)
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
    return (
        gz,
        jid,
        {
            "records": len(prog.t),
            "bytes": len(blob),
            "gz": len(gz),
            "secs": round(time.time() - t0, 1),
            "peak_rss_mb": rss,
        },
    )


def file_digest(path: pathlib.Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:20]


def firmware_params(stg) -> tuple[dict | None, str]:
    """Flags do firmware inferidas dos estágios de preparo anunciados (`stg`: 8 = calibração de extrusão, 1 = nivelamento)."""
    if isinstance(stg, list) and stg:
        ec, bl = int(8 in stg), int(1 in stg)
        return {"flags": {"extrude_cali_flag": ec, "g29_before_print_flag": bl}}, (f"-f{ec}{bl}" if (ec or bl) else "")
    return None, ""


class JobManager:
    """Um job por vez. `resolve(pub)` (async) devolve (caminho do 3MF, origem) ou None; injetado pelo hub."""

    def __init__(self, cache_dir: pathlib.Path, resolve, *, in_process: bool = False) -> None:
        self.cache_dir = cache_dir
        self.resolve = resolve
        self.in_process = in_process  # testes: sem subprocesso
        self.current: Job | None = None
        self._idle_since = 0.0
        self._task: asyncio.Task | None = None

    def observe(self, pub: dict) -> None:
        """Chamada a cada snapshot (barata, no event loop): decide se precisa carregar outro job."""
        state = pub.get("gcode_state")
        name = (pub.get("subtask_name") or "").strip() or norm_name(pub.get("gcode_file") or "")
        active = state in ACTIVE_STATES and bool(name)
        now = time.time()
        cur = self.current
        if cur is not None and cur.source == "sim":
            return
        if not active:
            if state == "IDLE":
                self._idle_since = self._idle_since or now
                if cur and now - self._idle_since > 20:
                    self.current = None
            return
        self._idle_since = 0.0
        key = f"{name}|{pub.get('gcode_file', '')}"
        if cur is None or cur.key != key:
            cur = Job(key=key, name=name)
            self.current = cur
        elif not (cur.status == "failed" and cur.tries < 6 and now - cur.last_try >= 20):
            return
        if self._task and not self._task.done():
            return  # um parse por vez; o próximo snapshot tenta de novo
        cur.status, cur.tries, cur.last_try = "loading", cur.tries + 1, now
        self._task = asyncio.get_running_loop().create_task(self._load(cur, dict(pub)))

    async def _load(self, job: Job, pub: dict) -> None:
        t0 = time.time()
        try:
            found = await self.resolve(pub, job.name)
            if not found:
                raise LookupError("arquivo do job não encontrado no Bambuddy (arquivo/biblioteca)")
            path, src, plate_hint = found
            plate = plate_of(pub.get("gcode_file", ""), plate_hint or 1)
            params, ftag = firmware_params(pub.get("stg"))
            digest = await asyncio.to_thread(file_digest, path)
            h = f"{digest}-p{plate}-v{PARSER_VERSION}{ftag}"
            cache = self.cache_dir / f"{h}.bin.gz"
            info: dict = {}
            if cache.exists():
                gz = await asyncio.to_thread(cache.read_bytes)
                jid = hashlib.sha1(gzip.decompress(gz)).hexdigest()[:16]
                info = {"cached": True}
            else:
                job_info = {"name": job.name, "source": src.split(":")[0], "plate": plate}
                gz, jid, info = await self._run_parser(str(path), plate, job_info, params)
                await asyncio.to_thread(self._store, cache, gz)
            if self.current is not job:
                return  # outro job começou enquanto este era interpretado
            job.blob_gz, job.id, job.source = gz, jid, src
            job.info = {**info, "gz": len(gz), "total_secs": round(time.time() - t0, 1)}
            job.status = "ready"
            log.info(
                "twin: job '%s' pronto de %s em %.1fs (%d KB gz)", job.name, src, time.time() - t0, len(gz) // 1024
            )
        except Exception as e:  # noqa: BLE001
            job.status, job.error = "failed", f"{type(e).__name__}: {e}"
            log.warning("twin: job '%s' falhou: %s", job.name, job.error)

    async def _run_parser(self, path: str, plate: int, job_info: dict, params: dict | None):
        if self.in_process:
            return await asyncio.to_thread(build_pack_gz, path, plate, job_info, params)
        ctx = multiprocessing.get_context("spawn")
        with concurrent.futures.ProcessPoolExecutor(max_workers=1, mp_context=ctx) as ex:
            return await asyncio.get_running_loop().run_in_executor(ex, build_pack_gz, path, plate, job_info, params)

    def _store(self, cache: pathlib.Path, gz: bytes) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_suffix(".tmp")
        tmp.write_bytes(gz)
        tmp.replace(cache)
        files = sorted(self.cache_dir.glob("*.bin.gz"), key=lambda p: p.stat().st_mtime)
        total = sum(p.stat().st_size for p in files)
        while files and (len(files) > CACHE_MAX_FILES or total > CACHE_MAX_BYTES) and files[0] != cache:
            total -= files[0].stat().st_size
            files.pop(0).unlink(missing_ok=True)

    def set_ready(self, name: str, gz: bytes, jid: str) -> None:
        """Modo de simulação/testes: injeta um job pronto."""
        self.current = Job(key=name, name=name, status="ready", id=jid, blob_gz=gz, source="sim")

    def public(self) -> dict:
        j = self.current
        if not j:
            return {"status": "none"}
        return {"status": j.status, "id": j.id if j.status == "ready" else "", "name": j.name}

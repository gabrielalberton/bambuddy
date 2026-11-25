"""Trabalho pesado do plotter, fora do processo do Bambuddy.

Vetorizar uma foto de celular aloca algumas centenas de MB e ocupa a CPU por segundos; o container do
Bambuddy tem teto de memória e um event loop só. Cada trabalho roda num processo filho (spawn), um por
vez, com prazo: se estourar a memória ou o tempo, morre o filho, não o servidor.

As funções ``*_job`` só importam o motor (numpy/OpenCV), nunca a aplicação.
"""

from __future__ import annotations

import asyncio
import multiprocessing
import threading
import traceback

VECTORIZE_TIMEOUT = 150.0
PLAN_TIMEOUT = 120.0
PREVIEW_MAX_SIDE = 1600
THUMB_MAX_SIDE = 160  # miniatura do histórico de envios (store.THUMB_SIDE)
SIM_MAX_POINTS = 12000

# Os testes ligam isto para rodar no próprio processo (sem spawn).
IN_PROCESS = False
# trava de thread (não de asyncio): vale entre event loops diferentes e mantém um filho só por vez
_one_at_a_time = threading.Lock()


class JobError(RuntimeError):
    """Falha do trabalho, com mensagem que pode ir para o usuário."""


def vectorize_job(data: bytes, options: dict | None) -> dict:
    """Imagem (bytes) -> {"drawing": json dos traços, "preview": JPEG da imagem normalizada}."""
    import cv2

    from .engine import VectorizeOptions, raster, vectorize

    opts = VectorizeOptions.from_dict(options)
    rgb = raster.decode_image(data, opts.raster().max_pixels)
    drawing = vectorize(rgb, opts)
    h, w = rgb.shape[:2]
    scale = min(1.0, PREVIEW_MAX_SIDE / max(h, w))
    small = rgb if scale >= 1.0 else cv2.resize(rgb, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
    bgr = cv2.cvtColor(small, cv2.COLOR_RGB2BGR)
    ok, jpg = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 82])
    t = min(1.0, THUMB_MAX_SIDE / max(bgr.shape[:2]))
    tiny = (
        bgr
        if t >= 1.0
        else cv2.resize(
            bgr, (max(1, round(bgr.shape[1] * t)), max(1, round(bgr.shape[0] * t))), interpolation=cv2.INTER_AREA
        )
    )
    ok_t, thumb = cv2.imencode(".jpg", tiny, [cv2.IMWRITE_JPEG_QUALITY, 72])
    return {
        "drawing": drawing.to_json(),
        "preview": jpg.tobytes() if ok else b"",
        "thumb": thumb.tobytes() if ok_t else b"",
    }


def plan_job(request: dict) -> dict:
    """Monta o plot (desenho ou padrão de calibração), valida e empacota.

    ``request``: kind, title, pen, paper, e conforme o tipo: drawing + placement + options, ou os
    parâmetros do padrão. Devolve o resumo (com a simulação) e os bytes do ``.gcode.3mf`` se passou.
    """
    from . import engine as E

    machine = E.MACHINES[request.get("machine", "A1")]
    pen = E.PenProfile.from_dict(request["pen"])
    paper = E.Paper.from_dict(request["paper"])
    kind = request.get("kind", "drawing")
    title = request.get("title") or kind
    extra: dict = {}
    if kind == "drawing":
        drawing = E.Drawing.from_json(request["drawing"])
        plot = E.make_plot(
            drawing,
            E.Placement.from_dict(request.get("placement")),
            paper,
            pen,
            machine,
            E.PlanOptions.from_dict(request.get("options")),
            title,
        )
    else:
        area = E.drawable_area(machine, pen, paper)
        if area is None:
            raise E.PlanError("o papel não tem área útil dentro do alcance da caneta")
        if kind == "ladder":
            paths, extra = E.calibration.pressure_ladder(area, pen, request.get("depths"))
        elif kind == "comb":
            paths, extra = E.calibration.spacing_comb(area, pen, request.get("depths"), request.get("spacings"))
        elif kind == "wedge":
            paths, extra = E.calibration.ruler_wedge(area, pen, request.get("top_depth"))
        elif kind == "wave":
            paths, extra = E.calibration.wave_tapers(area, pen)
        elif kind == "cross":
            target = request.get("target")
            paths, extra = E.calibration.offset_cross(area, pen, tuple(target) if target else None)
        elif kind == "frame":
            paths, extra = E.calibration.frame(area, pen)
        else:
            raise E.PlanError(f"tipo de plano desconhecido: {kind}")
        plot = E.plot_paths(paths, pen, paper, machine, title)
    report = plot.report
    summary = {
        "kind": kind,
        "title": title,
        "ok": plot.ok,
        "errors": report.errors,
        "warnings": [i.to_dict() for i in plot.issues] + report.warnings,
        "stats": {**plot.stats, **report.stats},
        "sim": E.thin_sim(report.sim, SIM_MAX_POINTS),
        "calibration": extra,
        "pen": pen.to_dict(),
        "paper": paper.to_dict(),
        "home": plot.stats.get("gcode", {}).get("home"),
    }
    return {"summary": summary, "package": plot.package() if plot.ok else None}


_JOBS = {"vectorize": vectorize_job, "plan": plan_job}


def _child_main(conn, name: str, args: tuple) -> None:
    try:
        conn.send(("ok", _JOBS[name](*args)))
    except Exception as exc:  # noqa: BLE001 - tudo vira mensagem para o pai
        user = type(exc).__name__ in ("ImageError", "PlanError", "ProfileError")
        conn.send(("user" if user else "error", str(exc) if user else traceback.format_exc(limit=6)))
    finally:
        conn.close()


def _run_child(name: str, args: tuple, timeout: float):
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=_child_main, args=(child, name, args), daemon=True)
    proc.start()
    child.close()
    try:
        if not parent.poll(timeout):
            raise JobError("o processamento demorou demais e foi cancelado")
        try:
            status, payload = parent.recv()
        except (EOFError, OSError) as exc:
            raise JobError("o processamento foi interrompido (imagem grande demais para a memória?)") from exc
    finally:
        parent.close()
        if proc.is_alive():
            proc.join(2)
        if proc.is_alive():
            proc.kill()
            proc.join(5)
    return status, payload


def _guarded(name: str, args: tuple, timeout: float):
    with _one_at_a_time:
        if IN_PROCESS:
            return "ok", _JOBS[name](*args)
        return _run_child(name, args, timeout)


async def run(name: str, *args, timeout: float):
    """Roda um trabalho (um por vez). Erro de dados do usuário vira ``ValueError``; o resto, ``JobError``."""
    status, payload = await asyncio.to_thread(_guarded, name, args, timeout)
    if status == "ok":
        return payload
    if status == "user":
        raise ValueError(payload)
    raise JobError(f"falha interna no processamento:\n{payload}")

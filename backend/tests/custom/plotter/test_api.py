"""custom(plotter): rotas, persistência, bloqueios de segurança e envio para a impressora (cliente falso)."""

import json
from types import SimpleNamespace

import pytest

from backend.app.custom.plotter import engine as E, hooks, printer as P, store, worker

from . import shapes

API = "/api/v1/custom/plotter"
TABLE = [[0.1, 0.3], [0.6, 0.8], [1.2, 1.6]]


class FakeClient:
    """Cliente MQTT de mentira: aceita G-code e devolve o aceite pelo handler bruto, como a A1."""

    topic_subscribe = "device/TEST/report"

    def __init__(self, **state):
        base = {
            "connected": True,
            "state": "IDLE",
            "temperatures": {"nozzle": 24.0, "nozzle_target": 0, "bed": 23.0, "bed_target": 0},
            "raw_data": {"home_flag": 7},
            "subtask_name": "",
            "progress": 0,
        }
        base.update(state)
        self.state = SimpleNamespace(**base)
        self.sent: list[str] = []
        self.handlers = []
        self.ack = "success"
        self._sequence_id = 100

    def register_raw_message_handler(self, handler):
        self.handlers.append(handler)

    def unregister_raw_message_handler(self, handler):
        self.handlers.remove(handler)

    def send_gcode(self, gcode):
        self._sequence_id += 1
        self.sent.append(gcode)
        if self.ack:
            report = {"command": "gcode_line", "sequence_id": str(self._sequence_id), "result": self.ack}
            payload = json.dumps({"print": report}).encode()
            for handler in list(self.handlers):
                handler(self.topic_subscribe, payload)
        return True


class FakeManager:
    def __init__(self, client=None):
        self.client = client
        self.awaiting = False
        self.started: list[tuple] = []
        self.accept = True

    def get_client(self, printer_id):
        return self.client

    def is_awaiting_plate_clear(self, printer_id):
        return self.awaiting

    def start_print(self, printer_id, filename, **kwargs):
        self.started.append((printer_id, filename, kwargs))
        return self.accept


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "base_dir", lambda: tmp_path / "plotter")
    monkeypatch.setattr(worker, "IN_PROCESS", True)
    P._jog.clear()
    P._start_locks.clear()
    hooks._pending.clear()
    yield
    P._jog.clear()
    P._start_locks.clear()
    hooks._pending.clear()


@pytest.fixture
def manager(monkeypatch):
    fake = FakeManager(FakeClient())
    monkeypatch.setattr(P, "_manager", lambda: fake)
    return fake


@pytest.fixture
def ftp(monkeypatch):
    """Troca o FTPS por um registro do que seria enviado/apagado."""
    from backend.app.services import bambu_ftp

    calls = SimpleNamespace(uploaded=[], deleted=[], ok=True)

    async def upload(ip, code, local_path, remote_path, **kwargs):
        calls.uploaded.append((ip, remote_path, local_path.read_bytes(), kwargs))
        return calls.ok

    async def delete(ip, code, remote_path, **kwargs):
        calls.deleted.append(remote_path)
        return bambu_ftp.DeleteResult.DELETED

    async def retry_settings():
        return False, 1, 0.0, 10.0

    monkeypatch.setattr(bambu_ftp, "upload_file_async", upload)
    monkeypatch.setattr(bambu_ftp, "delete_file_async", delete)
    monkeypatch.setattr(bambu_ftp, "get_ftp_retry_settings", retry_settings)
    return calls


async def _calibrated(client, printer_id, **pen):
    doc = (await client.get(f"{API}/printers/{printer_id}/settings")).json()
    doc["pens"]["padrao"].update({"z_contact": 4.0, "table": TABLE, **pen})
    body = {k: doc[k] for k in ("pens", "active_pen", "paper", "placement")}
    r = await client.put(f"{API}/printers/{printer_id}/settings", json=body)
    assert r.status_code == 200, r.text
    return r.json()


async def _drawing(client):
    files = {"file": ("cunha.png", shapes.png_bytes(shapes.wedge()), "image/png")}
    r = await client.post(f"{API}/drawings", files=files, data={"options": "{}"})
    assert r.status_code == 200, r.text
    return r.json()


async def _plan(client, printer_id, drawing_id, **over):
    body = {
        "kind": "drawing",
        "drawing_id": drawing_id,
        "placement": {"cx": 128, "cy": 110, "width": 160, "rotation": 0},
        **over,
    }
    return await client.post(f"{API}/printers/{printer_id}/plans", json=body)


# ---------------------------------------------------------------- leitura e ajustes
async def test_config_lista_impressoras_e_so_a_a1_e_suportada(async_client, printer_factory):
    a1 = await printer_factory(model="A1", name="A1 do Gabriel")
    x1 = await printer_factory(model="X1C")
    cfg = (await async_client.get(f"{API}/config")).json()
    by_id = {p["id"]: p for p in cfg["printers"]}
    assert by_id[a1.id]["supported"] and by_id[a1.id]["machine"]["plate_w"] == 256
    assert not by_id[x1.id]["supported"]
    assert {"A4", "A5"} <= {p["id"] for p in cfg["paper_presets"]}


async def test_ajustes_padrao_sao_a4_e_caneta_sem_calibrar(async_client, printer_factory, manager):
    printer = await printer_factory(model="A1")
    doc = (await async_client.get(f"{API}/printers/{printer.id}/settings")).json()
    assert (doc["paper"]["w"], doc["paper"]["h"]) == (210.0, 297.0)
    pen = doc["pens"][doc["active_pen"]]
    assert pen["z_contact"] is None and pen["offset_y"] == -32.0
    derived = doc["derived"][doc["active_pen"]]
    assert not derived["contact_calibrated"] and not derived["pressure_calibrated"]
    assert derived["area"] == [28.0, 5.0, 228.0, 222.0] and doc["home"] == [11.5, 3.0, False]


async def test_ajustes_gravam_e_recusam_dado_perigoso(async_client, printer_factory, manager):
    printer = await printer_factory(model="A1")
    saved = await _calibrated(async_client, printer.id, offset_x=1.5)
    assert saved["pens"]["padrao"]["offset_x"] == 1.5 and saved["derived"]["padrao"]["pressure_calibrated"]
    again = (await async_client.get(f"{API}/printers/{printer.id}/settings")).json()
    assert again["pens"]["padrao"]["table"] == TABLE
    bad = {k: again[k] for k in ("pens", "active_pen", "paper", "placement")}
    bad["pens"]["padrao"]["depth_max"] = 4.0  # além do aperto máximo do suporte (3 mm)
    r = await async_client.put(f"{API}/printers/{printer.id}/settings", json=bad)
    assert r.status_code == 422 and "max_compression" in r.json()["detail"]["message"]


# ---------------------------------------------------------------- desenho
async def test_envia_imagem_e_recebe_tracos_com_largura(async_client):
    d = await _drawing(async_client)
    assert d["width"] == 900 and d["height"] == 500 and d["meta"]["name"] == "cunha"
    assert len(d["strokes"]) == 1 and len(d["strokes"][0]["p"]) % 3 == 0
    widths = d["strokes"][0]["p"][2::3]
    assert min(widths) < 6 and max(widths) > 26
    again = (await async_client.get(f"{API}/drawings/{d['id']}")).json()
    assert again["strokes"] == d["strokes"]
    image = await async_client.get(f"{API}/drawings/{d['id']}/image")
    assert image.status_code == 200 and image.content[:2] == b"\xff\xd8"


async def test_revetoriza_com_outras_opcoes_sem_reenviar_a_imagem(async_client):
    d = await _drawing(async_client)
    r = await async_client.post(f"{API}/drawings/{d['id']}/vectorize", json={"options": {"simplify": 2.0}})
    assert r.status_code == 200 and r.json()["id"] == d["id"]
    assert len(r.json()["strokes"][0]["p"]) < len(d["strokes"][0]["p"])
    assert r.json()["meta"]["name"] == "cunha"


async def test_imagem_invalida_vazia_ou_inexistente(async_client):
    r = await async_client.post(f"{API}/drawings", files={"file": ("x.png", b"nao e imagem", "image/png")})
    assert r.status_code == 422 and "imagem" in r.json()["detail"]["message"]
    blank = shapes.png_bytes(shapes.rgb(shapes.canvas()))
    r = await async_client.post(f"{API}/drawings", files={"file": ("b.png", blank, "image/png")})
    assert r.status_code == 422 and "traço" in r.json()["detail"]["message"]
    assert (await async_client.get(f"{API}/drawings/aaaaaaaaaaaa")).status_code == 404
    assert (await async_client.get(f"{API}/drawings/..%2F..%2Fetc")).status_code == 404


async def test_processo_filho_de_verdade_vetoriza_e_devolve_erro_do_usuario(monkeypatch):
    monkeypatch.setattr(worker, "IN_PROCESS", False)
    out = await worker.run("vectorize", shapes.png_bytes(shapes.cross()), {}, timeout=120)
    assert len(out["drawing"]["strokes"]) == 2 and out["preview"][:2] == b"\xff\xd8"
    with pytest.raises(ValueError, match="imagem"):
        await worker.run("vectorize", b"lixo", {}, timeout=120)


# ---------------------------------------------------------------- plano
async def test_plano_gera_gcode_validado_e_pacote_para_baixar(async_client, printer_factory, manager):
    printer = await printer_factory(model="A1")
    await _calibrated(async_client, printer.id)
    d = await _drawing(async_client)
    r = await _plan(async_client, printer.id, d["id"])
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["ok"] and not plan["errors"] and plan["printer_id"] == printer.id
    assert plan["stats"]["pressure"] == "variable" and plan["stats"]["max_depth"] == pytest.approx(1.2)
    assert plan["sim"] and len(plan["sim"][0]) == 4
    assert "sim" not in (await async_client.get(f"{API}/printers/{printer.id}/plans/{plan['id']}")).json()
    pkg = await async_client.get(f"{API}/printers/{printer.id}/plans/{plan['id']}/download")
    assert pkg.status_code == 200 and "cunha.gcode.3mf" in pkg.headers["content-disposition"]
    gcode = E.package.read_gcode(pkg.content)
    assert "G28 Z P0 T140" in gcode and E.validate(gcode, E.A1, E.PenProfile.from_dict(plan["pen"]), E.Paper()).ok


async def test_plano_sem_altura_de_contato_e_recusado(async_client, printer_factory, manager):
    printer = await printer_factory(model="A1")
    d = await _drawing(async_client)
    r = await _plan(async_client, printer.id, d["id"])
    assert r.status_code == 422 and "contato" in r.json()["detail"]["message"]


async def test_plano_so_para_a1_e_com_desenho_existente(async_client, printer_factory, manager):
    x1 = await printer_factory(model="X1C")
    a1 = await printer_factory(model="A1")
    d = await _drawing(async_client)
    assert (await _plan(async_client, x1.id, d["id"])).status_code == 422
    assert (await _plan(async_client, a1.id, "bbbbbbbbbbbb")).status_code == 404
    assert (await _plan(async_client, 9999, d["id"])).status_code == 404


async def test_padroes_de_calibracao_viram_planos(async_client, printer_factory, manager):
    printer = await printer_factory(model="A1")
    await _calibrated(async_client, printer.id, table=[])  # só a altura de contato: já dá para a folha de teste
    ladder = await async_client.post(
        f"{API}/printers/{printer.id}/plans", json={"kind": "ladder", "depths": [0.0, 0.4, 0.8, 1.2]}
    )
    assert ladder.status_code == 200, ladder.text
    assert ladder.json()["ok"] and [r["depth"] for r in ladder.json()["calibration"]["rows"]] == [0.0, 0.4, 0.8, 1.2]
    comb = (await async_client.post(f"{API}/printers/{printer.id}/plans", json={"kind": "comb"})).json()
    assert comb["ok"] and comb["calibration"]["test"] == "comb" and len(comb["calibration"]["spacings"]) == 8
    wedge = await async_client.post(f"{API}/printers/{printer.id}/plans", json={"kind": "wedge", "top_depth": 1.0})
    assert wedge.json()["ok"] and wedge.json()["calibration"]["to"] == 1.0, wedge.text
    cross = await async_client.post(f"{API}/printers/{printer.id}/plans", json={"kind": "cross", "target": [100, 100]})
    assert cross.json()["ok"] and cross.json()["calibration"]["target"] == [100.0, 100.0]
    assert (await async_client.post(f"{API}/printers/{printer.id}/plans", json={"kind": "frame"})).json()["ok"]


# ---------------------------------------------------------------- envio
async def _ready_plan(client, printer):
    await _calibrated(client, printer.id)
    d = await _drawing(client)
    return (await _plan(client, printer.id, d["id"])).json()


async def test_iniciar_envia_o_arquivo_e_manda_imprimir_sem_calibracoes(async_client, printer_factory, manager, ftp):
    printer = await printer_factory(model="A1")
    plan = await _ready_plan(async_client, printer)
    r = await async_client.post(f"{API}/printers/{printer.id}/plans/{plan['id']}/start")
    assert r.status_code == 200, r.text
    name = f"penplot_{plan['id']}.3mf"
    assert r.json() == {"started": True, "file": name, "time_s": plan["stats"]["time_s"]}
    (ip, remote, data, kwargs) = ftp.uploaded[0]
    assert remote == f"/{name}" and ip == printer.ip_address and kwargs["printer_model"] == "A1"
    assert "M104 S0" in E.package.read_gcode(data)
    (pid, filename, opts) = manager.started[0]
    assert (pid, filename) == (printer.id, name)
    assert opts == {
        "plate_id": 1,
        "ams_mapping": None,
        "bed_levelling": "off",
        "flow_cali": "off",
        "vibration_cali": False,
        "layer_inspect": False,
        "timelapse": False,
        "use_ams": False,
        "nozzle_offset_cali": "off",
    }
    assert not ftp.deleted
    assert hooks.is_plotter_job(printer.id, {"subtask_name": name.removesuffix(".3mf")})


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (lambda m: setattr(m.client.state, "connected", False), "offline"),
        (lambda m: setattr(m.client.state, "state", "RUNNING"), "busy"),
        (lambda m: m.client.state.temperatures.update(nozzle=180.0), "nozzle_hot"),
        (lambda m: m.client.state.temperatures.update(nozzle_target=220), "nozzle_hot"),
        (lambda m: m.client.state.temperatures.update(bed_target=60), "bed_hot"),
        (lambda m: setattr(m, "awaiting", True), "plate_not_cleared"),
        (lambda m: setattr(m, "client", None), "offline"),
    ],
)
async def test_iniciar_e_bloqueado_e_nada_e_enviado(async_client, printer_factory, manager, ftp, change, code):
    printer = await printer_factory(model="A1")
    plan = await _ready_plan(async_client, printer)
    change(manager)
    status = (await async_client.get(f"{API}/printers/{printer.id}/status")).json()
    assert code in [b["code"] for b in status["blockers"]]
    r = await async_client.post(f"{API}/printers/{printer.id}/plans/{plan['id']}/start")
    assert r.status_code == 409
    assert code in [b["code"] for b in r.json()["detail"]["reasons"]]
    assert not ftp.uploaded and not manager.started


async def test_plano_de_caneta_recalibrada_fica_velho(async_client, printer_factory, manager, ftp):
    printer = await printer_factory(model="A1")
    plan = await _ready_plan(async_client, printer)
    await _calibrated(async_client, printer.id, z_contact=5.5)
    r = await async_client.post(f"{API}/printers/{printer.id}/plans/{plan['id']}/start")
    assert r.status_code == 409 and r.json()["detail"]["reasons"][0]["code"] == "stale"
    assert not ftp.uploaded


async def test_pacote_adulterado_no_disco_nao_sai(async_client, printer_factory, manager, ftp):
    printer = await printer_factory(model="A1")
    plan = await _ready_plan(async_client, printer)
    path = store.plan_package(plan["id"])
    bad = E.package.build_3mf(E.package.read_gcode(path.read_bytes()).replace("M104 S0", "M104 S220"), "x", 1)
    path.write_bytes(bad)
    r = await async_client.post(f"{API}/printers/{printer.id}/plans/{plan['id']}/start")
    assert r.status_code == 409 and r.json()["detail"]["reasons"][0]["code"] == "invalid"
    assert not ftp.uploaded


async def test_falha_de_envio_ou_recusa_da_impressora_nao_deixa_arquivo_no_sd(
    async_client, printer_factory, manager, ftp
):
    printer = await printer_factory(model="A1")
    plan = await _ready_plan(async_client, printer)
    ftp.ok = False
    r = await async_client.post(f"{API}/printers/{printer.id}/plans/{plan['id']}/start")
    assert r.status_code == 502 and r.json()["detail"]["reasons"][0]["code"] == "upload_failed"
    assert not manager.started
    ftp.ok, manager.accept = True, False
    r = await async_client.post(f"{API}/printers/{printer.id}/plans/{plan['id']}/start")
    assert r.status_code == 502 and r.json()["detail"]["reasons"][0]["code"] == "start_refused"
    assert ftp.deleted == [f"/penplot_{plan['id']}.3mf"]  # senão vira impressão fantasma ao religar a A1


async def test_plano_de_outra_impressora_ou_inexistente(async_client, printer_factory, manager, ftp):
    one = await printer_factory(model="A1")
    two = await printer_factory(model="A1")
    plan = await _ready_plan(async_client, one)
    assert (await async_client.post(f"{API}/printers/{two.id}/plans/{plan['id']}/start")).status_code == 409
    assert (await async_client.post(f"{API}/printers/{one.id}/plans/cccccccccccc/start")).status_code == 404
    assert (await async_client.get(f"{API}/printers/{two.id}/plans/{plan['id']}")).status_code == 404
    assert not ftp.uploaded


# ---------------------------------------------------------------- ajuste de altura
async def test_ajuste_de_altura_faz_home_desce_aos_poucos_e_grava_o_contato(async_client, printer_factory, manager):
    printer = await printer_factory(model="A1")
    r = await async_client.post(f"{API}/printers/{printer.id}/jog/start", json={})
    assert r.status_code == 200, r.text
    session = r.json()
    assert session["z"] == 20.0 and session["target"] == [128.0, 113.5]
    sent = "\n".join(manager.client.sent).splitlines()
    assert "G28 X" in sent and "G28 Z P0 T140" in sent and sent.index("G0 Y3 F3000") < sent.index("G28 Z P0 T140")
    assert "G0 X128 Y145.5 F6000" in sent  # ponta no meio da área útil: bico 32 mm atrás
    assert not any(ln.startswith(("M73", "M1002", ";")) for ln in sent)
    assert max(len(block.splitlines()) for block in manager.client.sent) <= P.SEND_CHUNK

    manager.client.sent.clear()
    for z in (15.0, 10.0, 6.0, 4.5, 4.2):
        r = await async_client.post(f"{API}/printers/{printer.id}/jog/move", json={"z": z})
        assert r.status_code == 200 and r.json()["z"] == z
    assert manager.client.sent[-1] == "G90\nG1 Z4.2 F300\nM400"
    status = (await async_client.get(f"{API}/printers/{printer.id}/status")).json()
    assert status["jog"]["z"] == 4.2

    r = await async_client.post(f"{API}/printers/{printer.id}/jog/finish", json={"save": True})
    assert r.json() == {"saved_z_contact": 4.2, "pen_id": "padrao"}
    assert manager.client.sent[-1].splitlines()[1] == "G1 Z24.2 F600"
    doc = (await async_client.get(f"{API}/printers/{printer.id}/settings")).json()
    assert doc["pens"]["padrao"]["z_contact"] == 4.2 and doc["derived"]["padrao"]["contact_calibrated"]
    assert (await async_client.get(f"{API}/printers/{printer.id}/status")).json()["jog"] is None


async def test_ajuste_de_altura_recusa_passo_grande_fora_da_faixa_e_sessao_vencida(
    async_client, printer_factory, manager, monkeypatch
):
    printer = await printer_factory(model="A1")
    url = f"{API}/printers/{printer.id}/jog"
    assert (await async_client.post(f"{url}/move", json={"z": 10})).status_code == 409  # sem sessão
    await async_client.post(f"{url}/start", json={})
    assert (await async_client.post(f"{url}/move", json={"z": 10})).status_code == 400  # 10 mm de uma vez
    for z in (15, 10, 5, 1):
        assert (await async_client.post(f"{url}/move", json={"z": z})).status_code == 200
    r = await async_client.post(f"{url}/move", json={"z": 0.2})
    assert r.status_code == 400 and r.json()["detail"]["reasons"][0]["code"] == "z_range"  # abaixo do piso do bico
    manager.client.state.state = "RUNNING"
    assert (await async_client.post(f"{url}/move", json={"z": 2})).status_code == 409
    manager.client.state.state = "IDLE"
    P._jog[printer.id].updated -= P.JOG_IDLE_SECONDS + 1  # motores podem ter desligado
    r = await async_client.post(f"{url}/move", json={"z": 2})
    assert r.status_code == 409 and r.json()["detail"]["reasons"][0]["code"] == "no_session"


async def test_ajuste_de_altura_nao_cria_sessao_se_a_impressora_recusa(async_client, printer_factory, manager):
    printer = await printer_factory(model="A1")
    manager.client.ack = "fail"
    r = await async_client.post(f"{API}/printers/{printer.id}/jog/start", json={})
    assert r.status_code == 502 and r.json()["detail"]["reasons"][0]["code"] == "rejected"
    assert (await async_client.get(f"{API}/printers/{printer.id}/status")).json()["jog"] is None
    manager.client.state.temperatures["nozzle"] = 200.0
    assert (await async_client.post(f"{API}/printers/{printer.id}/jog/start", json={})).status_code == 409


async def test_iniciar_plot_recusa_sessao_de_ajuste(async_client, printer_factory, manager, ftp):
    printer = await printer_factory(model="A1")
    plan = await _ready_plan(async_client, printer)
    await async_client.post(f"{API}/printers/{printer.id}/jog/start", json={})
    assert P.jog_public(printer.id)
    response = await async_client.post(f"{API}/printers/{printer.id}/plans/{plan['id']}/start")
    assert response.status_code == 409 and response.json()["detail"]["reasons"][0]["code"] == "jog_open"
    assert not ftp.uploaded
    assert P.jog_public(printer.id)


# ---------------------------------------------------------------- ganchos e interruptor
def test_gancho_reconhece_so_os_arquivos_do_plotter():
    job = {"gcode_file": "/sdcard/penplot_0123456789ab.3mf"}
    assert not hooks.is_plotter_job(1, job)
    hooks.register_plot(1, "penplot_0123456789ab.3mf")
    assert not hooks.is_plotter_job(2, job)
    assert not hooks.is_plotter_job(1, {"subtask_name": "benchy", "filename": "/benchy.3mf"})
    assert not hooks.is_plotter_job(1, {"subtask_name": None}) and not hooks.is_plotter_job(1, None)
    assert hooks.is_plotter_job(1, job)
    assert not hooks.is_plotter_job(1, job)


def test_gancho_esta_no_ponto_da_verificacao_de_mesa_vazia():
    import inspect

    from backend.app import main

    src = inspect.getsource(main.on_print_start)
    assert "printer.plate_detection_enabled and not is_plotter_job(printer_id, data)" in src


def test_interruptor_por_variavel_de_ambiente(monkeypatch):
    from backend.app.custom.plotter.router import plotter_enabled

    assert plotter_enabled()
    monkeypatch.setenv("BAMBUDDY_CUSTOM_PLOTTER", "off")
    assert not plotter_enabled()


def test_so_ficam_os_desenhos_mais_recentes():
    for i in range(store.KEEP_DRAWINGS + 3):
        store.save_drawing(f"{i:012x}", {"width": 1, "height": 1, "strokes": [], "meta": {}})
    kept = [d.name for d in (store.base_dir() / "drawings").iterdir()]
    assert len(kept) == store.KEEP_DRAWINGS


def test_historico_respeita_o_teto_de_disco_das_imagens(monkeypatch):
    monkeypatch.setattr(store, "KEEP_DRAWINGS_BYTES", 2500)
    for i in range(4):
        store.save_drawing(f"{i:012x}", {"width": 1, "height": 1, "strokes": [], "meta": {}}, source=b"x" * 1000)
    kept = sorted(d.name for d in (store.base_dir() / "drawings").iterdir())
    assert kept == [f"{2:012x}", f"{3:012x}"]  # os dois mais novos; o mais novo fica mesmo sozinho acima do teto


# ---------------------------------------------------------------- histórico de envios
async def test_historico_lista_envios_com_miniatura_e_opcoes(async_client):
    first = await _drawing(async_client)
    files = {"file": ("logo.png", shapes.png_bytes(shapes.wedge()), "image/png")}
    second = (await async_client.post(f"{API}/drawings", files=files, data={"options": '{"threshold": 0.4}'})).json()
    r = await async_client.get(f"{API}/drawings")
    assert r.status_code == 200
    items = r.json()["items"]
    assert [i["id"] for i in items] == [second["id"], first["id"]]  # mais recente primeiro
    top = items[0]
    assert top["name"] == "logo" and top["strokes"] == len(second["strokes"]) and top["options"] == {"threshold": 0.4}
    assert top["thumb"].startswith("data:image/jpeg;base64,") and top["can_revectorize"]
    assert (top["width"], top["height"]) == (900, 500) and top["created_at"] <= top["updated_at"]
    # revetorizar guarda as novas opções e mantém a data de envio
    await async_client.post(f"{API}/drawings/{first['id']}/vectorize", json={"options": {"simplify": 2.0}})
    items = (await async_client.get(f"{API}/drawings")).json()["items"]
    assert items[0]["id"] == first["id"] and items[0]["options"] == {"simplify": 2.0}


async def test_historico_completa_desenho_antigo_sem_miniatura(async_client):
    d = await _drawing(async_client)
    folder = store.base_dir() / "drawings" / d["id"]
    (folder / "info.json").unlink()
    (folder / "thumb.jpg").unlink()
    item = (await async_client.get(f"{API}/drawings")).json()["items"][0]
    assert item["name"] == "cunha" and item["thumb"].startswith("data:image/jpeg") and item["options"] == {}
    assert (folder / "info.json").is_file() and (folder / "thumb.jpg").is_file()


async def test_excluir_do_historico(async_client):
    d = await _drawing(async_client)
    assert (await async_client.delete(f"{API}/drawings/{d['id']}")).status_code == 200
    assert (await async_client.get(f"{API}/drawings")).json()["items"] == []
    assert (await async_client.get(f"{API}/drawings/{d['id']}")).status_code == 404
    assert (await async_client.delete(f"{API}/drawings/{d['id']}")).status_code == 404
    assert (await async_client.delete(f"{API}/drawings/settings.json")).status_code == 404


async def test_config_traz_tipos_de_caneta_e_ajustes_trazem_os_testes(async_client, printer_factory, manager):
    printer = await printer_factory(model="A1")
    cfg = (await async_client.get(f"{API}/config")).json()
    assert cfg["default_pen_type"] == "bic" and cfg["pen_types"][0]["key"] == "bic"
    assert {"bic", "canetinha", "pincel", "outra"} <= {t["key"] for t in cfg["pen_types"]}
    bic = cfg["pen_types"][0]["defaults"]
    assert bic["rigid"]["max_compression"] == 0.3 and bic["spring"]["name"] == "Caneta BIC com mola"
    doc = (await async_client.get(f"{API}/printers/{printer.id}/settings")).json()
    tests = doc["derived"]["padrao"]["tests"]
    assert tests["ladder"]["depths"][0] == 0.0 and tests["wedge"]["length"] == 100.0
    assert tests["comb"]["depths"] == [0.4, 0.77, 1.13, 1.5]
    # trocar o tipo de caneta é só mais um campo do perfil
    doc["pens"]["padrao"].update(E.PEN_TYPES["canetinha"].values_for("spring"), pen_type="canetinha")
    body = {k: doc[k] for k in ("pens", "active_pen", "paper", "placement")}
    saved = (await async_client.put(f"{API}/printers/{printer.id}/settings", json=body)).json()
    assert saved["pens"]["padrao"]["pen_type"] == "canetinha" and saved["pens"]["padrao"]["line_width"] == 1.0


# ---------------------------------------------------------------- modos do suporte
async def test_ha_um_perfil_com_mola_e_um_sem_mola_cada_um_com_sua_calibracao(async_client, printer_factory, manager):
    printer = await printer_factory(model="A1")
    cfg = (await async_client.get(f"{API}/config")).json()
    mounts = {m["key"]: m for m in cfg["mounts"]}
    assert set(mounts) == {"spring", "rigid"} and mounts["rigid"]["needs_mesh"]
    assert 0.02 in mounts["rigid"]["jog_steps"] and mounts["rigid"]["defaults"]["max_compression"] == 0.6
    doc = (await async_client.get(f"{API}/printers/{printer.id}/settings")).json()
    assert {p["mount"] for p in doc["pens"].values()} == {"spring", "rigid"}
    assert doc["active_pen"] == "padrao" and doc["pens"]["sem-mola"]["use_mesh"] is True
    assert doc["derived"]["sem-mola"]["mount"] == "rigid" and -0.02 in doc["derived"]["sem-mola"]["jog_steps"]
    # calibrar o sem mola não mexe no com mola
    doc["pens"]["sem-mola"].update({"z_contact": 5.5, "table": [[0.05, 0.5], [0.3, 1.5]]})
    body = {k: doc[k] for k in ("pens", "active_pen", "paper", "placement")}
    body["active_pen"] = "sem-mola"
    saved = (await async_client.put(f"{API}/printers/{printer.id}/settings", json=body)).json()
    assert saved["pens"]["sem-mola"]["z_contact"] == 5.5 and saved["pens"]["padrao"]["z_contact"] is None
    assert saved["active_pen"] == "sem-mola" and saved["derived"]["sem-mola"]["pressure_calibrated"]


async def test_ajustes_antigos_com_uma_caneta_ganham_o_perfil_sem_mola(async_client, printer_factory, manager):
    printer = await printer_factory(model="A1")
    old = {"pens": {"padrao": {"name": "Minha caneta", "z_contact": 4.2}}, "active_pen": "padrao"}
    saved = (await async_client.put(f"{API}/printers/{printer.id}/settings", json=old)).json()
    assert saved["pens"]["padrao"]["mount"] == "spring" and saved["pens"]["padrao"]["z_contact"] == 4.2
    assert saved["pens"]["sem-mola"]["mount"] == "rigid"


async def test_plano_sem_mola_sai_com_malha_e_aproximacao_lenta(async_client, printer_factory, manager):
    printer = await printer_factory(model="A1")
    doc = (await async_client.get(f"{API}/printers/{printer.id}/settings")).json()
    doc["pens"]["sem-mola"].update({"z_contact": 4.0, "table": [[0.05, 0.5], [0.3, 1.5]]})
    body = {k: doc[k] for k in ("pens", "active_pen", "paper", "placement")}
    assert (await async_client.put(f"{API}/printers/{printer.id}/settings", json=body)).status_code == 200
    drawing = await _drawing(async_client)
    r = await _plan(async_client, printer.id, drawing["id"], pen_id="sem-mola")
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["ok"] and plan["pen_id"] == "sem-mola" and plan["pen"]["mount"] == "rigid"
    assert "rigid_flatness" in {w["code"] for w in plan["warnings"]}
    pkg = (await async_client.get(f"{API}/printers/{printer.id}/plans/{plan['id']}/download")).content
    gcode = E.package.read_gcode(pkg)
    assert "G29.2 S1" in gcode and "; pen_mount = rigid" in gcode and " F120" in gcode

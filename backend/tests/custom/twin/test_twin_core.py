"""Gêmeo digital dentro do Bambuddy: somente leitura, lista branca, sem segredos, job a partir do arquivo local."""

import asyncio
import gzip
import json
import pathlib
import struct
import time
import zipfile
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from backend.app.custom.twin import hub as hubmod
from backend.app.custom.twin.jobs import JobManager, firmware_params, plate_of, program_from_3mf
from backend.app.custom.twin.recorder import Recorder
from backend.app.custom.twin.state import PUBLIC_KEYS, PrinterState

TWIN_PKG = pathlib.Path(hubmod.__file__).parent
SECRET = "SEGREDO123"

GCODE = """; HEADER_BLOCK_START
; model printing time: 1m 0s; total estimated time: 1m 10s
; total layer number: 2
; HEADER_BLOCK_END
M73 P0 R1
G28
M104 S220
G1 X10 Y10 Z0.2 F6000
M991 S0 P0
; CHANGE_LAYER
; Z_HEIGHT: 0.2
; FEATURE: Outer wall
G1 X50 Y10 E2 F1200
G1 X50 Y50 E2
M73 P50 R0
M991 S0 P1
; CHANGE_LAYER
; Z_HEIGHT: 0.4
G1 Z0.4
G1 X10 Y50 E2
G1 X10 Y10 E2
M73 P100 R0
"""


def make_3mf(path: pathlib.Path, gcode: str = GCODE, plate: int = 1) -> pathlib.Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(f"Metadata/plate_{plate}.gcode", gcode)
        z.writestr("Metadata/project_settings.config", json.dumps({"filament_colour": ["#FF0000", "00FF00"]}))
    return path


class FakeClient:
    """Imita o BambuMQTTClient do Bambuddy; qualquer publish é registrado (e não pode acontecer)."""

    def __init__(self, serial="01P00A000000001"):
        self.serial_number = serial
        self.access_code = SECRET
        self.topic_subscribe = f"device/{serial}/report"
        self.topic_publish = f"device/{serial}/request"
        self.handlers = []
        self.publish = MagicMock()
        self.publish_raw = MagicMock()
        self.request_status_update = MagicMock()
        self._client = MagicMock()
        self.state = SimpleNamespace(
            connected=True,
            state="RUNNING",
            progress=12,
            remaining_time=40,
            layer_num=3,
            total_layers=11,
            subtask_name="Stack Matrix",
            gcode_file="/data/Metadata/plate_1.gcode",
            temperatures={"bed": 60, "bed_target": 60, "nozzle": 220, "nozzle_target": 220},
            speed_level=2,
            stg_cur=0,
            stg=[2, 13, 4],
            mc_print_sub_stage=0,
            ams_status=768,
            tray_now=2,
            tray_tar=255,
            cooling_fan_speed=15,
            big_fan1_speed=0,
            big_fan2_speed=0,
            heatbreak_fan_speed=15,
            raw_data={
                "spd_mag": 100,
                "home_flag": 7,
                "net": {"info": [{"ip": 123}]},
                "ipcam": {"rtsp_url": f"rtsp://bblp:{SECRET}@1.2.3.4"},
                "ams": [{"id": "0", "tray": [{"id": "2", "tray_color": "FF8800FF", "tray_type": "PLA"}]}],
            },
        )

    def register_raw_message_handler(self, h):
        self.handlers.append(h)

    def unregister_raw_message_handler(self, h):
        self.handlers.remove(h)

    def deliver(self, topic, payload: dict):
        for h in list(self.handlers):
            h(topic, json.dumps(payload).encode())

    def assert_never_published(self):
        self.publish.assert_not_called()
        self.publish_raw.assert_not_called()
        self.request_status_update.assert_not_called()
        assert not self._client.publish.called


class FakeManager:
    def __init__(self, client):
        self.client = client

    def get_client(self, pid):
        return self.client


# ---------- portados do twin avulso ----------


def test_public_state_is_whitelisted():
    st = PrinterState()
    st.update(
        {
            "gcode_state": "RUNNING",
            "mc_percent": 5,
            "access_code": SECRET,
            "ssid": "casa",
            "ap_ssid": "x",
            "net": {"info": [{"ip": 1}]},
            "ipcam": {"rtsp_url": f"rtsp://bblp:{SECRET}@1.2.3.4/x"},
            "sequence_id": "9",
        },
        "mqtt",
    )
    pub = json.dumps(st.public())
    assert SECRET not in pub and "ssid" not in pub and "rtsp" not in pub
    assert set(st.public()) <= set(PUBLIC_KEYS) | {"ams"}


def test_recorder_refuses_secrets(tmp_path):
    rec = Recorder(tmp_path, (SECRET,))
    rec.write("mqtt", {"a": 1})
    rec.write("mqtt", {"a": f"contém {SECRET}"})
    rec.close()
    text = "".join(p.read_text() for p in tmp_path.glob("*.jsonl"))
    assert SECRET not in text and rec.refused == 1 and '"a":1' in text


# ---------- somente leitura ----------


def test_twin_code_has_no_publish_calls():
    """Nenhum módulo do twin chama publish/pushall/comandos: a única via para a impressora é o cliente do Bambuddy."""
    import re

    bad = re.compile(r"\.(publish|publish_raw|request_status_update|send_command|pushall|_send_command)\s*\(")
    for f in TWIN_PKG.glob("*.py"):
        assert not bad.search(f.read_text()), f"{f.name} chama publish"


async def test_hub_observes_without_publishing_and_never_leaks_secrets(tmp_path):
    client = FakeClient()
    resolve = MagicMock()

    async def _resolve(pub, name):
        resolve(pub, name)
        return None

    hub = hubmod.TwinHub(1, cache_dir=tmp_path, manager=FakeManager(client), resolve=_resolve, record=False)
    try:
        hub.start()
        assert len(client.handlers) == 1
        # semente veio do PrinterState do Bambuddy
        s = hub.snapshot()["s"]
        assert s["gcode_state"] == "RUNNING" and s["mc_percent"] == 12 and s["spd_mag"] == 100 and s["home_flag"] == 7
        assert s["ams"]["tray_now"] == 2 and s["ams"]["trays"][0]["tray_color"] == "FF8800FF"
        assert s["stg"] == [2, 13, 4]
        # delta real da A1 (com campos sensíveis) + mensagem no tópico de comandos (ignorada)
        client.deliver(
            client.topic_subscribe,
            {
                "print": {
                    "mc_percent": 13,
                    "mc_remaining_time": 39,
                    "spd_mag": 124,
                    "spd_lvl": 3,
                    "net": {"info": [{"ip": 99}]},
                    "ipcam": {"rtsp_url": f"rtsp://bblp:{SECRET}@x"},
                    "wifi_signal": "-40dBm",
                    "access_code": SECRET,
                }
            },
        )
        client.deliver(client.topic_publish, {"print": {"command": "pause", "mc_percent": 99}})
        await asyncio.sleep(0.05)
        snap = hub.snapshot()
        assert snap["s"]["mc_percent"] == 13 and snap["s"]["spd_mag"] == 124
        assert snap["since_pr"] is not None
        text = hub.encode()
        for leak in (SECRET, "rtsp", "wifi", "ipcam", "net", client.serial_number, "access_code"):
            assert leak not in text, leak
        assert set(snap["s"]) <= set(PUBLIC_KEYS) | {"ams"}
        # troca de cliente (reconexão do Bambuddy): reanexa no novo, solta o antigo
        new = FakeClient()
        hub._manager = FakeManager(new)
        hub._attach()
        assert client.handlers == [] and len(new.handlers) == 1
        client.assert_never_published()
        new.assert_never_published()
    finally:
        await hub.stop()


async def test_job_loads_from_local_3mf_and_caches(tmp_path):
    f = make_3mf(tmp_path / "job.gcode.3mf")
    calls = []

    async def _resolve(pub, name):
        calls.append(name)
        return f, "archive:7", 1

    client = FakeClient()
    client.state.subtask_name = "job"
    hub = hubmod.TwinHub(1, cache_dir=tmp_path / "cache", manager=FakeManager(client), resolve=_resolve, record=False)
    hub.jobs.in_process = True
    try:
        hub.start()
        hub.snapshot()
        for _ in range(100):
            await asyncio.sleep(0.05)
            if hub.jobs.current and hub.jobs.current.status != "loading":
                break
        j = hub.jobs.current
        assert j.status == "ready", j.error
        assert j.source == "archive:7" and len(j.id) == 16
        blob = gzip.decompress(j.blob_gz)
        assert blob[:4] == b"A1TW" and struct.unpack("<I", blob[4:8])[0] == 1
        hjlen = struct.unpack("<I", blob[8:12])[0]
        header = json.loads(blob[12 : 12 + hjlen])
        assert header["colors"] == ["#FF0000", "#00FF00"] and header["n"] > 4
        assert list((tmp_path / "cache").glob("*.bin.gz"))
        # o job público só tem id/nome/estado
        assert hub.snapshot()["job"] == {"status": "ready", "id": j.id, "name": "job"}
        client.assert_never_published()
    finally:
        await hub.stop()


def test_firmware_flags_and_plate():
    assert firmware_params([2, 13, 24, 4, 3, 14, 13]) == (
        {"flags": {"extrude_cali_flag": 0, "g29_before_print_flag": 0}},
        "",
    )
    assert firmware_params([8, 1])[1] == "-f11"
    assert firmware_params(None) == (None, "")
    assert plate_of("/data/Metadata/plate_3.gcode") == 3 and plate_of("x.3mf", 2) == 2


def test_program_from_3mf_path_and_bytes(tmp_path):
    f = make_3mf(tmp_path / "a.gcode.3mf")
    p1, c1 = program_from_3mf(f, 1)
    p2, _ = program_from_3mf(f.read_bytes(), 1)
    assert len(p1.t) == len(p2.t) > 0 and c1[1] == "#00FF00"
    with pytest.raises(ValueError):
        program_from_3mf(f, 2)


def test_cache_is_bounded(tmp_path):
    jm = JobManager(tmp_path, None)
    for i in range(12):
        p = tmp_path / f"{i}.bin.gz"
        jm._store(p, b"x" * 10)
        time.sleep(0.01)
    assert len(list(tmp_path.glob("*.bin.gz"))) == 8


def test_spawned_parser_runs_out_of_process(tmp_path):
    """O parser roda num processo à parte (spawn): o pico de memória não fica no processo do Bambuddy."""
    f = make_3mf(tmp_path / "s.gcode.3mf")
    jm = JobManager(tmp_path, None)
    gz, jid, info = asyncio.run(jm._run_parser(str(f), 1, {"name": "s"}, None))
    assert gzip.decompress(gz)[:4] == b"A1TW" and info["peak_rss_mb"] > 0


def test_snapshot_reports_plate_wait(tmp_path):
    """plate_wait: True com a placa aguardando liberação, False depois de "marcar placa como liberada"."""

    class M:
        awaiting = True

        def is_awaiting_plate_clear(self, pid):
            return self.awaiting

    m = M()
    hub = hubmod.TwinHub(7, cache_dir=tmp_path, manager=m, record=False)
    assert hub.snapshot()["plate_wait"] is True
    m.awaiting = False
    assert hub.snapshot()["plate_wait"] is False
    hub.sim = True
    assert hub.snapshot()["plate_wait"] is None

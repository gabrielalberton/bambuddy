"""custom(printer-prefs): bico 0.2/0.4 e velocidade padrão aplicada a partir da camada 2."""

from types import SimpleNamespace

import pytest

from backend.app.custom.printer_prefs import router as prefs


class FakeClient:
    def __init__(self, **state):
        base = {
            "state": "RUNNING",
            "layer_num": 0,
            "speed_level": 2,
            "subtask_name": "a",
            "gcode_file": "a.gcode",
            "subtask_id": "1",
        }
        base.update(state)
        self.state = SimpleNamespace(**base)
        self.sent = []

    def set_print_speed(self, mode):
        self.sent.append(mode)
        return True


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs, "_prefs_path", lambda: tmp_path / "printer_prefs.json")
    prefs._applied.clear()
    yield
    prefs._applied.clear()


def test_aplica_so_a_partir_da_camada_2_e_uma_vez_por_impressao():
    c = FakeClient(layer_num=1)
    assert not prefs.apply_once(1, c, 4)
    c.state.layer_num = 2
    assert prefs.apply_once(1, c, 4)
    assert c.sent == [4]
    c.state.layer_num = 30
    c.state.speed_level = 2  # o dono mudou na mão: respeita até a próxima impressão
    assert not prefs.apply_once(1, c, 4)
    c.state.state = "FINISH"
    prefs.apply_once(1, c, 4)
    c.state.state, c.state.layer_num, c.state.subtask_id = "RUNNING", 3, "2"
    assert prefs.apply_once(1, c, 4)
    assert c.sent == [4, 4]


def test_sem_padrao_ou_parada_nao_manda_nada():
    assert not prefs.apply_once(1, FakeClient(layer_num=5), None)
    assert not prefs.apply_once(1, FakeClient(state="IDLE", layer_num=5), 4)


def test_ja_no_modo_nao_reenvia():
    c = FakeClient(layer_num=5, speed_level=4)
    assert not prefs.apply_once(1, c, 4)
    assert c.sent == []


def test_prefs_persistem():
    prefs.save_prefs({"1": {"default_speed": 3}})
    assert prefs.load_prefs() == {"1": {"default_speed": 3}}

"""Rotas do gêmeo digital: autorização da câmera e do controle, SSE só com a lista branca."""

import gzip
import json
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from backend.app.custom.twin import hub as hubmod, router as twin_router
from backend.app.main import app

BASE = "/api/v1/custom/twin"


@pytest.fixture(autouse=True)
async def _twin_app(tmp_path, monkeypatch):
    twin_router.include_twin(app)
    monkeypatch.setattr(twin_router, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(hubmod, "data_dir", lambda: tmp_path)
    yield
    await hubmod.reset_hubs()


async def _admin_jwt(client: AsyncClient) -> str:
    await client.post(
        "/api/v1/auth/setup",
        json={"auth_enabled": True, "admin_username": "twinadmin", "admin_password": "AdminPass1!"},
    )
    r = await client.post("/api/v1/auth/login", json={"username": "twinadmin", "password": "AdminPass1!"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def _user_jwt(client: AsyncClient, admin: str, name: str, perms: list[str]) -> str:
    h = {"Authorization": f"Bearer {admin}"}
    g = await client.post("/api/v1/groups/", headers=h, json={"name": f"grp_{name}", "permissions": perms})
    assert g.status_code in (200, 201), g.text
    u = await client.post(
        "/api/v1/users/", headers=h, json={"username": name, "password": "UserPass1!", "group_ids": [g.json()["id"]]}
    )
    assert u.status_code in (200, 201), u.text
    r = await client.post("/api/v1/auth/login", json={"username": name, "password": "UserPass1!"})
    return r.json()["access_token"]


async def _camera_token(client: AsyncClient, jwt: str) -> str:
    r = await client.post("/api/v1/printers/camera/stream-token", headers={"Authorization": f"Bearer {jwt}"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def test_twin_routes_before_spa_catch_all():
    paths = [getattr(r, "path", "") for r in app.router.routes]
    twin = [r for r in app.router.routes if getattr(r, "path", "").startswith(BASE)]
    assert len(twin) == 5
    for r in twin:
        expected = {"POST"} if r.path.endswith("/reference") else {"GET", "HEAD"}
        assert r.methods <= expected, r.path
        assert paths.index(r.path) < paths.index("/{full_path:path}")


async def test_non_get_methods_are_refused(async_client: AsyncClient, printer_factory):
    p = await printer_factory(model="A1")
    for m in ("POST", "PUT", "PATCH", "DELETE"):
        r = await async_client.request(m, f"{BASE}/{p.id}/health")
        assert r.status_code == 405, (m, r.status_code)


async def test_auth_off_health_and_unknown_printer(async_client: AsyncClient, printer_factory):
    p = await printer_factory(model="A1")
    r = await async_client.get(f"{BASE}/{p.id}/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["job"] == {"status": "none"}
    assert "access_code" not in r.text and p.serial_number not in r.text and p.ip_address not in r.text
    assert (await async_client.get(f"{BASE}/9999/health")).status_code == 404


async def test_model_glb_optional(async_client: AsyncClient, printer_factory, tmp_path):
    p = await printer_factory(model="A1")
    assert (await async_client.get(f"{BASE}/stream/{p.id}/model.glb")).status_code == 404
    (tmp_path / "a1.glb").write_bytes(b"glTF\x02\x00\x00\x00")
    r = await async_client.get(f"{BASE}/stream/{p.id}/model.glb")
    assert r.status_code == 200 and r.content.startswith(b"glTF") and r.headers["content-type"] == "model/gltf-binary"


async def test_reference_requires_control_permission_and_a1(async_client: AsyncClient, printer_factory, monkeypatch):
    from backend.app.custom.twin import reference

    a1 = await printer_factory(model="A1")
    p1 = await printer_factory(model="P1S")
    path = f"{BASE}/{a1.id}/reference"
    admin = await _admin_jwt(async_client)
    jwt = await _user_jwt(async_client, admin, "readonly", ["camera:view"])
    assert (await async_client.post(path, headers={"Authorization": f"Bearer {jwt}"})).status_code == 403
    assert (await async_client.post(path + "?token=" + await _camera_token(async_client, admin))).status_code == 401

    async def fake_move(_manager, printer_id):
        assert printer_id == a1.id
        return {"x": 128, "y": 128, "z": 20}

    monkeypatch.setattr(reference, "move_to_reference", fake_move)
    headers = {"Authorization": f"Bearer {admin}"}
    assert (await async_client.post(path, headers=headers)).json() == {"position": {"x": 128, "y": 128, "z": 20}}
    assert (await async_client.post(f"{BASE}/{p1.id}/reference", headers=headers)).status_code == 400


@pytest.mark.parametrize(("reply", "flag", "expected"), [("success", 7, 200), ("fail", 7, 502), ("success", 3, 504)])
async def test_reference_waits_for_ack_and_homed_report(monkeypatch, reply, flag, expected):
    from fastapi import HTTPException

    from backend.app.custom.twin import reference

    class Client:
        topic_subscribe = "device/test/report"
        state = SimpleNamespace(connected=True, state="IDLE", raw_data={"home_flag": 0})
        handler = None

        def register_raw_message_handler(self, handler):
            self.handler = handler

        def unregister_raw_message_handler(self, handler):
            assert self.handler is handler
            self.handler = None

        def send_gcode(self, gcode):
            assert gcode.splitlines() == ["G28", "M400", "G90", "G1 Z20 F1200", "G1 X128 Y128 F6000", "M400"]
            for report in (
                {"command": "gcode_line", "param": gcode, "result": reply},
                {"command": "push_status", "home_flag": flag},
            ):
                self.handler(self.topic_subscribe, json.dumps({"print": report}).encode())
            return True

    client = Client()
    manager = SimpleNamespace(get_client=lambda _: client)
    monkeypatch.setattr(reference, "SETTLE_SECONDS", 0)
    monkeypatch.setattr(reference, "REPORT_TIMEOUT", 0.02)
    if expected == 200:
        assert await reference.move_to_reference(manager, 1) == {"x": 128, "y": 128, "z": 20}
    else:
        with pytest.raises(HTTPException) as exc:
            await reference.move_to_reference(manager, 1)
        assert exc.value.status_code == expected
    assert client.handler is None


async def test_job_404_until_ready(async_client: AsyncClient, printer_factory):
    p = await printer_factory(model="A1")
    assert (await async_client.get(f"{BASE}/stream/{p.id}/job/abc")).status_code == 404
    hub = hubmod.get_hub(p.id)
    hub.jobs.set_ready("x", gzip.compress(b"A1TW-fake"), "abc")
    r = await async_client.get(f"{BASE}/stream/{p.id}/job/abc")
    assert r.status_code == 200 and r.headers["content-encoding"] == "gzip" and r.content == b"A1TW-fake"


async def test_auth_on_requires_camera_token_or_permission(async_client: AsyncClient, printer_factory, tmp_path):
    p = await printer_factory(model="A1")
    (tmp_path / "a1.glb").write_bytes(b"glTF")
    admin = await _admin_jwt(async_client)
    # sem nada: 401 em tudo
    for path in ("stream/{id}/events", "stream/{id}/model.glb", "stream/{id}/job/x", "{id}/health"):
        assert (await async_client.get(f"{BASE}/" + path.format(id=p.id))).status_code == 401, path
    # token lixo
    assert (await async_client.get(f"{BASE}/stream/{p.id}/model.glb?token=lixo")).status_code == 401
    # token de câmera de quem tem camera:view abre o que o navegador carrega sem cabeçalho
    tok = await _camera_token(async_client, admin)
    assert (await async_client.get(f"{BASE}/stream/{p.id}/model.glb?token={tok}")).status_code == 200
    assert (
        await async_client.get(f"{BASE}/stream/{p.id}/job/x?token={tok}")
    ).status_code == 404  # passou da autorização
    # o prefixo público do middleware não abre a saúde (que fica por cabeçalho)
    assert (await async_client.get(f"{BASE}/{p.id}/health?token={tok}")).status_code == 401
    # health: cabeçalho
    assert (
        await async_client.get(f"{BASE}/{p.id}/health", headers={"Authorization": f"Bearer {admin}"})
    ).status_code == 200
    # usuário sem camera:view: não obtém token e não vê a saúde
    jwt = await _user_jwt(async_client, admin, "semcamera", ["printers:read"])
    r = await async_client.post("/api/v1/printers/camera/stream-token", headers={"Authorization": f"Bearer {jwt}"})
    assert r.status_code == 403
    assert (
        await async_client.get(f"{BASE}/{p.id}/health", headers={"Authorization": f"Bearer {jwt}"})
    ).status_code == 403


async def test_sse_stream_sends_only_whitelisted_state(async_client: AsyncClient, printer_factory, monkeypatch):
    """O SSE (chamado direto: o transporte ASGI do httpx não faz streaming infinito) só leva a lista branca."""
    from backend.app.core.auth import StreamOpener
    from backend.tests.custom.twin.test_twin_core import SECRET, FakeClient, FakeManager

    p = await printer_factory(model="A1")
    client = FakeClient()
    hub = hubmod.TwinHub(p.id, manager=FakeManager(client), record=False)
    hubmod._hubs[p.id] = hub
    resp = await twin_router.twin_events(p.id, StreamOpener(auth_on=False))
    assert resp.media_type == "text/event-stream"
    it = resp.body_iterator
    first = await it.__anext__()
    assert first.startswith(b"retry:")
    data = (await it.__anext__()).decode()
    assert data.startswith("data: ")
    msg = json.loads(data[6:])
    assert msg["s"]["gcode_state"] == "RUNNING" and msg["conn"]["mqtt"] is True
    for leak in (SECRET, "rtsp", "ipcam", client.serial_number):
        assert leak not in data
    assert len(hub.clients) == 1
    await it.aclose()
    assert len(hub.clients) == 0
    client.assert_never_published()

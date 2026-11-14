"""Testes do Web Push do fork (backend/app/custom/webpush)."""

from __future__ import annotations

import json
import logging
import os
import secrets
import stat
import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import select

from backend.app.custom.webpush import crypto, keys, sender
from backend.app.custom.webpush.models import CustomWebPushSubscription
from backend.app.custom.webpush.provider import build_message, deep_link, notify

_PW = "Aa1!" + secrets.token_urlsafe(12)  # pragma: allowlist secret

# --- RFC 8291, Apêndice A -----------------------------------------------------------
RFC = {
    "plaintext": b"When I grow up, I want to be a watermelon",
    "as_private": "yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw",
    "as_public": "BP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A8",
    "ua_private": "q1dXpw3UpT5VOmu_cf_v6ih07Aems3njxI-JWgLcM94",
    "ua_public": "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4",
    "salt": "DGv6ra1nlYgDCS1FRnbzlw",
    "auth_secret": "BTBZMqHH6r4Tts7J_aSIgg",
    "ecdh_secret": "kyrL1jIIOHEzg3sM2ZWRHDRB62YACZhhSlknJ672kSs",
    "ikm": "S4lYMb_L0FxCeq0WhDx813KgSYqU26kOyzWUdsXYyrg",
    "prk": "09_eUZGrsvxChDCGRCdkLiDXrReGOEVeSCdCcPBSJSc",
    "cek": "oIhVW04MRdy2XN9CiKLxTg",
    "nonce": "4h_95klXJ5E_qnoN",
    "message": (
        "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzA"
        "C8wEqKK6PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN"
    ),
}


def _rfc_keys():
    d = crypto.b64url_decode
    return (
        crypto.private_key_from_bytes(d(RFC["as_private"])),
        crypto.private_key_from_bytes(d(RFC["ua_private"])),
        d(RFC["auth_secret"]),
        d(RFC["salt"]),
    )


class TestRfc8291:
    def test_public_keys_match_vectors(self):
        as_priv, ua_priv, _, _ = _rfc_keys()
        assert crypto.b64url_encode(crypto.public_key_bytes(as_priv.public_key())) == RFC["as_public"]
        assert crypto.b64url_encode(crypto.public_key_bytes(ua_priv.public_key())) == RFC["ua_public"]

    def test_intermediate_values(self):
        as_priv, _, auth, salt = _rfc_keys()
        k = crypto.derive_keys(
            as_private=as_priv, ua_public=crypto.b64url_decode(RFC["ua_public"]), auth_secret=auth, salt=salt
        )
        for name in ("ecdh_secret", "ikm", "prk", "cek", "nonce"):
            assert crypto.b64url_encode(getattr(k, name)) == RFC[name], name

    def test_encrypted_message_matches_vector(self):
        as_priv, _, auth, salt = _rfc_keys()
        body = crypto.encrypt(
            RFC["plaintext"],
            ua_public=crypto.b64url_decode(RFC["ua_public"]),
            auth_secret=auth,
            as_private=as_priv,
            salt=salt,
        )
        assert crypto.b64url_encode(body) == RFC["message"]

    def test_decrypt_vector(self):
        _, ua_priv, auth, _ = _rfc_keys()
        assert (
            crypto.decrypt(crypto.b64url_decode(RFC["message"]), ua_private=ua_priv, auth_secret=auth)
            == RFC["plaintext"]
        )

    def test_random_salt_and_key_roundtrip(self):
        ua = ec.generate_private_key(ec.SECP256R1())
        auth = os.urandom(16)
        pub = crypto.public_key_bytes(ua.public_key())
        a = crypto.encrypt(b"oi", ua_public=pub, auth_secret=auth)
        b = crypto.encrypt(b"oi", ua_public=pub, auth_secret=auth)
        assert a[:16] != b[:16]  # salt novo
        assert a[21:86] != b[21:86]  # chave efêmera nova
        assert crypto.decrypt(a, ua_private=ua, auth_secret=auth) == b"oi"

    @pytest.mark.parametrize(
        ("ua_public", "auth"),
        [(b"\x04" + b"\x00" * 10, b"a" * 16), (b"\x02" + b"\x00" * 64, b"a" * 16)],
        ids=["curta", "comprimida"],
    )
    def test_rejects_bad_subscription_keys(self, ua_public, auth):
        with pytest.raises(ValueError):
            crypto.encrypt(b"x", ua_public=ua_public, auth_secret=auth)

    def test_rejects_bad_auth_and_oversized(self):
        pub = crypto.b64url_decode(RFC["ua_public"])
        with pytest.raises(ValueError):
            crypto.encrypt(b"x", ua_public=pub, auth_secret=b"short")
        with pytest.raises(ValueError):
            crypto.encrypt(b"x" * 5000, ua_public=pub, auth_secret=os.urandom(16))


class TestVapid:
    def test_jwt_shape_and_expiry(self):
        priv = ec.generate_private_key(ec.SECP256R1())
        now = time.time()
        token = crypto.vapid_jwt(priv, audience="https://fcm.googleapis.com", subject="mailto:a@b.invalid", now=now)
        header = jwt.get_unverified_header(token)
        assert header == {"alg": "ES256", "typ": "JWT"}
        claims = jwt.decode(token, priv.public_key(), algorithms=["ES256"], audience="https://fcm.googleapis.com")
        assert claims["sub"] == "mailto:a@b.invalid"
        assert 0 < claims["exp"] - int(now) <= 24 * 3600
        # assinatura JWS crua (r||s, 64 bytes), não DER
        assert len(crypto.b64url_decode(token.split(".")[2])) == 64

    def test_authorization_header(self):
        priv = ec.generate_private_key(ec.SECP256R1())
        value = crypto.vapid_authorization(
            priv, endpoint="https://fcm.googleapis.com/fcm/send/abc:def?x=1", subject="mailto:a@b.invalid"
        )
        assert value.startswith("vapid t=")
        t_part, k_part = value[len("vapid ") :].split(", ")
        token = t_part[2:]
        assert k_part == "k=" + crypto.b64url_encode(crypto.public_key_bytes(priv.public_key()))
        claims = jwt.decode(token, priv.public_key(), algorithms=["ES256"], audience="https://fcm.googleapis.com")
        assert claims["aud"] == "https://fcm.googleapis.com"

    def test_expired_token_is_rejected_by_verifier(self):
        priv = ec.generate_private_key(ec.SECP256R1())
        token = crypto.vapid_jwt(priv, audience="https://x.push.apple.com", subject="mailto:a@b.invalid", now=0)
        with pytest.raises(jwt.ExpiredSignatureError):
            jwt.decode(token, priv.public_key(), algorithms=["ES256"], audience="https://x.push.apple.com")


@pytest.fixture
def vapid_file(tmp_path, monkeypatch):
    path = tmp_path / "custom" / "webpush" / "vapid.json"
    monkeypatch.setenv("BAMBUDDY_CUSTOM_WEBPUSH_KEY_FILE", str(path))
    keys.reset_cache()
    yield path
    keys.reset_cache()


class TestKeys:
    def test_generated_once_mode_600(self, vapid_file):
        k1 = keys.get_vapid_keys()
        assert vapid_file.exists()
        assert stat.S_IMODE(vapid_file.stat().st_mode) == 0o600
        keys.reset_cache()
        k2 = keys.get_vapid_keys()
        assert k1.public_key_b64 == k2.public_key_b64
        assert len(crypto.b64url_decode(k1.public_key_b64)) == 65

    def test_repr_hides_private(self, vapid_file):
        k = keys.get_vapid_keys()
        priv = json.loads(vapid_file.read_text())["private_key"]
        assert priv not in repr(k)
        assert priv not in str(k)


class TestEndpointValidation:
    @pytest.mark.parametrize(
        "endpoint",
        [
            "https://fcm.googleapis.com/fcm/send/abc",
            "https://updates.push.services.mozilla.com/wpush/v2/x",
            "https://web.push.apple.com/abc",
            "https://wns2-par02p.notify.windows.com/w/?token=x",
        ],
    )
    def test_known_services_ok(self, endpoint, monkeypatch):
        monkeypatch.delenv("BAMBUDDY_CUSTOM_WEBPUSH_ALLOW_ANY_ENDPOINT", raising=False)
        assert sender.validate_endpoint(endpoint) is None

    @pytest.mark.parametrize(
        "endpoint",
        [
            "http://fcm.googleapis.com/fcm/send/abc",
            "https://192.168.1.10/push",
            "https://evilfcm.googleapis.com.attacker.net/x",
            "https://localhost/x",
            "file:///etc/passwd",
        ],
    )
    def test_rejects_others(self, endpoint, monkeypatch):
        monkeypatch.delenv("BAMBUDDY_CUSTOM_WEBPUSH_ALLOW_ANY_ENDPOINT", raising=False)
        assert sender.validate_endpoint(endpoint) is not None


class TestDeepLinks:
    @pytest.mark.parametrize(
        ("event", "variables", "expected"),
        [
            ("print_complete", {"archive_id": "12"}, "/archives/12"),
            ("print_failed", {"archive_id": 7}, "/archives/7"),
            ("print_start", {"archive_id": "3"}, "/"),
            ("print_confirm_request", {"archive_id": 9}, "/archives/9"),
            ("queue_job_waiting", {}, "/queue"),
            ("filament_low", {}, "/inventory"),
            ("maintenance_due", {}, "/maintenance"),
            ("printer_error", {}, "/"),
            ("plate_clear_required", {}, "/"),
            ("test", {}, "/settings?tab=notifications"),
        ],
    )
    def test_deep_link(self, event, variables, expected):
        assert deep_link(event, variables, 1) == expected

    def test_urgency_and_tag(self):
        m = build_message("t", "b", event_type="print_failed", variables={}, printer_id=2)
        assert (m.urgency, m.require_interaction, m.tag) == ("high", True, "bambuddy-print_failed-2")
        m = build_message("t", "b", event_type="print_progress", variables={}, printer_id=None)
        assert (m.urgency, m.require_interaction, m.tag) == ("low", False, "bambuddy-print_progress-all")

    def test_payload_truncated_to_record(self):
        raw = sender.PushMessage(title="t", body="é" * 5000).payload()
        assert len(raw) <= crypto.MAX_PLAINTEXT
        assert json.loads(raw)["body"].endswith("…")


# --- Mock de serviço de push ----------------------------------------------------------


class MockPushService:
    """Recebe os POSTs do sender; decifra com a chave do "navegador"."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.status_for: dict[str, int] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status_for.get(str(request.url), 201))


class FakeBrowser:
    def __init__(self, name: str):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.auth = os.urandom(16)
        self.endpoint = f"https://fcm.googleapis.com/fcm/send/{name}-{secrets.token_hex(4)}"

    def subscription_json(self) -> dict:
        return {
            "endpoint": self.endpoint,
            "keys": {
                "p256dh": crypto.b64url_encode(crypto.public_key_bytes(self.key.public_key())),
                "auth": crypto.b64url_encode(self.auth),
            },
        }

    def decrypt(self, request: httpx.Request) -> dict:
        return json.loads(crypto.decrypt(request.content, ua_private=self.key, auth_secret=self.auth))


@pytest.fixture
def push_service(vapid_file):
    mock = MockPushService()
    client = httpx.AsyncClient(transport=httpx.MockTransport(mock.handler))
    sender.set_client(client)
    yield mock
    sender.set_client(None)


async def _admin(client) -> dict:
    await client.post(
        "/api/v1/auth/setup", json={"auth_enabled": True, "admin_username": "wpadmin", "admin_password": _PW}
    )
    login = await client.post("/api/v1/auth/login", json={"username": "wpadmin", "password": _PW})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


API = "/api/v1/custom/webpush"


class TestApi:
    async def test_public_key_and_no_private_leak(self, async_client, vapid_file, caplog):
        caplog.set_level(logging.DEBUG)
        r = await async_client.get(f"{API}/public-key")
        assert r.status_code == 200
        pub = r.json()["public_key"]
        stored = json.loads(vapid_file.read_text())
        assert pub == stored["public_key"]
        assert stored["private_key"] not in r.text
        assert stored["private_key"] not in caplog.text

    async def test_subscribe_list_unsubscribe_auth_disabled(self, async_client, db_session, push_service):
        b = FakeBrowser("a")
        r = await async_client.post(f"{API}/subscribe", json=b.subscription_json())
        assert r.status_code == 200, r.text
        assert r.json()["created"] is True
        # renovar não duplica
        r = await async_client.post(f"{API}/subscribe", json=b.subscription_json())
        assert r.json()["created"] is False
        r = await async_client.get(f"{API}/devices", params={"endpoint": b.endpoint})
        devices = r.json()
        assert len(devices) == 1 and devices[0]["this_device"] is True
        assert devices[0]["service"] == "fcm.googleapis.com"
        # nada de segredo da inscrição na listagem
        sub = b.subscription_json()
        for secret in (sub["endpoint"], sub["keys"]["p256dh"], sub["keys"]["auth"]):
            assert secret not in r.text
        r = await async_client.request("DELETE", f"{API}/subscribe", json={"endpoint": b.endpoint})
        assert r.json() == {"deleted": 1}
        assert (await async_client.get(f"{API}/devices")).json() == []

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda s: s.update(endpoint="https://10.0.0.5/push"),
            lambda s: s.update(endpoint="http://fcm.googleapis.com/x"),
            lambda s: s["keys"].update(auth=crypto.b64url_encode(b"x" * 10 + b"y" * 10)),
            lambda s: s["keys"].update(p256dh="A" * 90),
        ],
    )
    async def test_subscribe_rejects_invalid(self, async_client, vapid_file, mutate, monkeypatch):
        monkeypatch.delenv("BAMBUDDY_CUSTOM_WEBPUSH_ALLOW_ANY_ENDPOINT", raising=False)
        payload = FakeBrowser("bad").subscription_json()
        mutate(payload)
        r = await async_client.post(f"{API}/subscribe", json=payload)
        assert r.status_code in (400, 422), r.text

    async def test_auth_required_and_scoped_per_user(self, async_client, db_session, push_service):
        admin = await _admin(async_client)
        b = FakeBrowser("adm")
        for path, method in (("/public-key", "GET"), ("/subscribe", "POST"), ("/devices", "GET"), ("/test", "POST")):
            r = await async_client.request(method, f"{API}{path}", json=b.subscription_json())
            assert r.status_code == 401, (path, r.status_code)
        r = await async_client.post(f"{API}/subscribe", json=b.subscription_json(), headers=admin)
        assert r.status_code == 200, r.text
        row = (await db_session.execute(select(CustomWebPushSubscription))).scalar_one()
        assert row.user_id is not None

        # outro usuário não vê nem apaga a inscrição do admin
        grp = await async_client.post("/api/v1/groups/", headers=admin, json={"name": "wp_g", "permissions": []})
        await async_client.post(
            "/api/v1/users/",
            headers=admin,
            json={"username": "wpuser", "password": _PW, "role": "user", "group_ids": [grp.json()["id"]]},
        )
        login = await async_client.post("/api/v1/auth/login", json={"username": "wpuser", "password": _PW})
        user = {"Authorization": f"Bearer {login.json()['access_token']}"}
        assert (await async_client.get(f"{API}/devices", headers=user)).json() == []
        r = await async_client.request("DELETE", f"{API}/subscribe", json={"endpoint": b.endpoint}, headers=user)
        assert r.json() == {"deleted": 0}
        assert (await async_client.post(f"{API}/test", headers=user)).status_code == 404

        r = await async_client.post(f"{API}/test", headers=admin, json={})
        assert r.status_code == 200, r.text
        assert r.json()["sent"] == 1
        payload = b.decrypt(push_service.requests[-1])
        assert payload["url"] == "/settings?tab=notifications"

    async def test_test_endpoint_sends_encrypted_with_vapid(self, async_client, db_session, push_service, vapid_file):
        b = FakeBrowser("t")
        await async_client.post(f"{API}/subscribe", json=b.subscription_json())
        r = await async_client.post(f"{API}/test", json={"endpoint": b.endpoint})
        assert r.status_code == 200 and r.json()["sent"] == 1
        req = push_service.requests[-1]
        assert str(req.url) == b.endpoint
        assert req.headers["content-encoding"] == "aes128gcm"
        assert int(req.headers["ttl"]) > 0
        assert req.headers["urgency"] == "low"
        auth = req.headers["authorization"]
        token = auth.split("t=")[1].split(",")[0]
        pub = crypto.public_key_from_bytes(crypto.b64url_decode(json.loads(vapid_file.read_text())["public_key"]))
        claims = jwt.decode(token, pub, algorithms=["ES256"], audience="https://fcm.googleapis.com")
        assert claims["exp"] > time.time()
        payload = b.decrypt(req)
        assert payload["title"] and payload["icon"].startswith("/img/")
        assert payload["badge"] == "/custom/webpush-badge.png"
        assert payload["tag"] == "bambuddy-test-all"

    async def test_410_and_404_remove_subscription_500_keeps(self, async_client, db_session, push_service):
        gone, missing, broken, ok = (FakeBrowser(n) for n in ("gone", "missing", "broken", "ok"))
        for b in (gone, missing, broken, ok):
            await async_client.post(f"{API}/subscribe", json=b.subscription_json())
        push_service.status_for = {gone.endpoint: 410, missing.endpoint: 404, broken.endpoint: 500}
        result = await notify(None, "Oi", "corpo", url="/queue", tag="x", db=db_session)
        assert (result.sent, result.failed, result.removed) == (1, 1, 2)
        rows = (await db_session.execute(select(CustomWebPushSubscription))).scalars().all()
        remaining = {r.endpoint: r for r in rows}
        assert set(remaining) == {broken.endpoint, ok.endpoint}
        assert remaining[broken.endpoint].last_error.startswith("HTTP 500")
        assert remaining[ok.endpoint].last_success_at is not None
        assert ok.decrypt(push_service.requests[-1])["url"] == "/queue"


class TestProviderDispatch:
    async def _provider(self, db, **fields):
        from backend.app.models.notification import NotificationProvider

        p = NotificationProvider(
            name="Celular",
            provider_type="webpush",
            enabled=True,
            config="{}",
            attach_photo=False,
            on_printer_offline=True,
            **fields,
        )
        db.add(p)
        await db.commit()
        return p

    async def test_create_via_api_and_test_config(self, async_client, db_session, push_service):
        b = FakeBrowser("p")
        await async_client.post(f"{API}/subscribe", json=b.subscription_json())
        r = await async_client.post(
            "/api/v1/notifications/",
            json={"name": "Celular", "provider_type": "webpush", "config": {}, "on_print_complete": True},
        )
        assert r.status_code in (200, 201), r.text
        assert r.json()["provider_type"] == "webpush"
        r = await async_client.post(
            "/api/v1/notifications/test-config", json={"provider_type": "webpush", "config": {}, "attach_photo": False}
        )
        assert r.status_code == 200, r.text
        assert r.json()["success"] is True, r.json()
        assert b.decrypt(push_service.requests[-1])["event"] == "test"

    async def test_event_goes_through_notification_service(self, async_client, db_session, push_service):
        from backend.app.services.notification_service import notification_service

        b = FakeBrowser("ev")
        await async_client.post(f"{API}/subscribe", json=b.subscription_json())
        provider = await self._provider(db_session)
        await notification_service.on_printer_offline(1, "A1", db_session)
        assert len(push_service.requests) == 1
        payload = b.decrypt(push_service.requests[0])
        assert payload["tag"] == "bambuddy-printer_offline-1"
        assert payload["printer_id"] == 1
        assert "A1" in payload["title"] + payload["body"]
        await db_session.refresh(provider)
        assert provider.last_success is not None

    async def test_quiet_hours_respected(self, async_client, db_session, push_service):
        from backend.app.services.notification_service import notification_service

        b = FakeBrowser("q")
        await async_client.post(f"{API}/subscribe", json=b.subscription_json())
        await self._provider(db_session, quiet_hours_enabled=True, quiet_hours_start="00:00", quiet_hours_end="23:59")
        await notification_service.on_printer_offline(1, "A1", db_session)
        assert push_service.requests == []

    async def test_no_devices_reports_error(self, db_session, push_service):
        from backend.app.services.notification_service import notification_service

        provider = await self._provider(db_session)
        ok, msg = await notification_service._send_to_provider(provider, "t", "m", db_session, event_type="x")
        assert ok is False and "Nenhum aparelho" in msg

    async def test_attach_photo_relative_path(self, db_session, push_service, tmp_path, monkeypatch):
        from backend.app.services.notification_service import notification_service

        monkeypatch.setattr("backend.app.utils.notification_photos.notification_photos_dir", lambda: tmp_path)
        b = FakeBrowser("ph")
        db_session.add(
            CustomWebPushSubscription(
                endpoint=b.endpoint, p256dh=b.subscription_json()["keys"]["p256dh"], auth=crypto.b64url_encode(b.auth)
            )
        )
        await db_session.commit()
        provider = await self._provider(db_session)
        provider.attach_photo = True
        ok, _ = await notification_service._send_to_provider(
            provider, "t", "m", db_session, image_data=b"\xff\xd8jpeg", event_type="print_complete", photo_cache={}
        )
        assert ok
        image = b.decrypt(push_service.requests[-1])["image"]
        assert image.startswith("/api/v1/notifications/photos/print_complete_")


async def test_static_mount_no_cache(tmp_path):
    from fastapi import FastAPI

    from backend.app.custom.webpush.routes import NoCacheStaticFiles

    (tmp_path / "sw-push.js").write_text("self.x=1;")
    app = FastAPI()
    app.mount("/custom", NoCacheStaticFiles(directory=tmp_path), name="c")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/custom/sw-push.js")
        assert r.status_code == 200
        assert "javascript" in r.headers["content-type"]
        assert "no-cache" in r.headers["cache-control"]
        assert (await c.get("/custom/nope.js")).status_code == 404


def test_routes_registered_in_app():
    from backend.app.main import app

    paths = {(m, r.path) for r in app.routes for m in (getattr(r, "methods", None) or ())}
    for expected in (
        ("GET", "/api/v1/custom/webpush/public-key"),
        ("POST", "/api/v1/custom/webpush/subscribe"),
        ("DELETE", "/api/v1/custom/webpush/subscribe"),
        ("POST", "/api/v1/custom/webpush/test"),
        ("GET", "/api/v1/custom/webpush/devices"),
    ):
        assert expected in paths

"""Envio de Web Push: payload, cifragem, VAPID, POST no serviço de push e limpeza 404/410."""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .crypto import MAX_PLAINTEXT, b64url_decode, encrypt, vapid_authorization
from .keys import get_vapid_keys
from .models import CustomWebPushSubscription

logger = logging.getLogger(__name__)

ICON = "/img/android-chrome-192x192.png"
BADGE = "/custom/webpush-badge.png"
DEFAULT_TTL = 24 * 3600

# Serviços de push conhecidos (Chrome/Edge/Android = FCM, Firefox = Mozilla, Safari = Apple,
# Windows = WNS). O servidor faz POST no endpoint que o navegador entregou; restringir o
# host impede que alguém use o Bambuddy para mandar requisições à rede interna.
ALLOWED_PUSH_HOST_SUFFIXES = (
    "fcm.googleapis.com",
    "android.googleapis.com",
    "push.services.mozilla.com",
    "push.apple.com",
    "notify.windows.com",
)


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def validate_endpoint(endpoint: str) -> str | None:
    """Mensagem de erro, ou None se o endpoint for aceitável."""
    try:
        parts = urlsplit(endpoint)
    except ValueError:
        return "endpoint inválido"
    host = (parts.hostname or "").lower()
    if not host:
        return "endpoint inválido"
    # Só para o teste ponta a ponta local (mock de serviço de push).
    if _env_flag("BAMBUDDY_CUSTOM_WEBPUSH_ALLOW_ANY_ENDPOINT"):
        return None if parts.scheme in {"http", "https"} else "endpoint inválido"
    if parts.scheme != "https":
        return "o endpoint precisa ser https"
    if not any(host == s or host.endswith("." + s) for s in ALLOWED_PUSH_HOST_SUFFIXES):
        return "serviço de push desconhecido"
    return None


def vapid_subject() -> str:
    subject = os.environ.get("BAMBUDDY_CUSTOM_WEBPUSH_SUBJECT", "").strip()
    if subject.startswith(("mailto:", "https://")):
        return subject
    # Genérico de propósito (vai no JWT para o serviço de push). Sintaticamente válido,
    # que é o que a Apple confere; FCM/Mozilla aceitam qualquer um.
    return "mailto:webpush@bambuddy.invalid"


@dataclass
class PushMessage:
    title: str
    body: str = ""
    url: str = "/"
    tag: str | None = None
    image: str | None = None
    event_type: str | None = None
    printer_id: int | None = None
    urgency: str = "normal"  # very-low | low | normal | high (RFC 8030)
    require_interaction: bool = False
    ttl: int = DEFAULT_TTL

    def payload(self) -> bytes:
        data: dict = {
            "title": self.title[:200],
            "body": self.body,
            "icon": ICON,
            "badge": BADGE,
            "url": self.url or "/",
            "timestamp": int(time.time() * 1000),
        }
        if self.tag:
            data["tag"] = self.tag[:120]
            data["renotify"] = True
        if self.image:
            data["image"] = self.image
        if self.event_type:
            data["event"] = self.event_type
        if self.printer_id is not None:
            data["printer_id"] = self.printer_id
        if self.require_interaction:
            data["requireInteraction"] = True
        raw = json.dumps(data, ensure_ascii=False).encode()
        # Corta o corpo até caber num registro (os serviços limitam a ~4 KiB).
        while len(raw) > MAX_PLAINTEXT and data["body"]:
            excess = len(raw) - MAX_PLAINTEXT
            data["body"] = data["body"][: max(0, len(data["body"]) - excess - 4)] + "…"
            raw = json.dumps(data, ensure_ascii=False).encode()
        return raw


@dataclass
class SendResult:
    sent: int = 0
    failed: int = 0
    removed: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.sent + self.failed + self.removed


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=10.0), follow_redirects=False)
    return _client


def set_client(client: httpx.AsyncClient | None) -> None:
    """Para testes (transporte mock)."""
    global _client
    _client = client


async def _post_one(sub: CustomWebPushSubscription, payload: bytes, msg: PushMessage) -> tuple[int | None, str]:
    keys = get_vapid_keys()
    body = encrypt(payload, ua_public=b64url_decode(sub.p256dh), auth_secret=b64url_decode(sub.auth))
    headers = {
        "Authorization": vapid_authorization(keys.private_key, endpoint=sub.endpoint, subject=vapid_subject()),
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
        "TTL": str(msg.ttl),
        "Urgency": msg.urgency,
    }
    try:
        resp = await _get_client().post(sub.endpoint, content=body, headers=headers)
    except httpx.HTTPError as exc:
        return None, f"falha de rede: {type(exc).__name__}"
    if 200 <= resp.status_code < 300:
        return resp.status_code, ""
    # Sem ecoar o corpo inteiro (pode citar cabeçalhos); só o status e um trecho curto.
    snippet = (resp.text or "")[:120].replace("\n", " ")
    return resp.status_code, f"HTTP {resp.status_code} {snippet}".strip()


async def send_to_subscriptions(
    db: AsyncSession, subs: Iterable[CustomWebPushSubscription], msg: PushMessage
) -> SendResult:
    result = SendResult()
    payload = msg.payload()
    gone: list[int] = []
    for sub in list(subs):
        try:
            status, error = await _post_one(sub, payload, msg)
        except Exception as exc:  # chave corrompida etc.: não derruba os outros aparelhos
            logger.warning("Web Push: falha ao preparar envio para a inscrição %s: %s", sub.id, type(exc).__name__)
            status, error = None, f"erro interno: {type(exc).__name__}"
        if status is not None and 200 <= status < 300:
            result.sent += 1
            sub.last_success_at = _now()
            sub.last_error = None
        elif status in (404, 410):
            # Inscrição expirada/cancelada no serviço de push: some daqui.
            result.removed += 1
            gone.append(sub.id)
        else:
            result.failed += 1
            result.errors.append(error)
            sub.last_error = error[:500]
            sub.last_error_at = _now()
    if gone:
        await db.execute(delete(CustomWebPushSubscription).where(CustomWebPushSubscription.id.in_(gone)))
        logger.info("Web Push: %d inscrição(ões) expirada(s) removida(s)", len(gone))
    await db.commit()
    return result


async def subscriptions_for(
    db: AsyncSession, user_ids: Iterable[int | None] | None = None, endpoint: str | None = None
) -> list[CustomWebPushSubscription]:
    """``user_ids=None`` = todos os aparelhos. ``None`` dentro da lista casa inscrições sem usuário."""
    query = select(CustomWebPushSubscription)
    if user_ids is not None:
        ids = list(user_ids)
        concrete = [i for i in ids if i is not None]
        cond = CustomWebPushSubscription.user_id.in_(concrete) if concrete else None
        if None in ids:
            null_cond = CustomWebPushSubscription.user_id.is_(None)
            cond = null_cond if cond is None else (cond | null_cond)
        if cond is None:
            return []
        query = query.where(cond)
    if endpoint is not None:
        query = query.where(CustomWebPushSubscription.endpoint == endpoint)
    with db.no_autoflush:
        rows = await db.execute(query.order_by(CustomWebPushSubscription.id))
    return list(rows.scalars().all())

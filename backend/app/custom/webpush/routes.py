"""Rotas do Web Push (``/api/v1/custom/webpush/*``) e arquivos estáticos do service worker."""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.auth import is_auth_enabled, require_auth_if_enabled
from backend.app.core.config import settings as app_settings
from backend.app.core.database import get_db
from backend.app.models.user import User

from .crypto import b64url_decode
from .keys import get_vapid_keys
from .models import CustomWebPushSubscription
from .provider import build_message
from .sender import send_to_subscriptions, subscriptions_for, validate_endpoint

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/custom/webpush", tags=["custom-webpush"])


class SubscriptionKeys(BaseModel):
    p256dh: str = Field(..., min_length=80, max_length=128)
    auth: str = Field(..., min_length=16, max_length=64)


class SubscribeRequest(BaseModel):
    endpoint: str = Field(..., min_length=10, max_length=2048)
    keys: SubscriptionKeys


class EndpointRequest(BaseModel):
    endpoint: str | None = Field(default=None, max_length=2048)


class DeviceOut(BaseModel):
    id: int
    service: str
    user_agent: str | None
    created_at: datetime | None
    last_success_at: datetime | None
    last_error: str | None
    this_device: bool = False


async def _owner(db: AsyncSession, user: User | None) -> int | None:
    """Dono da inscrição. Com auth ligada, API key (user=None) não serve: precisa de usuário."""
    if user is not None:
        return user.id
    if await is_auth_enabled(db):
        raise HTTPException(status_code=403, detail="Web Push precisa de uma sessão de usuário")
    return None


def _service_name(endpoint: str) -> str:
    from urllib.parse import urlsplit

    return (urlsplit(endpoint).hostname or "?").lower()


@router.get("/public-key")
async def public_key(_: User | None = Depends(require_auth_if_enabled)):
    return {"public_key": get_vapid_keys().public_key_b64}


@router.post("/subscribe")
async def subscribe(
    data: SubscribeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db, scope="function"),
    user: User | None = Depends(require_auth_if_enabled),
):
    owner = await _owner(db, user)
    error = validate_endpoint(data.endpoint)
    if error:
        raise HTTPException(status_code=400, detail=error)
    try:
        if len(b64url_decode(data.keys.p256dh)) != 65 or len(b64url_decode(data.keys.auth)) != 16:
            raise ValueError
    except ValueError:
        raise HTTPException(status_code=400, detail="chaves da inscrição inválidas") from None
    ua = (request.headers.get("user-agent") or "")[:300] or None

    existing = (
        await db.execute(select(CustomWebPushSubscription).where(CustomWebPushSubscription.endpoint == data.endpoint))
    ).scalar_one_or_none()
    created = existing is None
    if existing is None:
        existing = CustomWebPushSubscription(endpoint=data.endpoint)
        db.add(existing)
    # Mesmo endpoint de novo (renovação, troca de usuário no aparelho): atualiza no lugar.
    existing.user_id = owner
    existing.p256dh = data.keys.p256dh
    existing.auth = data.keys.auth
    existing.user_agent = ua
    existing.last_error = None
    await db.commit()
    logger.info(
        "Web Push: inscrição %s (%s) %s", existing.id, _service_name(data.endpoint), "criada" if created else "renovada"
    )
    return {"id": existing.id, "created": created}


@router.delete("/subscribe")
async def unsubscribe(
    data: EndpointRequest,
    db: AsyncSession = Depends(get_db, scope="function"),
    user: User | None = Depends(require_auth_if_enabled),
):
    owner = await _owner(db, user)
    if not data.endpoint:
        raise HTTPException(status_code=400, detail="endpoint obrigatório")
    query = delete(CustomWebPushSubscription).where(CustomWebPushSubscription.endpoint == data.endpoint)
    if owner is not None:
        query = query.where(CustomWebPushSubscription.user_id == owner)
    result = await db.execute(query)
    await db.commit()
    return {"deleted": result.rowcount or 0}


@router.get("/devices", response_model=list[DeviceOut])
async def devices(
    endpoint: str | None = None,
    db: AsyncSession = Depends(get_db, scope="function"),
    user: User | None = Depends(require_auth_if_enabled),
):
    owner = await _owner(db, user)
    subs = await subscriptions_for(db, [owner])
    return [
        DeviceOut(
            id=s.id,
            service=_service_name(s.endpoint),
            user_agent=s.user_agent,
            created_at=s.created_at,
            last_success_at=s.last_success_at,
            last_error=s.last_error,
            this_device=bool(endpoint) and s.endpoint == endpoint,
        )
        for s in subs
    ]


@router.post("/test")
async def send_test(
    data: EndpointRequest | None = None,
    db: AsyncSession = Depends(get_db, scope="function"),
    user: User | None = Depends(require_auth_if_enabled),
):
    """Manda uma notificação de teste para os aparelhos de quem chamou (ou só para ``endpoint``)."""
    owner = await _owner(db, user)
    subs = await subscriptions_for(db, [owner], endpoint=data.endpoint if data else None)
    if not subs:
        raise HTTPException(status_code=404, detail="Nenhum aparelho inscrito")
    msg = build_message(
        "Bambuddy: teste",
        "Se você está vendo isto, as notificações deste aparelho funcionam.",
        event_type="test",
        variables={},
        printer_id=None,
    )
    result = await send_to_subscriptions(db, subs, msg)
    return {"sent": result.sent, "failed": result.failed, "removed": result.removed, "errors": result.errors[:5]}


# --- Arquivos estáticos do fork (fora de /api) --------------------------------------


class NoCacheStaticFiles(StaticFiles):
    """``frontend/public/custom/*`` (compilado em ``static/custom``) com revalidação sempre.

    ``no-cache`` importa para o ``sw-push.js``: o ``importScripts`` do service worker usa
    o cache HTTP (``updateViaCache: 'imports'``), então sem isso uma versão velha poderia
    ficar presa. Montado como ``Mount`` (não ``APIRoute``), como /assets e /img do upstream.
    """

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response


def mount_static(app) -> None:
    directory = app_settings.static_dir / "custom"
    if directory.is_dir():
        app.mount("/custom", NoCacheStaticFiles(directory=directory), name="custom-static")

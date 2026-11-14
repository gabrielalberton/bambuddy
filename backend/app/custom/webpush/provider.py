"""Provedor de notificação ``webpush`` ("Web Push (PWA)") ligado ao notification_service do upstream.

O upstream chama :func:`send_for_provider` / :func:`send_test` a partir de um gancho de
2-3 linhas em ``_send_to_provider`` e ``_send_test_notification``. Horário silencioso,
eventos por provedor, modelos de mensagem e resumo diário continuam sendo do upstream:
quando o gancho é alcançado tudo isso já foi decidido.

Config do provedor (JSON, tudo opcional):
- ``usernames``: lista separada por vírgula; vazio = todos os aparelhos inscritos.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .sender import PushMessage, SendResult, send_to_subscriptions, subscriptions_for

logger = logging.getLogger(__name__)

PROVIDER_TYPE = "webpush"

# Eventos que pedem atenção: urgência alta (o Android acorda o aparelho em Doze) e a
# notificação fica até ser tocada.
_URGENT_EVENTS = {
    "print_failed",
    "print_stopped",
    "printer_error",
    "ai_failure_detection",
    "plate_not_empty",
    "plate_clear_required",
    "print_confirm_request",
    "queue_job_waiting",
    "queue_job_failed",
    "billing_charge_failed",
    "print_missing_spool_assignment",
}
_QUIET_EVENTS = {"print_progress", "bed_cooled", "first_layer_complete", "daily_digest", "test"}


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def deep_link(event_type: str | None, variables: dict | None, printer_id: int | None) -> str:
    """Página do Bambuddy aberta ao tocar na notificação (sempre caminho relativo, mesma origem)."""
    v = variables or {}
    ev = event_type or ""
    archive_id = _int(v.get("archive_id"))
    if ev == "print_confirm_request" and archive_id is not None:
        return f"/archives/{archive_id}"
    if ev.startswith("queue_"):
        return "/queue"
    if ev in {"filament_low", "stock_reorder_alert", "stock_break_alert"}:
        return "/inventory"
    if ev == "maintenance_due":
        return "/maintenance"
    if ev.startswith("print_") and archive_id is not None and ev in {"print_complete", "print_failed", "print_stopped"}:
        return f"/archives/{archive_id}"
    if ev in {"daily_digest", "app_message"}:
        return "/notifications"
    if ev == "test":
        return "/settings?tab=notifications"
    return "/"


def build_message(
    title: str,
    message: str,
    *,
    event_type: str | None,
    variables: dict | None,
    printer_id: int | None,
    image: str | None = None,
) -> PushMessage:
    ev = event_type or "event"
    urgent = ev in _URGENT_EVENTS
    return PushMessage(
        title=title or "Bambuddy",
        body=message or "",
        url=deep_link(event_type, variables, printer_id),
        # Um por impressora+evento: o "progresso 50%" substitui o "25%", em vez de empilhar.
        tag=f"bambuddy-{ev}-{printer_id if printer_id is not None else 'all'}",
        image=image,
        event_type=event_type,
        printer_id=printer_id,
        urgency="high" if urgent else ("low" if ev in _QUIET_EVENTS else "normal"),
        require_interaction=urgent,
    )


async def _target_user_ids(db: AsyncSession, config: dict | None) -> list[int | None] | None:
    raw = (config or {}).get("usernames")
    if isinstance(raw, list):
        names = [str(n).strip() for n in raw if str(n).strip()]
    else:
        names = [n.strip() for n in str(raw or "").split(",") if n.strip()]
    if not names:
        return None  # todos os aparelhos
    from backend.app.models.user import User

    rows = await db.execute(select(User.id).where(User.username.in_(names)))
    return list(rows.scalars().all())


async def _photo_path(image_data: bytes | None, event_type: str | None, photo_cache: dict | None) -> str | None:
    """Foto da câmera como URL relativa (a mesma origem do aparelho que abriu o PWA).

    Usa o mesmo armazenamento das fotos de HA/Bark/Slack (nome não adivinhável = credencial,
    expira sozinho), mas não depende do ``external_url``: o service worker resolve o caminho
    contra a origem em que o PWA foi instalado.
    """
    if not image_data:
        return None
    if photo_cache is not None and "custom_webpush_path" in photo_cache:
        return photo_cache["custom_webpush_path"]
    from backend.app.utils.notification_photos import save_notification_photo

    try:
        filename = await asyncio.to_thread(save_notification_photo, image_data, event_type or "event")
    except Exception as exc:
        logger.warning("Web Push: não consegui salvar a foto da notificação: %s", type(exc).__name__)
        return None
    path = f"/api/v1/notifications/photos/{filename}"
    if photo_cache is not None:
        photo_cache["custom_webpush_path"] = path
    return path


def _summarize(result: SendResult, total_subs: int) -> tuple[bool, str]:
    if total_subs == 0:
        return False, "Nenhum aparelho inscrito (ative em Configurações → Notificações → Neste aparelho)"
    if result.sent > 0:
        extra = []
        if result.failed:
            extra.append(f"{result.failed} falharam")
        if result.removed:
            extra.append(f"{result.removed} expiradas removidas")
        suffix = f" ({', '.join(extra)})" if extra else ""
        return True, f"Enviada para {result.sent} aparelho(s){suffix}"
    if result.removed and not result.failed:
        return False, f"Todas as {result.removed} inscrição(ões) tinham expirado e foram removidas"
    return False, "; ".join(sorted(set(result.errors)))[:300] or "Falha no envio"


async def send_for_provider(
    provider: Any,
    title: str,
    message: str,
    db: AsyncSession | None,
    image_data: bytes | None = None,
    event_type: str | None = None,
    variables: dict | None = None,
    printer_id: int | None = None,
    photo_cache: dict | None = None,
) -> tuple[bool, str]:
    """Gancho do ``NotificationService._send_to_provider`` (evento real ou resumo diário)."""
    from . import enabled

    if not enabled():
        return False, "Web Push desligado (BAMBUDDY_CUSTOM_WEBPUSH=0)"
    if db is None:
        return False, "sem sessão de banco"
    config = json.loads(provider.config) if isinstance(provider.config, str) else (provider.config or {})
    image = await _photo_path(image_data, event_type, photo_cache) if provider.attach_photo else None
    msg = build_message(title, message, event_type=event_type, variables=variables, printer_id=printer_id, image=image)
    try:
        subs = await subscriptions_for(db, await _target_user_ids(db, config))
        result = await send_to_subscriptions(db, subs, msg)
    except Exception as exc:
        logger.exception("Web Push: erro ao enviar")
        return False, f"erro interno: {type(exc).__name__}"
    return _summarize(result, len(subs))


async def send_test(
    config: dict | None, title: str, message: str, db: AsyncSession | None, image_data: bytes | None = None
) -> tuple[bool, str]:
    """Gancho do ``NotificationService._send_test_notification`` (botão "Testar" do provedor)."""
    from . import enabled

    if not enabled():
        return False, "Web Push desligado (BAMBUDDY_CUSTOM_WEBPUSH=0)"
    if db is None:
        return False, "sem sessão de banco"
    image = await _photo_path(image_data, "test", None)
    msg = build_message(title, message, event_type="test", variables={}, printer_id=None, image=image)
    try:
        subs = await subscriptions_for(db, await _target_user_ids(db, config))
        result = await send_to_subscriptions(db, subs, msg)
    except Exception as exc:
        logger.exception("Web Push: erro ao enviar o teste")
        return False, f"erro interno: {type(exc).__name__}"
    return _summarize(result, len(subs))


async def notify(
    user_ids: list[int | None] | None,
    title: str,
    body: str = "",
    url: str = "/",
    tag: str | None = None,
    *,
    urgent: bool = False,
    db: AsyncSession | None = None,
) -> SendResult:
    """Atalho para outras personalizações do fork (catálogo de modelos, gêmeo digital...).

    Manda direto para os aparelhos (``user_ids=None`` = todos), sem passar pelos
    provedores/horário silencioso do upstream. Para respeitar as regras de evento do
    usuário, prefira disparar um evento do ``notification_service``.
    """
    from . import enabled

    if not enabled():
        return SendResult()
    msg = PushMessage(
        title=title,
        body=body,
        url=url if url.startswith("/") else "/",
        tag=tag,
        urgency="high" if urgent else "normal",
        require_interaction=urgent,
    )
    if db is not None:
        return await send_to_subscriptions(db, await subscriptions_for(db, user_ids), msg)
    from backend.app.core.database import async_session

    async with async_session() as session:
        return await send_to_subscriptions(session, await subscriptions_for(session, user_ids), msg)

"""Web Push (notificações nativas do PWA) do fork. Ver ``custom/docs/notificacoes-pwa.md``.

Interruptor: ``BAMBUDDY_CUSTOM_WEBPUSH=0`` desliga rotas e provedor (padrão: ligado).

Para outras personalizações: ``from backend.app.custom.webpush import notify``.
"""

from __future__ import annotations

import os

from fastapi import FastAPI

from .provider import PROVIDER_TYPE, notify, send_for_provider, send_test

__all__ = ["PROVIDER_TYPE", "enabled", "notify", "register", "send_for_provider", "send_test"]


def enabled() -> bool:
    return os.environ.get("BAMBUDDY_CUSTOM_WEBPUSH", "1").strip().lower() not in {"0", "false", "no", "off"}


def register(app: FastAPI, api_prefix: str) -> None:
    # O modelo é importado sempre (a tabela existe mesmo desligado: ligar de novo não perde nada).
    from . import models  # noqa: F401

    if not enabled():
        return
    from .routes import mount_static, router

    app.include_router(router, prefix=api_prefix)
    mount_static(app)

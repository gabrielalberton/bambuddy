"""Tabela própria do fork (prefixo ``custom_``): inscrições Web Push por aparelho.

Criada pelo ``Base.metadata.create_all`` do upstream (``init_db``), porque este módulo é
importado pelo ``install()`` de ``backend/app/custom/api.py`` (entrada ``backend.app.custom.asgi``), antes do lifespan. Nada de migração
nem coluna em tabela do upstream.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.core.database import Base


class CustomWebPushSubscription(Base):
    __tablename__ = "custom_webpush_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # NULL quando a autenticação do Bambuddy está desligada (todo aparelho é "do dono").
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # O endpoint é uma URL de capacidade do serviço de push: nunca volta inteira na API.
    endpoint: Mapped[str] = mapped_column(String(2048), nullable=False, unique=True)
    p256dh: Mapped[str] = mapped_column(String(128), nullable=False)
    auth: Mapped[str] = mapped_column(String(64), nullable=False)
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

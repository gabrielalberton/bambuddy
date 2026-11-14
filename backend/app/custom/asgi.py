"""Ponto de entrada ASGI da imagem do fork: app do upstream + rotas nossas.

    uvicorn backend.app.custom.asgi:app

Evita tocar em ``backend/app/main.py`` (zero linhas no upstream). O
``custom/Dockerfile`` troca só o módulo no CMD do upstream.
"""

from backend.app.custom.api import install
from backend.app.main import app

install(app)

__all__ = ["app"]

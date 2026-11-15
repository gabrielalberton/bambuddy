"""Registro das rotas do fork na aplicação do upstream, sem editar ``main.py``.

O upstream termina ``main.py`` com uma rota "pega-tudo" do SPA
(``GET /{full_path:path}``). Rotas incluídas depois dela nunca seriam
alcançadas por GET, então as nossas são inseridas logo antes dela.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from starlette.routing import Route

logger = logging.getLogger(__name__)

_INSTALLED_FLAG = "_bambuddy_custom_installed"


def install(app: FastAPI) -> list[str]:
    """Inclui os routers do fork (idempotente). Devolve os paths adicionados."""
    if getattr(app.state, _INSTALLED_FLAG, False):
        return []
    from backend.app.core.config import settings as app_settings

    from .models_catalog.router import catalog_enabled, router as models_router

    before = list(app.router.routes)
    if catalog_enabled():
        app.include_router(models_router, prefix=app_settings.api_prefix)
    else:
        logger.info("Catálogo de modelos do fork desligado (BAMBUDDY_CUSTOM_MODELS_CATALOG)")
    from .webpush import register as register_webpush

    register_webpush(app, app_settings.api_prefix)
    # Prévia instantânea da câmera (custom/docs/camera-previa.md)
    from .camera_preview import add_public_prefix, router as camera_preview_router

    app.include_router(camera_preview_router, prefix=app_settings.api_prefix)
    add_public_prefix(app_settings.api_prefix)
    from .draco_worker_csp import allow_draco_worker

    allow_draco_worker()
    added = [r for r in app.router.routes if r not in before]
    if added:
        remaining = [r for r in app.router.routes if r not in added]
        catch_all = _spa_catch_all_index(remaining)
        app.router.routes[:] = remaining[:catch_all] + added + remaining[catch_all:]
    # Gêmeo digital da A1 (custom/docs/gemeo-digital.md): include_twin também insere antes do pega-tudo do SPA.
    from .twin.router import include_twin

    twin_paths = include_twin(app)
    setattr(app.state, _INSTALLED_FLAG, True)
    return [getattr(r, "path", "") for r in added] + twin_paths


def _spa_catch_all_index(routes: list) -> int:
    for index, route in enumerate(routes):
        if isinstance(route, Route) and route.path == "/{full_path:path}":
            return index
    return len(routes)

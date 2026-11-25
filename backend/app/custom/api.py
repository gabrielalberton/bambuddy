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
    # Vídeo ao vivo em H.264 via go2rtc (custom/docs/camera-h264.md); WebSocket não passa pelos middlewares HTTP
    from .camera_h264 import router as camera_h264_router

    app.include_router(camera_h264_router, prefix=app_settings.api_prefix)
    # Bico e velocidade no card (custom/CUSTOMIZATIONS.md, printer-prefs)
    from .printer_prefs.router import StartApplierMiddleware, router as printer_prefs_router

    app.include_router(printer_prefs_router, prefix=app_settings.api_prefix)
    from .library_org.router import router as library_org_router

    app.include_router(library_org_router, prefix=app_settings.api_prefix)
    from .model_preview.router import router as model_preview_router

    app.include_router(model_preview_router, prefix=app_settings.api_prefix)
    # Área da mesa em quadrilátero: fundo do editor (custom/CUSTOMIZATIONS.md)
    from .plate_roi_router import router as plate_roi_router

    app.include_router(plate_roi_router, prefix=app_settings.api_prefix)
    from .print_history import router as print_history_router

    app.include_router(print_history_router, prefix=app_settings.api_prefix)
    # Plotter de caneta na A1 (custom/docs/plotter.md)
    from .plotter.router import plotter_enabled, router as plotter_router

    if plotter_enabled():
        app.include_router(plotter_router, prefix=app_settings.api_prefix)
    else:
        logger.info("Plotter de caneta do fork desligado (BAMBUDDY_CUSTOM_PLOTTER)")
    from .asset_404 import Asset404NoStoreMiddleware

    if not any(m.cls is Asset404NoStoreMiddleware for m in app.user_middleware):
        try:
            app.add_middleware(Asset404NoStoreMiddleware)
        except RuntimeError:  # app já iniciado (testes)
            pass
    if not any(m.cls is StartApplierMiddleware for m in app.user_middleware):
        try:
            app.add_middleware(StartApplierMiddleware)
        except RuntimeError:  # app já iniciado (testes): o vigia sobe no 1º GET /prefs
            pass
    # Miniaturas com a cor do filamento (custom/CUSTOMIZATIONS.md, thumb-color)
    from .thumb_color import install as install_thumb_color

    install_thumb_color()
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

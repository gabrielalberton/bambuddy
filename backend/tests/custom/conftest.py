"""Os testes do fork usam o ``app`` do upstream com as rotas nossas instaladas
(exatamente o que ``backend.app.custom.asgi`` faz na imagem)."""

import pytest


@pytest.fixture(autouse=True)
def _install_custom_routes():
    from backend.app.custom.api import install
    from backend.app.custom.models_catalog.transport import clear_cache
    from backend.app.main import app

    routes_before = list(app.router.routes)
    install(app)
    clear_cache()
    yield
    clear_cache()
    # Desinstala: as suítes do upstream que rodam no mesmo processo (ex.: test_route_auth_coverage) veem o app puro.
    app.router.routes[:] = routes_before
    for flag in ("_bambuddy_custom_installed", "custom_twin_included"):
        if hasattr(app.state, flag):
            delattr(app.state, flag)

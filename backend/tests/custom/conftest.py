"""Os testes do fork usam o ``app`` do upstream com as rotas nossas instaladas
(exatamente o que ``backend.app.custom.asgi`` faz na imagem)."""

import pytest


@pytest.fixture(autouse=True)
def _install_custom_routes():
    from backend.app.custom.api import install
    from backend.app.custom.models_catalog.transport import clear_cache
    from backend.app.main import app

    install(app)
    clear_cache()
    yield
    clear_cache()

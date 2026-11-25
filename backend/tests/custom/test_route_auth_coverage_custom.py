"""A regra SEC-AUTH-1 do upstream (toda rota com dependência de auth ou na allowlist) vale também para as rotas do
fork. Reaproveita o teste do upstream com ``install()`` aplicado e só as exceções nossas acrescentadas aqui."""

from __future__ import annotations

from backend.tests.unit import test_route_auth_coverage as upstream_check

# Rotas do fork sem dependência de auth, cada uma com o motivo.
CUSTOM_PUBLIC_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        # Proxy de miniatura do catálogo (igual a /makerworld/thumbnail do upstream): <img> não manda cabeçalho;
        # só busca imagens em hosts da allowlist de cada fonte, sem dados do Bambuddy.
        ("GET", "/api/v1/custom/models/{source_id}/thumbnail"),
    }
)


# WebSockets do fork que validam o token DENTRO do endpoint, mas com outra função do upstream (o teste do upstream
# só reconhece chamada a ``verify_websocket_token``). Não são públicos: ``test_ws_com_token_proprio_validam_o_token``
# confere que o endpoint chama a validação antes de aceitar a conexão.
CUSTOM_WS_INLINE_AUTH: dict[tuple[str, str], str] = {
    # vídeo H.264 (go2rtc): mesmo token de stream da câmera do /camera/stream (require_camera_stream_token_if_auth_enabled)
    ("WS", "/api/v1/custom/camera/h264/{printer_id}/ws"): "authorized(",
}


def test_custom_routes_have_explicit_auth_deps(monkeypatch) -> None:
    allowed = upstream_check._PUBLIC_ROUTES | CUSTOM_PUBLIC_ROUTES | frozenset(CUSTOM_WS_INLINE_AUTH)
    monkeypatch.setattr(upstream_check, "_PUBLIC_ROUTES", allowed)
    upstream_check.test_routes_have_explicit_auth_deps()


def test_ws_com_token_proprio_validam_o_token() -> None:
    import inspect

    from fastapi.routing import APIWebSocketRoute

    from backend.app.main import app

    routes = {("WS", r.path): r for r in app.routes if isinstance(r, APIWebSocketRoute)}
    for key, call in CUSTOM_WS_INLINE_AUTH.items():
        source = inspect.getsource(routes[key].endpoint)
        assert call in source and source.index(call) < source.index("websocket.accept("), key


def test_custom_public_routes_exist() -> None:
    from backend.app.main import app

    real = {(m, r.path) for r in app.routes for m in getattr(r, "methods", None) or ()}
    assert CUSTOM_PUBLIC_ROUTES <= real

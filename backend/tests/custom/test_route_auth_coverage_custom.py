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


def test_custom_routes_have_explicit_auth_deps(monkeypatch) -> None:
    monkeypatch.setattr(upstream_check, "_PUBLIC_ROUTES", upstream_check._PUBLIC_ROUTES | CUSTOM_PUBLIC_ROUTES)
    upstream_check.test_routes_have_explicit_auth_deps()


def test_custom_public_routes_exist() -> None:
    from backend.app.main import app

    real = {(m, r.path) for r in app.routes for m in getattr(r, "methods", None) or ()}
    assert CUSTOM_PUBLIC_ROUTES <= real

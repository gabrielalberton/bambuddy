"""Curtidos e salvos do usuário no MakerWorld (fork gabriel).

Usa a credencial Bambu Cloud já salva do usuário (a mesma do import do
MakerWorld) contra ``api.bambulab.com`` (sem o Cloudflare do makerworld.com):

- curtidos: ``GET /v1/design-service/my/design/like``
- salvos (favoritos): ``GET /v1/design-service/favorites/designs/{uid}``,
  com o ``uid`` de ``GET /v1/user-service/my/profile``.

Conferido ao vivo em 2026-11-16 (61 curtidos, 7 salvos). Dado privado: nada
disto passa pelo cache compartilhado do catálogo.
"""

from __future__ import annotations

from typing import Any, Literal

import httpx
from fastapi import HTTPException

from .makerworld import card
from .transport import HEADERS

API = "https://api.bambulab.com/v1"
MineKind = Literal["likes", "saved"]

_SIGNED_OUT = "Entre na Bambu Cloud (Configurações > Nuvem) para ver seus curtidos e salvos do MakerWorld."
_EXPIRED = "A sessão da Bambu Cloud expirou. Entre de novo em Configurações > Nuvem."


async def _get(client: httpx.AsyncClient, token: str, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        response = await client.get(
            url, params=params, headers={**HEADERS, "Authorization": f"Bearer {token}"}, timeout=30
        )
    except httpx.HTTPError as exc:
        raise HTTPException(502, "MakerWorld não respondeu. Tente de novo.") from exc
    # 409 (não 401): um 401 aqui faria o app achar que a sessão do Bambuddy caiu.
    if response.status_code in (401, 403):
        raise HTTPException(409, _EXPIRED)
    if response.status_code != 200:
        raise HTTPException(502, f"MakerWorld respondeu HTTP {response.status_code}")
    try:
        data = response.json()
    except ValueError as exc:
        raise HTTPException(502, "MakerWorld devolveu uma resposta inválida") from exc
    if not isinstance(data, dict):
        raise HTTPException(502, "MakerWorld devolveu uma resposta inválida")
    return data


async def my_designs(
    client: httpx.AsyncClient, token: str | None, kind: MineKind, offset: int, limit: int
) -> dict[str, Any]:
    if not token:
        raise HTTPException(409, _SIGNED_OUT)
    params = {"offset": offset, "limit": limit}
    if kind == "likes":
        envelope = await _get(client, token, f"{API}/design-service/my/design/like", params)
    else:
        profile = await _get(client, token, f"{API}/user-service/my/profile")
        uid = profile.get("uid")
        if not isinstance(uid, int):
            raise HTTPException(502, "Perfil da Bambu Cloud sem identificador")
        envelope = await _get(client, token, f"{API}/design-service/favorites/designs/{uid}", params)
    hits = envelope.get("hits") or []
    if not isinstance(hits, list):
        hits = []
    items = [card(h) for h in hits if isinstance(h, dict) and h.get("id") and not h.get("nsfw")]
    total = envelope.get("total")
    return {
        "items": items,
        "total": total if isinstance(total, int) else None,
        "has_more": offset + len(hits) < total if isinstance(total, int) else len(hits) == limit,
        "author": {"id": kind, "name": None},
    }

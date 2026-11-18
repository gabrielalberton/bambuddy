"""custom(library-org): ver o plano, aplicar e ligar a organização automática."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from backend.app.core.auth import require_permission_if_auth_enabled
from backend.app.core.permissions import Permission

from . import service
from .organizer import load_state, save_state

router = APIRouter(prefix="/custom/library/organize", tags=["custom"])

_need = Depends(require_permission_if_auth_enabled(Permission.LIBRARY_UPDATE_ALL))


@router.get("")
async def plan(_=_need):
    """O que seria movido/renomeado agora (não muda nada)."""
    service.ensure_auto()
    result = await service.run(apply=False)
    result["auto"] = bool(load_state().get("auto"))
    return result


@router.post("")
async def apply(_=_need):
    service.ensure_auto()
    return await service.run(apply=True)


@router.put("/auto")
async def set_auto(enabled: bool = Query(...), _=_need):
    state = load_state()
    state["auto"] = enabled
    save_state(state)
    service.ensure_auto()
    return {"auto": enabled}

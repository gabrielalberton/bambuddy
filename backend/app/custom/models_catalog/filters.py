"""Filtro avançado do catálogo: esquema por fonte + validação dos valores enviados pelo frontend.

Cada fonte publica um esquema (``GET /custom/models/{fonte}/filters``) com grupos de filtros. Tipos:

- ``enum``: um valor da lista (``"cb"``);
- ``multi``: lista de valores da lista (``["0.2", "0.4"]``), a fonte combina com OU;
- ``bool``: só ``true`` (desligado = ausente);
- ``range``: ``[min, max]`` com valores da lista ordenada de ``options`` (``null`` = sem limite);
- ``days``: um valor da lista (dias ou expressão da fonte), igual ao ``enum`` mas mostrado como período.

Só entra no esquema o que foi medido ao vivo mudando o total da busca (custom/docs/fontes-de-modelos.md).
O ``/browse`` recebe ``filters`` (JSON) e rejeita (400) qualquer id/valor fora do esquema da fonte.
"""

from __future__ import annotations

import json
from typing import Any, Literal

FilterType = Literal["enum", "multi", "bool", "range", "days"]
MAX_FILTERS_JSON = 2000


class FilterError(ValueError):
    """Filtro fora do esquema da fonte (vira HTTP 400)."""


def label(pt: str, en: str) -> dict[str, str]:
    return {"pt": pt, "en": en}


def opt(value: str, pt: str, en: str | None = None) -> dict[str, Any]:
    return {"value": value, "label": label(pt, en or pt)}


def fdef(
    fid: str,
    ftype: FilterType,
    pt: str,
    en: str,
    options: list[dict[str, Any]] | None = None,
    *,
    hint: tuple[str, str] | None = None,
    requires_min: bool = False,
) -> dict[str, Any]:
    out: dict[str, Any] = {"id": fid, "type": ftype, "label": label(pt, en), "options": options or []}
    if hint:
        out["hint"] = label(*hint)
    if requires_min:
        out["requires_min"] = True
    return out


def group(gid: str, pt: str, en: str, filters: list[dict[str, Any]]) -> dict[str, Any]:
    return {"id": gid, "label": label(pt, en), "filters": [f for f in filters if f]}


def schema(source: str, groups: list[dict[str, Any]], origin: str) -> dict[str, Any]:
    return {"source": source, "origin": origin, "groups": [g for g in groups if g["filters"]]}


def index(schema_: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {f["id"]: f for g in schema_.get("groups", []) for f in g["filters"]}


def parse_filters(raw: str | None) -> dict[str, Any]:
    """Texto JSON do query param → dict (sem validar contra o esquema ainda)."""
    if not raw:
        return {}
    if len(raw) > MAX_FILTERS_JSON:
        raise FilterError("filters too long")
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise FilterError("filters must be a JSON object") from exc
    if not isinstance(data, dict):
        raise FilterError("filters must be a JSON object")
    return data


def validate(schema_: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    """Normaliza (descarta vazios, ordena listas) e rejeita id/valor fora do esquema."""
    defs = index(schema_)
    out: dict[str, Any] = {}
    for fid, value in raw.items():
        spec = defs.get(fid)
        if spec is None:
            raise FilterError(f"unknown filter: {str(fid)[:40]}")
        allowed = [o["value"] for o in spec["options"]]
        kind = spec["type"]
        if value is None or value is False or value == "" or value == []:
            continue
        if kind == "bool":
            if value is not True:
                raise FilterError(f"{fid}: expected true")
            out[fid] = True
        elif kind in ("enum", "days"):
            if not isinstance(value, str) or value not in allowed:
                raise FilterError(f"{fid}: invalid value")
            out[fid] = value
        elif kind == "multi":
            if not isinstance(value, list) or not all(isinstance(v, str) and v in allowed for v in value):
                raise FilterError(f"{fid}: invalid values")
            out[fid] = sorted(set(value), key=allowed.index)
        elif kind == "range":
            if not isinstance(value, list) or len(value) != 2:
                raise FilterError(f"{fid}: expected [min, max]")
            lo, hi = value
            for v in (lo, hi):
                if v is not None and (not isinstance(v, str) or v not in allowed):
                    raise FilterError(f"{fid}: invalid bound")
            if lo is None and hi is None:
                continue
            if lo is not None and hi is not None and allowed.index(lo) >= allowed.index(hi):
                raise FilterError(f"{fid}: min must be below max")
            if spec.get("requires_min") and lo is None:
                raise FilterError(f"{fid}: this source needs a start bound")
            out[fid] = [lo, hi]
        else:  # pragma: no cover - esquema mal formado
            raise FilterError(f"{fid}: unsupported type")
    return dict(sorted(out.items()))


def cache_token(filters: dict[str, Any]) -> str:
    """Forma canônica para a chave de cache (mesmos filtros em outra ordem = mesma chave)."""
    return json.dumps(filters, sort_keys=True, separators=(",", ":")) if filters else ""


DAYS_OPTIONS = [
    opt("1", "Últimas 24 h", "Last 24 h"),
    opt("7", "Últimos 7 dias", "Last 7 days"),
    opt("30", "Últimos 30 dias", "Last 30 days"),
    opt("90", "Últimos 90 dias", "Last 90 days"),
    opt("365", "Último ano", "Last year"),
]

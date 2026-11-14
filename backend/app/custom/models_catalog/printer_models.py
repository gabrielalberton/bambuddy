"""Modelo da impressora do usuário -> identificadores usados por cada fonte.

O frontend manda o ``model`` das impressoras cadastradas (``GET /printers/``),
que pode vir como nome ("A1") ou código interno/SSDP ("N2S"). Normalizamos
pelo mapa do próprio upstream (``PRINTER_MODEL_ID_MAP``) e traduzimos:

- MakerWorld: ``devModelName`` aceito pelo parâmetro ``devModelNames`` do
  search-service (conferido ao vivo, ver custom/docs/fontes-de-modelos.md).
- Printables: id do catálogo de impressoras (``{ printers { id name } }``), usado
  pelo argumento ``printerIds`` do ``searchPrints2`` (impressora declarada pelo autor).
"""

from __future__ import annotations

from backend.app.utils.printer_models import PRINTER_MODEL_ID_MAP

# Usado só se o usuário não enxerga nenhuma impressora (fallback pedido pelo Gabriel).
FALLBACK_MODEL = "A1"

# Nome normalizado -> devModelName do MakerWorld (códigos vistos em
# design.instances[].extention.modelInfo.compatibility/otherCompatibility).
MAKERWORLD_DEV_CODES: dict[str, str] = {
    "X1C": "BL-P001",
    "X1": "BL-P002",
    "X1E": "C13",
    "P1P": "C11",
    "P1S": "C12",
    "P2S": "N7",
    "X2D": "N6",
    "A2L": "N9",
    "A1": "N2S",
    "A1 MINI": "N1",
    "H2D": "O1D",
    "H2D PRO": "O1E",
    "H2C": "O1C2",
    "H2S": "O1S",
    "H3C": "N10",
}

# Nome normalizado -> id do Printables (consultado em 2026-11-14).
PRINTABLES_PRINTER_IDS: dict[str, int] = {
    "A1": 711,
    "A1 MINI": 682,
    "H2C": 802,
    "H2D": 784,
    "P1P": 496,
    "P1S": 652,
    "P2S": 793,
    "X1": 336,
    "X1C": 768,
    "X1E": 683,
}

_ALIASES = {"A1MINI": "A1 MINI", "A1-MINI": "A1 MINI", "A1M": "A1 MINI", "X1 CARBON": "X1C", "X1-CARBON": "X1C"}


def normalize_model(raw: str | None) -> str | None:
    """'N2S' / 'A1' / 'Bambu Lab A1' -> 'A1'; 'A1 mini' -> 'A1 MINI'. None se vazio."""
    if not raw or not isinstance(raw, str):
        return None
    value = raw.strip()
    if not value:
        return None
    if value in PRINTER_MODEL_ID_MAP:
        value = PRINTER_MODEL_ID_MAP[value]
    value = value.upper()
    if value.startswith("BAMBU LAB "):
        value = value[len("BAMBU LAB ") :]
    return _ALIASES.get(value, value)


def resolve_models(raw_models: list[str] | None) -> list[str]:
    """Lista normalizada, sem repetição; cai no FALLBACK_MODEL se vazia."""
    out: list[str] = []
    for raw in raw_models or []:
        for part in str(raw).split(","):
            norm = normalize_model(part)
            if norm and norm not in out:
                out.append(norm)
    return out or [FALLBACK_MODEL]


def makerworld_codes(models: list[str]) -> list[str]:
    return [MAKERWORLD_DEV_CODES[m] for m in models if m in MAKERWORLD_DEV_CODES]


def printables_ids(models: list[str]) -> list[int]:
    return [PRINTABLES_PRINTER_IDS[m] for m in models if m in PRINTABLES_PRINTER_IDS]


def display_name(model: str) -> str:
    return "A1 mini" if model == "A1 MINI" else ("H2D Pro" if model == "H2D PRO" else model)

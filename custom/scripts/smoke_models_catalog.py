"""Smoke ao vivo do catálogo de modelos (poucas requisições, anônimas).

Uso (da raiz do repo):
    .venv-custom/bin/python -m custom.scripts.smoke_models_catalog [termo]

Não baixa arquivos nem toca na biblioteca: só lista, busca e detalhe.
"""

from __future__ import annotations

import asyncio
import json
import sys

import httpx

from backend.app.custom.models_catalog.base import BrowseRequest
from backend.app.custom.models_catalog.makerworld import MakerWorldSource
from backend.app.custom.models_catalog.printables import PrintablesSource


async def main(term: str) -> dict:
    out: dict = {}
    mw, pr = MakerWorldSource(), PrintablesSource()
    models = ["A1"]
    async with httpx.AsyncClient(timeout=30) as client:
        for flt in (False, True):
            r = await mw.browse(client, BrowseRequest(sort="trending", limit=12, models=models, printer_filter=flt))
            out[f"makerworld_trending_filter_{flt}"] = {
                "total": r["total"],
                "n": len(r["items"]),
                "pf": r["printer_filter"],
            }
            r = await mw.browse(
                client, BrowseRequest(query=term, sort="relevance", limit=12, models=models, printer_filter=flt)
            )
            out[f"makerworld_search_{term}_filter_{flt}"] = {
                "total": r["total"],
                "first": [i["id"] for i in r["items"][:3]],
            }
            await asyncio.sleep(0.3)
        first_id = out[f"makerworld_search_{term}_filter_True"]["first"][0]
        d = await mw.detail(client, first_id, models)
        out["makerworld_detail"] = {
            "id": first_id,
            "title": d["title"],
            "profiles": len(d["files"]),
            "first_three": [(f["name"][:40], f["printer"], f["printer_match"]) for f in d["files"][:3]],
            "preselect": d["preselect_file_id"],
            "match_counts": {
                m: sum(f["printer_match"] == m for f in d["files"])
                for m in ("native", "compatible", "other", "unknown")
            },
        }
        r = await pr.browse(client, BrowseRequest(sort="popular", limit=12, models=models))
        out["printables_popular"] = {"total": r["total"], "n": len(r["items"]), "pf": r["printer_filter"]}
        for ap in (False, True):
            r = await pr.browse(
                client, BrowseRequest(query=term, sort="relevance", limit=12, models=models, author_printer=ap)
            )
            out[f"printables_search_{term}_author_printer_{ap}"] = {
                "total": r["total"],
                "first": [i["id"] for i in r["items"][:3]],
            }
        pid = out[f"printables_search_{term}_author_printer_False"]["first"][0]
        d = await pr.detail(client, pid, models)
        out["printables_detail"] = {
            "id": pid,
            "title": d["title"],
            "files": [(f["name"][:40], f["format"], f["printer_match"], f["sliceable"]) for f in d["files"][:6]],
            "author_printer": d["metadata"].get("author_printer"),
            "preselect": d["preselect_file_id"],
        }
    return out


if __name__ == "__main__":
    print(json.dumps(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "vase")), indent=1, ensure_ascii=False))

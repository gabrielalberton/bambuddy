"""Prévia 3D do catálogo (GLB com Draco): o decodificador roda num worker que compila WASM.

O CSP do documento do upstream não deixa criar worker de ``blob:`` nem compilar WASM. O upstream resolve isso para os
workers dele (STEP, pdf.js) dando um CSP próprio à resposta do script do worker (CSP3: quem governa um worker dedicado é
o CSP do próprio script). Fazemos o mesmo, só para ``/custom/draco/draco_worker.js``: acrescentamos esse caminho à regex
do worker do pdf.js (``'wasm-unsafe-eval'``, sem eval de JS). Se o upstream renomear a regex, nada muda e a prévia mostra
erro (falha fechada).
"""

from __future__ import annotations

import re

WORKER_PATH = "/custom/draco/draco_worker.js"


def allow_draco_worker() -> None:
    from backend.app import main as upstream_main

    current = getattr(upstream_main, "_PDF_WORKER_ASSET_RE", None)
    if not isinstance(current, re.Pattern) or current.match(WORKER_PATH):
        return
    upstream_main._PDF_WORKER_ASSET_RE = re.compile(f"(?:{current.pattern})|^{re.escape(WORKER_PATH)}$")

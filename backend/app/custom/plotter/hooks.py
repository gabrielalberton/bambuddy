"""Ganchos chamados de dentro do upstream. Sem dependências (nem numpy): não podem falhar nem pesar."""

from __future__ import annotations

# Prefixo do arquivo que o plotter manda para a impressora; o nome do job (subtask) herda o prefixo.
FILE_PREFIX = "penplot_"


def is_plotter_job(data: dict | None) -> bool:
    """True quando o job que está começando é um plot nosso (gancho em ``main.on_print_start``).

    O papel preso na mesa faria a verificação de "mesa vazia" pausar o plot; num plot o papel é o
    próprio trabalho, então a verificação é pulada só para estes arquivos.
    """
    if not isinstance(data, dict):
        return False
    for key in ("subtask_name", "filename", "gcode_file"):
        value = data.get(key)
        if isinstance(value, str) and value.rsplit("/", 1)[-1].startswith(FILE_PREFIX):
            return True
    return False

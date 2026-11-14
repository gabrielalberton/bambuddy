"""Gravação rotativa dos relatórios reais (JSONL) para ajustar a sincronização depois. Nunca grava segredos."""

from __future__ import annotations

import gzip
import json
import pathlib
import shutil
import time


class Recorder:
    def __init__(
        self, directory: pathlib.Path, secrets: tuple[str, ...], max_file_mb: int = 24, max_total_mb: int = 400
    ) -> None:
        self.dir = directory
        self.dir.mkdir(parents=True, exist_ok=True)
        self.secrets = secrets
        self.max_file = max_file_mb * 1024 * 1024
        self.max_total = max_total_mb * 1024 * 1024
        self._fh = None
        self._path: pathlib.Path | None = None
        self.refused = 0

    def _open(self) -> None:
        if self._fh:
            self._fh.close()
        stamp = time.strftime("%Y-%m-%d_%H-%M-%S")
        self._path = self.dir / f"a1-{stamp}.jsonl"
        self._fh = open(self._path, "a", buffering=1, encoding="utf-8")  # noqa: SIM115 (fica aberto entre gravações)
        self._prune()

    def write(self, src: str, payload: dict, t: float | None = None) -> None:
        line = json.dumps(
            {"t": round(t or time.time(), 3), "src": src, "d": payload}, ensure_ascii=False, separators=(",", ":")
        )
        if any(s and s in line for s in self.secrets):
            self.refused += 1  # defesa em profundidade: nunca persistir um segredo
            return
        if self._fh is None or (self._path and self._path.stat().st_size > self.max_file):
            self._open()
        assert self._fh
        self._fh.write(line + "\n")

    def _prune(self) -> None:
        files = sorted(self.dir.glob("a1-*.jsonl*"), key=lambda p: p.stat().st_mtime)
        for p in files[:-1]:
            if p.suffix == ".jsonl" and p != self._path:
                with open(p, "rb") as f, gzip.open(str(p) + ".gz", "wb") as g:
                    shutil.copyfileobj(f, g)
                p.unlink()
        files = sorted(self.dir.glob("a1-*.jsonl*"), key=lambda p: p.stat().st_mtime)
        total = sum(p.stat().st_size for p in files)
        while files and total > self.max_total and files[0] != self._path:
            total -= files[0].stat().st_size
            files.pop(0).unlink()

    def close(self) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None

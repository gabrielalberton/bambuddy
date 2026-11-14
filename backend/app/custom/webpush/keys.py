"""Par de chaves VAPID do servidor: gerado uma vez e guardado no volume de dados.

Arquivo: ``<DATA_DIR>/custom/webpush/vapid.json`` (modo 600; diretório 700). Nunca vai
para o git nem para log. Apagar o arquivo invalida todas as inscrições (os aparelhos se
reinscrevem sozinhos ao abrir o app, porque a chave pública muda).
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ec

from backend.app.core.config import settings

from .crypto import b64url_decode, b64url_encode, private_key_bytes, private_key_from_bytes, public_key_bytes

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_cached: VapidKeys | None = None


@dataclass(frozen=True)
class VapidKeys:
    private_key: ec.EllipticCurvePrivateKey
    public_key_b64: str  # applicationServerKey (base64url, 65 bytes)

    def __repr__(self) -> str:  # nunca imprimir a privada
        return f"VapidKeys(public_key_b64={self.public_key_b64!r})"


def key_path() -> Path:
    override = os.environ.get("BAMBUDDY_CUSTOM_WEBPUSH_KEY_FILE")
    if override:
        return Path(override)
    return settings.base_dir / "custom" / "webpush" / "vapid.json"  # SEC-PATH-OK: constante


def _write_new(path: Path) -> VapidKeys:
    private = ec.generate_private_key(ec.SECP256R1())
    data = {
        "private_key": b64url_encode(private_key_bytes(private)),
        "public_key": b64url_encode(public_key_bytes(private.public_key())),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    # O_EXCL: se outro processo criou no meio do caminho, usamos o dele.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(data, fh)
    logger.info("Web Push: par de chaves VAPID novo gerado em %s", path)
    return VapidKeys(private_key=private, public_key_b64=data["public_key"])


def _read(path: Path) -> VapidKeys:
    data = json.loads(path.read_text())
    private = private_key_from_bytes(b64url_decode(data["private_key"]))
    public_b64 = b64url_encode(public_key_bytes(private.public_key()))
    if (path.stat().st_mode & 0o077) != 0:
        try:
            os.chmod(path, 0o600)
        except OSError:
            logger.warning("Web Push: não consegui restringir as permissões de %s", path)
    return VapidKeys(private_key=private, public_key_b64=public_b64)


def get_vapid_keys() -> VapidKeys:
    global _cached
    if _cached is not None:
        return _cached
    with _lock:
        if _cached is not None:
            return _cached
        path = key_path()
        try:
            _cached = _read(path)
        except FileNotFoundError:
            try:
                _cached = _write_new(path)
            except FileExistsError:
                _cached = _read(path)
        return _cached


def reset_cache() -> None:
    """Para testes."""
    global _cached
    with _lock:
        _cached = None

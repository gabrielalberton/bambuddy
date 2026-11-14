"""Cache de metadados públicos e transporte de arquivos/imagens com allowlist.

Portado de 1337faye/bambuddy-model-search (commit 1b3b65b59, AGPL-3.0,
``backend/app/services/model_providers/online.py``), adaptado ao fork.

Regras: nenhum proxy arbitrário, sem seguir redirect (exceto quando a fonte
declara um salto para um host da própria allowlist), sem cookies nem tokens
repassados para CDNs.
"""

from __future__ import annotations

import asyncio
import copy
import io
import struct
import time
import zipfile
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlsplit

import httpx

from backend.app.services.model_providers.base import ProviderUnavailableError, ProviderUrlError

# Identificação honesta: quem somos e onde está o código.
USER_AGENT = "Bambuddy-gabriel-fork/1.3 (+https://github.com/gabrielalberton/bambuddy; catalogo de modelos)"
HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json"}
MAX_FILE_BYTES = 200 * 1024 * 1024
MAX_IMAGE_BYTES = 10 * 1024 * 1024
_CACHE_MAX = 128
_cache: OrderedDict[tuple, tuple[float, Any]] = OrderedDict()
_cache_locks = [asyncio.Lock() for _ in range(32)]


def clear_cache() -> None:
    _cache.clear()


async def cached(key: tuple, loader: Callable[[], Awaitable[Any]], ttl: float = 120) -> Any:
    """Só metadado PÚBLICO e bem-sucedido entra no cache (nunca download/credencial)."""
    async with _cache_locks[hash(key) % len(_cache_locks)]:
        now = time.monotonic()
        item = _cache.get(key)
        if item and item[0] > now:
            _cache.move_to_end(key)
            return copy.deepcopy(item[1])
        result = await loader()
        _cache[key] = (time.monotonic() + ttl, copy.deepcopy(result))
        _cache.move_to_end(key)
        while len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)
        return result


def validate_asset_url(url: str, hosts: tuple[str, ...]) -> None:
    try:
        p = urlsplit(url)
        valid = (
            p.scheme == "https" and p.hostname in hosts and p.port in (None, 443) and not p.username and not p.password
        )
    except ValueError:
        valid = False
    if not valid:
        raise ProviderUrlError("Refusing an asset URL outside this source's HTTPS CDN allowlist")


async def fetch_asset(
    client: httpx.AsyncClient,
    url: str,
    hosts: tuple[str, ...],
    *,
    image: bool = False,
    headers: dict[str, str] | None = None,
    redirect_hosts: tuple[str, ...] = (),
) -> tuple[bytes, str]:
    """GET limitado em tamanho. ``redirect_hosts``: permite UM redirect para esses hosts."""
    validate_asset_url(url, hosts)
    cap = MAX_IMAGE_BYTES if image else MAX_FILE_BYTES
    req_headers = {"User-Agent": USER_AGENT, **(headers or {})}
    try:
        for hop in range(2):
            async with client.stream("GET", url, headers=req_headers, follow_redirects=False, timeout=60) as response:
                if response.status_code in (301, 302, 303, 307, 308) and hop == 0 and redirect_hosts:
                    location = response.headers.get("location", "")
                    validate_asset_url(location, redirect_hosts)
                    url = location
                    # O CDN não precisa (nem deve receber) a credencial da API.
                    req_headers = {"User-Agent": USER_AGENT}
                    continue
                if response.status_code != 200:
                    raise ProviderUnavailableError(
                        f"Source asset returned HTTP {response.status_code}; redirects are not followed"
                    )
                mime = response.headers.get("content-type", "").split(";")[0].lower()
                if image and mime not in (
                    "image/jpeg",
                    "image/png",
                    "image/webp",
                    "image/gif",
                    "application/octet-stream",
                    "binary/octet-stream",
                ):
                    raise ProviderUnavailableError("Source returned non-image content")
                length = response.headers.get("content-length", "")
                if length.isdigit() and int(length) > cap:
                    raise ProviderUnavailableError("Source asset exceeds the size limit")
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(data) + len(chunk) > cap:
                        raise ProviderUnavailableError("Source asset exceeds the size limit")
                    data.extend(chunk)
                break
        else:  # pragma: no cover - laço sempre termina com break ou raise
            raise ProviderUnavailableError("Too many redirects")
    except httpx.HTTPError as exc:
        # Não logar URL assinada.
        raise ProviderUnavailableError("Source asset request failed or timed out") from exc
    payload = bytes(data)
    if image:
        mime = image_mime(payload)
    return payload, mime


def image_mime(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    raise ProviderUnavailableError("Source did not return a supported raster image")


def validate_model_file(data: bytes, filename: str) -> None:
    """Recusa HTML, projeto corrompido, traversal e zip bomb antes do parser da biblioteca.

    O 3MF é inspecionado sem extrair e guardado byte a byte (placas, pintura e
    materiais do projeto preservados).
    """
    if not data or len(data) > MAX_FILE_BYTES:
        raise ProviderUnavailableError("Model file is empty or exceeds 200 MB")
    suffix = PurePosixPath(filename).suffix.lower()
    if data.lstrip().lower().startswith((b"<!doctype html", b"<html", b'{"error')):
        raise ProviderUnavailableError("Source returned an error page instead of a model")
    if suffix == ".3mf":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                entries = archive.infolist()
                if len(entries) > 10000 or sum(x.file_size for x in entries) > 1024 * 1024 * 1024:
                    raise ValueError("Archive expansion exceeds limit")
                for item in entries:
                    name = item.filename.replace("\\", "/")
                    if name.startswith("/") or ".." in PurePosixPath(name).parts or item.flag_bits & 1:
                        raise ValueError("Unsafe archive entry")
                    if item.file_size > max(1024 * 1024, item.compress_size * 1000):
                        raise ValueError("Archive compression ratio exceeds limit")
                if not any(x.filename.lower().endswith(".model") for x in entries):
                    raise ValueError("No 3MF model data")
                if archive.testzip() is not None:
                    raise ValueError("Corrupt archive")
        except (zipfile.BadZipFile, ValueError, RuntimeError, OSError, EOFError) as exc:
            raise ProviderUnavailableError("Source returned an invalid or unsafe 3MF project") from exc
    elif suffix == ".stl":
        binary = len(data) >= 84 and 84 + struct.unpack_from("<I", data, 80)[0] * 50 == len(data)
        lowered = data[:4096].lower()
        ascii_stl = (
            data.lstrip().lower().startswith(b"solid") and b"facet" in lowered and b"endsolid" in data[-4096:].lower()
        )
        if not (binary or ascii_stl):
            raise ProviderUnavailableError("Source returned an invalid STL file")


def safe_filename(raw: str | None, fallback: str) -> str:
    """Basename sem caracteres de controle/inválidos em FAT32."""
    from urllib.parse import unquote

    name = unquote((raw or "").strip()).replace("\\", "/").rsplit("/", 1)[-1]
    if not name or name in (".", "..") or len(name) > 255:
        name = fallback
    return "".join("_" if ord(c) < 32 or c in '<>:"|?*' else c for c in name)

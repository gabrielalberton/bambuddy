"""Transporte/validação do catálogo (portado dos testes de 1337faye, commit 1b3b65b59)."""

import io
import zipfile

import httpx
import pytest

from backend.app.custom.models_catalog.transport import (
    USER_AGENT,
    cached,
    clear_cache,
    fetch_asset,
    safe_filename,
    validate_asset_url,
    validate_model_file,
)
from backend.app.services.model_providers.base import ProviderUnavailableError, ProviderUrlError
from backend.tests.custom.helpers import valid_3mf, valid_stl


@pytest.mark.parametrize(
    "url",
    [
        "http://media.printables.com/a",
        "https://media.printables.com:8443/a",
        "https://media.printables.com.evil.example/a",
        "https://127.0.0.1/a",
        "https://media.printables.com@127.0.0.1/a",
        "https://user:pass@media.printables.com/a",
        "file:///etc/passwd",
        "https://[::1]/a",
        "https://169.254.169.254/latest/meta-data",
    ],
)
def test_rejects_unsafe_asset_urls(url):
    with pytest.raises(ProviderUrlError):
        validate_asset_url(url, ("media.printables.com",))


async def test_redirect_not_followed_and_no_credentials_sent():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderUnavailableError):
            await fetch_asset(client, "https://media.printables.com/m.stl?signature=x", ("media.printables.com",))
    assert len(requests) == 1
    assert "authorization" not in requests[0].headers
    assert requests[0].headers["user-agent"] == USER_AGENT


async def test_declared_redirect_only_to_allowlisted_host_and_drops_token():
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.host == "api.thingiverse.com":
            return httpx.Response(302, headers={"location": "https://cdn.thingiverse.com/assets/x.stl"})
        return httpx.Response(200, content=valid_stl())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        data, _ = await fetch_asset(
            client,
            "https://api.thingiverse.com/files/1/download",
            ("api.thingiverse.com", "cdn.thingiverse.com"),
            headers={"Authorization": "Bearer k"},
            redirect_hosts=("cdn.thingiverse.com",),
        )
    assert data == valid_stl()
    assert seen[0].headers["authorization"] == "Bearer k"
    assert "authorization" not in seen[1].headers

    def evil(request):
        return httpx.Response(302, headers={"location": "https://evil.example/x"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(evil)) as client:
        with pytest.raises(ProviderUrlError):
            await fetch_asset(
                client,
                "https://api.thingiverse.com/files/1/download",
                ("api.thingiverse.com",),
                redirect_hosts=("cdn.thingiverse.com",),
            )


async def test_image_sniff_and_declared_size_cap():
    for headers, data in [
        ({"content-type": "image/png"}, b"<html>fake</html>"),
        ({"content-type": "image/png", "content-length": str(11 * 1024 * 1024)}, b"\x89PNG\r\n\x1a\n"),
        ({"content-type": "text/html"}, b"\x89PNG\r\n\x1a\n"),
    ]:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r, h=headers, d=data: httpx.Response(200, headers=h, content=d))
        ) as client:
            with pytest.raises(ProviderUnavailableError):
                await fetch_asset(client, "https://media.printables.com/a.png", ("media.printables.com",), image=True)


def test_content_validation_preserves_project_materials():
    original = valid_3mf()
    validate_model_file(original, "project.3mf")
    with zipfile.ZipFile(io.BytesIO(original)) as archive:
        assert b"#00FF00" in archive.read("Metadata/project_settings.config")
    validate_model_file(valid_stl(), "model.stl")
    validate_model_file(b"solid x\nfacet normal 0 0 0\nendfacet\nendsolid x\n", "ascii.stl")


@pytest.mark.parametrize(
    "data,name",
    [
        (b"<html>blocked</html>", "test.stl"),
        (b"PK\x03\x04broken", "test.3mf"),
        (b"solid garbage", "test.stl"),
        (b"", "test.stl"),
    ],
)
def test_invalid_model_bytes_rejected(data, name):
    with pytest.raises(ProviderUnavailableError):
        validate_model_file(data, name)


def test_unsafe_archive_and_zip_bomb_rejected():
    for name, data in [("../escape.model", b"unsafe"), ("3D/model.model", b"x" * (2 * 1024 * 1024))]:
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(name, data)
        with pytest.raises(ProviderUnavailableError):
            validate_model_file(output.getvalue(), "project.3mf")


def test_safe_filename():
    assert safe_filename("../../evil.3mf", "x.3mf") == "evil.3mf"
    assert safe_filename("a%20b.stl", "x") == "a b.stl"
    assert safe_filename("", "fallback.stl") == "fallback.stl"
    assert safe_filename('a<b>:"c.stl', "x") == "a_b___c.stl"


async def test_cache_returns_copies_and_coalesces():
    clear_cache()
    calls = []

    async def loader():
        calls.append(1)
        return {"items": [1]}

    first = await cached(("k",), loader)
    first["items"].append(2)
    second = await cached(("k",), loader)
    assert second == {"items": [1]}
    assert len(calls) == 1
    clear_cache()

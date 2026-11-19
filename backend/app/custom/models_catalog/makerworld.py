"""MakerWorld: catálogo pelo search-service público da Bambu (não o design/search vazio).

Portado de 1337faye/bambuddy-model-search (commit 1b3b65b59, AGPL-3.0,
``makerworld/catalogue.py``) e estendido com o filtro por impressora:
``devModelNames=<código>`` no ``select/design2`` filtra no servidor pelos
modelos com algum perfil compatível (``compatibility`` ou
``otherCompatibility``) com a impressora. Evidência: custom/docs/fontes-de-modelos.md.

Detalhe e download continuam no ``MakerWorldService`` do upstream (download
pelo ``/makerworld/import`` com a credencial Bambu Cloud já salva).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx

from backend.app.services.model_providers.base import (
    ProviderForbiddenError,
    ProviderNotFoundError,
    ProviderResourceRef,
    ProviderUnavailableError,
)
from backend.app.services.model_providers.makerworld.http import MAKERWORLD_CDN_HOSTS
from backend.app.services.model_providers.makerworld.service import MakerWorldService

from . import filters as F
from .base import BrowseRequest, CatalogSource, ReviewsRequest, order_files, review_item
from .printer_models import makerworld_codes
from .transport import HEADERS, fetch_asset

SEARCH_BASE = "https://api.bambulab.com/v1/search-service"
# Avaliações e comentários (o mesmo backend não oficial do site/Bambu Handy; anônimo para leitura).
# ``type=2`` = avaliações (estrelas), ``type=1`` = comentários; ``sort=1`` = mais recentes (padrão = relevantes).
COMMENTS_URL = "https://api.bambulab.com/v1/comment-service/commentandrating"
# Modelos publicados por um autor (o mesmo que o perfil do autor no site/app usa).
AUTHOR_DESIGNS_URL = "https://api.bambulab.com/v1/design-service/published/{uid}/design"


def sized(url: str | None, width: int) -> str | None:
    """Versão redimensionada pelo próprio CDN (o mesmo parâmetro OSS que o site usa).

    Capa original chega a 2-7 MB; em webp com 400 px fica com poucos KB (celular).
    """
    if not isinstance(url, str) or not url or "?" in url:
        return url or None
    if urlsplit(url).hostname not in MAKERWORLD_CDN_HOSTS:
        return url
    return f"{url}?x-oss-process=image/resize,w_{width}/format,webp"


def card(design: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": "makerworld",
        "id": str(design["id"]),
        "title": design.get("title") or "Untitled model",
        "url": f"https://makerworld.com/en/models/{design['id']}",
        "creator": (design.get("designCreator") or {}).get("name") or "Unknown creator",
        "creator_id": str((design.get("designCreator") or {}).get("uid") or "") or None,
        "thumbnail": sized(design.get("coverUrl") or design.get("cover") or None, 400),
        "downloads": design.get("downloadCount"),
        "likes": design.get("likeCount"),
        # Selo "CyberBrick" no card (o hit traz os dois campos; o filtro é ``model_tag=cb``).
        "cyberbrick": design.get("cyberBrickNeeded") is True or design.get("isFeaturedCyberBrick") is True,
    }


def _dev_codes(info: dict[str, Any], instance: dict[str, Any]) -> tuple[str | None, list[str]]:
    primary = info.get("compatibility") or instance.get("compatibility") or {}
    others = info.get("otherCompatibility") or instance.get("otherCompatibility") or []
    code = primary.get("devModelName") if isinstance(primary, dict) else None
    other_codes = [o.get("devModelName") for o in others if isinstance(o, dict) and o.get("devModelName")]
    return code, other_codes


def _profile_rating(instance: dict[str, Any]) -> dict[str, Any]:
    count = instance.get("ratingCount")
    total = instance.get("ratingScoreTotal")
    if not isinstance(count, int) or count <= 0 or not isinstance(total, (int, float)):
        return {}
    return {"rating_average": round(total / count, 2), "rating_count": count}


def _num(value: Any) -> float | None:
    """Número ou string numérica da API ("16.30", "0.4") → float; resto → None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value) if isinstance(value, str) and value.strip() else None
    except ValueError:
        return None


def _when(value: Any) -> str | None:
    return value if isinstance(value, str) and 10 <= len(value) <= 40 else None


def _profile_stats(instance: dict[str, Any], info: dict[str, Any], design: dict[str, Any]) -> dict[str, Any]:
    """O que o card de perfil do Bambu Handy mostra: autor/"Designer", datas, impressões, tempo, peso, bico,
    filamentos e impressoras compatíveis. Tudo já vem no ``/design/{id}`` (perfis da comunidade que só aparecem em
    ``/instances`` trazem menos campos; o que faltar fica ``None``)."""
    creator = instance.get("instanceCreator") or instance.get("creator") or {}
    designer = (design.get("designCreator") or {}).get("uid")
    primary = info.get("compatibility") or instance.get("compatibility") or {}
    others = info.get("otherCompatibility") or instance.get("otherCompatibility") or []
    printers = [
        c.get("devProductName")
        for c in [primary, *others]
        if isinstance(c, dict) and isinstance(c.get("devProductName"), str) and c.get("devProductName")
    ]
    filaments = []
    for f in instance.get("instanceFilaments") or []:
        if isinstance(f, dict) and isinstance(f.get("type"), str):
            color = f.get("color") if isinstance(f.get("color"), str) and len(f.get("color")) <= 9 else None
            filaments.append({"type": f["type"][:40], "color": color, "grams": _num(f.get("usedG"))})
    nozzle = _num(primary.get("nozzleDiameter")) if isinstance(primary, dict) else None
    plates = info.get("plates")
    plate_count = len(plates) if isinstance(plates, list) and plates else instance.get("plateCnt")
    prediction = _num(instance.get("prediction"))
    return {
        "is_designer": bool(designer) and isinstance(creator, dict) and creator.get("uid") == designer,
        "published": _when(instance.get("publishTime")) or _when(instance.get("createTime")),
        "updated": _when(instance.get("updateTime")),
        "prints": instance.get("printCount") if isinstance(instance.get("printCount"), int) else None,
        "plate_count": plate_count if isinstance(plate_count, int) and plate_count > 0 else None,
        "print_time_s": int(prediction) if prediction and prediction > 0 else None,
        "weight_g": _num(instance.get("weight")),
        "nozzle_mm": nozzle,
        "filaments": filaments[:16],
        "compatible_printers": list(dict.fromkeys(printers))[:20],
    }


PROFILE_SUMMARY_MAX = 20_000


def _profile_media(instance: dict[str, Any]) -> dict[str, Any]:
    """Foto e descrição próprias do perfil: a capa (miniatura na lista), as fotos (vão para a galeria quando o perfil
    está selecionado) e o texto do autor do perfil (HTML, higienizado no navegador como a descrição do modelo)."""
    pictures = [
        sized(p["url"], 1200)
        for p in instance.get("pictures") or []
        if isinstance(p, dict) and isinstance(p.get("url"), str) and p["url"]
    ]
    cover = instance.get("cover") if isinstance(instance.get("cover"), str) else None
    summary = instance.get("summary")
    return {
        "cover": sized(cover, 300),
        "pictures": list(dict.fromkeys(u for u in pictures if u))[:12],
        "summary_html": summary[:PROFILE_SUMMARY_MAX] if isinstance(summary, str) else "",
    }


def design_stats(design: dict[str, Any]) -> dict[str, Any]:
    """Números do topo do modelo (como no Handy): downloads, impressões, curtidas, impulsos, publicação."""
    boost = design.get("boostInfo") if isinstance(design.get("boostInfo"), dict) else {}

    def count(value: Any) -> int | None:
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None

    return {
        "downloads": count(design.get("downloadCount")),
        "prints": count(design.get("printCount")),
        "likes": count(design.get("likeCount")),
        "collections": count(design.get("collectionCount")),
        "boosts": count(boost.get("total")),
        "published": _when(design.get("createTime")),
    }


def printer_match(code: str | None, others: list[str], wanted: list[str]) -> str:
    if not code and not others:
        return "unknown"
    if code in wanted:
        return "native"
    if any(o in wanted for o in others):
        return "compatible"
    return "other"


async def _search(client: httpx.AsyncClient, path: str, params: dict[str, Any]) -> dict[str, Any]:
    return await _api_json(client, f"{SEARCH_BASE}{path}", params)


async def _api_json(client: httpx.AsyncClient, url: str, params: dict[str, Any]) -> dict[str, Any]:
    try:
        response = await client.get(f"{url}?{urlencode(params)}", headers=HEADERS, timeout=30)
    except httpx.HTTPError as exc:
        raise ProviderUnavailableError("MakerWorld search request failed or timed out") from exc
    if response.status_code == 403:
        raise ProviderForbiddenError("MakerWorld refused the search request")
    if response.status_code == 404:
        raise ProviderNotFoundError("MakerWorld search endpoint not found")
    if response.status_code == 418:
        raise ProviderUnavailableError(
            "MakerWorld is challenging this IP (HTTP 418, CAPTCHA). It usually clears in a few hours."
        )
    if response.status_code == 429:
        raise ProviderUnavailableError("MakerWorld rate-limited the request (HTTP 429). Try again shortly.")
    if response.status_code != 200:
        raise ProviderUnavailableError(f"MakerWorld search returned HTTP {response.status_code}")
    try:
        data = response.json()
    except ValueError as exc:
        raise ProviderUnavailableError("MakerWorld search returned non-JSON data") from exc
    if not isinstance(data, dict) or not isinstance(data.get("hits") or [], list):
        raise ProviderUnavailableError("MakerWorld returned an invalid search response")
    return data


def rating_summary(instances: Any) -> dict[str, Any]:
    """Nota do modelo = soma das notas / soma das avaliações de todos os perfis (o que o site mostra).

    Conferido em 2026-11-14: modelo 1685835 → 4618/942 = 4,90, e o ``total`` de
    ``commentandrating?type=2`` também deu 942.
    """
    total = count = 0
    for inst in instances if isinstance(instances, list) else []:
        if not isinstance(inst, dict):
            continue
        t, c = inst.get("ratingScoreTotal"), inst.get("ratingCount")
        if isinstance(t, (int, float)) and isinstance(c, int) and c > 0:
            total += t
            count += c
    return {"average": round(total / count, 2) if count else None, "count": count}


def _images(urls: Any) -> list[dict[str, str]]:
    out = []
    for url in urls if isinstance(urls, list) else []:
        if isinstance(url, str) and urlsplit(url).scheme == "https" and urlsplit(url).hostname in MAKERWORLD_CDN_HOSTS:
            out.append({"thumb": sized(url, 240) or url, "full": sized(url, 1200) or url})
    return out


def _name(user: Any) -> Any:
    return user.get("name") if isinstance(user, dict) else None


def parse_review(hit: dict[str, Any]) -> dict[str, Any] | None:
    """Um item de ``commentandrating`` → formato comum (``None`` para itens inválidos/ocultos)."""
    rating = hit.get("ratingItem")
    if hit.get("type") == 2 and isinstance(rating, dict) and rating.get("id"):
        if rating.get("status") not in (None, 1):
            return None
        inst = rating.get("instInfo") if isinstance(rating.get("instInfo"), dict) else {}
        profile = None
        if inst.get("profileId"):
            profile = {"id": str(inst["profileId"]), "name": str(inst.get("title") or "")[:200]}
        details = [d for d in rating.get("lowScoreDetails") or [] if isinstance(d, dict)]
        text = rating.get("content") or ""
        if not str(text).strip():
            # Avaliação baixa sem texto: o motivo escrito pela pessoa vira o texto.
            text = next((d.get("reasonDescription") for d in details if d.get("reasonDescription")), "")
        return review_item(
            item_id=f"r{rating['id']}",
            kind="rating",
            author=_name(rating.get("creator")),
            rating=rating.get("score"),
            text=text,
            created=rating.get("createTime"),
            likes=rating.get("likeCount"),
            replies=rating.get("replyCount"),
            images=_images(rating.get("images")),
            profile=profile,
            printed=rating.get("successPrinted") if isinstance(rating.get("successPrinted"), bool) else None,
            issues=[d.get("reason") for d in details],
        )
    comment = hit.get("comment")
    if hit.get("type") == 1 and isinstance(comment, dict) and comment.get("id"):
        if comment.get("isValid") is False:
            return None
        replies = [r for r in comment.get("commentReply") or [] if isinstance(r, dict)]
        return review_item(
            item_id=f"c{comment['id']}",
            kind="comment",
            author=_name(comment.get("user")),
            text=comment.get("content"),
            created=comment.get("createTime"),
            likes=comment.get("likeCount"),
            replies=comment.get("replyCount"),
            images=_images(comment.get("images")),
            boosted=comment.get("boosted") is True,
            reply_preview=[
                review_item(
                    item_id=f"c{r.get('id')}",
                    kind="comment",
                    author=_name(r.get("user")),
                    text=r.get("content"),
                    created=r.get("createTime"),
                    likes=r.get("likeCount"),
                )
                for r in replies[:3]
            ],
        )
    return None


PREVIEW_MAX_UNZIPPED = 150 * 1024 * 1024


def preview_zip_url(instance: dict[str, Any]) -> str | None:
    """Zip com o GLB leve (Draco) de cada placa que o próprio MakerWorld usa no visualizador 3D do site."""
    for f in (instance.get("extention") or {}).get("extensionModelFileList") or []:
        url = f.get("modelFile") if isinstance(f, dict) else None
        if isinstance(url, str) and "glb" in str(f.get("compressType") or "") and urlsplit(url).hostname in MAKERWORLD_CDN_HOSTS:
            return url
    return None


def extract_plates(data: bytes) -> list[bytes]:
    """GLBs do zip, em ordem de placa (``input_plate_<n>.glb``). Limita nomes, quantidade e tamanho descompactado."""
    import io
    import re
    import zipfile

    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ProviderUnavailableError("MakerWorld preview is not a valid archive") from exc
    entries = [i for i in zf.infolist() if i.filename.lower().endswith(".glb") and "/" not in i.filename][:64]
    if sum(i.file_size for i in entries) > PREVIEW_MAX_UNZIPPED:
        raise ProviderUnavailableError("MakerWorld preview exceeds the size limit")

    def plate_no(name: str) -> int:
        m = re.search(r"(\d+)\.glb$", name, re.I)
        return int(m.group(1)) if m else 0

    entries.sort(key=lambda i: plate_no(i.filename))
    plates = [zf.read(i) for i in entries]
    plates = [p for p in plates if p[:4] == b"glTF"]
    if not plates:
        raise ProviderUnavailableError("MakerWorld preview has no 3D model")
    return plates


CFG_URL = f"{SEARCH_BASE}/cfg2"
# orderBy do search-service (todos listados no cfg2 ou medidos mudando a ordem em 2026-11-19).
ORDER_BY = {
    "popular": "downloadCount",
    "newest": "newUploads",
    "likes": "likeCount",
    "boosts": "boosts",
    "prints": "printCount",
    "collections": "collectionCount",
    "random": "random",
}
# Rótulos pt-BR das opções do cfg2 (o cfg2 só vem em inglês).
_PT = {
    "featured": "Destaque",
    "exclusive": "Exclusivo",
    "cb": "CyberBrick",
    "ms": "Maker's Supply",
    "custom": "Customizável",
    "param": "Paramétrico",
    "Standard": "Padrão",
    "High Flow": "Alto fluxo",
    "TPU285": "TPU 285",
    "false": "Só uma cor",
    "true": "Só multicor",
    "CC0": "Domínio público (CC0)",
    "Standard Digital File License": "Licença padrão de arquivo digital",
}
# Filtros do cfg2 que funcionam (medido: o total muda). Fora daqui de propósito: ``devModelNames`` (é o filtro
# "Só para minha impressora"), ``total_weight`` e ``my_filament`` (o servidor ignora/precisa de login).
# id do cfg2 -> (parâmetro do design2, tipo, rótulo pt, rótulo en, grupo)
CFG_FILTERS: dict[str, tuple[str, F.FilterType, str, str, str]] = {
    "model_tag": ("model_tag", "enum", "Tipo de modelo", "Model tag", "model"),
    "volumeTypes": ("volumeTypes", "multi", "Tipo de bico", "Nozzle type", "profile"),
    "nozzleDiameters": ("nozzleDiameters", "multi", "Diâmetro do bico", "Nozzle diameter", "profile"),
    "multiColor": ("multiColor", "enum", "Cores", "Colors", "profile"),
    "print_duration": ("printDuration", "range", "Tempo de impressão", "Print time", "profile"),
    "licenses": ("licenses", "multi", "Licença", "License", "license"),
}
STATIC_CFG = {
    "model_tag": [("featured", "Featured"), ("exclusive", "Exclusive"), ("cb", "CyberBrick"),
                  ("ms", "Maker's Supply"), ("custom", "Customizable"), ("param", "Parametric")],
    "volumeTypes": [("Standard", "Std"), ("High Flow", "HF"), ("TPU285", "TPU 285")],
    "nozzleDiameters": [("0.2", "0.2mm"), ("0.4", "0.4mm"), ("0.6", "0.6mm"), ("0.8", "0.8mm")],
    "multiColor": [("false", "Single Color Only"), ("true", "Multi-Color Only")],
    "print_duration": [("1", "1 min"), ("5", "5 min"), ("15", "15 min"), ("30", "30 min"), ("60", "1 hr"),
                       ("120", "2 hrs"), ("300", "5 hrs"), ("600", "10 hrs"), ("1440", "1 day"), ("2880", "2 days"),
                       ("4320", "3 days")],
    "licenses": [("CC0", "Public Domain"), ("BY", "BY"), ("BY-SA", "BY-SA"), ("BY-ND", "BY-ND"), ("BY-NC", "BY-NC"),
                 ("BY-NC-SA", "BY-NC-SA"), ("BY-NC-ND", "BY-NC-ND"),
                 ("Standard Digital File License", "Standard Digital File License")],
}


def _duration_pt(value: str, en: str) -> str:
    return en.replace("hrs", "h").replace("hr", "h").replace("days", "dias").replace("day", "dia")


def _cfg_options(cfg: dict[str, Any]) -> dict[str, list[tuple[str, str]]]:
    """``filter.design`` do cfg2 → {id: [(valor, rótulo en)]} só dos filtros que usamos."""
    found: dict[str, list[tuple[str, str]]] = {}

    def walk(nodes: Any) -> None:
        for node in nodes if isinstance(nodes, list) else []:
            if not isinstance(node, dict):
                continue
            name = node.get("name")
            if name in CFG_FILTERS and isinstance(node.get("option"), list):
                opts = [
                    (str(o["value"])[:60], str(o.get("displayName") or o["value"])[:60])
                    for o in node["option"]
                    if isinstance(o, dict) and isinstance(o.get("value"), (str, int, float)) and str(o["value"]) != "-"
                ]
                if opts:
                    found[name] = opts
            walk(node.get("children"))

    walk(((cfg.get("filter") or {}) if isinstance(cfg, dict) else {}).get("design"))
    return found


def build_schema(cfg_opts: dict[str, list[tuple[str, str]]], origin: str) -> dict[str, Any]:
    defs: dict[str, list[dict[str, Any]]] = {"model": [], "profile": [], "license": []}
    for cfg_id, (param, ftype, pt, en, grp) in CFG_FILTERS.items():
        options = cfg_opts.get(cfg_id) or STATIC_CFG[cfg_id]
        opts = [
            F.opt(v, _duration_pt(v, e) if cfg_id == "print_duration" else _PT.get(v, e), e) for v, e in options
        ]
        hint = None
        if cfg_id == "model_tag":
            hint = ("Um tipo por vez (o MakerWorld combina tipos com E).", "One tag at a time (MakerWorld ANDs tags).")
        elif cfg_id == "multiColor":
            hint = ("Pela placa do perfil de impressão.", "From the print profile plate.")
        defs[grp].append(F.fdef(param, ftype, pt, en, opts, hint=hint))
    defs["model"].append(F.fdef("designCreateSince", "days", "Publicado", "Published", F.DAYS_OPTIONS))
    defs["model"].append(
        F.fdef(
            "isPrintable", "bool", "Com perfil de impressão", "Has a print profile",
            hint=("Só modelos com perfil pronto para fatiar.", "Only models with a ready print profile."),
        )
    )
    return F.schema(
        "makerworld",
        [
            F.group("model", "Modelo", "Model", defs["model"]),
            F.group("profile", "Perfil de impressão", "Print profile", defs["profile"]),
            F.group("license", "Licença", "License", defs["license"]),
        ],
        origin,
    )


def apply_filters(params: dict[str, Any], filters: dict[str, Any]) -> None:
    for fid, value in filters.items():
        if fid == "printDuration":
            lo, hi = value
            params[fid] = f"{lo or 0}-{hi or ''}"
        elif fid == "isPrintable":
            params[fid] = "true"
        elif fid == "designCreateSince":
            params[fid] = int(value)
        elif isinstance(value, list):
            params[fid] = ",".join(value)
        else:
            params[fid] = value


class MakerWorldSource(CatalogSource):
    id = "makerworld"
    name = "MakerWorld"
    default_folder = "MakerWorld"
    thumbnail_hosts = MAKERWORLD_CDN_HOSTS
    supports_author = True
    permission_kind = "makerworld"
    printer_filter = "server"
    sorts = ("trending", "popular", "newest", "relevance", "likes", "boosts", "prints", "collections", "random")
    review_kinds = ("ratings", "comments")
    review_sorts = ("top", "newest")

    def printer_filter_note(self) -> str:
        return "server: search-service devModelNames (profile compatibility)"

    def build_params(self, req: BrowseRequest) -> tuple[str, dict[str, Any], list[str]]:
        codes = makerworld_codes(req.models) if req.printer_filter else []
        params: dict[str, Any] = {"keyword": req.query, "offset": req.offset, "limit": req.limit}
        if req.category:
            params["categories"] = req.category
        if req.sort in ORDER_BY:
            # "newest" = ``newUploads`` (ordenação real do cfg2; antes era o filtro "últimas 24 h",
            # que agora é ``designCreateSince`` no filtro avançado).
            params["orderBy"] = ORDER_BY[req.sort]
        if codes:
            params["devModelNames"] = ",".join(codes)
        apply_filters(params, req.filters)
        # O feed Trending (nav) ignora devModelNames e os filtros (conferido ao vivo); com filtro
        # usamos o ranking padrão do design2, que é o mesmo feed de "em alta" sem palavra-chave.
        if not req.query and not req.category and req.sort == "trending" and not codes and not req.filters:
            params["navKey"] = "Trending"
            return "/select/design/nav", params, codes
        return "/select/design2", params, codes

    async def browse(self, client: httpx.AsyncClient, req: BrowseRequest) -> dict[str, Any]:
        path, params, codes = self.build_params(req)
        envelope = await _search(client, path, params)
        hits = envelope.get("hits") or []
        items = [card(h) for h in hits if isinstance(h, dict) and h.get("id") and not h.get("nsfw")]
        total = envelope.get("total")
        return {
            "items": items,
            "total": total if isinstance(total, int) else None,
            "has_more": req.offset + len(hits) < total if isinstance(total, int) else len(hits) == req.limit,
            "printer_filter": {"mode": "server", "applied": bool(codes), "codes": codes},
        }

    async def author(self, client: httpx.AsyncClient, author_id: str, offset: int, limit: int) -> dict[str, Any]:
        envelope = await _api_json(client, AUTHOR_DESIGNS_URL.format(uid=author_id), {"offset": offset, "limit": limit})
        hits = envelope.get("hits") or envelope.get("list") or []
        items = [card(h) for h in hits if isinstance(h, dict) and h.get("id") and not h.get("nsfw")]
        total = envelope.get("total")
        name = next((i["creator"] for i in items if i.get("creator")), None)
        return {
            "items": items,
            "total": total if isinstance(total, int) else None,
            "has_more": offset + len(hits) < total if isinstance(total, int) else len(hits) == limit,
            "author": {"id": author_id, "name": name},
        }

    async def preview(self, client: httpx.AsyncClient, model_id: str, file_id: str) -> list[bytes]:
        service = MakerWorldService(client=client)
        resolved = await service.resolve(ProviderResourceRef(source_type="makerworld", external_id=model_id))
        instances = [*(resolved.design.get("instances") or []), *resolved.instances]
        for instance in instances:
            if isinstance(instance, dict) and str(instance.get("profileId")) == file_id:
                url = preview_zip_url(instance)
                if url:
                    data, _ = await fetch_asset(client, url, MAKERWORLD_CDN_HOSTS)
                    return extract_plates(data)
        raise ProviderNotFoundError("This profile has no 3D preview")

    async def filter_schema(self, client: httpx.AsyncClient) -> dict[str, Any]:
        """Do ``cfg2`` oficial (o mesmo que monta os filtros do site); sem ele, a lista estática medida."""
        try:
            opts = _cfg_options(await _api_json(client, CFG_URL, {}))
        except Exception:  # noqa: BLE001 - qualquer falha do cfg2 cai na lista estática
            opts = {}
        return build_schema(opts, "cfg2" if opts else "static")

    async def categories(self, client: httpx.AsyncClient) -> list[dict[str, str]]:
        service = MakerWorldService(client=client)
        root = await service._get_json("/design/category")
        result: list[dict[str, str]] = []

        def walk(nodes: list[Any], parent: str = "") -> None:
            for node in nodes:
                if not isinstance(node, dict) or "id" not in node or "name" not in node:
                    continue
                name = f"{parent} / {node['name']}" if parent else node["name"]
                result.append({"id": str(node["id"]), "name": name})
                walk(node.get("children") or [], name)

        walk(root.get("children") or [])
        return result

    async def detail(self, client: httpx.AsyncClient, model_id: str, models: list[str]) -> dict[str, Any]:
        service = MakerWorldService(client=client)
        resolved = await service.resolve(ProviderResourceRef(source_type="makerworld", external_id=model_id))
        design = resolved.design
        wanted = makerworld_codes(models)
        by_profile: dict[str, dict[str, Any]] = {
            str(i.get("profileId")): i for i in design.get("instances") or [] if isinstance(i, dict)
        }
        for instance in resolved.instances:
            if isinstance(instance, dict) and instance.get("profileId"):
                key = str(instance["profileId"])
                by_profile[key] = {**instance, **by_profile.get(key, {})}
        files = []
        for pid, instance in by_profile.items():
            if not pid.isdigit() or int(pid) <= 0:
                continue
            info = (instance.get("extention") or {}).get("modelInfo") or {}
            code, others = _dev_codes(info, instance)
            primary = info.get("compatibility") or instance.get("compatibility") or {}
            plates = info.get("plates") or []
            files.append(
                {
                    "id": pid,
                    "name": instance.get("title") or f"Print profile {pid}",
                    "format": "3mf",
                    "size": (info.get("f3mf") or {}).get("size") or None,
                    "sliceable": True,
                    "printer_match": printer_match(code, others, wanted),
                    "printer": (primary.get("devProductName") if isinstance(primary, dict) else None) or None,
                    "metadata": {
                        "printer_code": code,
                        "compatible_codes": others,
                        "plates": plates if isinstance(plates, list) else [],
                        "requires_ams": bool(instance.get("needAms", False)),
                        "creator": (instance.get("instanceCreator") or instance.get("creator") or {}).get("name"),
                        "downloads": instance.get("downloadCount"),
                        "preview_3d": bool(preview_zip_url(instance)),
                        **_profile_media(instance),
                        **_profile_rating(instance),
                        **_profile_stats(instance, info, design),
                    },
                }
            )
        ordered, preselect = order_files(files)
        ext = design.get("designExtension") or {}
        images = [
            p["url"]
            for key in ("design_pictures", "real_pictures")
            for p in ext.get(key) or []
            if isinstance(p, dict) and p.get("url")
        ]
        license_value = design.get("license")
        return {
            **card(design),
            "thumbnail": sized(design.get("coverUrl") or design.get("cover") or None, 1200),
            "description_html": design.get("summary") or "",
            "images": [sized(u, 1200) for u in images[:40]],
            "license": license_value if isinstance(license_value, str) else None,
            "files": ordered,
            "preselect_file_id": preselect,
            "printer_models": models,
            "metadata": {"tags": design.get("tags") or []},
            "rating": rating_summary(design.get("instances")),
            "stats": design_stats(design),
        }

    async def reviews(self, client: httpx.AsyncClient, model_id: str, req: ReviewsRequest) -> dict[str, Any]:
        params: dict[str, Any] = {
            "designId": model_id,
            "offset": req.offset,
            "limit": req.page_size,
            "type": 1 if req.kind == "comments" else 2,
        }
        if req.sort == "newest":
            params["sort"] = 1
        envelope = await _api_json(client, COMMENTS_URL, params)
        hits = [h for h in envelope.get("hits") or [] if isinstance(h, dict)]
        total = envelope.get("total")
        items = [item for h in hits if (item := parse_review(h)) is not None]
        return {
            "items": items,
            "total": total if isinstance(total, int) else None,
            "has_more": req.offset + len(hits) < total if isinstance(total, int) else len(hits) == req.page_size,
        }

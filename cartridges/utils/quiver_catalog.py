# quiver_catalog.py
#
# Copyright 2026 Jolven contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Catálogo público do quiverlauncher.com, para enriquecer apps do Quiver.

O `apps.json` do Quiver Launcher descreve cada app pelo que o jogador
instalou: nome, repositório, ícone. O catálogo público do
quiverlauncher.com descreve o mesmo app pelo lado de quem o indexa: capa,
descrição, versão, desenvolvedora e tags. Este módulo junta as duas coisas.

O catálogo é público e não pede credencial: todo endpoint é um GET simples.
Nada é enviado além do termo de busca (o nome do app ou o repositório), e
nenhum dado do usuário sai daqui.

Resolução da identidade, nesta ordem:

1. ``catalogEntryId`` → casado com o ``id`` dos itens de ``GET /apps?search=…``.
   O upstream grava ali o ``id`` do app no catálogo, e é o mesmo campo que a
   busca devolve: a identidade mais forte é resolvida na busca que já seria
   feita, sem uma requisição extra. Um ``apps.json`` escrito à mão pode trazer
   o ``slug``, então ``GET /apps/{valor}`` continua como último recurso.
2. ``repository`` → ``GET /apps?search=…`` com o nome do repositório. Só é
   aceito um candidato cujo repositório é igual ao da entrada, confirmado
   no detalhe do app (``project.repository``).
3. ``name`` → ``GET /apps?search=…`` com o nome. Só é aceito um candidato
   cujo nome é igual ao da entrada, e apenas se for o único.

Nunca se adota "o primeiro resultado". Uma busca que devolve três candidatos
sem um campo que case exatamente é uma ambiguidade, e a resposta é ``None``:
metadado errado numa biblioteca é pior do que metadado ausente.

Cache: JSON versionado em ``<cache>/jolven/quiver_catalog.json``, TTL de 24 h
e o mesmo formato do `xcloud_catalog.py`. A cadeia de queda é rede → cache
velho → ``None``. Nada aqui levanta: falha de rede, JSON inválido ou corpo
grande demais viram "sem enriquecimento", nunca uma exceção para o
importador.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote, urlencode, urlparse

import requests

from cartridges.utils.download import get_capped
from cartridges.utils.name_cleaner import split_camel_case

# O catálogo público do Quiver Launcher. `api.quiverlauncher.com` é um
# domínio próprio na frente da implantação Convex; quando o handshake TLS
# dele falha, o host da implantação ainda responde — é o mesmo mecanismo que
# o upstream usa.
DEFAULT_BASE_URL = "https://api.quiverlauncher.com/api/v1"
FALLBACK_BASE_URL = "https://famous-wildebeest-660.convex.site/api/v1"

REQUEST_TIMEOUT = 10
# O catálogo responde JSON. Uma página de 48 itens tem algumas dezenas de KB;
# 2 MiB é folgado e ainda impede que uma resposta enorme consuma a memória.
MAX_CATALOG_BYTES = 2 * 1024 * 1024
SEARCH_LIMIT = 48

CACHE_FILE = "quiver_catalog.json"
CACHE_VERSION = 1
CACHE_TTL = 86400

USER_AGENT = "Jolven (Quiver catalog reader)"

_HEADERS = {"Accept": "application/json", "User-Agent": USER_AGENT}

# Quantos candidatos podem ser conferidos no detalhe durante a busca por
# repositório. O filtro barato (projectName/slug) já reduz a lista para
# quase um item; o teto existe para que uma entrada patológica não vire uma
# sequência de requisições.
_MAX_DETAIL_PROBES = 3

# Separa camelCase e dígito de letra: "OpenTTD-patches" → "Open TTD patches",
# "2ship2harkinian" → "2 ship 2 harkinian". Só é usado para montar a
# consulta de busca, nunca para comparar identidades.
_WORD_BOUNDARY_RE = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])")

_cache_lock = threading.Lock()


@dataclass(frozen=True)
class QuiverEnrichment:
    """O que o catálogo sabe sobre um app que a biblioteca local não sabe.

    Só os campos que o catálogo realmente publica. ``None`` significa "o
    catálogo não diz"; a lista vazia de ``tags`` significa "sem tags".
    """

    cover_url: Optional[str] = None
    description: Optional[str] = None
    version: Optional[str] = None
    developer: Optional[str] = None
    tags: list[str] = field(default_factory=list)


def api_base() -> str:
    """Base do catálogo. ``QUIVER_API`` sobrescreve, como no upstream."""
    override = os.environ.get("QUIVER_API", "").strip()
    return (override or DEFAULT_BASE_URL).rstrip("/")


def catalog_cache_path(base: Optional[Path] = None) -> Optional[Path]:
    """Caminho do arquivo de cache.

    ``base`` é o diretório (o mesmo papel de ``shared.cache_dir / "jolven"``
    usado pelo `xcloud_catalog.py`) e isola o cache nos testes. Sem ``base``
    e sem `cartridges.shared` disponível, o cache é desativado e a função
    devolve ``None`` — o enriquecimento segue funcionando, só sem cache.
    """
    if base is not None:
        return Path(base) / CACHE_FILE
    try:
        from cartridges import shared
    except Exception:  # pragma: no cover - headless, sem shared gerado
        return None
    cache_dir = getattr(shared, "cache_dir", None)
    if cache_dir is None:
        return None
    return Path(cache_dir) / "jolven" / CACHE_FILE


def _resolve_cache_path(path: Optional[Path]) -> Optional[Path]:
    """Aceita o caminho completo do arquivo; sem ele, usa o local padrão."""
    if path is not None:
        return Path(path)
    return catalog_cache_path()


# region Texto e normalização


def _text(value: Any) -> Optional[str]:
    """Texto não vazio, ou ``None``."""
    return value.strip() if isinstance(value, str) and value.strip() else None


def _norm(value: Any) -> str:
    """Forma comparável de um nome: sem caixa, acentos ou pontuação."""
    if not isinstance(value, str):
        return ""
    decomposed = unicodedata.normalize("NFKD", value)
    folded = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", folded.casefold())


def _same_text(left: Any, right: Any) -> bool:
    """True quando os dois textos são iguais ignorando caixa e espaços."""
    left_text = _text(left)
    right_text = _text(right)
    if left_text is None or right_text is None:
        return False
    return left_text.casefold() == right_text.casefold()


def _repo_name(repository: str) -> str:
    """A parte final de ``owner/repo``."""
    return repository.rsplit("/", 1)[-1].strip()


def _loosen(value: str) -> str:
    """Quebra um identificador colado em palavras, para a busca."""
    spaced = _WORD_BOUNDARY_RE.sub(" ", split_camel_case(value))
    spaced = re.sub(r"[-_.]+", " ", spaced)
    return re.sub(r"\s+", " ", spaced).strip()


# endregion


# region Rede


def _request(url: str) -> requests.Response:
    """GET com timeout e teto de corpo (``get_capped``)."""
    return get_capped(
        url,
        max_bytes=MAX_CATALOG_BYTES,
        timeout=REQUEST_TIMEOUT,
        headers=_HEADERS,
    )


def _get_json(path: str, params: Optional[dict[str, Any]] = None) -> Any:
    """GET JSON do catálogo. ``None`` quando o endpoint responde 404."""
    base = api_base()
    query = f"?{urlencode(params)}" if params else ""
    url = f"{base}{path}{query}"
    try:
        response = _request(url)
    except requests.ConnectionError:
        if base != DEFAULT_BASE_URL:
            raise
        # O domínio próprio falhou no TLS/na conexão; o host da implantação
        # responde o mesmo conteúdo.
        response = _request(f"{FALLBACK_BASE_URL}{path}{query}")
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


def _search(query: str) -> list[dict]:
    """``GET /apps?search=…``; devolve os itens da primeira página."""
    payload = _get_json("/apps", {"limit": SEARCH_LIMIT, "search": query})
    if not isinstance(payload, dict):
        return []
    items = payload.get("items")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _detail(value: str) -> Optional[dict]:
    """``GET /apps/{slug}``; ``None`` quando o catálogo não tem esse app."""
    if not value:
        return None
    payload = _get_json(f"/apps/{quote(value, safe='')}")
    return payload if isinstance(payload, dict) else None


# endregion


# region Resolução da identidade


def _app_of(payload: dict) -> dict:
    """O app dentro de um payload: ``{"entry": {...}}`` ou o próprio app."""
    inner = payload.get("entry")
    if isinstance(inner, dict):
        return inner
    return payload


def _detail_repository(detail: dict) -> Optional[str]:
    """O repositório de um detalhe (``project.repository``)."""
    project = detail.get("project")
    if isinstance(project, dict):
        repository = _text(project.get("repository"))
        if repository:
            return repository
    return _text(detail.get("repository"))


def _hint_rank(wanted: str, candidate: dict) -> Optional[int]:
    """Quanto o candidato "parece" o repositório procurado.

    A busca não devolve o repositório (só o detalhe tem), mas devolve o nome
    do projeto e o slug, que normalmente são o repositório escrito de outro
    jeito. Serve só como filtro: a confirmação vem do detalhe.

    O ranking vai do melhor para o pior — o nome do projeto idêntico ao
    repositório (0), o mesmo nome com um sufixo de variante (1) e o nome
    apenas contendo o repositório (2) — para que a requisição de detalhe
    seja gasta nos candidatos que têm mais chance de confirmar.
    """
    best: Optional[int] = None
    for key in ("projectName", "slug"):
        value = _text(candidate.get(key))
        if not value:
            continue
        normalized = _norm(value)
        if not normalized:
            continue
        if normalized == wanted:
            rank = 0
        elif normalized.startswith(wanted):
            rank = 1
        elif wanted in normalized:
            rank = 2
        else:
            continue
        best = rank if best is None else min(best, rank)
    return best


def _repository_queries(repository: str) -> list[str]:
    """Consultas de busca derivadas do repositório, da mais provável à menos.

    A busca do catálogo indexa nomes de app e de projeto, não repositórios:
    ``owner/repo`` literalmente não encontra nada. O nome do repositório é a
    consulta útil, e a forma quebrada em palavras cobre os repositórios
    colados (``2ship2harkinian`` → ``2 ship 2 harkinian``).
    """
    repo_name = _repo_name(repository)
    queries: list[str] = []
    for candidate in (repo_name, _loosen(repo_name), repository):
        value = candidate.strip()
        if value and value not in queries:
            queries.append(value)
    return queries


def _same_entry(candidate: dict, entry_id: str) -> bool:
    """True quando o item do catálogo é o app apontado pela biblioteca.

    O upstream grava em ``catalogEntryId`` o ``id`` do app no catálogo, que
    é exatamente o campo que a busca devolve. Uma biblioteca escrita à mão
    pode trazer o ``catalogId``; os dois são identificadores exatos, então a
    comparação é literal e nunca aproximada.
    """
    wanted = entry_id.casefold()
    for key in ("id", "catalogId"):
        value = _text(candidate.get(key))
        if value and value.casefold() == wanted:
            return True
    return False


def _select(
    candidates: list[dict],
    repository: Optional[str],
    name: Optional[str],
    entry_id: Optional[str] = None,
) -> Optional[dict]:
    """Escolhe o candidato sem ambiguidade, ou ``None``.

    A identidade do catálogo vem primeiro: quando a biblioteca aponta um
    ``catalogEntryId``, o item da busca que tem esse ``id`` é o app certo, sem
    nenhuma confirmação adicional. Depois o repositório tem precedência sobre
    o nome: ele identifica o projeto, enquanto o nome identifica o jogo que o
    app joga — e o catálogo usa os dois para as mesmas coisas em apps
    diferentes.
    """
    if entry_id:
        id_hits = [
            candidate
            for candidate in candidates
            if _same_entry(candidate, entry_id)
        ]
        if len(id_hits) == 1:
            return id_hits[0]
        if len(id_hits) > 1:
            # O mesmo id em dois itens só pode ser resposta corrompida.
            return None

    if repository:
        wanted = _norm(_repo_name(repository))
        ranked = [
            (rank, candidate)
            for candidate in candidates
            if (rank := _hint_rank(wanted, candidate)) is not None
        ]
        ranked.sort(key=lambda item: item[0])
        confirmed: list[dict] = []
        for _rank, candidate in ranked[:_MAX_DETAIL_PROBES]:
            slug = _text(candidate.get("slug"))
            if not slug:
                continue
            detail = _detail(slug)
            if detail is None:
                continue
            if _same_text(_detail_repository(detail), repository):
                confirmed.append(detail)
        if len(confirmed) == 1:
            return confirmed[0]
        if len(confirmed) > 1:
            # Mesmo repositório, apps diferentes (build por sistema). O nome
            # do app ainda pode desempatar; se não, é ambiguidade.
            hits = [
                detail
                for detail in confirmed
                if _same_text(_app_of(detail).get("name"), name)
            ]
            return hits[0] if len(hits) == 1 else None

    if name:
        hits = [
            candidate
            for candidate in candidates
            if _same_text(candidate.get("name"), name)
        ]
        if len(hits) == 1:
            return hits[0]
    return None


def _resolve(
    entry_id: Optional[str],
    repository: Optional[str],
    name: Optional[str],
) -> Optional[dict]:
    """Encontra o app no catálogo. ``None`` quando não há casamento certo.

    O ``catalogEntryId`` é conferido nos itens de cada busca, antes do
    repositório e do nome: ele é a identidade exata e não custa requisição
    nenhuma. O ``GET /apps/{valor}`` fica para o fim, porque ele só resolve o
    ``slug`` — serve para a entrada escrita à mão que guardou o slug ali.
    """
    queries: list[str] = []
    if repository:
        queries.extend(_repository_queries(repository))
    if name and name not in queries:
        queries.append(name)

    for query in queries:
        candidates = _search(query)
        if not candidates:
            continue
        selected = _select(candidates, repository, name, entry_id)
        if selected is not None:
            return selected

    if entry_id:
        return _detail(entry_id)
    return None


# endregion


# region Enriquecimento


def _safe_url(value: Any) -> Optional[str]:
    """URL http/https com host. Qualquer outro esquema é descartado."""
    url = _text(value)
    if url is None:
        return None
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ("http", "https"):
        return None
    if not parsed.netloc:
        return None
    return url


def _cover_url(app: dict) -> Optional[str]:
    """A capa: header, depois capsule, depois a arte solta."""
    options: list[Any] = []
    library_art = app.get("libraryArt")
    if isinstance(library_art, dict):
        options.append(library_art.get("header"))
        options.append(library_art.get("capsule"))
    options.append(app.get("artwork"))
    for option in options:
        url = _safe_url(option)
        if url:
            return url
    return None


def _version(app: dict) -> Optional[str]:
    """A versão: a última release publicada, ou a verificada."""
    version = _text(app.get("lastReleaseVersion"))
    if version:
        return version
    verified = app.get("verified")
    if isinstance(verified, dict):
        return _text(verified.get("version"))
    return None


def _developer(app: dict) -> Optional[str]:
    """A desenvolvedora: o catálogo traz um objeto com o nome."""
    developer = app.get("developer")
    if isinstance(developer, dict):
        return _text(developer.get("name"))
    return _text(developer)


def _tags(app: dict) -> list[str]:
    """As tags do catálogo, sem vazios."""
    tags = app.get("tags")
    if not isinstance(tags, list):
        return []
    return [tag for tag in (_text(value) for value in tags) if tag]


def _enrichment_from_payload(payload: Optional[dict]) -> Optional[QuiverEnrichment]:
    """Monta o enriquecimento a partir de um item ou de um detalhe."""
    if not isinstance(payload, dict):
        return None
    app = _app_of(payload)
    if not app:
        return None
    enrichment = QuiverEnrichment(
        cover_url=_cover_url(app),
        description=_text(app.get("description")),
        version=_version(app),
        developer=_developer(app),
        tags=_tags(app),
    )
    if not (
        enrichment.cover_url
        or enrichment.description
        or enrichment.version
        or enrichment.developer
        or enrichment.tags
    ):
        return None
    return enrichment


def _enrichment_to_dict(enrichment: Optional[QuiverEnrichment]) -> Optional[dict]:
    if enrichment is None:
        return None
    return {
        "cover_url": enrichment.cover_url,
        "description": enrichment.description,
        "version": enrichment.version,
        "developer": enrichment.developer,
        "tags": list(enrichment.tags),
    }


def _enrichment_from_dict(data: Any) -> Optional[QuiverEnrichment]:
    if not isinstance(data, dict):
        return None
    tags = data.get("tags")
    return QuiverEnrichment(
        cover_url=_safe_url(data.get("cover_url")),
        description=_text(data.get("description")),
        version=_text(data.get("version")),
        developer=_text(data.get("developer")),
        tags=[tag for tag in (_text(value) for value in tags or []) if tag],
    )


# endregion


# region Cache


def _read_cache(path: Optional[Path]) -> dict[str, dict]:
    """O cache gravado; vazio quando ausente, corrompido ou de outra versão."""
    if path is None:
        return {}
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict) or raw.get("version") != CACHE_VERSION:
        return {}
    entries = raw.get("entries")
    if not isinstance(entries, dict):
        return {}
    return {
        key: value
        for key, value in entries.items()
        if isinstance(key, str) and isinstance(value, dict)
    }


def _write_cache(path: Optional[Path], key: str, record: dict) -> None:
    """Grava o cache de forma atômica. Falha de disco não é erro."""
    if path is None:
        return
    target = Path(path)
    temporary = target.with_name(target.name + ".tmp")
    try:
        with _cache_lock:
            entries = _read_cache(target)
            entries[key] = record
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(
                json.dumps(
                    {"version": CACHE_VERSION, "entries": entries},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            temporary.replace(target)
    except OSError as error:
        logging.debug("Não foi possível gravar o cache do catálogo Quiver: %s", error)
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _is_fresh(record: dict, now: Optional[float]) -> bool:
    """True quando o registro está dentro do TTL."""
    fetched_at = record.get("fetched_at")
    if isinstance(fetched_at, bool) or not isinstance(fetched_at, (int, float)):
        return False
    current = time.time() if now is None else now
    return (current - fetched_at) < CACHE_TTL


def _cache_key(
    entry_id: Optional[str],
    repository: Optional[str],
    name: Optional[str],
) -> str:
    """A chave do cache: o identificador mais estável que a entrada tem."""
    if entry_id:
        return f"id:{entry_id.casefold()}"
    if repository:
        return f"repo:{repository.casefold()}"
    return f"name:{(name or '').casefold()}"


def _enrichment_from_record(record: dict) -> Optional[QuiverEnrichment]:
    """O enriquecimento guardado, ou ``None`` se o registro é negativo."""
    if not record.get("found"):
        return None
    return _enrichment_from_dict(record.get("enrichment"))


# endregion


def enrich_entry(
    entry: dict,
    *,
    cache_path: Optional[Path] = None,
    now: Optional[float] = None,
) -> Optional[QuiverEnrichment]:
    """Enriquece uma entrada do `apps.json` do Quiver com o catálogo público.

    ``entry`` é o dicionário de um app, como o `AppCatalogService` do upstream
    lê: ``catalogEntryId``, ``name``, ``repository`` (``owner/repo``),
    ``appIconUrl``. A função é leve: pode ser chamada repetidamente, de
    qualquer worker, e nunca levanta — devolve ``None`` quando o catálogo
    não sabe o app, está fora do ar ou devolve algo inesperado.

    ``cache_path`` é o arquivo de cache (nos testes, um caminho temporário);
    ``now`` fixa o relógio, para exercitar o TTL sem esperar.
    """
    if not isinstance(entry, dict):
        return None

    entry_id = _text(entry.get("catalogEntryId"))
    repository = _text(entry.get("repository"))
    name = _text(entry.get("name"))
    if not entry_id and not repository and not name:
        # Sem identidade não há o que buscar: nenhuma requisição é feita.
        return None

    key = _cache_key(entry_id, repository, name)
    path = _resolve_cache_path(cache_path)
    cached = _read_cache(path)
    record = cached.get(key)
    if record is not None and _is_fresh(record, now):
        return _enrichment_from_record(record)

    try:
        payload = _resolve(entry_id, repository, name)
    except (requests.RequestException, ValueError, KeyError, TypeError) as error:
        # O `RequestException` cobre o `ResponseTooLargeError` do `get_capped`;
        # o `ValueError` cobre o JSON inválido (`JSONDecodeError` é subclasse).
        # A URL não entra no log: a consulta carrega o nome do app.
        logging.debug("Catálogo Quiver indisponível (%s)", type(error).__name__)
        if record is not None:
            return _enrichment_from_record(record)
        return None

    enrichment = _enrichment_from_payload(payload)
    new_record = {
        "fetched_at": time.time() if now is None else now,
        "found": enrichment is not None,
        "enrichment": _enrichment_to_dict(enrichment),
    }
    if record is None or record.get("found") != new_record["found"] or record.get(
        "enrichment"
    ) != new_record["enrichment"]:
        _write_cache(path, key, new_record)
    return enrichment

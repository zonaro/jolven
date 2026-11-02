# model.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Modelo persistido da identidade canônica de um jogo (issue #110).

A identidade mora no próprio JSON do jogo, na chave ``identity``: não existe
arquivo paralelo de cadastro. O dicionário é deliberadamente simples (apenas
strings, listas e números) para atravessar backup, ``FileManager`` e leitura de
arquivos antigos sem conversão especial.

O que a identidade guarda é **evidência**, não um veredito: plataforma, serial,
hashes por algoritmo, IDs externos de provedores e o arquivo de onde cada dado
veio. Quem consome (agrupamento, reconciliação, conquistas) decide a força da
prova com :func:`strong_match` — nunca por semelhança de título.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Optional

#: Versão do formato da identidade. Um registro de versão mais nova é mantido
#: intacto e ignorado para cálculo, do mesmo jeito que ``SPEC_VERSION`` faz com
#: o JSON do jogo: regravar às cegas perderia campos desconhecidos.
IDENTITY_SPEC = 1

CONFIDENCE_NONE = 0
CONFIDENCE_LOW = 1
CONFIDENCE_MEDIUM = 2
CONFIDENCE_HIGH = 3

CONFIDENCE_LABELS = {
    CONFIDENCE_NONE: "none",
    CONFIDENCE_LOW: "low",
    CONFIDENCE_MEDIUM: "medium",
    CONFIDENCE_HIGH: "high",
}

#: Algoritmos aceitos em ``hashes``. ``ra`` é o hash no formato do
#: RetroAchievements e só é gravado quando a regra da plataforma é documentada
#: (ver ``hashing.retroachievements_hash``); ``partial-md5`` é uma impressão
#: digital de arquivos grandes, boa para detectar arquivo movido e inútil para
#: identificar um dump.
HASH_ALGORITHMS = frozenset({"md5", "sha1", "crc32", "ra", "partial-md5"})

#: Provedores cujo ID pode ser guardado em ``external_ids``.
EXTERNAL_PROVIDERS = frozenset(
    {
        "steam",
        "epic",
        "gog",
        "itch",
        "amazon",
        "xbox",
        "lutris",
        "heroic",
        "retroachievements",
        "psn",
    }
)

#: Evidências cujo valor identifica um dump sem ambiguidade. Hashes parciais e
#: serial lido do nome do arquivo ficam de fora: servem para reconciliação de
#: caminho, não para afirmar que dois arquivos são o mesmo jogo.
_STRONG_EVIDENCE_KINDS = frozenset({"hash", "serial", "external_id"})

_MAX_SERIAL = 64
_MAX_HASH = 128
_MAX_ID = 128
_MAX_EVIDENCE = 32
_MAX_EXTERNAL_IDS = 16
_MAX_PLATFORM = 32

_SERIAL_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,31}$")
_HASH_RE = re.compile(r"^[0-9a-f]{8,128}$")
_ID_RE = re.compile(r"^[^\s\x00-\x1f]{1,128}$")
_PLATFORM_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


def empty_identity() -> dict[str, Any]:
    """Uma identidade vazia, pronta para receber evidências."""
    return {
        "spec": IDENTITY_SPEC,
        "platform": "",
        "serial": "",
        "media_id": "",
        "hashes": {},
        "external_ids": {},
        "evidence": [],
        "confidence": CONFIDENCE_NONE,
        "file": {},
        "title_key": "",
    }


def _clean_serial(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    value = value.strip().upper()
    if not value or len(value) > _MAX_SERIAL or not _SERIAL_RE.match(value):
        return ""
    return value


def _clean_hash(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    value = value.strip().lower()
    if not value or len(value) > _MAX_HASH or not _HASH_RE.match(value):
        return ""
    return value


def _clean_id(value: Any) -> str:
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if not value or len(value) > _MAX_ID or not _ID_RE.match(value):
        return ""
    # Um caminho ou URL nunca é ID de loja: o campo é publicado em backup e em
    # integrações, e não deve carregar dados pessoais.
    if "/" in value or "\\" in value or "://" in value:
        return ""
    return value


def _clean_platform(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    value = value.strip().lower()
    if not _PLATFORM_RE.match(value):
        return ""
    return value


def sanitize_identity(value: Any) -> dict[str, Any]:
    """Normaliza uma identidade lida de disco, sem nunca levantar exceção.

    Campo desconhecido ou inválido é descartado, não propagado: um JSON de jogo
    editado à mão ou vindo de uma versão futura não pode derrubar a importação.
    """
    identity = empty_identity()
    if not isinstance(value, dict):
        return identity

    spec = value.get("spec", IDENTITY_SPEC)
    if isinstance(spec, int) and not isinstance(spec, bool) and spec > 0:
        identity["spec"] = spec

    identity["platform"] = _clean_platform(value.get("platform"))
    identity["serial"] = _clean_serial(value.get("serial"))
    identity["media_id"] = _clean_serial(value.get("media_id"))
    identity["title_key"] = _clean_id(value.get("title_key"))[:96].lower()

    hashes = value.get("hashes")
    if isinstance(hashes, dict):
        for algorithm, digest in hashes.items():
            if algorithm not in HASH_ALGORITHMS:
                continue
            cleaned = _clean_hash(digest)
            if cleaned:
                identity["hashes"][algorithm] = cleaned

    external_ids = value.get("external_ids")
    if isinstance(external_ids, dict):
        for provider, identifier in external_ids.items():
            if provider not in EXTERNAL_PROVIDERS:
                continue
            cleaned = _clean_id(identifier)
            if cleaned:
                identity["external_ids"][provider] = cleaned

    evidence = value.get("evidence")
    if isinstance(evidence, list):
        for item in evidence[:_MAX_EVIDENCE]:
            if isinstance(item, dict):
                cleaned = _sanitize_evidence(item)
                if cleaned:
                    identity["evidence"].append(cleaned)

    file_info = value.get("file")
    if isinstance(file_info, dict):
        path = file_info.get("path")
        size = file_info.get("size")
        mtime = file_info.get("mtime")
        if isinstance(path, str) and path.startswith("/") and len(path) <= 4096:
            identity["file"]["path"] = path
        if isinstance(size, int) and not isinstance(size, bool) and size >= 0:
            identity["file"]["size"] = size
        if isinstance(mtime, (int, float)) and not isinstance(mtime, bool):
            identity["file"]["mtime"] = int(mtime)

    identity["confidence"] = compute_confidence(identity)
    return identity


def _sanitize_evidence(item: dict[str, Any]) -> Optional[dict[str, Any]]:
    kind = item.get("kind")
    source = item.get("source")
    if not isinstance(kind, str) or not isinstance(source, str):
        return None
    cleaned: dict[str, Any] = {
        "kind": kind[:32],
        "source": source[:32],
    }
    algorithm = item.get("algo")
    if isinstance(algorithm, str) and algorithm in HASH_ALGORITHMS:
        cleaned["algo"] = algorithm
    provider = item.get("provider")
    if isinstance(provider, str) and provider in EXTERNAL_PROVIDERS:
        cleaned["provider"] = provider
    value = item.get("value")
    if isinstance(value, str):
        cleaned["value"] = value[:128]
    confidence = item.get("confidence")
    if isinstance(confidence, int) and not isinstance(confidence, bool):
        cleaned["confidence"] = max(CONFIDENCE_NONE, min(CONFIDENCE_HIGH, confidence))
    return cleaned


def add_evidence(
    identity: dict[str, Any],
    kind: str,
    source: str,
    *,
    value: str = "",
    algo: str = "",
    provider: str = "",
    confidence: int = CONFIDENCE_MEDIUM,
) -> dict[str, Any]:
    """Acrescenta uma evidência sem duplicar a mesma prova.

    A mesma prova vinda de duas fontes é mantida uma vez só: importações
    repetidas não podem inflar o JSON nem mudar a confiança do jogo.
    """
    entry: dict[str, Any] = {
        "kind": kind[:32],
        "source": source[:32],
        "confidence": max(CONFIDENCE_NONE, min(CONFIDENCE_HIGH, confidence)),
    }
    if value:
        entry["value"] = value[:128]
    if algo:
        entry["algo"] = algo
    if provider:
        entry["provider"] = provider

    for existing in identity["evidence"]:
        if (
            existing.get("kind") == entry["kind"]
            and existing.get("source") == entry["source"]
            and existing.get("value") == entry.get("value")
            and existing.get("algo") == entry.get("algo")
            and existing.get("provider") == entry.get("provider")
        ):
            return identity

    if len(identity["evidence"]) >= _MAX_EVIDENCE:
        identity["evidence"].pop(0)
    identity["evidence"].append(entry)
    identity["confidence"] = compute_confidence(identity)
    return identity


def compute_confidence(identity: dict[str, Any]) -> int:
    """A maior confiança entre as evidências fortes da identidade.

    Contar evidências fracas não promove um jogo: dez palpites continuam sendo
    um palpite. Só hash, serial de mídia ou ID de loja elevam a confiança, e o
    maior deles vence.
    """
    confidence = CONFIDENCE_NONE
    for item in identity.get("evidence") or []:
        if item.get("kind") not in _STRONG_EVIDENCE_KINDS:
            continue
        value = item.get("confidence")
        if isinstance(value, int) and value > confidence:
            confidence = value
    if identity.get("hashes"):
        confidence = max(confidence, CONFIDENCE_MEDIUM)
    if identity.get("serial"):
        confidence = max(confidence, CONFIDENCE_MEDIUM)
    return confidence


def identity_keys(identity: dict[str, Any]) -> list[tuple[str, str]]:
    """Chaves fortes de uma identidade, na ordem de preferência.

    Cada chave é ``(tipo, valor)``: ``serial:<plataforma>:<serial>``,
    ``hash:<algoritmo>:<digest>`` e ``external:<provedor>:<id>``. O hash
    parcial fica de fora de propósito — ele prova que o arquivo é o mesmo,
    não que o jogo é o mesmo.
    """
    keys: list[tuple[str, str]] = []
    platform = identity.get("platform") or ""
    serial = identity.get("serial") or ""
    if platform and serial:
        keys.append(("serial", f"{platform}:{serial}"))
    hashes = identity.get("hashes") or {}
    for algorithm in ("ra", "md5", "sha1"):
        digest = hashes.get(algorithm)
        if digest:
            keys.append(("hash", f"{algorithm}:{digest}"))
    for provider, identifier in (identity.get("external_ids") or {}).items():
        keys.append(("external", f"{provider}:{identifier}"))
    return keys


def strong_match(
    first: dict[str, Any], second: dict[str, Any]
) -> Optional[tuple[str, str]]:
    """A primeira prova de que duas identidades são o mesmo jogo, ou ``None``.

    Regras deliberadamente conservadoras:

    * plataformas diferentes nunca casam (um mesmo título em dois dumps de
      consoles distintos é outro produto);
    * serial só vale com a plataforma junto;
    * hash igual é prova de dump igual — hash diferente nunca é "quase";
    * ID de loja igual é prova mesmo sem hash (o jogo pode não ter sido baixado
      pelo Jolven).
    """
    first_platform = (first.get("platform") or "").lower()
    second_platform = (second.get("platform") or "").lower()
    if first_platform and second_platform and first_platform != second_platform:
        return None

    first_keys = dict(identity_keys(first))
    for kind, value in identity_keys(second):
        if first_keys.get(kind) == value:
            return kind, value
    return None


def merge_identity(
    base: dict[str, Any], extra: dict[str, Any]
) -> dict[str, Any]:
    """Combina duas identidades sem perder prova nem sobrescrever a mais forte.

    ``base`` é a identidade já persistida (autoridade sobre o arquivo e os
    campos preenchidos); ``extra`` é o que a importação acabou de descobrir.
    Campos vazios são preenchidos, hashes e IDs são unidos e uma divergência de
    serial é registrada como evidência em vez de sobrescrever em silêncio.
    """
    merged = sanitize_identity(base)
    incoming = sanitize_identity(extra)

    for field in ("platform", "serial", "media_id", "title_key"):
        if not merged.get(field) and incoming.get(field):
            merged[field] = incoming[field]

    conflict = bool(
        merged.get("serial")
        and incoming.get("serial")
        and merged["serial"] != incoming["serial"]
    )

    for algorithm, digest in incoming.get("hashes", {}).items():
        current = merged["hashes"].get(algorithm)
        if not current:
            merged["hashes"][algorithm] = digest
        elif current != digest:
            conflict = True

    for provider, identifier in incoming.get("external_ids", {}).items():
        current = merged["external_ids"].get(provider)
        if not current:
            merged["external_ids"][provider] = identifier
        elif current != identifier:
            conflict = True

    if incoming.get("file") and not merged.get("file"):
        merged["file"] = dict(incoming["file"])

    for item in incoming.get("evidence", []):
        add_evidence(
            merged,
            item.get("kind", ""),
            item.get("source", ""),
            value=item.get("value", ""),
            algo=item.get("algo", ""),
            provider=item.get("provider", ""),
            confidence=int(item.get("confidence", CONFIDENCE_MEDIUM)),
        )

    if conflict:
        add_evidence(
            merged,
            "conflict",
            "identity",
            value="divergent",
            confidence=CONFIDENCE_LOW,
        )
    merged["confidence"] = compute_confidence(merged)
    return merged


def describe(identity: dict[str, Any]) -> str:
    """Resumo curto e estável para log — nunca inclui caminho do arquivo."""
    if not identity:
        return "sem identidade"
    parts = []
    if identity.get("platform"):
        parts.append(identity["platform"])
    if identity.get("serial"):
        parts.append(identity["serial"])
    hashes = identity.get("hashes") or {}
    for algorithm in ("ra", "md5"):
        if digest := hashes.get(algorithm):
            parts.append(f"{algorithm}:{digest[:12]}")
    if not parts:
        parts.append("sem prova")
    label = CONFIDENCE_LABELS.get(identity.get("confidence", 0), "none")
    return f"{', '.join(parts)} ({label})"


def merge_external_ids(
    identity: dict[str, Any], external_ids: Iterable[tuple[str, str]], source: str
) -> dict[str, Any]:
    """Registra IDs externos descobertos pelo importador como evidência."""
    for provider, identifier in external_ids:
        provider = provider.strip().lower()
        identifier = _clean_id(identifier)
        if not provider or not identifier or provider not in EXTERNAL_PROVIDERS:
            continue
        current = identity["external_ids"].get(provider)
        if current == identifier:
            continue
        if current and current != identifier:
            add_evidence(
                identity,
                "conflict",
                source,
                value=f"{provider}:divergent",
                confidence=CONFIDENCE_LOW,
            )
            continue
        identity["external_ids"][provider] = identifier
        add_evidence(
            identity,
            "external_id",
            source,
            value=f"{provider}:{identifier}",
            provider=provider,
            confidence=CONFIDENCE_HIGH,
        )
    identity["confidence"] = compute_confidence(identity)
    return identity

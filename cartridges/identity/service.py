# service.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Serviço de identidade canônica de jogos (issue #110).

Independente de GTK: recebe nome, caminho e o que o importador já sabe, e
devolve um dicionário de identidade pronto para ser persistido. Roda em worker
(``IdentityManager``); nada aqui toca widget, rede ou GSettings.

Decisões de projeto:

* **Sem varredura em massa.** Só o jogo que está sendo processado é lido, e
  cada arquivo tem teto de bytes (``IdentityLimits``). Abrir a biblioteca não
  calcula hash de nada: jogos carregados do disco chegam com ``skip_save`` e o
  manager os ignora.
* **Cache por assinatura do arquivo.** A chave é caminho + tamanho + mtime; um
  arquivo que não mudou não é lido de novo. O cache é descartável e fica em
  ``cache_dir``, nunca dentro do JSON do jogo.
* **Nada de chute.** Plataforma, serial e hash são gravados só quando lidos do
  cabeçalho, do ISO ou do nome do arquivo — e a evidência diz de onde vieram.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from cartridges.identity import hashing
from cartridges.identity.model import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_NONE,
    add_evidence,
    compute_confidence,
    empty_identity,
    merge_external_ids,
    sanitize_identity,
)
from cartridges.identity.serials import identify_media

MAX_CACHE_ENTRIES = 5000
#: Intervalo mínimo entre gravações do cache, em segundos. O cache é útil, não
#: crítico: gravar a cada jogo importado num lote grande só geraria I/O.
_CACHE_SAVE_INTERVAL = 30.0


@dataclass
class IdentityLimits:
    """Teto de I/O por arquivo e por lote de importação."""

    max_full_hash_bytes: int = hashing.DEFAULT_FULL_HASH_LIMIT
    max_partial_bytes: int = hashing.DEFAULT_PARTIAL_BYTES
    max_files_per_run: int = 2000
    max_bytes_per_run: int = 4 * 1024 * 1024 * 1024
    header_bytes: int = hashing.HEADER_BYTES


@dataclass
class _Budget:
    files: int = 0
    bytes: int = 0

    def reset(self) -> None:
        self.files = 0
        self.bytes = 0


class IdentityService:
    """Calcula e memoriza a identidade de arquivos de jogo."""

    def __init__(
        self,
        cache_path: Optional[Path] = None,
        limits: Optional[IdentityLimits] = None,
    ) -> None:
        self.cache_path = cache_path
        self.limits = limits or IdentityLimits()
        self._cache: Optional[dict[str, dict]] = None
        self._cache_dirty = False
        self._last_save = 0.0
        self._budget = _Budget()

    # -- orçamento -------------------------------------------------------
    def reset_budget(self) -> None:
        """Reabre o orçamento de I/O (chamado no começo de cada importação)."""
        self._budget.reset()

    def _budget_left(self) -> bool:
        if self._budget.files >= self.limits.max_files_per_run:
            return False
        if self._budget.bytes >= self.limits.max_bytes_per_run:
            return False
        return True

    def _charge(self, size: int) -> None:
        self._budget.files += 1
        self._budget.bytes += max(0, size)

    # -- cache -----------------------------------------------------------
    def _load_cache(self) -> dict[str, dict]:
        if self._cache is not None:
            return self._cache
        self._cache = {}
        if self.cache_path is None:
            return self._cache
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                entries = data.get("entries")
                if isinstance(entries, dict):
                    self._cache = {
                        str(key): value
                        for key, value in entries.items()
                        if isinstance(value, dict)
                    }
        except (OSError, ValueError):
            self._cache = {}
        return self._cache

    def _save_cache(self, force: bool = False) -> None:
        if self.cache_path is None or self._cache is None or not self._cache_dirty:
            return
        now = time.monotonic()
        if not force and now - self._last_save < _CACHE_SAVE_INTERVAL:
            return
        entries = self._cache
        if len(entries) > MAX_CACHE_ENTRIES:
            # Dict preserva a ordem de inserção: as entradas mais antigas saem.
            for key in list(entries)[: len(entries) - MAX_CACHE_ENTRIES]:
                entries.pop(key, None)
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.cache_path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps({"version": 1, "entries": entries}, ensure_ascii=False),
                encoding="utf-8",
            )
            os.replace(temporary, self.cache_path)
            self._cache_dirty = False
            self._last_save = now
        except OSError as error:
            logging.debug("Não foi possível salvar o cache de identidade: %s", error)

    def flush(self) -> None:
        """Grava o cache agora (usado ao terminar uma importação)."""
        self._save_cache(force=True)

    @staticmethod
    def _cache_key(path: Path, signature: dict[str, Any]) -> str:
        return f"{path.resolve() if path.is_absolute() else path}|{signature.get('size', 0)}|{signature.get('mtime', 0)}"

    # -- identidade ------------------------------------------------------
    def identify(
        self,
        name: str = "",
        path: Optional[Path] = None,
        *,
        platform_hint: str = "",
        external_ids: Iterable[tuple[str, str]] = (),
        use_cache: bool = True,
    ) -> dict[str, Any]:
        """Identidade do arquivo, combinada com os IDs que o importador trouxe.

        Um jogo de loja sem arquivo local recebe identidade só com os IDs
        externos — o suficiente para vinculação e para conquistas, sem inventar
        plataforma ou hash.
        """
        identity = empty_identity()
        merge_external_ids(identity, external_ids, "importer")

        if path is not None:
            identity = self._identify_file(identity, path, platform_hint, use_cache)

        if name:
            identity["title_key"] = _title_key(name)
        identity["confidence"] = compute_confidence(identity)
        return sanitize_identity(identity)

    def _identify_file(
        self,
        identity: dict[str, Any],
        path: Path,
        platform_hint: str,
        use_cache: bool,
    ) -> dict[str, Any]:
        signature = hashing.file_signature(path)
        if not signature:
            add_evidence(
                identity,
                "file",
                "filesystem",
                value="missing",
                confidence=CONFIDENCE_NONE,
            )
            return identity

        key = self._cache_key(path, signature)
        cache = self._load_cache()
        if use_cache and key in cache:
            cached = sanitize_identity(cache[key])
            if cached.get("file"):
                identity = _merge_cached(identity, cached)
                return identity

        if not self._budget_left():
            logging.debug(
                "Orçamento de identidade esgotado; %s fica sem hash", path.name
            )
            identity["file"] = {"path": str(path), **signature}
            add_evidence(
                identity,
                "budget",
                "service",
                value="exhausted",
                confidence=CONFIDENCE_LOW,
            )
            return identity

        self._charge(signature["size"])
        media = identify_media(path, platform_hint=platform_hint)

        if media.platform:
            identity["platform"] = media.platform
            add_evidence(
                identity,
                "platform",
                media.source or "file",
                value=media.platform,
                confidence=CONFIDENCE_LOW,
            )
        if media.serial:
            identity["serial"] = media.serial
            add_evidence(
                identity,
                "serial",
                media.source or "file",
                value=media.serial,
                confidence=CONFIDENCE_HIGH,
            )
        if media.media_id:
            identity["media_id"] = media.media_id

        hashes = dict(media.hashes)
        if "ra" not in hashes:
            computed, mode = hashing.best_effort_hashes(
                path,
                media.platform,
                full_limit=self.limits.max_full_hash_bytes,
                partial_bytes=self.limits.max_partial_bytes,
            )
            for algorithm, digest in computed.items():
                hashes.setdefault(algorithm, digest)
            if mode.get("mode") == "partial":
                add_evidence(
                    identity,
                    "hash",
                    "file",
                    algo="partial-md5",
                    value=hashes.get("partial-md5", ""),
                    confidence=CONFIDENCE_LOW,
                )

        for algorithm, digest in hashes.items():
            identity["hashes"][algorithm] = digest
            confidence = (
                CONFIDENCE_HIGH
                if algorithm == "ra"
                else CONFIDENCE_MEDIUM
                if algorithm in ("md5", "sha1")
                else CONFIDENCE_LOW
            )
            add_evidence(
                identity,
                "hash",
                "file",
                algo=algorithm,
                value=digest,
                confidence=confidence,
            )

        identity["file"] = {"path": str(path), **signature}
        identity["confidence"] = compute_confidence(identity)

        if use_cache:
            cache[key] = identity
            self._cache_dirty = True
            self._save_cache()

        return identity


def _merge_cached(base: dict[str, Any], cached: dict[str, Any]) -> dict[str, Any]:
    """Usa o resultado do cache sem perder os IDs recém-descobertos."""
    merged = dict(cached)
    for provider, identifier in (base.get("external_ids") or {}).items():
        merged.setdefault("external_ids", {}).setdefault(provider, identifier)
    for item in base.get("evidence") or []:
        if item.get("kind") == "external_id":
            merged.setdefault("evidence", []).append(item)
    merged["confidence"] = compute_confidence(merged)
    return merged


def _title_key(name: str) -> str:
    """Chave de título normalizada, para desempate — nunca prova de identidade."""
    return " ".join((name or "").casefold().split())[:96]

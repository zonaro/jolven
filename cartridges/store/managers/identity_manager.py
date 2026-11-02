# identity_manager.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Manager que calcula a identidade canônica durante a importação (#110).

Roda como manager bloqueante do ``Pipeline``, antes de ``DisplayManager`` e
``FileManager``: quando o card é montado e o JSON é gravado, o jogo já carrega
serial, hash e IDs externos. Assim o agrupamento por identidade (#111) vale
desde a primeira exibição, sem remontar a grade depois.

Nunca toca widget, GSettings ou rede. Jogos carregados do disco chegam com
``skip_save`` e são ignorados: abrir o Jolven não calcula hash de biblioteca.
"""

from __future__ import annotations

import logging
from typing import Any

from cartridges import shared
from cartridges.game import Game
from cartridges.identity import catalog, paths
from cartridges.identity.model import (
    CONFIDENCE_MEDIUM,
    describe,
    merge_external_ids,
    merge_identity,
    sanitize_identity,
)
from cartridges.identity.service import IdentityService, IdentityLimits
from cartridges.store.managers.manager import Manager


class IdentityManager(Manager):
    """Preenche ``Game.identity`` a partir do arquivo e dos IDs da fonte."""

    run_after: tuple[type[Manager], ...] = ()
    blocking = True
    signals: set[str] = set()

    def __init__(self) -> None:
        super().__init__()
        self.service = IdentityService(
            cache_path=shared.cache_dir / "jolven" / "identity-cache.json",
            limits=IdentityLimits(),
        )

    def on_import_start(self) -> None:
        self.service.reset_budget()

    def on_import_end(self) -> None:
        self.service.flush()

    def main(self, game: Game, additional_data: dict[str, Any]) -> None:
        if additional_data.get("skip_save"):
            return

        existing = sanitize_identity(getattr(game, "identity", None))
        external_ids = catalog.external_ids_from_game(game, additional_data)
        platform_hint = catalog.platform_hint_from_source(game, additional_data)
        refresh = bool(additional_data.get("identity_refresh"))

        # Já identificado com prova forte: só completa IDs de loja novos, sem
        # reler o arquivo a cada importação.
        if (
            not refresh
            and existing.get("confidence", 0) >= CONFIDENCE_MEDIUM
            and existing.get("hashes")
        ):
            updated = merge_external_ids(
                sanitize_identity(existing), external_ids, catalog.source_label(game)
            )
            if sanitize_identity(updated) != existing:
                game.identity = sanitize_identity(updated)
            return

        path = paths.game_file_path(game, additional_data)
        computed = self.service.identify(
            game.name or "",
            path,
            platform_hint=platform_hint,
            external_ids=external_ids,
            use_cache=not refresh,
        )

        media_id = catalog.media_id_from_source(game, additional_data)
        if media_id:
            computed["media_id"] = computed.get("media_id") or media_id

        merged = merge_identity(existing, computed)
        if sanitize_identity(merged) == existing:
            return

        game.identity = sanitize_identity(merged)
        logging.debug(
            "Identidade de %s (%s): %s",
            game.name,
            game.game_id,
            describe(game.identity),
        )

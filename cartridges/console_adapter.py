# console_adapter.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Adaptador de leitura Jolven Store -> DTOs imutáveis do ConsoleUI.

Objetivo: expor para a camada WebKit/SPA um retrato estável e serializável do
estado da biblioteca, sem devolver objetos ``Game``/GTK nem expor detalhes de
implementação do Flat.

O adaptador é **somente leitura**. Não cria ``library.json`` paralelo, não usa
``Date.now()`` para gerar ids, e não duplica a pipeline de importação/ajuste
(FileManager, SgdbManager, TheGamesDBManager, DisplayManager). Toda escrita
continua sendo feita pelos mecanismos existentes da Store.

Este módulo não importa ``cartridges.game`` nem qualquer widget GTK, para que
possa ser carregado em testes headless e na sessão do Console sem dependência
de display.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, replace
from typing import Any, Optional


@dataclass(frozen=True)
class GameSummary:
    """Retrato mínimo e imutável de um jogo para listagens do Console."""

    game_id: str
    name: str
    source: str
    base_source: str
    description: Optional[str] = None
    developer: Optional[str] = None
    publisher: Optional[str] = None
    release_date: Optional[str] = None
    genre: Optional[str] = None
    controller_support: Optional[str] = None
    gamepad_recommended: bool = False
    rating: int = 0
    stars: int = 0
    added: int = 0
    last_played: int = 0
    playtime: int = 0
    hidden: bool = False
    removed: bool = False
    blacklisted: bool = False
    zerado: bool = False
    tags: tuple[str, ...] = ()
    has_update: bool = False
    update_url: str = ""
    # Jogos presentes na Store já foram descobertos/instalados por algum
    # importador. Jogos que não estão mais instalados são removidos da Store
    # pelo pipeline, não apenas marcados aqui.
    installed: bool = True
    # O status de execução é preenchido pelo adaptador de sessão quando a
    # camada Game/ProcessSession for conectada (issue #189). Por enquanto,
    # não assumimos que o jogo está rodando.
    running: bool = False


@dataclass(frozen=True)
class GameDetails:
    """Detalhes sob demanda de um jogo. Mais pesado que GameSummary."""

    summary: GameSummary
    steam_appid: Optional[str] = None
    tgdb_id: Optional[int] = None
    tgdb_platform: Optional[str] = None
    tgdb_players: Optional[int] = None
    tgdb_age_rating: Optional[str] = None
    tgdb_coop: Optional[str] = None
    tgdb_screenshots: tuple[str, ...] = ()
    tgdb_fanart: tuple[str, ...] = ()
    notes: str = ""
    version: int = 0
    track_updates: bool = False
    update_available_ts: int = 0
    install_size: int = 0
    mods: tuple[str, ...] = ()


def _as_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return bool(value)


def _as_tags(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple, set)):
        return ()
    return tuple(str(tag) for tag in value if tag)


def _as_str_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple, set)):
        return ()
    return tuple(str(item) for item in value if item)


def _stars(rating: Any) -> int:
    try:
        return max(0, min(5, int(rating or 0)))
    except (TypeError, ValueError):
        return 0


def _zerado(game: Any) -> bool:
    return bool(getattr(game, "removed", False)) and not bool(getattr(game, "blacklisted", False)) and str(getattr(game, "status", "") or "") == "beaten"


def to_summary(game: Any) -> GameSummary:
    """Serializa um ``Game`` (ou objeto duck-typed) em ``GameSummary``.

    Nunca levanta exceção por um campo extra ou ausente: campos faltantes
    recebem defaults compatíveis com o schema histórico do Jolven.
    """

    return GameSummary(
        game_id=str(getattr(game, "game_id", "")),
        name=str(getattr(game, "name", "")),
        source=str(getattr(game, "source", "")),
        base_source=str(getattr(game, "base_source", str(getattr(game, "source", "")).split("_")[0] if str(getattr(game, "source", "")) else "")),
        description=_as_str(getattr(game, "description", None)),
        developer=_as_str(getattr(game, "developer", None)),
        publisher=_as_str(getattr(game, "publisher", None)),
        release_date=_as_str(getattr(game, "release_date", None)),
        genre=_as_str(getattr(game, "genre", None)),
        controller_support=_as_str(getattr(game, "controller_support", None)),
        gamepad_recommended=_as_bool(getattr(game, "gamepad_recommended", False)),
        rating=_as_int(getattr(game, "rating", 0)),
        stars=_stars(getattr(game, "rating", 0)),
        added=_as_int(getattr(game, "added", 0)),
        last_played=_as_int(getattr(game, "last_played", 0)),
        playtime=_as_int(getattr(game, "playtime", 0)),
        hidden=_as_bool(getattr(game, "hidden", False)),
        removed=_as_bool(getattr(game, "removed", False)),
        blacklisted=_as_bool(getattr(game, "blacklisted", False)),
        zerado=_zerado(game),
        tags=_as_tags(getattr(game, "tags", ())),
        has_update=_as_bool(getattr(game, "track_updates", False)) and _as_int(getattr(game, "update_available_ts", 0)) > 0,
        update_url=str(getattr(game, "update_url", "") or ""),
    )


def to_details(game: Any) -> GameDetails:
    summary = to_summary(game)
    return GameDetails(
        summary=summary,
        steam_appid=_as_str(getattr(game, "steam_appid", None)),
        tgdb_id=_as_int(getattr(game, "tgdb_id", 0)) or None,
        tgdb_platform=_as_str(getattr(game, "tgdb_platform", None)),
        tgdb_players=_as_int(getattr(game, "tgdb_players", 0)) or None,
        tgdb_age_rating=_as_str(getattr(game, "tgdb_age_rating", None)),
        tgdb_coop=_as_str(getattr(game, "tgdb_coop", None)),
        tgdb_screenshots=_as_str_tuple(getattr(game, "tgdb_screenshots", ())),
        tgdb_fanart=_as_str_tuple(getattr(game, "tgdb_fanart", ())),
        notes=str(getattr(game, "notes", "") or ""),
        version=_as_int(getattr(game, "version", 0)),
        track_updates=_as_bool(getattr(game, "track_updates", False)),
        update_available_ts=_as_int(getattr(game, "update_available_ts", 0)),
        install_size=_as_int(getattr(game, "install_size", 0)),
        mods=_as_str_tuple(getattr(game, "uzdoom_mods", ())),
    )


def visible_for_console(game: Any, *, include_hidden: bool = False) -> bool:
    """Define se o jogo aparece na biblioteca padrão do Console.

    Jogos removidos da biblioteca (``removed`` sem ``blacklisted``) e jogos
    catalogados como escondidos não devem aparecer. Jogos blacklisted nunca
    aparecem. A decisão de filtrar por fonte/playlist fica com a UI.
    """

    if _as_bool(getattr(game, "blacklisted", False)):
        return False
    if _as_bool(getattr(game, "removed", False)):
        return False
    if not include_hidden and _as_bool(getattr(game, "hidden", False)):
        return False
    return True


class LibrarySnapshot:
    """Retrato imutável da biblioteca com revisão monotônica."""

    def __init__(self, *, revision: int, items: list[GameSummary], total: int, offset: int, limit: int) -> None:
        self.revision = revision
        self.items = tuple(items)
        self.total = total
        self.offset = offset
        self.limit = limit

    def to_dict(self) -> dict[str, Any]:
        return {
            "revision": self.revision,
            "total": self.total,
            "offset": self.offset,
            "limit": self.limit,
            "items": [asdict(item) for item in self.items],
        }


def _name_sort_key(name: Any) -> str:
    return str(name or "").strip().casefold().removeprefix("the ")


def list_snapshot(
    games: Any,
    *,
    revision: int = 0,
    offset: int = 0,
    limit: int = 100,
    include_hidden: bool = False,
) -> LibrarySnapshot:
    """Gera um snapshot limitado/paginado da biblioteca.

    ``games`` deve ser iterável de ``Game`` (ou duck-typed equivalente).
    A revisão é provida pelo chamador (normalmente ``shared.store.revision``).
    O snapshot não é fortemente consistente com alterações concorrentes; para
    isso, o SPA deve lidar com eventos ``library.changed`` em conjunto com
    invalidação de revisão.
    """

    visible = [game for game in games if visible_for_console(game, include_hidden=include_hidden)]
    # Espelha a ordenação padrão da Flat: last_played decrescente com
    # desempate por name (case-insensitive, ignorando "the " inicial).
    visible.sort(key=lambda game: (-_as_int(getattr(game, "last_played", 0)), _name_sort_key(getattr(game, "name", ""))))
    total = len(visible)
    sliced = visible[offset : offset + limit]
    return LibrarySnapshot(
        revision=revision,
        items=[to_summary(game) for game in sliced],
        total=total,
        offset=offset,
        limit=limit,
    )


def list_summaries(
    games: Any,
    *,
    offset: int = 0,
    limit: int = 100,
    include_hidden: bool = False,
) -> list[GameSummary]:
    """Lista resumos imutáveis sem metadados de paginação/revisão."""

    snapshot = list_snapshot(
        games,
        revision=0,
        offset=offset,
        limit=limit,
        include_hidden=include_hidden,
    )
    return list(snapshot.items)


def find_by_id(games: Any, game_id: str) -> Optional[Any]:
    """Localiza um jogo na coleção iterável pelo ``game_id`` real."""

    for game in games:
        if str(getattr(game, "game_id", "")) == game_id:
            return game
    return None


def details_by_id(games: Any, game_id: str) -> Optional[GameDetails]:
    game = find_by_id(games, game_id)
    if game is None:
        return None
    return to_details(game)


def summary_by_id(games: Any, game_id: str) -> Optional[GameSummary]:
    game = find_by_id(games, game_id)
    if game is None:
        return None
    return to_summary(game)

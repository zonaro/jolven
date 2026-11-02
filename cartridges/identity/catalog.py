# catalog.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""IDs externos e dica de plataforma que a importação já conhece (issue #110).

Nenhuma chamada de rede aqui. O que este módulo faz é ler o que o importador
descobriu — ``steam_appid`` nos dados adicionais, o prefixo do ``game_id`` que
codifica a loja, o core do RetroArch, o título do Cemu — e transformar isso em
``(provedor, id)`` e ``platform_hint``. Quem enriquece com RetroAchievements ou
lojas é o serviço de conquistas (#112/#119), que também grava aqui a evidência.

IDs inválidos são descartados: ``Game.game_id`` é gerado por nós, mas nenhum
consumidor deve confiar cegamente nele ao montar URL ou backup.
"""

from __future__ import annotations

import re
from pathlib import PurePath
from typing import Any, Optional

_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_STEAM_APPID_RE = re.compile(r"^\d{1,10}$")

#: Prefixos de ``base_source`` (ou ``source``) que carregam ID de loja.
_SOURCE_PROVIDERS = {
    "steam": "steam",
    "epic": "epic",
    "legendary": "epic",
    "gog": "gog",
    "heroic": "heroic",
    "itch": "itch",
    "lutris": "lutris",
    "amazon": "amazon",
    "xbox": "xbox",
    "xcloud": "xbox",
}

#: ID de loja embutido no ``game_id`` além do prefixo da fonte. A Heroic é a
#: única que acrescenta o serviço (``heroic_epic_<id>``).
_HEROIC_SERVICES = {"epic": "epic", "gog": "gog", "amazon": "amazon", "sideload": ""}

#: Nome do core do RetroArch → plataforma. Só o que é inequívoco: um core
#: multi-sistema devolve "" e a plataforma fica para o cabeçalho do arquivo.
_CORE_PLATFORMS = (
    ("snes9x", "snes"),
    ("bsnes", "snes"),
    ("mesen", "nes"),
    ("fceumm", "nes"),
    ("nestopia", "nes"),
    ("genesis_plus_gx", "genesis"),
    ("picodrive", "genesis"),
    ("gambatte", "gb"),
    ("sameboy", "gb"),
    ("mgba", "gba"),
    ("vba_next", "gba"),
    ("desmume", "nds"),
    ("melonds", "nds"),
    ("mupen64plus", "n64"),
    ("parallel_n64", "n64"),
    ("pcsx_rearmed", "psx"),
    ("swanstation", "psx"),
    ("beetle_psx", "psx"),
    ("ppsspp", "psp"),
    ("dolphin", "gamecube"),
    ("flycast", "dreamcast"),
    ("yabause", "saturn"),
    ("beetle_saturn", "saturn"),
    ("mednafen_pce", "pcengine"),
    ("handy", "lynx"),
    ("prosystem", "atari7800"),
    ("stella", "atari2600"),
)


def _clean_identifier(value: Any) -> str:
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if not value or not _TOKEN_RE.match(value):
        return ""
    if "://" in value or "/" in value:
        return ""
    return value


def external_ids_from_game(
    game: Any, additional_data: Optional[dict] = None
) -> list[tuple[str, str]]:
    """IDs de loja conhecidos para o jogo, deduplicados e validados."""
    found: dict[str, str] = {}
    additional_data = additional_data or {}

    steam_appid = additional_data.get("steam_appid") or getattr(
        game, "steam_appid", None
    )
    steam_appid = _clean_identifier(steam_appid)
    if steam_appid and _STEAM_APPID_RE.match(steam_appid):
        found["steam"] = steam_appid

    extra = additional_data.get("external_ids")
    if isinstance(extra, dict):
        for provider, identifier in extra.items():
            provider = str(provider).strip().lower()
            clean = _clean_identifier(identifier)
            if provider and clean:
                found.setdefault(provider, clean)

    game_id = getattr(game, "game_id", "") or ""
    source = getattr(game, "base_source", "") or (
        getattr(game, "source", "") or ""
    ).split("_")[0]

    if source == "heroic" and game_id.startswith("heroic_"):
        parts = game_id.split("_", 2)
        if len(parts) == 3:
            provider = _HEROIC_SERVICES.get(parts[1], "")
            if provider and parts[2]:
                found.setdefault(provider, _clean_identifier(parts[2]))
    elif source == "lutris" and game_id.startswith("lutris_"):
        parts = game_id.split("_", 2)
        if len(parts) == 3 and parts[2]:
            found.setdefault("lutris", _clean_identifier(parts[2]))
    else:
        provider = _SOURCE_PROVIDERS.get(source, "")
        if provider and game_id.startswith(f"{source}_"):
            identifier = _clean_identifier(game_id[len(source) + 1 :])
            if identifier:
                found.setdefault(provider, identifier)

    return [(provider, identifier) for provider, identifier in found.items() if identifier]


def platform_hint_from_source(
    game: Any, additional_data: Optional[dict] = None
) -> str:
    """Plataforma que a fonte já sabe, quando ela sabe.

    É só uma dica: o cabeçalho do arquivo sempre vence. Um jogo de Steam não
    recebe plataforma aqui — "PC" não é uma plataforma de emulador e não ajuda
    a identificar dump.
    """
    additional_data = additional_data or {}
    hint = additional_data.get("platform_hint")
    if isinstance(hint, str) and hint:
        return hint.strip().lower()

    source = getattr(game, "base_source", "") or ""
    if source == "cemu":
        return "wiiu"
    if source == "dolphin":
        # O Dolphin cobre GameCube e Wii; o código do jogo não separa os dois.
        return ""
    if source == "retroarch":
        return _platform_from_core(getattr(game, "executable", "") or "")
    return ""


def _platform_from_core(executable: str) -> str:
    if not executable:
        return ""
    lowered = executable.lower()
    if "_libretro" not in lowered:
        return ""
    for token, platform in _CORE_PLATFORMS:
        if token in lowered:
            return platform
    return ""


def media_id_from_source(
    game: Any, additional_data: Optional[dict] = None
) -> str:
    """Código de mídia que o importador já conhece (title ID do Cemu, etc.)."""
    additional_data = additional_data or {}
    media_id = additional_data.get("media_id")
    if isinstance(media_id, str) and media_id:
        return media_id
    if getattr(game, "base_source", "") == "cemu":
        game_id = getattr(game, "game_id", "") or ""
        if game_id.startswith("cemu_"):
            return game_id[len("cemu_") :]
    if getattr(game, "base_source", "") == "dolphin":
        game_id = getattr(game, "game_id", "") or ""
        if game_id.startswith("dolphin_"):
            return game_id[len("dolphin_") :]
    return ""


def source_label(game: Any) -> str:
    """Nome legível da fonte, usado em evidência e UI."""
    base = getattr(game, "base_source", "") or ""
    return base or "unknown"

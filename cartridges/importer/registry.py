# SPDX-License-Identifier: GPL-3.0-or-later
"""Registro central das fontes de importação.

Antes desta lista existir, ``CartridgesApplication.on_import_action`` e
``CartridgesPreferences`` mantinham cada um a sua própria sequência de fontes.
As duas divergiram: ``WaydroidSource`` era importado em ``main.py`` mas nunca
entrava no fluxo de importação, então o Waydroid nunca era varrido mesmo
instalado. Uma única fonte de verdade (issue #71, subissue #93) evita que a
reimportação manual e a tela de Preferências voltem a discordar.

A ordem é só de leitura humana: cada fonte roda na sua própria thread e a
detecção acontece ao resolver as ``locations`` de cada instância.
"""

from __future__ import annotations

import logging

from cartridges.importer.appimage_source import AppimageSource
from cartridges.importer.bottles_source import BottlesSource
from cartridges.importer.cemu_source import CemuSource
from cartridges.importer.desktop_source import DesktopSource
from cartridges.importer.dolphin_source import DolphinSource
from cartridges.importer.eden_source import EdenSource
from cartridges.importer.epic_source import EpicSource
from cartridges.importer.flatpak_source import FlatpakSource
from cartridges.importer.heroic_source import HeroicSource
from cartridges.importer.itch_source import ItchSource
from cartridges.importer.legendary_source import LegendarySource
from cartridges.importer.lutris_source import LutrisSource
from cartridges.importer.quiver_source import QuiverSource
from cartridges.importer.retroarch_source import RetroarchSource
from cartridges.importer.shortcuts_source import ShortcutsSource
from cartridges.importer.source import Source
from cartridges.importer.steam_source import SteamSource
from cartridges.importer.twintail_source import TwintailSource
from cartridges.importer.uzdoom_source import UzdoomSource
from cartridges.importer.waydroid_source import WaydroidSource
from cartridges.importer.yuzu_source import YuzuSource

#: Toda fonte de jogos suportada. O ``source_id`` de cada classe é a chave do
#: schema que liga e desliga a fonte.
SOURCE_CLASSES: tuple[type[Source], ...] = (
    AppimageSource,
    BottlesSource,
    CemuSource,
    DesktopSource,
    DolphinSource,
    EdenSource,
    EpicSource,
    FlatpakSource,
    HeroicSource,
    ItchSource,
    LegendarySource,
    LutrisSource,
    QuiverSource,
    RetroarchSource,
    ShortcutsSource,
    SteamSource,
    TwintailSource,
    UzdoomSource,
    WaydroidSource,
    YuzuSource,
)


def enabled_source_classes(schema) -> list[type[Source]]:
    """Classes das fontes ligadas nas preferências.

    Uma chave ausente no schema conta como desligada: é o mesmo critério que
    ``Importer.remove_games`` usa para decidir se pode podar a fonte.
    """
    return [
        source_class
        for source_class in SOURCE_CLASSES
        if schema.get_boolean(source_class.source_id)
    ]


def build_sources(schema=None) -> list[Source]:
    """Instancia as fontes ligadas, reavaliando a detecção a cada chamada.

    As ``locations`` são resolvidas sob demanda por ``Source.__iter__``, então
    uma plataforma instalada depois da última importação aparece aqui sem
    reiniciar o Jolven.
    """
    if schema is None:
        from cartridges import shared

        schema = shared.schema

    sources: list[Source] = []
    for source_class in enabled_source_classes(schema):
        try:
            sources.append(source_class())
        except Exception:  # pylint: disable=broad-exception-caught
            # Uma fonte com construtor quebrado não pode derrubar as demais.
            logging.exception(
                "Não foi possível preparar a fonte %s", source_class.source_id
            )
    return sources

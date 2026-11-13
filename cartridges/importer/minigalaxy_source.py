# minigalaxy_source.py
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

"""Source do Minigalaxy: importa a biblioteca instalada localmente.

A leitura dos formatos fica em :mod:`cartridges.importer.minigalaxy` (o contrato
puro) e a montagem do comando em :mod:`cartridges.importer.minigalaxy_launch`.
Aqui ficam as ``locations``, a varredura e a criação dos :class:`Game`.

Nenhuma pasta de instalação é assumida como única:

* ``minigalaxy-location`` aponta para o diretório de configuração (o que guarda
  ``config.json``);
* ``minigalaxy-games-location`` aponta para a pasta onde os jogos vivem. O
  padrão deriva de ``install_dir`` no ``config.json`` (ou ``GOG Games``), e o
  usuário pode substituí-lo nas preferências.

A precedência é a do próprio :class:`~cartridges.importer.location.Location` —
nenhum mecanismo paralelo é criado:

1. o override manual no GSettings (``minigalaxy-location`` e
   ``minigalaxy-games-location``), escolhido na tela de preferências;
2. o ``install_dir`` detectado no ``config.json`` do cliente escolhido;
3. o padrão do Minigalaxy, ``~/GOG Games``.

Os candidatos de configuração são avaliados em ordem determinística e o
primeiro válido vence; clientes presentes ao mesmo tempo nunca são
misturados. A ordem é: config do sandbox/nativo, config do host (um Jolven
em Flatpak) e, por último, o config do Minigalaxy em Flatpak
(``~/.var/app/io.github.sharkwouter.Minigalaxy/config/minigalaxy``).

A pasta de jogos é enumerada apenas um nível, pelos subdiretórios imediatos
da raiz resolvida: ``scan_install_dir`` nunca desce recursivamente e rejeita
links simbólicos que apontem para fora da instalação. Um ``install_dir``
derivado do ``config.json`` que seja o ``~`` (ou que o contenha) é
descartado em favor do padrão. Um ``config.json`` presente, porém ilegível,
retém a fonte com ``SourceScanError`` em vez de varrer um palpite — a poda
da biblioteca fica retida porque a fonte não é escaneada.
"""

from __future__ import annotations

import builtins
import logging
import shutil
from pathlib import Path
from typing import NamedTuple, Tuple

from cartridges import shared
from cartridges.game import Game
from cartridges.importer.location import Location, LocationSubPath
from cartridges.importer.minigalaxy import (
    MINIGALAXY_CACHE_DIR_NAME,
    default_install_dir,
    read_install_dir,
    scan_install_dir,
    stable_game_ids,
)
from cartridges.importer.minigalaxy_launch import (
    fps_environment,
    launch_working_directory,
    make_executable,
)
from cartridges.importer.source import (
    Source,
    SourceIterable,
    SourceScanError,
)

# O launcher roda ``gettext.install`` antes de importar qualquer módulo do
# app; o fallback mantém este módulo importável em testes e ferramentas sem
# catálogo — o mesmo guarda de ``cartridges/importer/appimage_source.py``.
if not hasattr(builtins, "_"):
    builtins._ = lambda text: text  # type: ignore[attr-defined]


def _available_programs() -> Tuple[str, ...]:
    """Programas do host que o launcher detectado precisa existir.

    Só consulta o ``PATH`` do processo (sem GTK e sem rede), no espírito do
    issue #167: nenhuma dependência de GNOME é tocada para esta checagem.
    """

    return tuple(
        name
        for name in ("wine", "dosbox", "scummvm")
        if shutil.which(name) is not None
    )


class MinigalaxyLocations(NamedTuple):
    """As duas pastas que a fonte precisa: configuração e instalação."""

    config: Location
    install: Location


def _is_unsafe_install_dir(candidate: Path) -> bool:
    """Recusa uma raiz derivada que seja o ``~`` ou que o contenha.

    Um ``install_dir`` igual ao diretório pessoal (ou ancestral dele) faria
    a varredura enumerar pastas alheias ao Minigalaxy; mesmo o contrato
    olhando um nível só, a raiz derivada deve ficar fora do ``~``. O
    override manual no GSettings não passa por aqui: escolha explícita do
    usuário é respeitada.
    """

    try:
        home = Path.home().resolve(strict=False)
        resolved = candidate.expanduser().resolve(strict=False)
    except OSError:
        return True
    return home == resolved or home.is_relative_to(resolved)


def _install_candidates(config: Location) -> Tuple[Path, ...]:
    """Pasta de jogos derivada de ``config.json``, com o padrão do cliente.

    A raiz derivada entra na frente do padrão para que um apontamento
    válido vença; um ``install_dir`` relativo, inseguro ou que aponte para
    algo que não é diretório é rejeitado pelo ``check_candidate`` e a
    localização cai no padrão sem deixar de resolver.
    """

    try:
        config_path = config["config.json"]
        install_dir = read_install_dir(config_path)
    except Exception as error:  # pylint: disable=broad-exception-caught
        logging.debug(
            "Não foi possível ler install_dir de %s: %s",
            config.schema_key,
            error,
        )
        return (default_install_dir(),)
    if install_dir is None:
        return (default_install_dir(),)
    if _is_unsafe_install_dir(install_dir):
        logging.debug(
            "install_dir de %s contém o diretório pessoal; usando o padrão",
            config.schema_key,
        )
        return (default_install_dir(),)
    return (install_dir, default_install_dir())


def _config_is_readable(config_path: Path) -> bool:
    """Confere se ``config.json`` pode ser aberto, sem ler o conteúdo.

    A abertura não consome bytes: o ``refresh_token`` do cliente nunca é
    tocado aqui nem em lugar nenhum deste módulo.
    """

    try:
        with config_path.open("rb"):
            return True
    except PermissionError:
        return False
    except OSError:
        return True


class MinigalaxySourceIterable(SourceIterable):
    """Produz ``(Game, additional_data)`` a partir da biblioteca local."""

    source: "MinigalaxySource"

    def __iter__(self):
        source = self.source
        config_path = source.locations.config["config.json"]
        # Um config.json presente mas ilegível não pode virar um palpite de
        # "~/GOG Games": sem a localização verdadeira, varrer e podar seria
        # arriscado. A fonte fica retida com um erro explicável.
        if not _config_is_readable(config_path):
            raise SourceScanError(
                _("Não foi possível ler a configuração do Minigalaxy"),
                _("O arquivo de configuração existe, mas o acesso foi negado"),
            )
        config_dir = config_path.parent
        install_root = source.locations.install.root
        cache_dir = shared.host_cache_dir / MINIGALAXY_CACHE_DIR_NAME

        scan = scan_install_dir(
            install_root,
            config_dir=config_dir,
            cache_dir=cache_dir,
            available_programs=_available_programs(),
        )
        if not scan.complete:
            raise SourceScanError(
                _("Não foi possível examinar a biblioteca do Minigalaxy"),
                scan.reason
                or _("A pasta onde os jogos ficam não pôde ser lida por completo"),
            )

        game_ids = stable_game_ids(scan.games)
        for game in scan.games:
            yield self._make_game(source, game, game_ids[game.directory])

    def _make_game(self, source, game, game_id: str) -> tuple[Game, dict]:
        preferences = game.preferences
        values = {
            "added": shared.import_time if shared.import_time is not None else 0,
            "name": game.name,
            "source": source.source_id,
            "game_id": game_id,
            "executable": make_executable(game),
            "hidden": preferences.hidden,
            "launch_working_directory": launch_working_directory(game),
        }
        produced = Game(values)
        # Só força quando ligado: a ausência da chave no Minigalaxy não pode
        # desautorizar o padrão global de GameMode/MangoHud do Jolven.
        if preferences.use_gamemode:
            produced.game_mode_use_gamemode = True
        if preferences.use_mangohud:
            produced.game_mode_use_mangohud = True

        environment = fps_environment(preferences)
        if game.launcher == "wine":
            environment = {
                **environment,
                "WINEPREFIX": str(game.directory / "prefix"),
            }
        if environment:
            produced.launch_environment = environment

        additional_data = {}
        if game.artwork:
            additional_data["local_image_path"] = str(game.artwork)
        if game.icon:
            additional_data["local_icon_path"] = str(game.icon)
        if game.gog_id:
            additional_data["external_ids"] = {"gog": game.gog_id}
        return produced, additional_data


class MinigalaxySource(Source):
    """Fonte de jogos instalados pelo Minigalaxy (GOG)."""

    source_id = "minigalaxy"
    name = _("Minigalaxy")  # pylint: disable=undefined-variable
    iterable_class = MinigalaxySourceIterable
    available_on = {"linux"}

    locations: MinigalaxyLocations

    def __init__(self) -> None:
        super().__init__()
        config = Location(
            schema_key="minigalaxy-location",
            candidates=(
                shared.config_dir / "minigalaxy",
                shared.host_config_dir / "minigalaxy",
                # O Minigalaxy em Flatpak guarda o config sob ~/.var/app/<id>:
                # por último na ordem para que o nativo vença quando houver os
                # dois clientes instalados.
                shared.flatpak_dir
                / "io.github.sharkwouter.Minigalaxy"
                / "config"
                / "minigalaxy",
            ),
            paths={"config.json": LocationSubPath("config.json")},
            invalid_subtitle=Location.CONFIG_INVALID_SUBTITLE,
        )
        install = Location(
            schema_key="minigalaxy-games-location",
            candidates=lambda: _install_candidates(config),
            paths={".": LocationSubPath(".", is_directory=True)},
            invalid_subtitle=Location.DATA_INVALID_SUBTITLE,
        )
        self.locations = MinigalaxyLocations(config=config, install=install)

    def make_executable(self, *args, **kwargs) -> str:
        """O comando é montado por jogo na varredura (cada um o seu)."""

        return ""

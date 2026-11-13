# minigalaxy.py
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

"""Leitura offline da biblioteca local do Minigalaxy.

Contrato puro (sem ``gi``, sem GTK e sem importar código do Minigalaxy) dos
formatos que o cliente grava no disco. Implementação própria baseada nos
formatos observados no upstream ``sharkwouter/minigalaxy`` (master, commit
``f23e237``):

* ``$XDG_CONFIG_HOME/minigalaxy/config.json`` guarda ``install_dir`` **e o
  ``refresh_token``**. Apenas ``install_dir`` é lido; o restante do arquivo
  nunca é interpretado, copiado, registrado em log ou persistido.
* ``$XDG_CONFIG_HOME/minigalaxy/games/<pasta>.json`` guarda preferências por
  jogo (``custom_wine``, ``last_launch_option``, ``use_gamemode``...). Somente
  as chaves necessárias são lidas; ``command`` e ``variable`` são ignorados de
  propósito (execução arbitrária exige decisão explícita do usuário).
* Jogos Linux têm um arquivo ``gameinfo``: nome na primeira linha e ID GOG na
  quinta linha (0 ou vazio quando desconhecido).
* Jogos Windows instalados sob Wine têm ``goggame-<id>.info`` em JSON com BOM
  opcional (``utf-8-sig``), contendo ``name``, ``gameId`` e ``playTasks``.
* A capa local de um jogo é ``<instalação>/thumbnail.jpg``; o ícone em cache é
  ``$XDG_CACHE_HOME/minigalaxy/icons/<gog_id>.png``.

Regra de atualização: se o Minigalaxy mudar esses formatos, este módulo e as
fixtures de ``tests/fixtures/minigalaxy`` devem ser revistos junto com o novo
commit do upstream registrado em ``SUPPORTED_UPSTREAM``.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Literal, Optional

#: Commit do Minigalaxy cujos formatos este módulo reproduz.
SUPPORTED_UPSTREAM = "f23e237"

#: Teto de leitura de qualquer metadado. Arquivos maiores são tratados como
#: inválidos em vez de carregados na memória.
MAX_METADATA_BYTES = 1024 * 1024

#: Nome padrão usado pelo Minigalaxy quando o usuário não configura a pasta.
DEFAULT_INSTALL_DIR_NAME = "GOG Games"

#: Subpasta de cache do Minigalaxy, onde ficam os ícones dos jogos.
MINIGALAXY_CACHE_DIR_NAME = "minigalaxy"

GOGGAME_INFO_PATTERN = re.compile(r"^goggame-(?P<game_id>[0-9]*)\.info$")
DOSBOX_CONFIG_PATTERN = re.compile(r"^dosbox_?([A-Za-z]|[0-9])+(_single)?\.conf$")
SCUMMVM_CONFIG_PATTERN = re.compile(r"^.*\.ini$")
_UNSAFE_ID_CHARS = re.compile(r"[^a-z0-9]+")

LauncherKind = Literal[
    "start_script",
    "dosbox",
    "scummvm",
    "wine",
    "final_resort",
    "unavailable",
]
PlatformKind = Literal["linux", "windows"]


class InvalidMinigalaxyConfig(ValueError):
    """``config.json`` ilegível, truncado ou com ``install_dir`` inválido."""


class InvalidGameMetadata(ValueError):
    """Metadados de um jogo não puderam ser lidos; o item deve ser pulado."""


@dataclass(frozen=True)
class MinigalaxyPreferences:
    """Subconjunto de preferências por jogo que o Jolven respeita."""

    custom_wine: Optional[str] = None
    last_launch_option: Optional[str] = None
    use_mangohud: bool = False
    use_gamemode: bool = False
    show_fps: bool = False
    hidden: bool = False


@dataclass(frozen=True)
class MinigalaxyGame:
    """Jogo instalado, já normalizado e independente do cliente."""

    gog_id: Optional[str]
    name: str
    platform: PlatformKind
    directory: Path
    launcher: LauncherKind
    artwork: Optional[Path] = None
    icon: Optional[Path] = None
    preferences: MinigalaxyPreferences = field(default_factory=MinigalaxyPreferences)
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScanFailure:
    """Item descartado com o motivo, sem interromper a varredura inteira."""

    directory: Path
    reason: str


@dataclass(frozen=True)
class MinigalaxyScan:
    """Resultado de uma varredura.

    ``complete`` só é verdadeiro quando a raiz foi lida por inteiro. Um scan
    incompleto nunca deve autorizar poda de jogos.
    """

    install_dir: Path
    games: tuple[MinigalaxyGame, ...]
    failures: tuple[ScanFailure, ...]
    complete: bool
    reason: Optional[str] = None


def default_install_dir(home: Optional[Path] = None) -> Path:
    """Pasta de instalação padrão do Minigalaxy."""

    return (home or Path.home()) / DEFAULT_INSTALL_DIR_NAME


def read_install_dir(config_path: Path) -> Optional[Path]:
    """Lê **somente** ``install_dir`` de um ``config.json``.

    Devolve ``None`` quando a chave não existe ou está vazia, para que o
    chamador aplique o padrão. Nunca expõe outros valores do arquivo.
    """

    raw = _read_metadata_bytes(config_path)
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InvalidMinigalaxyConfig(
            "config.json ilegível ou truncado"
        ) from error
    if not isinstance(data, dict):
        raise InvalidMinigalaxyConfig("config.json não é um objeto JSON")
    value = data.get("install_dir")
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise InvalidMinigalaxyConfig("install_dir não é texto")
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        raise InvalidMinigalaxyConfig("install_dir não é um caminho absoluto")
    return candidate


def read_preferences(config_dir: Optional[Path], game_directory: Path) -> MinigalaxyPreferences:
    """Preferências por jogo, quando o arquivo existir.

    Chaves desconhecidas e valores de tipo inesperado são ignorados. O arquivo
    malformado nunca derruba o jogo: ele só perde as preferências.
    """

    if config_dir is None:
        return MinigalaxyPreferences()
    status_file = config_dir / "games" / f"{game_directory.name}.json"
    try:
        raw = _read_metadata_bytes(status_file)
        data = json.loads(raw.decode("utf-8-sig"))
    except (OSError, InvalidGameMetadata, UnicodeDecodeError, json.JSONDecodeError):
        return MinigalaxyPreferences()
    return parse_preferences(data)


def parse_preferences(data: object) -> MinigalaxyPreferences:
    """Normaliza preferências já decodificadas (função pura)."""

    if not isinstance(data, dict):
        return MinigalaxyPreferences()
    custom_wine = data.get("custom_wine")
    last_launch = data.get("last_launch_option")
    return MinigalaxyPreferences(
        custom_wine=custom_wine if isinstance(custom_wine, str) and custom_wine else None,
        last_launch_option=last_launch if isinstance(last_launch, str) else None,
        use_mangohud=_as_bool(data.get("use_mangohud")),
        use_gamemode=_as_bool(data.get("use_gamemode")),
        show_fps=_as_bool(data.get("show_fps")),
        hidden=_as_bool(data.get("hide_game")),
    )


def parse_gameinfo(path: Path) -> tuple[str, Optional[str]]:
    """Lê ``gameinfo`` e devolve ``(nome, gog_id)``.

    O formato é posicional: nome na primeira linha, ID na quinta. Linhas extras
    são aceitas e ignoradas. ID vazio ou ``0`` vira ``None``.
    """

    raw = _read_metadata_bytes(path)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise InvalidGameMetadata("gameinfo não está em UTF-8") from error
    lines = text.splitlines()
    if len(lines) < 5:
        raise InvalidGameMetadata("gameinfo truncado")
    name = lines[0].strip()
    if not name:
        raise InvalidGameMetadata("gameinfo sem nome")
    raw_id = lines[4].strip()
    if not raw_id or raw_id == "0":
        return name, None
    if not raw_id.isdigit():
        raise InvalidGameMetadata("gameinfo com ID GOG inválido")
    return name, raw_id


def parse_goggame_info(path: Path) -> tuple[str, Optional[str], Optional[dict]]:
    """Lê ``goggame-<id>.info`` e devolve ``(nome, id, tarefa primária)``."""

    raw = _read_metadata_bytes(path)
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InvalidGameMetadata("goggame ilegível") from error
    if not isinstance(data, dict):
        raise InvalidGameMetadata("goggame não é um objeto JSON")
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise InvalidGameMetadata("goggame sem nome")
    game_id = data.get("gameId")
    if isinstance(game_id, bool) or not isinstance(game_id, (str, int)):
        game_id = None
    else:
        game_id = str(game_id).strip() or None
        if game_id is not None and not game_id.isdigit():
            game_id = None
        elif game_id == "0":
            game_id = None
    path_match = GOGGAME_INFO_PATTERN.match(path.name)
    if game_id is None and path_match:
        fallback = path_match.group("game_id")
        game_id = fallback if fallback and fallback != "0" else None
    tasks = data.get("playTasks")
    if not isinstance(tasks, list) or not tasks:
        raise InvalidGameMetadata("goggame sem playTasks")
    primary = None
    for task in tasks:
        if isinstance(task, dict) and task.get("isPrimary") is True:
            primary = task
            break
    return name.strip(), game_id, primary


def detect_launcher(
    directory: Path,
    entries: Iterable[str],
    available_programs: Iterable[str],
) -> LauncherKind:
    """Decide como o jogo inicia, imitando a ordem do Minigalaxy.

    ``available_programs`` é o conjunto de binários do host já verificados
    (``wine``, ``dosbox``, ``scummvm``). A ordem reproduz
    ``determine_launcher_type`` do upstream.
    """

    names = set(entries)
    programs = set(available_programs)
    if any(DOSBOX_CONFIG_PATTERN.match(name) for name in names) and "dosbox" in programs:
        return "dosbox"
    if any(SCUMMVM_CONFIG_PATTERN.match(name) for name in names) and "scummvm" in programs:
        return "scummvm"
    if "start.sh" in names:
        return "start_script"
    if "prefix" in names and "wine" in programs:
        return "wine"
    if (directory / "game").is_dir():
        return "final_resort"
    return "unavailable"


def scan_install_dir(
    install_dir: Path,
    config_dir: Optional[Path] = None,
    cache_dir: Optional[Path] = None,
    available_programs: Iterable[str] = (),
) -> MinigalaxyScan:
    """Enumera somente subdiretórios imediatos da instalação.

    Pasta inexistente, ilegível ou que não é diretório produz
    ``complete=False``: o chamador deve tratar como scan inseguro e não podar.
    Falha isolada de um jogo vira ``ScanFailure`` e mantém o scan completo.
    """

    root = install_dir.expanduser()
    try:
        resolved_root = root.resolve(strict=True)
        if not resolved_root.is_dir():
            raise NotADirectoryError
        children = sorted(resolved_root.iterdir(), key=lambda item: item.name)
    except OSError as error:
        return MinigalaxyScan(
            install_dir=root,
            games=(),
            failures=(),
            complete=False,
            reason=f"pasta de instalação indisponível: {error.__class__.__name__}",
        )

    games: list[MinigalaxyGame] = []
    failures: list[ScanFailure] = []
    seen_directories: list[Path] = []
    for child in children:
        if child.name.startswith(".") or child.name == "installer":
            continue
        try:
            if child.is_symlink():
                target = child.resolve(strict=True)
                if resolved_root not in target.parents:
                    failures.append(
                        ScanFailure(child, "link simbólico aponta para fora da instalação")
                    )
                    continue
            if not child.is_dir():
                continue
            game = _read_game(child, config_dir=config_dir, cache_dir=cache_dir,
                              available_programs=available_programs)
        except InvalidGameMetadata as error:
            failures.append(ScanFailure(child, str(error)))
            continue
        except OSError as error:
            failures.append(ScanFailure(child, f"erro de leitura: {error.__class__.__name__}"))
            continue
        if game is None:
            continue
        games.append(game)
        seen_directories.append(game.directory)

    diagnostics = _duplicate_ids(tuple(games))
    return MinigalaxyScan(
        install_dir=resolved_root,
        games=tuple(
            game if not diagnostics.get(game.directory) else _with_diagnostics(game, diagnostics)
            for game in games
        ),
        failures=tuple(failures),
        complete=True,
    )


def stable_game_ids(games: Iterable[MinigalaxyGame]) -> dict[Path, str]:
    """IDs persistentes por diretório de instalação.

    ``minigalaxy_<gog_id>`` quando o ID GOG é único; quando há mais de uma
    instalação com o mesmo ID, o nome da pasta entra no ID. Sem ID GOG, o
    fallback é o nome normalizado da pasta — sempre determinístico.
    """

    grouped: dict[str, list[MinigalaxyGame]] = {}
    without_id: list[MinigalaxyGame] = []
    for game in games:
        if game.gog_id:
            grouped.setdefault(game.gog_id, []).append(game)
        else:
            without_id.append(game)

    ids: dict[Path, str] = {}
    for gog_id, group in grouped.items():
        for game in group:
            suffix = "" if len(group) == 1 else f"_{_slug(game.directory.name)}"
            ids[game.directory] = f"minigalaxy_{gog_id}{suffix}"
    for game in without_id:
        ids[game.directory] = f"minigalaxy_local_{_slug(game.directory.name)}"
    return ids


def _read_game(
    directory: Path,
    config_dir: Optional[Path],
    cache_dir: Optional[Path],
    available_programs: Iterable[str],
) -> Optional[MinigalaxyGame]:
    entries = _list_names(directory)
    if not entries:
        raise InvalidGameMetadata("pasta vazia")

    preferences = read_preferences(config_dir, directory)
    artwork = directory / "thumbnail.jpg"
    artwork = artwork if artwork.is_file() else None

    if "gameinfo" in entries:
        name, gog_id = parse_gameinfo(directory / "gameinfo")
        platform: PlatformKind = "linux"
    else:
        goggame_names = sorted(
            name for name in entries if GOGGAME_INFO_PATTERN.match(name)
        )
        if not goggame_names:
            return None
        name, gog_id = _read_any_goggame(directory, goggame_names)
        if len(goggame_names) > 1:
            preferences = preferences  # mantém a primeira tarefa primária encontrada
        platform = "windows"

    icon = None
    if cache_dir is not None and gog_id:
        candidate = cache_dir / "icons" / f"{gog_id}.png"
        icon = candidate if candidate.is_file() else None

    launcher = detect_launcher(directory, entries, available_programs)
    return MinigalaxyGame(
        gog_id=gog_id,
        name=name,
        platform=platform,
        directory=directory,
        launcher=launcher,
        artwork=artwork,
        icon=icon,
        preferences=preferences,
    )


def _read_any_goggame(
    directory: Path, candidates: list[str]
) -> tuple[str, Optional[str]]:
    """Escolhe o ``goggame`` com tarefa primária, na ordem dos nomes."""

    readable: list[tuple[str, Optional[str]]] = []
    for filename in candidates:
        try:
            name, gog_id, _task = parse_goggame_info(directory / filename)
        except InvalidGameMetadata:
            continue
        readable.append((name, gog_id))
    if not readable:
        raise InvalidGameMetadata("nenhum goggame legível")
    return readable[0]


def _list_names(directory: Path) -> list[str]:
    try:
        return sorted(os.listdir(directory))
    except OSError as error:
        raise InvalidGameMetadata(
            f"pasta ilegível: {error.__class__.__name__}"
        ) from error


def _duplicate_ids(games: tuple[MinigalaxyGame, ...]) -> dict[Path, str]:
    grouped: dict[str, int] = {}
    for game in games:
        if game.gog_id:
            grouped[game.gog_id] = grouped.get(game.gog_id, 0) + 1
    return {
        game.directory: "mais de uma instalação com o mesmo ID GOG; o ID inclui a pasta"
        for game in games
        if game.gog_id and grouped.get(game.gog_id, 0) > 1
    }


def _with_diagnostics(
    game: MinigalaxyGame, extra: dict[Path, str]
) -> MinigalaxyGame:
    message = extra[game.directory]
    return MinigalaxyGame(
        gog_id=game.gog_id,
        name=game.name,
        platform=game.platform,
        directory=game.directory,
        launcher=game.launcher,
        artwork=game.artwork,
        icon=game.icon,
        preferences=game.preferences,
        diagnostics=game.diagnostics + (message,),
    )


def _read_metadata_bytes(path: Path) -> bytes:
    try:
        stat = path.stat()
    except OSError as error:
        raise InvalidGameMetadata(f"arquivo ausente: {path.name}") from error
    if not path.is_file():
        raise InvalidGameMetadata(f"não é um arquivo: {path.name}")
    if stat.st_size > MAX_METADATA_BYTES:
        raise InvalidGameMetadata(f"arquivo grande demais: {path.name}")
    return path.read_bytes()


def _as_bool(value: object) -> bool:
    return value is True


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = _UNSAFE_ID_CHARS.sub("-", ascii_only).strip("-")
    return slug[:40] or "instalacao"

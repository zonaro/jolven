# playlists.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Playlists pessoais da biblioteca (issue #155).

Uma playlist é só uma lista ordenada de ``game_id`` da `Store`: nada é
copiado nem regravado, então renomear ou reimportar um jogo não quebra a
referência. O arquivo vive na pasta do app (``playlists.json``), no mesmo
espaço de ``fitas.json``.

O módulo é puro: sem GTK e sem ``gi``. O caminho padrão depende de
``cartridges.shared``, que puxa ``gi``, por isso ele só é resolvido dentro
de :func:`default_path` — os testes passam um caminho próprio.

Durabilidade:
- gravação atômica (temporário + ``os.replace``), como os outros JSON do app;
- campos desconhecidos do arquivo (do topo e de cada playlist) são
  preservados ao salvar;
- arquivo corrompido/ilegível rende uma store vazia e nunca é sobrescrito
  nem apagado: só na primeira gravação ele é renomeado para
  ``<arquivo>.corrupt`` para dar lugar ao novo;
- ids são estáveis: slug do nome + sufixo numérico em colisão, e um id
  usado alguma vez nunca volta a ser emitido (o contador monotônico e a
  lista de ids emitidos são persistidos junto).
"""

import json
import logging
import os
import re
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

PLAYLISTS_VERSION = 1

_FILE_NAME = "playlists.json"


@dataclass
class Playlist:
    """Uma playlist: id estável, nome e a ordem dos jogos."""

    playlist_id: str
    name: str
    game_ids: list[str]
    created_at: int
    updated_at: int
    # Campos desconhecidos lidos do arquivo; devolvidos ao salvar. Nunca é
    # o mesmo dict entre playlists (cada uma é dona do seu).
    extra: dict = field(default_factory=dict, repr=False)


def default_path() -> Path:
    """Caminho padrão do arquivo de playlists.

    ``cartridges.shared`` importa GTK, então a importação fica aqui dentro:
    o módulo inteiro continua importável sem GTK (os testes passam caminho).
    """
    from cartridges import shared  # pylint: disable=import-outside-toplevel

    return shared.app_dir / _FILE_NAME


def slug(name: str) -> str:
    """Slug estável de um nome: sem acentos, minúsculo, só ``a-z0-9-``."""
    texto = unicodedata.normalize("NFKD", str(name or ""))
    texto = "".join(caractere for caractere in texto if not unicodedata.combining(caractere))
    texto = texto.lower().strip()
    texto = re.sub(r"[^a-z0-9]+", "-", texto)
    texto = texto.strip("-")
    return texto or "playlist"


class PlaylistStore:
    """Registro de playlists, persistido em ``playlists.json``."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = Path(path) if path is not None else None
        self._playlists: list[Playlist] = []
        self._extra: dict[str, Any] = {}
        # Todo id já emitido alguma vez; um id de playlist apagada continua
        # aqui, então nunca volta a existir.
        self._used_ids: set[str] = set()
        self._counter: int = 0
        # True quando o arquivo existe mas não pôde ser lido/interpretado.
        self._corrupt: bool = False
        self.load()

    # ── leitura ────────────────────────────────────────────────────────────

    def load(self) -> None:
        """Lê o arquivo do disco. Erro de leitura rende store vazia."""
        self._playlists = []
        self._extra = {}
        self._used_ids = set()
        self._counter = 0
        self._corrupt = False

        path = self._arquivo()
        if path is None or not path.is_file():
            return
        try:
            dados = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(dados, dict):
                raise ValueError("playlists.json não é um objeto")
        except (OSError, ValueError, UnicodeDecodeError):
            # Nunca apagar nem sobrescrever silenciosamente: a store fica
            # vazia e o arquivo é preservado até a primeira gravação, quando
            # é renomeado para *.corrupt.
            logging.warning("playlists.json ilegível; começando sem playlists")
            self._corrupt = True
            return

        self._extra = {
            chave: valor
            for chave, valor in dados.items()
            if chave not in ("version", "playlists", "used_ids", "counter")
        }

        contador = dados.get("counter", 0)
        self._counter = _inteiro(contador, 0)
        if self._counter < 0:
            self._counter = 0

        usados = dados.get("used_ids", [])
        if isinstance(usados, list):
            self._used_ids = {item for item in usados if isinstance(item, str)}

        lista = dados.get("playlists", [])
        if not isinstance(lista, list):
            return
        for item in lista:
            playlist = self._playlist_do_json(item)
            if playlist is not None:
                self._playlists.append(playlist)

    @staticmethod
    def _playlist_do_json(item: Any) -> Optional[Playlist]:
        """Uma playlist do arquivo; entrada inválida é ignorada, não falha."""
        if not isinstance(item, dict):
            return None
        id_play = item.get("id", item.get("playlist_id"))
        if not isinstance(id_play, str) or not id_play:
            return None
        nome = item.get("name")
        if not isinstance(nome, str):
            nome = ""
        ids = item.get("game_ids", [])
        if not isinstance(ids, list):
            ids = []
        ids = [ident for ident in ids if isinstance(ident, str)]
        return Playlist(
            playlist_id=id_play,
            name=nome,
            game_ids=list(ids),
            created_at=_inteiro(item.get("created_at"), 0),
            updated_at=_inteiro(item.get("updated_at"), 0),
            extra={
                chave: valor
                for chave, valor in item.items()
                if chave
                not in (
                    "id",
                    "playlist_id",
                    "name",
                    "game_ids",
                    "created_at",
                    "updated_at",
                )
            },
        )

    # ── gravação ───────────────────────────────────────────────────────────

    def save(self) -> None:
        """Grava o arquivo com temporário + ``os.replace``.

        Se o arquivo original foi encontrado corrompido no último ``load``,
        ele é renomeado para ``*.corrupt`` antes da gravação — a única forma
        de ele ser tocado. Nunca levanta: falha de disco só é registrada.
        """
        path = self._arquivo()
        if path is None:
            return
        if self._corrupt and path.is_file():
            if not self._relegar_corrupto(path):
                # Não conseguindo guardar o corrompido, escrever por cima o
                # destruiria: a gravação desiste e o arquivo permanece.
                return
        self._corrupt = False

        dados = {
            "version": PLAYLISTS_VERSION,
            "playlists": [self._json_da_playlist(p) for p in self._playlists],
            "used_ids": sorted(self._used_ids),
            "counter": self._counter,
        }
        dados.update(self._extra)

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporario = path.with_name(path.name + ".tmp")
            temporario.write_text(
                json.dumps(dados, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(temporario, path)
        except OSError as error:
            logging.error("Could not save playlists: %s", error)

    @staticmethod
    def _json_da_playlist(playlist: Playlist) -> dict:
        dados = dict(playlist.extra)
        dados.update(
            {
                "id": playlist.playlist_id,
                "name": playlist.name,
                "game_ids": list(playlist.game_ids),
                "created_at": playlist.created_at,
                "updated_at": playlist.updated_at,
            }
        )
        return dados

    def _relegar_corrupto(self, path: Path) -> bool:
        """Guarda o arquivo corrompido como ``<nome>.corrupt``."""
        alvo = path.with_name(path.name + ".corrupt")
        tentativa = 2
        while alvo.exists():
            alvo = path.with_name(f"{path.name}.corrupt{tentativa}")
            tentativa += 1
        try:
            os.replace(path, alvo)
            logging.warning("playlists.json corrompido guardado em %s", alvo)
            return True
        except OSError as error:
            logging.error("Could not quarantine a corrupt playlists file: %s", error)
            return False

    def _arquivo(self) -> Optional[Path]:
        """O caminho deste arquivo: o do teste ou o padrão preguiçoso."""
        if self._path is not None:
            return self._path
        try:
            return default_path()
        except Exception:  # pylint: disable=broad-exception-caught
            return None

    # ── consulta ───────────────────────────────────────────────────────────

    @property
    def playlists(self) -> tuple:
        """As playlists, na ordem de criação/reordenação da lista."""
        return tuple(self._playlists)

    def get(self, playlist_id: str) -> Optional[Playlist]:
        """A playlist com este id, ou ``None``."""
        for playlist in self._playlists:
            if playlist.playlist_id == playlist_id:
                return playlist
        return None

    def playlist_ids(self) -> tuple:
        """Os ids de todas as playlists."""
        return tuple(playlist.playlist_id for playlist in self._playlists)

    def for_game(self, game_id: str) -> tuple:
        """As playlists que contêm este jogo (referência por id da store)."""
        return tuple(
            playlist for playlist in self._playlists if game_id in playlist.game_ids
        )

    # ── mutação ────────────────────────────────────────────────────────────

    def create(self, name: str) -> Playlist:
        """Cria uma playlist com id estável e a devolve.

        O id é o slug do nome; se ele já foi emitido alguma vez, recebe um
        sufixo numérico vindo do contador monotônico persistido. O mesmo id
        nunca é reaproveitado depois de um ``delete``.
        """
        nome = str(name).strip()
        if not nome:
            # A interface nunca manda nome vazio; sem nome, um id digno.
            nome = "playlist"
        base = slug(nome)
        id_play = base
        if id_play in self._used_ids or self.get(id_play) is not None:
            # Colisão com um id já emitido: sufixo numérico vindo do contador
            # monotônico. O primeiro sufixo é 2 (o nome cru já está tomado).
            numero = max(2, self._counter + 1)
            while f"{base}-{numero}" in self._used_ids:
                numero += 1
            self._counter = numero
            id_play = f"{base}-{numero}"
        self._used_ids.add(id_play)
        agora = int(time.time())
        playlist = Playlist(
            playlist_id=id_play,
            name=nome,
            game_ids=[],
            created_at=agora,
            updated_at=agora,
        )
        self._playlists.append(playlist)
        self.save()
        return playlist

    def rename(self, playlist_id: str, name: str) -> None:
        """Renomeia sem tocar no id (as referências continuam valendo)."""
        playlist = self.get(playlist_id)
        nome = str(name).strip()
        if playlist is None or not nome or playlist.name == nome:
            return
        playlist.name = nome
        playlist.updated_at = int(time.time())
        self.save()

    def delete(self, playlist_id: str) -> None:
        """Apaga a playlist. O id volta a existir jamais."""
        playlist = self.get(playlist_id)
        if playlist is None:
            return
        self._playlists.remove(playlist)
        self.save()

    def add(self, playlist_id: str, game_ids: Any) -> None:
        """Adiciona jogos ao fim, sem duplicar nem reordenar os que já estão."""
        playlist = self.get(playlist_id)
        if playlist is None:
            return
        mudou = False
        for ident in _ids_validos(game_ids):
            if ident not in playlist.game_ids:
                playlist.game_ids.append(ident)
                mudou = True
        if mudou:
            playlist.updated_at = int(time.time())
            self.save()

    def remove(self, playlist_id: str, game_ids: Any) -> None:
        """Tira os jogos indicados; os outros mantêm a ordem."""
        playlist = self.get(playlist_id)
        if playlist is None:
            return
        a_remover = set(_ids_validos(game_ids))
        if not a_remover:
            return
        nova = [ident for ident in playlist.game_ids if ident not in a_remover]
        if nova != playlist.game_ids:
            playlist.game_ids = nova
            playlist.updated_at = int(time.time())
            self.save()

    def reorder(self, playlist_id: str, game_ids: Any) -> None:
        """Define a ordem inteira da playlist (a lista passada é a ordem)."""
        playlist = self.get(playlist_id)
        if playlist is None:
            return
        nova = list(dict.fromkeys(_ids_validos(game_ids)))
        if nova == playlist.game_ids:
            return
        playlist.game_ids = nova
        playlist.updated_at = int(time.time())
        self.save()

    def move(self, playlist_id: str, game_id: str, index: int) -> None:
        """Move um jogo da playlist para ``index``, limitando às pontas."""
        playlist = self.get(playlist_id)
        if playlist is None or game_id not in playlist.game_ids:
            return
        lista = playlist.game_ids
        origem = lista.index(game_id)
        try:
            destino = int(index)
        except (TypeError, ValueError):
            return
        destino = max(0, min(destino, len(lista) - 1))
        if destino == origem:
            return
        lista.pop(origem)
        lista.insert(destino, game_id)
        playlist.updated_at = int(time.time())
        self.save()

    def prune(self, known_ids: Any) -> None:
        """Solta referências a jogos que não existem mais na store.

        As playlists continuam, mesmo ficando vazias; só os ``game_id``
        ausentes de ``known_ids`` desaparecem.
        """
        conhecidos = {
            ident for ident in _ids_validos(known_ids)
        }
        mudou = False
        for playlist in self._playlists:
            nova = [ident for ident in playlist.game_ids if ident in conhecidos]
            if nova != playlist.game_ids:
                playlist.game_ids = nova
                playlist.updated_at = int(time.time())
                mudou = True
        if mudou:
            self.save()


def _ids_validos(valor: Any) -> list:
    """Os ``game_id`` de um valor de entrada; qualquer coisa estranha cai fora."""
    if isinstance(valor, str):
        valor = [valor]
    if not isinstance(valor, (list, tuple, set)):
        return []
    return [ident for ident in valor if isinstance(ident, str) and ident]


def _inteiro(valor: Any, padrao: int) -> int:
    """Um int de qualquer entrada; o que não converte vira o padrão."""
    try:
        return int(valor)
    except (TypeError, ValueError):
        return padrao

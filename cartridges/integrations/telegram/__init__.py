# __init__.py
#
# Copyright 2026 Jolven contributors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Integração opcional com o Telegram via TDLib.

O pacote não importa GTK em nenhum nível. Toda rede e toda chamada à biblioteca
nativa TDLib (``libtdjson``) acontecem fora da thread do GTK. Quando a TDLib não
está instalada, a integração se declara indisponível e o Jolven continua
funcionando 100% sem ela.

``disponivel()``     Se a biblioteca nativa TDLib pode ser carregada.
``biblioteca()``     A CDLL carregada de ``libtdjson``, ou ``None``.
``EstadoAutorizacao``   Estados do fluxo de autorização da TDLib.
``adapter``          O adaptador de alto nível (cliente, estados de autorização).
``auth``             Estados do fluxo de autorização da TDLib.
``errors``           Erros específicos da integração.
"""

from __future__ import annotations

import ctypes
import ctypes.util
from typing import Optional

from cartridges.integrations.telegram.auth import EstadoAutorizacao

#: Nome da biblioteca nativa do cliente JSON da TDLib.
_LIB_TDJSON = "libtdjson.so"

_lib_tdjson: Optional[ctypes.CDLL] = None


def _carregar_biblioteca() -> Optional[ctypes.CDLL]:
    """Carrega ``libtdjson`` de forma tolerante, sem trazer GTK."""
    global _lib_tdjson
    if _lib_tdjson is not None:
        return _lib_tdjson
    caminho = ctypes.util.find_library(_LIB_TDJSON)
    if not caminho:
        return None
    try:
        _lib_tdjson = ctypes.CDLL(caminho)
    except OSError:
        _lib_tdjson = None
    return _lib_tdjson


def biblioteca() -> Optional[ctypes.CDLL]:
    """Devolve a biblioteca TDLib carregada, ou ``None`` se não estiver presente."""
    return _carregar_biblioteca()


def disponivel() -> bool:
    """Se a TDLib nativa está instalada e pode ser carregada."""
    return biblioteca() is not None


__all__ = ["biblioteca", "disponivel", "EstadoAutorizacao"]

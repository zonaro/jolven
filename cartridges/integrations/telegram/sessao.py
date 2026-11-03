# sessao.py
#
# Copyright 2026 Jolven contributors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Persistência da sessão local do Telegram no cofre do usuário (Secret Service).

A TDLib grava o banco de dados da sessão (incluindo a chave de criptografia)
num diretório local. O Jolven não guarda mensagens nem a conta remota: apenas
mantém, no cofre do próprio usuário, a chave necessária para reabrir o banco
local na próxima inicialização, sem pedir o login do zero.

Nunca levanta: sem cofre alcançável ou com erro, degrada para não persistir.
"""

import logging
import os
from pathlib import Path

import gi

try:
    gi.require_version("Secret", "1")
except Exception:
    pass
try:
    from gi.repository import Secret
except Exception:  # Secret Service indisponível: degrada sem levantar
    Secret = None  # type: ignore[assignment]

if Secret is not None:
    _SCHEMA = Secret.Schema.new(
        "io.github.zonaro.Jolven.telegram",
        Secret.SchemaFlags.NONE,
        {"app": Secret.SchemaAttributeType.STRING},
    )
    _SCHEMA_API = Secret.Schema.new(
        "io.github.zonaro.Jolven.telegram.api",
        Secret.SchemaFlags.NONE,
        {
            "app": Secret.SchemaAttributeType.STRING,
            "campo": Secret.SchemaAttributeType.STRING,
        },
    )
else:
    _SCHEMA = None
    _SCHEMA_API = None

_ATRIBUTOS = {"app": "jolven"}
_ATRIBUTOS_API = {"app": "jolven", "campo": "api-hash"}
_CHAVE_ENCRIPTACAO = "tdlib-encryption-key"
_ROTULO = "Jolven: chave de criptografia da sessão do Telegram"
_ROTULO_API = "Jolven: API hash do Telegram"


def diretorio_sessao() -> Path:
    """Diretório local onde a TDLib guarda o banco e os arquivos da sessão.

    Fica sob o diretório de dados do usuário (``XDG_DATA_HOME``), nunca dentro
    do repositório. O caminho é criado com permissões restritas quando possível.
    """
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    caminho = Path(base) / "jolven" / "telegram"
    try:
        caminho.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError:
        logging.warning("Não foi possível criar o diretório da sessão do Telegram")
    return caminho



def salvar_chave_encriptacao(chave: str) -> None:
    """Grava a chave de criptografia da sessão TDLib no cofre. Nunca levanta."""
    try:
        if Secret is None or _SCHEMA is None:
            raise RuntimeError("Secret Service indisponível")
        Secret.password_store_sync(
            _SCHEMA,
            _ATRIBUTOS,
            Secret.COLLECTION_DEFAULT,
            _ROTULO,
            chave,
            None,
        )
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Não foi possível guardar a sessão do Telegram no cofre")


def carregar_chave_encriptacao() -> str:
    """A chave salva, ou ``""`` quando não houver nada no cofre."""
    try:
        if Secret is None or _SCHEMA is None:
            return ""
        segredo = Secret.password_lookup_sync(_SCHEMA, _ATRIBUTOS, None)
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Cofre do Telegram ilegível; a sessão não foi carregada")
        return ""
    if not segredo or not isinstance(segredo, str):
        return ""
    return segredo


def salvar_api_hash(api_hash: str) -> None:
    """Guarda o API hash no cofre do usuário. Nunca levanta.

    O API hash é uma credencial da aplicação Telegram; não pertence ao
    GSettings nem a arquivos de configuração legíveis.
    """
    try:
        if Secret is None or _SCHEMA_API is None:
            raise RuntimeError("Secret Service indisponível")
        Secret.password_store_sync(
            _SCHEMA_API,
            _ATRIBUTOS_API,
            Secret.COLLECTION_DEFAULT,
            _ROTULO_API,
            api_hash,
            None,
        )
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Não foi possível guardar o API hash do Telegram no cofre")


def carregar_api_hash() -> str:
    """O API hash salvo, ou ``""`` quando não houver nada no cofre."""
    try:
        if Secret is None or _SCHEMA_API is None:
            return ""
        segredo = Secret.password_lookup_sync(_SCHEMA_API, _ATRIBUTOS_API, None)
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Cofre do Telegram ilegível; o API hash não foi lido")
        return ""
    if not segredo or not isinstance(segredo, str):
        return ""
    return segredo


def apagar_sessao() -> None:
    """Remove a chave de criptografia da sessão do cofre. Nunca levanta.

    Chamado quando o usuário desconecta a conta: apenas descarta a sessão
    local do Jolven, sem apagar mensagens nem a conta no Telegram.
    """
    try:
        if Secret is None or _SCHEMA is None:
            return
        Secret.password_clear_sync(_SCHEMA, _ATRIBUTOS, None)
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Não foi possível apagar a sessão do Telegram do cofre")

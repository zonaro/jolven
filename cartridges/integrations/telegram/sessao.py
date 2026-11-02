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
else:
    _SCHEMA = None

_ATRIBUTOS = {"app": "jolven"}
_CHAVE_ENCRIPTACAO = "tdlib-encryption-key"
_ROTULO = "Jolven: chave de criptografia da sessão do Telegram"


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

# sunshine_credenciais.py
#
# Copyright 2026 Jolven contributors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A senha da Web UI do Sunshine, guardada para não pedir de novo.

Guardada no Secret Service (o cofre do usuário), que só esse usuário
desbloqueia — o mesmo modelo de um navegador guardando senha salva. O segredo
mora no cofre e não nas configurações, então o backup não o leva: numa
instalação nova, `carregar_senha` devolve ``""`` e a tela de preferências
mostra o campo vazio.

Nunca levanta: sem cofre alcançável, cofre trancado ou valor ilegível, avisa
no log (sem o segredo) e degrada para ``""``.
"""

import logging

import gi

try:
    gi.require_version("Secret", "1")
except Exception:
    pass
try:
    from gi.repository import Secret
except Exception:  # Secret Service indisponível: degrada para "" sem levantar
    Secret = None  # type: ignore[assignment]

if Secret is not None:
    _SCHEMA = Secret.Schema.new(
        "io.github.zonaro.Jolven.sunshine",
        Secret.SchemaFlags.NONE,
        {"app": Secret.SchemaAttributeType.STRING},
    )
else:
    _SCHEMA = None
_ATRIBUTOS = {"app": "jolven"}
_ROTULO = "Jolven: senha do Sunshine"


def salvar_senha(senha: str) -> None:
    """Grava a senha no cofre. Nunca levanta."""
    try:
        if Secret is None or _SCHEMA is None:
            raise RuntimeError("Secret Service indisponível")
        Secret.password_store_sync(
            _SCHEMA,
            _ATRIBUTOS,
            Secret.COLLECTION_DEFAULT,
            _ROTULO,
            senha,
            None,
        )
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Não foi possível guardar a senha do Sunshine no cofre")


def carregar_senha() -> str:
    """A senha salva, ou ``""``.

    ``""`` sem nada no cofre, sem cofre alcançável, ou com o valor
    corrompido/ilegível — em todos os casos a tela mostra o campo vazio,
    como se nada tivesse sido salvo.
    """
    try:
        if Secret is None or _SCHEMA is None:
            return ""
        segredo = Secret.password_lookup_sync(_SCHEMA, _ATRIBUTOS, None)
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Cofre do Sunshine ilegível; a senha não foi carregada")
        return ""
    if not segredo or not isinstance(segredo, str):
        return ""
    return segredo

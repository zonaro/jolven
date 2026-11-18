# ui_mode.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Resolução da interface da sessão: Jolven Flat (GTK) ou Jolven Console (WebKitGTK).

A escolha é persistida em ``ui-mode`` no schema ``<APP_ID>.State`` (chave
adicionada ao gsettings na issue #179 do épico ConsoleUI #176) e exposta nas
Preferências. O padrão é ``flat``, preservando o comportamento das
instalações existentes.

Toda leitura de GSettings é guardada: `Gio.Settings.get_string` em uma chave
ausente dispara um `g_error` do GLib que aborta o processo (nao e excecao
Python, entao `try/except` nao protege), exatamente o defeito da issue #205.
Antes de ler, confirma-se com `schema_available` que o schema existe e com
`has_key` que a chave esta presente; caso contrario, devolve o padrao Flat.

Quando o Console e escolhido mas o WebKitGTK nao esta disponível (ou o renderer
falha), cai de volta ao Flat em vez de impedir a abertura do aplicativo.
"""

from __future__ import annotations

from cartridges import shared
from cartridges.utils.gschema import schema_lookup

FLAT = "flat"
CONSOLE = "console"

_DEFAULT = FLAT
_SCHEMA_ID = shared.APP_ID + ".State"
_KEY = "ui-mode"


def selected() -> str:
    """Modo de interface salvo pelo usuario, com fallback ao Flat."""

    schema = schema_lookup(_SCHEMA_ID)
    if schema is None:
        return _DEFAULT
    try:
        if _KEY not in schema.list_keys():
            return _DEFAULT
        value = shared.state_schema.get_string(_KEY)
    except Exception:  # leitura falhou por qualquer motivo
        return _DEFAULT
    if value in (FLAT, CONSOLE):
        return value
    return _DEFAULT


def is_console() -> bool:
    """True quando o usuario escolheu explicitamente o Jolven Console."""

    return selected() == CONSOLE

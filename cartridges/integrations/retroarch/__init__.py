# __init__.py
#
# Copyright 2026 Jolven contributors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Integração com o RetroArch: comandos por rede (UDP).

``commands``
    O cliente do Network Command Interface do RetroArch: allowlist de
    comandos, envio de datagrama UDP com timeout, sondagem de disponibilidade
    e o parser da resposta do ``GET_STATUS`` — tudo fora da thread do GTK.

O pacote não importa GTK em nenhum nível: ele é usado pela Jolven Session,
que aciona os comandos a partir da sobreposição de gamepad.
"""

from __future__ import annotations

from cartridges.integrations.retroarch.commands import (
    COMANDOS_PERMITIDOS,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_TIMEOUT,
    RetroarchCommandClient,
    parse_status,
)

__all__ = [
    "COMANDOS_PERMITIDOS",
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "DEFAULT_TIMEOUT",
    "RetroarchCommandClient",
    "parse_status",
]

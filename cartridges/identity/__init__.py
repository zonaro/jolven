# __init__.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Identidade canônica de jogos (issue #110).

Ponto de entrada do pacote: quem precisa identificar um jogo usa
``IdentityService``; quem precisa comparar duas identidades usa
``model.strong_match``. Nada aqui importa GTK, então módulos de testes e
workers podem usar o pacote inteiro.
"""

from cartridges.identity.model import (  # noqa: F401
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_NONE,
    describe,
    merge_identity,
    sanitize_identity,
    strong_match,
)
from cartridges.identity.service import IdentityLimits, IdentityService  # noqa: F401

__all__ = [
    "CONFIDENCE_HIGH",
    "CONFIDENCE_LOW",
    "CONFIDENCE_MEDIUM",
    "CONFIDENCE_NONE",
    "describe",
    "merge_identity",
    "sanitize_identity",
    "strong_match",
    "IdentityLimits",
    "IdentityService",
]

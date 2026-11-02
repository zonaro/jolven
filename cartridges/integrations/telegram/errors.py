# errors.py
#
# Copyright 2026 Jolven contributors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Erros específicos da integração com o Telegram."""

from __future__ import annotations


class TelegramIntegrationError(Exception):
    """Erro genérico da integração com o Telegram."""


class TelegramUnavailableError(TelegramIntegrationError):
    """A TDLib não está instalada ou não pôde ser carregada."""

    def __init__(self) -> None:
        super().__init__(
            "A biblioteca TDLib (libtdjson) não está instalada no sistema. "
            "A integração com o Telegram fica indisponível e o Jolven continua "
            "funcionando sem ela."
        )


class TelegramNotAuthorizedError(TelegramIntegrationError):
    """A conta do Telegram não está autorizada (sessão expirada ou nunca vinculada)."""


class TelegramNetworkError(TelegramIntegrationError):
    """Falha de rede ou de comunicação com a TDLib."""


class TelegramApiLimitsError(TelegramIntegrationError):
    """Limite de API do Telegram atingido (flood wait etc.)."""

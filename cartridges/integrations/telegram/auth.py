# auth.py
#
# Copyright 2026 Jolven contributors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Estados do fluxo de autorização da TDLib."""

from __future__ import annotations

from enum import StrEnum


class EstadoAutorizacao(StrEnum):
    """Possíveis estados de autorização de uma conta Telegram."""

    DESLIGADO = "desligado"
    CONECTANDO = "conectando"
    AUTORIZANDO_TELEFONE = "autorizando_telefone"
    AUTORIZANDO_CODIGO = "autorizando_codigo"
    AUTORIZANDO_SENHA = "autorizando_senha"
    AUTORIZANDO_QR = "autorizando_qr"
    AUTORIZADO = "autorizado"
    ERRO = "erro"

    @property
    def necessita_acao_do_usuario(self) -> bool:
        """Se o estado espera que o usuário forneça telefone/código/senha/QR."""
        return self in {
            EstadoAutorizacao.AUTORIZANDO_TELEFONE,
            EstadoAutorizacao.AUTORIZANDO_CODIGO,
            EstadoAutorizacao.AUTORIZANDO_SENHA,
            EstadoAutorizacao.AUTORIZANDO_QR,
        }

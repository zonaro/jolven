# base.py
#
# Copyright 2026 Jolven contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O contrato que todo provedor de iluminação cumpre.

São cinco operações e uma regra: **nenhum método levanta**. Um provedor que
não consegue falar com o hardware devolve ``[]``, ``None`` ou ``False`` e
registra o motivo. O coordenador decide o que fazer com a falha; a sessão do
jogo não pode cair porque uma fita saiu da tomada.

Todos os métodos são chamados de uma única thread de trabalho do coordenador,
nunca da thread do GTK. Um provedor pode guardar conexão entre chamadas
justamente por isso.
"""

from __future__ import annotations

import abc
from typing import Optional

from cartridges.iluminacao.modelo import Alvo, Estado, Plano


class Provedor(abc.ABC):
    """Um jeito de controlar luz: o servidor do OpenRGB, as fitas Tuya."""

    #: Chave estável usada no perfil e no diário (``"openrgb"``, ``"tuya"``).
    chave: str = ""

    #: Nome para a interface, já traduzível.
    nome: str = ""

    @abc.abstractmethod
    def ativo(self) -> bool:
        """O usuário ligou este provedor nas Preferências?"""

    @abc.abstractmethod
    def alvos(self) -> list[Alvo]:
        """Os dispositivos disponíveis agora. Vazio quando não há nenhum."""

    @abc.abstractmethod
    def ler(self, alvo: Alvo) -> Optional[Estado]:
        """O estado atual do dispositivo, para o diário. ``None`` se ilegível."""

    @abc.abstractmethod
    def aplicar(self, alvo: Alvo, plano: Plano) -> bool:
        """Veste o plano no dispositivo. ``False`` quando não deu."""

    @abc.abstractmethod
    def restaurar(self, alvo: Alvo, estado: Estado) -> bool:
        """Devolve o dispositivo ao estado guardado. ``False`` quando não deu."""

    def fechar(self) -> None:
        """Libera conexões. Chamado no fim da sessão e no fechamento do app."""

    # -- utilidades --------------------------------------------------

    def por_chave(self) -> dict[str, Alvo]:
        return {alvo.chave: alvo for alvo in self.alvos()}

    def alvo(self, chave: str) -> Optional[Alvo]:
        for alvo in self.alvos():
            if alvo.chave == chave:
                return alvo
        return None

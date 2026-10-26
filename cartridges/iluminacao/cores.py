# cores.py
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

"""A cor que atravessa perfis, diário e provedores.

Duas conversões moram aqui porque as duas têm armadilha:

* ``#rrggbb`` é o que o perfil grava. É o que o usuário vê no seletor, e não
  depende do brilho — mudar o brilho não pode reescrever a cor do perfil.
* HSV de 0–359 / 0–1000 / 0–1000 é o que a fita Tuya aceita no ponto de dado
  24. Converter por ``colorsys`` é o mesmo caminho que o
  :mod:`cartridges.utils.session_fita` já usa, então as duas rotas concordam.

O brilho nunca é aplicado à cor guardada: ele é um campo separado do plano.
Aplicá-lo ao RGB antes de gravar faria o perfil "escurecer" a cada sessão.
"""

from __future__ import annotations

import colorsys
from dataclasses import dataclass


def _byte(valor: object) -> int:
    """Um canal 0–255, tolerante a lixo vindo de JSON ou de widget."""
    try:
        numero = int(valor)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return max(0, min(255, numero))


@dataclass(frozen=True, order=True)
class Cor:
    """Uma cor RGB de 8 bits por canal."""

    vermelho: int = 0
    verde: int = 0
    azul: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "vermelho", _byte(self.vermelho))
        object.__setattr__(self, "verde", _byte(self.verde))
        object.__setattr__(self, "azul", _byte(self.azul))

    # -- texto -------------------------------------------------------

    @classmethod
    def de_hex(cls, valor: object, padrao: "Cor | None" = None) -> "Cor":
        """``#9141ac``, ``9141ac`` ou ``#fav`` como cor.

        Valor ilegível devolve ``padrao`` (preto por omissão) em vez de
        levantar: cor vem de arquivo e de widget, e um perfil com um campo
        torto não pode impedir a sessão inteira de ser aplicada.
        """
        texto = str(valor or "").strip().lstrip("#")
        if len(texto) == 3:
            texto = "".join(digito * 2 for digito in texto)
        if len(texto) != 6:
            return padrao if padrao is not None else cls()
        try:
            return cls(int(texto[0:2], 16), int(texto[2:4], 16), int(texto[4:6], 16))
        except ValueError:
            return padrao if padrao is not None else cls()

    def como_hex(self) -> str:
        return f"#{self.vermelho:02x}{self.verde:02x}{self.azul:02x}"

    def __str__(self) -> str:
        return self.como_hex()

    # -- conversões --------------------------------------------------

    def como_hsv(self, brilho: int = 100) -> tuple[int, int, int]:
        """Matiz 0–359, saturação 0–1000 e brilho 0–1000.

        ``brilho`` é a porcentagem do plano, não o valor da cor: o perfil
        guarda a cor cheia e o brilho à parte, e é aqui que os dois viram o
        valor que o módulo Tuya entende.
        """
        matiz, saturacao, _valor = colorsys.rgb_to_hsv(
            self.vermelho / 255, self.verde / 255, self.azul / 255
        )
        teto = max(0, min(100, int(brilho)))
        return (
            round(matiz * 360) % 360,
            round(saturacao * 1000),
            max(10, round(teto * 10)) if teto else 0,
        )

    def com_valor(self, por_cento: int) -> "Cor":
        """A mesma cor com o valor (brilho) multiplicado.

        Usada onde o hardware não tem controle de brilho separado: o único
        jeito de escurecer é mandar um RGB menor. O matiz é preservado.
        """
        fator = max(0, min(100, int(por_cento))) / 100
        return Cor(
            round(self.vermelho * fator),
            round(self.verde * fator),
            round(self.azul * fator),
        )

    def distante_de(self, outra: "Cor") -> int:
        """Distância de Manhattan entre duas cores (para agrupar LEDs)."""
        return (
            abs(self.vermelho - outra.vermelho)
            + abs(self.verde - outra.verde)
            + abs(self.azul - outra.azul)
        )


PRETO = Cor()
BRANCO = Cor(255, 255, 255)


def do_app() -> Cor:
    """O roxo da paleta do Jolven, a cor padrão de um perfil novo."""
    return Cor(0x91, 0x41, 0xAC)

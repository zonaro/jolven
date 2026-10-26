# tuya.py
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

"""Provedor das fitas Tuya: o mesmo módulo que o Jolven já usa, outro dono.

As fitas continuam sendo do :mod:`cartridges.utils.session_fita` — a conversa
com o módulo, as travas por fita, o fade e o estado guardado no GSettings são
dele. Este provedor só entra quando um **perfil** cita uma fita: aí o perfil
manda na cor dela durante a sessão, e o ciclo normal (cor do jogo tirada da
capa) é suspenso para não brigar pelo mesmo módulo.

O que este arquivo NÃO faz, de propósito:

* não abre conexão própria com a fita (usaria outra sessão do mesmo módulo de
  rede e brigaria com a trava do ``session_fita``);
* não grava nada na configuração da fita;
* não mexe no estado guardado do GSettings, que é do ciclo do app inteiro.

O brilho de cada fita continua sendo um teto: o brilho pedido pelo perfil vale
*sobre* o teto do dispositivo, exatamente como o brilho do app e o do jogo no
caminho antigo.
"""

from __future__ import annotations

import colorsys
import logging
from typing import Optional

from cartridges.iluminacao.cores import PRETO, Cor
from cartridges.iluminacao.modelo import Alvo, Estado, Plano
from cartridges.iluminacao.provedores.base import Provedor
from cartridges.utils import session_fita


def _fita(identificador: str) -> Optional[session_fita.Fita]:
    for fita in session_fita.fitas():
        if fita.id == identificador:
            return fita
    return None


def _cor_de_hsv(valor: str) -> Optional[Cor]:
    """A cor HSV crua do ponto de dado 24 como RGB, para exibir."""
    hsv = session_fita.cor_de_hex(valor)
    if hsv is None:
        return None
    vermelho, verde, azul = colorsys.hsv_to_rgb(
        max(0, min(360, hsv.matiz)) / 360,
        max(0, min(1000, hsv.saturacao)) / 1000,
        1.0,
    )
    return Cor(round(vermelho * 255), round(verde * 255), round(azul * 255))


class ProvedorTuya(Provedor):
    """As fitas configuradas no Jolven, vistas como dispositivos de um perfil."""

    chave = "tuya"
    nome = "Fitas Tuya"

    def ativo(self) -> bool:
        """Só quando o usuário ligou a iluminação inteligente e há fita.

        Respeitar o interruptor é deliberado: quem desligou "Mudar a cor da
        iluminação inteligente" não espera que um perfil RGB acenda as fitas
        pelas costas.
        """
        if not session_fita.ligada():
            return False
        return bool(session_fita.fitas())

    def alvos(self) -> list[Alvo]:
        if not self.ativo():
            return []
        alvos: list[Alvo] = []
        for fita in session_fita.fitas():
            alvos.append(
                Alvo(
                    provedor=self.chave,
                    chave=fita.id,
                    nome=fita.nome,
                    categoria="fita",
                    fabricante="Tuya",
                    descricao=fita.ip,
                    tem_brilho=True,
                    brilho_atual=fita.brilho,
                    cor_atual=PRETO,
                    extras={"teto_brilho": fita.brilho, "versao": fita.versao},
                )
            )
        return alvos

    def ler(self, alvo: Alvo) -> Optional[Estado]:
        fita = _fita(alvo.chave)
        if fita is None:
            return None
        lido = session_fita.ler_estado(fita)
        if not isinstance(lido, dict):
            return None
        cru = str(lido.get("cor", ""))
        return Estado(
            provedor=self.chave,
            chave=alvo.chave,
            nome=alvo.nome,
            ligado=bool(lido.get("ligada", False)),
            cor=_cor_de_hsv(cru),
            brilho=None,
            # A cor crua é o que a devolução reaplica: converter para RGB e de
            # volta perderia precisão de matiz e o brilho que a fita guardou.
            bruto={"cor": cru},
        )

    def aplicar(self, alvo: Alvo, plano: Plano) -> bool:
        fita = _fita(alvo.chave)
        if fita is None:
            logging.info("Fita %s saiu da configuração antes de aplicar o perfil", alvo.nome)
            return False

        if not plano.ligado:
            return session_fita.aplicar(fita, False, "")

        cor = plano.cor
        if cor is None:
            cor = _cor_de_hsv((self.ler(alvo) or Estado("", "")).bruto.get("cor", ""))
        if cor is None:
            # Sem cor no plano e sem estado legível: a cor do app é o que o
            # ciclo normal usaria, e é melhor que apagar a fita.
            roxo = session_fita.cor_do_app()
            vermelho, verde, azul = colorsys.hsv_to_rgb(
                roxo.matiz / 360, roxo.saturacao / 1000, 1.0
            )
            cor = Cor(round(vermelho * 255), round(verde * 255), round(azul * 255))

        brilho = plano.brilho if plano.brilho is not None else 100
        matiz, saturacao, valor = cor.como_hsv(brilho)
        # O teto do dispositivo entra aqui: `session_fita._vestir` o aplicaria
        # via `na_fita`, mas este caminho fala direto com `aplicar`.
        valor = max(
            session_fita.BRILHO_MINIMO,
            round(valor * max(1, min(100, fita.brilho)) / 100),
        )
        hexa = session_fita.hsv_hex(session_fita.Cor(matiz, saturacao, valor))
        return session_fita.aplicar(fita, True, hexa)

    def restaurar(self, alvo: Alvo, estado: Estado) -> bool:
        fita = _fita(alvo.chave)
        if fita is None:
            # Fita removida da configuração: nada a devolver neste dispositivo,
            # e não é falha (insistir deixaria o diário pendurado para sempre).
            return True
        cru = str(estado.bruto.get("cor", ""))
        if not cru and estado.ligado:
            # Estado sem cor só acontece para fita apagada (o módulo não reporta
            # o ponto 24 nesse caso); ligar sem cor a deixaria na cor do jogo.
            return session_fita.aplicar(fita, estado.ligado, "")
        return session_fita.aplicar(fita, estado.ligado, cru)

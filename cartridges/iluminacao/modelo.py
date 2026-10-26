# modelo.py
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

"""O que é um dispositivo de luz, um plano de perfil e um estado guardado.

Três estruturas e uma regra que vale para todas: **nada aqui guarda índice de
hardware**. Índice de controlador e id de dispositivo do OpenRGB mudam quando o
servidor reinicia, quando um cabo troca de porta e quando o usuário instala
outro módulo. O perfil identifica o dispositivo pela chave estável de
:func:`chave_do_dispositivo`; o índice só existe na hora de falar com o
servidor, dentro do provedor.

Um :class:`Plano` é a intenção ("teclado: só WASD em roxo"). Um :class:`Estado`
é o que o dispositivo mostrava antes ("ligado, modo Direct, cores X, Y, Z"). O
diário guarda estados; o perfil guarda planos.
"""

from __future__ import annotations

import builtins
import hashlib
from dataclasses import dataclass, field
from typing import Any, Optional

from cartridges.iluminacao.cores import PRETO, Cor


def _(mensagem: str) -> str:
    """Traduz via o gettext instalado pelo launcher; senão, devolve igual.

    Definido localmente (em vez de assumir o ``_`` builtin como os módulos de
    UI fazem) porque ``CATEGORIAS`` é avaliada na importação: ferramentas e
    testes que importam este módulo sem launcher continuam funcionando, e o
    ``xgettext`` extrai as strings do mesmo jeito.
    """
    traduzir = getattr(builtins, "_", None)
    if callable(traduzir):
        try:
            return str(traduzir(mensagem))
        except Exception:  # pylint: disable=broad-except
            pass
    return mensagem

#: Prefixo de provedor. Fica no começo da chave para o diário e o perfil
#: poderem ser lidos sem consultar o provedor.
PROVEDOR_OPENRGB = "openrgb"
PROVEDOR_TUYA = "tuya"

#: O que fazer com os LEDs que o plano não cita.
MANTER = "manter"
APAGAR = "apagar"
PINTAR = "pintar"

#: Categorias que a UI usa para agrupar os dispositivos. A chave é estável; o
#: rótulo é traduzido na importação e usado como estão.
CATEGORIAS: tuple[tuple[str, str], ...] = (
    ("teclado", _("Teclado")),
    ("mouse", _("Mouse")),
    ("mousepad", _("Mousepad")),
    ("memoria", _("Memória")),
    ("placa-mae", _("Placa-mãe")),
    ("gpu", _("Placa de vídeo")),
    ("gabinete", _("Gabinete")),
    ("cooler", _("Cooler")),
    ("fita", _("Fita LED")),
    ("ventoinha", _("Ventoinha")),
    ("headset", _("Headset")),
    ("alto-falante", _("Alto-falante")),
    ("controle", _("Controle")),
    ("armazenamento", _("Armazenamento")),
    ("outro", _("Outro")),
)


def chave_do_dispositivo(
    provedor: str,
    *,
    tipo: str = "",
    fabricante: str = "",
    nome: str = "",
    serie: str = "",
    localizacao: str = "",
) -> str:
    """Chave estável de um dispositivo, sem nenhum índice de hardware.

    O número de série é o melhor identificador: sobrevive a trocar de porta
    USB, a reiniciar o servidor e a reordenar a lista. Sem ele, o conjunto
    tipo + fabricante + nome é o que sobra — e dois dispositivos iguais do
    mesmo modelo caem na mesma chave. Nesse caso o provedor acrescenta a
    localização só aos empatados (:func:`desempatar_chaves`), para a chave dos
    outros não mudar quando um deles é desconectado.

    O resultado é legível de propósito: aparece no JSON do perfil e num
    ``grep``, e um hash opaco não ajudaria ninguém a diagnosticar nada.
    """

    def limpar(valor: object) -> str:
        return " ".join(str(valor or "").split()).strip().lower()

    if serie:
        partes = [limpar(tipo), limpar(nome), f"sn={limpar(serie)}"]
    else:
        partes = [limpar(tipo), limpar(fabricante), limpar(nome)]
        # Localização só entra no desempate; sem ela a chave é estável.
        if localizacao:
            partes.append(f"em={limpar(localizacao)}")
    corpo = "|".join(parte for parte in partes if parte) or "desconhecido"
    # Um sufixo curto do hash preserva a legibilidade e evita que dois nomes
    # parecidos com "|" dentro gerem a mesma chave.
    resumo = hashlib.sha1(corpo.encode("utf-8")).hexdigest()[:8]
    return f"{provedor}:{resumo}:{corpo[:72]}"


def desempatar_chaves(chaves: list[str]) -> list[str]:
    """Sufixa com o índice só as chaves repetidas, preservando a ordem.

    Dois teclados idênticos sem número de série são o caso real. Acrescentar o
    índice a todos faria a chave de um único teclado mudar quando um segundo
    aparecesse; acrescentar só aos repetidos mantém o primeiro estável.
    """
    contagem: dict[str, int] = {}
    for chave in chaves:
        contagem[chave] = contagem.get(chave, 0) + 1
    vistos: dict[str, int] = {}
    resultado: list[str] = []
    for chave in chaves:
        if contagem[chave] == 1:
            resultado.append(chave)
            continue
        posicao = vistos.get(chave, 0)
        vistos[chave] = posicao + 1
        resultado.append(f"{chave}#{posicao + 1}")
    return resultado


@dataclass(frozen=True)
class Zona:
    """Uma zona endereçável de um dispositivo.

    ``chave`` é estável dentro do dispositivo (o nome da zona, desempatado);
    ``inicio`` é o índice global do primeiro LED dela, usado só para montar o
    pacote de cores do OpenRGB, que sempre manda o dispositivo inteiro.
    """

    chave: str
    nome: str
    leds: tuple[str, ...] = ()
    inicio: int = 0
    matriz: Optional[tuple[tuple[Optional[int], ...], ...]] = None

    @property
    def total(self) -> int:
        return len(self.leds)

    @property
    def tem_matriz(self) -> bool:
        return bool(self.matriz)


@dataclass(frozen=True)
class Alvo:
    """Um dispositivo que um perfil pode controlar, do jeito que a UI o vê."""

    provedor: str
    chave: str
    nome: str
    categoria: str = "outro"
    fabricante: str = ""
    descricao: str = ""
    zonas: tuple[Zona, ...] = ()
    tem_brilho: bool = False
    brilho_atual: Optional[int] = None
    tem_modos: bool = False
    modos: tuple[str, ...] = ()
    modo_atual: str = ""
    cor_atual: Cor = PRETO
    #: Dados que só o provedor entende e que a UI devolve intactos.
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def total_leds(self) -> int:
        return sum(zona.total for zona in self.zonas) or len(self.zonas)

    @property
    def por_led(self) -> bool:
        """Dá para pintar LED a LED (matriz ou lista de LEDs com nome)?"""
        return any(zona.total > 0 for zona in self.zonas)

    @property
    def rotulo_categoria(self) -> str:
        for chave, rotulo in CATEGORIAS:
            if chave == self.categoria:
                return rotulo
        return _("Outro")


def zona_de(alvo: Alvo, chave: str) -> Optional[Zona]:
    for zona in alvo.zonas:
        if zona.chave == chave:
            return zona
    return None


@dataclass
class CoresDaZona:
    """O que o plano pede para uma zona: cor cheia e/ou LEDs específicos."""

    zona: str = ""
    cor: Optional[Cor] = None
    #: Índice do LED dentro da zona -> cor. Índice, aqui, é posição na lista
    #: da zona, que é estável para o mesmo hardware.
    leds: dict[int, Cor] = field(default_factory=dict)
    extras: dict[str, Any] = field(default_factory=dict)

    def para_json(self) -> dict[str, Any]:
        dados: dict[str, Any] = {"zona": self.zona}
        if self.cor is not None:
            dados["cor"] = self.cor.como_hex()
        if self.leds:
            dados["leds"] = {
                str(indice): cor.como_hex() for indice, cor in sorted(self.leds.items())
            }
        dados.update(self.extras)
        return dados

    @classmethod
    def de_json(cls, dados: object) -> Optional["CoresDaZona"]:
        if not isinstance(dados, dict):
            return None
        leds: dict[int, Cor] = {}
        bruto = dados.get("leds")
        if isinstance(bruto, dict):
            for indice, cor in bruto.items():
                try:
                    posicao = int(indice)
                except (TypeError, ValueError):
                    continue
                if posicao >= 0:
                    leds[posicao] = Cor.de_hex(cor)
        cor = Cor.de_hex(dados["cor"]) if dados.get("cor") else None
        conhecidos = {"zona", "cor", "leds"}
        extras = {chave: valor for chave, valor in dados.items() if chave not in conhecidos}
        return cls(str(dados.get("zona", "")), cor, leds, extras)


@dataclass
class Plano:
    """O que um perfil manda um dispositivo fazer durante o jogo."""

    provedor: str
    chave: str
    nome: str = ""
    ligado: bool = True
    cor: Optional[Cor] = None
    brilho: Optional[int] = None
    modo: str = ""
    zonas: list[CoresDaZona] = field(default_factory=list)
    #: O que fazer com LEDs que nenhuma zona citou.
    padrao: str = MANTER
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def identificador(self) -> str:
        return f"{self.provedor}:{self.chave}"

    @property
    def vazio(self) -> bool:
        return (
            self.cor is None
            and self.brilho is None
            and not self.zonas
            and not self.modo
            and self.padrao == MANTER
        )

    def brilho_efetivo(self) -> int:
        return 100 if self.brilho is None else max(1, min(100, int(self.brilho)))

    def para_json(self) -> dict[str, Any]:
        dados: dict[str, Any] = {
            "provedor": self.provedor,
            "chave": self.chave,
            "nome": self.nome,
            "ligado": self.ligado,
            "padrao": self.padrao,
        }
        if self.cor is not None:
            dados["cor"] = self.cor.como_hex()
        if self.brilho is not None:
            dados["brilho"] = int(self.brilho)
        if self.modo:
            dados["modo"] = self.modo
        if self.zonas:
            dados["zonas"] = [zona.para_json() for zona in self.zonas]
        dados.update(self.extras)
        return dados

    @classmethod
    def de_json(cls, dados: object) -> Optional["Plano"]:
        if not isinstance(dados, dict):
            return None
        provedor = str(dados.get("provedor", "")).strip()
        chave = str(dados.get("chave", "")).strip()
        if not provedor or not chave:
            return None
        brilho = dados.get("brilho")
        try:
            brilho_numero = None if brilho is None else max(1, min(100, int(brilho)))
        except (TypeError, ValueError):
            brilho_numero = None
        zonas: list[CoresDaZona] = []
        bruto_zonas = dados.get("zonas")
        if isinstance(bruto_zonas, list):
            for item in bruto_zonas:
                zona = CoresDaZona.de_json(item)
                if zona is not None:
                    zonas.append(zona)
        padrao = str(dados.get("padrao", MANTER))
        if padrao not in (MANTER, APAGAR, PINTAR):
            padrao = MANTER
        cor = Cor.de_hex(dados["cor"]) if dados.get("cor") else None
        conhecidos = {
            "provedor",
            "chave",
            "nome",
            "ligado",
            "cor",
            "brilho",
            "modo",
            "zonas",
            "padrao",
        }
        extras = {chave_: valor for chave_, valor in dados.items() if chave_ not in conhecidos}
        return cls(
            provedor=provedor,
            chave=chave,
            nome=str(dados.get("nome", "")),
            ligado=bool(dados.get("ligado", True)),
            cor=cor,
            brilho=brilho_numero,
            modo=str(dados.get("modo", "")),
            zonas=zonas,
            padrao=padrao,
            extras=extras,
        )


@dataclass
class Estado:
    """O que um dispositivo mostrava antes de o Jolven mexer nele.

    É o que o diário grava e o que a devolução reaplica. ``bruto`` guarda o
    que só o provedor entende (a cor HSV crua da fita Tuya, por exemplo) para
    a devolução ser exata em vez de uma aproximação por RGB.
    """

    provedor: str
    chave: str
    nome: str = ""
    ligado: bool = True
    cor: Optional[Cor] = None
    brilho: Optional[int] = None
    modo: str = ""
    leds: list[Cor] = field(default_factory=list)
    bruto: dict[str, Any] = field(default_factory=dict)

    @property
    def identificador(self) -> str:
        return f"{self.provedor}:{self.chave}"

    def para_json(self) -> dict[str, Any]:
        dados: dict[str, Any] = {
            "provedor": self.provedor,
            "chave": self.chave,
            "nome": self.nome,
            "ligado": self.ligado,
        }
        if self.cor is not None:
            dados["cor"] = self.cor.como_hex()
        if self.brilho is not None:
            dados["brilho"] = int(self.brilho)
        if self.modo:
            dados["modo"] = self.modo
        if self.leds:
            dados["leds"] = [cor.como_hex() for cor in self.leds]
        if self.bruto:
            dados["bruto"] = dict(self.bruto)
        return dados

    @classmethod
    def de_json(cls, dados: object) -> Optional["Estado"]:
        if not isinstance(dados, dict):
            return None
        provedor = str(dados.get("provedor", "")).strip()
        chave = str(dados.get("chave", "")).strip()
        if not provedor or not chave:
            return None
        brilho = dados.get("brilho")
        try:
            brilho_numero = None if brilho is None else int(brilho)
        except (TypeError, ValueError):
            brilho_numero = None
        leds: list[Cor] = []
        bruto_leds = dados.get("leds")
        if isinstance(bruto_leds, list):
            leds = [Cor.de_hex(item) for item in bruto_leds]
        bruto = dados.get("bruto")
        return cls(
            provedor=provedor,
            chave=chave,
            nome=str(dados.get("nome", "")),
            ligado=bool(dados.get("ligado", True)),
            cor=Cor.de_hex(dados["cor"]) if dados.get("cor") else None,
            brilho=brilho_numero,
            modo=str(dados.get("modo", "")),
            leds=leds,
            bruto=dict(bruto) if isinstance(bruto, dict) else {},
        )

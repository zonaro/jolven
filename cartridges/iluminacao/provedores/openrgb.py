# openrgb.py
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

"""Provedor do OpenRGB: periféricos, memória, placa-mãe, fitas, coolers.

Este módulo é a ponte entre o modelo do Jolven (:class:`Alvo`, :class:`Plano`,
:class:`Estado`) e o SDK. Toda a conversa binária fica em
:mod:`cartridges.integrations.openrgb.protocol`; aqui só se decide *o que*
mandar.

Três decisões que o código abaixo toma de propósito:

* **Nada é gravado na memória do controlador.** ``SaveMode`` nunca é chamado.
  O perfil empresta a iluminação por uma sessão e a devolve; a configuração
  permanente do usuário fica onde está.
* **``SetCustomMode`` antes de ``UpdateLEDs``.** Mandar cores sem entrar em
  modo direto é aceito pelo servidor e ignorado pelo hardware em vários
  controladores — o sintoma é "o perfil não faz nada no meu teclado".
* **Identificação por chave estável, nunca por índice.** O índice do
  controlador muda quando o servidor reinicia; a chave vem de número de série,
  tipo e nome (:func:`chave_do_dispositivo`).
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Optional

from cartridges.iluminacao.cores import PRETO, Cor
from cartridges.iluminacao.modelo import (
    APAGAR,
    PINTAR,
    Alvo,
    Estado,
    Plano,
    Zona,
    chave_do_dispositivo,
    desempatar_chaves,
    zona_de,
)
from cartridges.iluminacao.provedores.base import Provedor
from cartridges.integrations.openrgb import protocol

#: Tipo de controlador do SDK -> categoria da interface.
_CATEGORIA = {
    int(protocol.DeviceType.MOTHERBOARD): "placa-mae",
    int(protocol.DeviceType.DRAM): "memoria",
    int(protocol.DeviceType.GPU): "gpu",
    int(protocol.DeviceType.COOLER): "cooler",
    int(protocol.DeviceType.LEDSTRIP): "fita",
    int(protocol.DeviceType.KEYBOARD): "teclado",
    int(protocol.DeviceType.MOUSE): "mouse",
    int(protocol.DeviceType.MOUSEMAT): "mousepad",
    int(protocol.DeviceType.HEADSET): "headset",
    int(protocol.DeviceType.HEADSET_STAND): "headset",
    int(protocol.DeviceType.GAMEPAD): "controle",
    int(protocol.DeviceType.LIGHT): "fita",
    int(protocol.DeviceType.SPEAKER): "alto-falante",
    int(protocol.DeviceType.STORAGE): "armazenamento",
    int(protocol.DeviceType.CASE): "gabinete",
    int(protocol.DeviceType.KEYPAD): "teclado",
}

def _categoria(controlador: protocol.Controller) -> str:
    indice = int(controlador.device_type)
    if indice in _CATEGORIA:
        return _CATEGORIA[indice]
    # v0–v4 não têm tipo de dispositivo: o nome é a única pista.
    nome = f"{controlador.name} {controlador.description}".lower()
    for palavra, categoria in (
        ("keyboard", "teclado"),
        ("keypad", "teclado"),
        ("mouse", "mouse"),
        ("dram", "memoria"),
        ("memory", "memoria"),
        ("gpu", "gpu"),
        ("cooler", "cooler"),
        ("strip", "fita"),
        ("fan", "ventoinha"),
        ("headset", "headset"),
        ("motherboard", "placa-mae"),
    ):
        if palavra in nome:
            return categoria
    return "outro"


def _tipo_nome(controlador: protocol.Controller) -> str:
    """Nome legível do tipo do controlador, tolerante a valor fora da enum."""
    try:
        return protocol.DeviceType(int(controlador.device_type)).name
    except ValueError:
        return str(controlador.device_type)


def _chaves(controladores: list[protocol.Controller]) -> list[str]:
    """Chave estável de cada controlador, desempatando só os repetidos.

    Sem número de série, dois teclados iguais caem na mesma chave base. Nesse
    caso a localização USB entra — e só nesse caso, para a chave do teclado
    único não mudar quando um segundo aparecer.
    """
    bases = [
        chave_do_dispositivo(
            "openrgb",
            tipo=_tipo_nome(controlador),
            fabricante=controlador.vendor,
            nome=controlador.name,
            serie=controlador.serial,
        )
        for controlador in controladores
    ]
    contagem: dict[str, int] = {}
    for base in bases:
        contagem[base] = contagem.get(base, 0) + 1
    detalhadas: list[str] = []
    for controlador, base in zip(controladores, bases):
        if contagem[base] > 1 and controlador.location:
            detalhadas.append(
                chave_do_dispositivo(
                    "openrgb",
                    tipo=_tipo_nome(controlador),
                    fabricante=controlador.vendor,
                    nome=controlador.name,
                    localizacao=controlador.location,
                )
            )
        else:
            detalhadas.append(base)
    return desempatar_chaves(detalhadas)


def _zonas(controlador: protocol.Controller) -> tuple[Zona, ...]:
    """Zonas do controlador com os LEDs delas, na ordem global do dispositivo."""
    nomes = [zona.name.strip() or f"Zona {indice + 1}" for indice, zona in enumerate(controlador.zones)]
    chaves = desempatar_chaves([nome.lower() for nome in nomes])
    zonas: list[Zona] = []
    for zona, nome, chave in zip(controlador.zones, nomes, chaves):
        inicio = zona.start_index
        fim = inicio + zona.leds_count
        nomes_leds = [
            led.name or f"LED {indice + 1}"
            for indice, led in enumerate(controlador.leds[inicio:fim])
        ]
        while len(nomes_leds) < zona.leds_count:
            nomes_leds.append(f"LED {len(nomes_leds) + 1}")
        matriz = None
        if zona.matrix:
            matriz = tuple(tuple(linha) for linha in zona.matrix)
        zonas.append(
            Zona(
                chave=chave,
                nome=nome,
                leds=tuple(nomes_leds),
                inicio=inicio,
                matriz=matriz,
            )
        )
    return tuple(zonas)


def _brilho_absoluto(modo: protocol.Mode, por_cento: int) -> int:
    """Porcentagem do usuário -> valor que o controlador declara aceitar."""
    minimo, maximo = modo.brightness_min, modo.brightness_max
    if maximo <= minimo:
        return modo.brightness
    return minimo + round((maximo - minimo) * max(0, min(100, por_cento)) / 100)


def _brilho_por_cento(modo: Optional[protocol.Mode]) -> Optional[int]:
    if modo is None or not modo.has_brightness:
        return None
    if modo.brightness_max <= modo.brightness_min:
        return None
    faixa = modo.brightness_max - modo.brightness_min
    return round((modo.brightness - modo.brightness_min) * 100 / faixa)


def _total_de_leds(controlador: protocol.Controller) -> int:
    return protocol.leds_of(controlador)


def _cores_atuais(controlador: protocol.Controller) -> list[Cor]:
    """As cores que o servidor reporta, ajustadas ao número real de LEDs.

    Controlador que reporta menos cores do que LEDs existe; completar com a
    primeira cor (em vez de preto) é o que preserva ``padrao="manter"``: os
    LEDs não citados pelo perfil continuam com a cor que já tinham.
    """
    total = _total_de_leds(controlador)
    cores = [Cor(rgb.red, rgb.green, rgb.blue) for rgb in controlador.colors]
    if not total:
        return cores
    if not cores:
        return [PRETO] * total
    if len(cores) < total:
        cores = cores + [cores[0]] * (total - len(cores))
    return cores[:total]


class ProvedorOpenRGB(Provedor):
    """Um servidor do SDK, uma conexão reaproveitada, nenhum índice guardado."""

    chave = "openrgb"
    nome = "OpenRGB"

    #: Prazo de rede. Curto de propósito: a sessão do jogo já começou.
    PRAZO = 5.0

    def __init__(self, host: str = protocol.DEFAULT_HOST, porta: int = protocol.DEFAULT_PORT) -> None:
        self.host = host
        self.porta = int(porta)
        self._cliente: Optional[protocol.OpenRGBClient] = None

    # -- preferência -------------------------------------------------

    def ativo(self) -> bool:
        from cartridges import shared  # noqa: PLC0415

        return shared.schema.get_boolean("openrgb")

    # -- conexão -----------------------------------------------------

    def _conectar(self) -> Optional[protocol.OpenRGBClient]:
        if self._cliente is not None and self._cliente.connected:
            return self._cliente
        try:
            self._cliente = protocol.OpenRGBClient(
                self.host, self.porta, timeout=self.PRAZO
            ).connect()
        except (protocol.OpenRGBError, OSError) as erro:
            logging.info("OpenRGB indisponível em %s:%s (%s)", self.host, self.porta, erro)
            self._cliente = None
            return None
        return self._cliente

    def fechar(self) -> None:
        if self._cliente is not None:
            self._cliente.close()
            self._cliente = None

    def _controladores(self) -> list[protocol.Controller]:
        cliente = self._conectar()
        if cliente is None:
            return []
        try:
            return cliente.controllers()
        except (protocol.OpenRGBError, OSError) as erro:
            logging.warning("OpenRGB não devolveu a lista de dispositivos: %s", erro)
            self.fechar()
            return []

    def _encontrar(
        self, chave: str
    ) -> tuple[Optional[protocol.Controller], list[protocol.Controller]]:
        controladores = self._controladores()
        for controlador, chave_dele in zip(controladores, _chaves(controladores)):
            if chave_dele == chave:
                return controlador, controladores
        return None, controladores

    # -- contrato ----------------------------------------------------

    def alvos(self) -> list[Alvo]:
        if not self.ativo():
            return []
        controladores = self._controladores()
        chaves = _chaves(controladores)
        alvos: list[Alvo] = []
        for controlador, chave in zip(controladores, chaves):
            zonas = _zonas(controlador)
            direto = controlador.direct_mode
            modo_ativo = controlador.active
            cores = _cores_atuais(controlador)
            alvos.append(
                Alvo(
                    provedor=self.chave,
                    chave=chave,
                    nome=controlador.display,
                    categoria=_categoria(controlador),
                    fabricante=controlador.vendor,
                    descricao=" ".join(
                        parte
                        for parte in (controlador.description, controlador.location)
                        if parte
                    ),
                    zonas=zonas,
                    tem_brilho=bool(
                        (direto and direto.has_brightness)
                        or (modo_ativo and modo_ativo.has_brightness)
                    ),
                    brilho_atual=_brilho_por_cento(modo_ativo or direto),
                    tem_modos=bool(controlador.modes),
                    modos=tuple(modo.name for modo in controlador.modes if modo.name.strip()),
                    modo_atual=(modo_ativo.name if modo_ativo else ""),
                    cor_atual=cores[0] if cores else PRETO,
                    extras={
                        "tem_direto": direto is not None,
                        "total_leds": len(cores),
                    },
                )
            )
        return alvos

    def ler(self, alvo: Alvo) -> Optional[Estado]:
        controlador, _ = self._encontrar(alvo.chave)
        if controlador is None:
            return None
        modo = controlador.active
        cores = _cores_atuais(controlador)
        return Estado(
            provedor=self.chave,
            chave=alvo.chave,
            nome=alvo.nome,
            ligado=not (modo is not None and modo.is_off),
            cor=cores[0] if cores else None,
            brilho=_brilho_por_cento(modo),
            modo=modo.name if modo else "",
            leds=cores,
        )

    def aplicar(self, alvo: Alvo, plano: Plano) -> bool:
        controlador, _ = self._encontrar(alvo.chave)
        if controlador is None:
            logging.info("OpenRGB: %s sumiu antes de aplicar o perfil", alvo.nome)
            return False
        cliente = self._conectar()
        if cliente is None:
            return False
        try:
            self._aplicar_com(cliente, controlador, alvo, plano)
        except (protocol.OpenRGBError, OSError) as erro:
            logging.warning("OpenRGB não aceitou o perfil em %s: %s", alvo.nome, erro)
            self.fechar()
            return False
        return True

    def _aplicar_com(
        self,
        cliente: protocol.OpenRGBClient,
        controlador: protocol.Controller,
        alvo: Alvo,
        plano: Plano,
    ) -> None:
        dispositivo = controlador.device_id

        if not plano.ligado:
            desligado = next((modo for modo in controlador.modes if modo.is_off), None)
            if desligado is not None:
                cliente.update_mode(dispositivo, desligado)
                return
            cliente.update_leds(dispositivo, [PRETO] * max(1, _total_de_leds(controlador)))
            return

        modo_pedido = None
        if plano.modo:
            modo_pedido = next(
                (modo for modo in controlador.modes if modo.name == plano.modo), None
            )
        modo_efetivo = modo_pedido or controlador.direct_mode
        if modo_efetivo is not None and not modo_efetivo.is_direct and modo_pedido is None:
            # Sem modo direto: o caminho é o modo que aceita cor própria.
            modo_efetivo = next(
                (modo for modo in controlador.modes if modo.has_mode_color),
                modo_efetivo,
            )

        # Cor por LED: só faz sentido no modo direto. Nos outros, a cor vai no
        # próprio modo (UpdateMode), e mandar UpdateLEDs seria ignorado.
        if modo_efetivo is not None and modo_efetivo.is_direct:
            cliente.set_custom_mode(dispositivo)
            if plano.brilho is not None and modo_efetivo.has_brightness:
                cliente.update_mode(
                    dispositivo,
                    replace(
                        modo_efetivo,
                        brightness=_brilho_absoluto(modo_efetivo, plano.brilho),
                    ),
                )
            cliente.update_leds(dispositivo, self._colorir(controlador, alvo, plano))
            return

        if modo_efetivo is not None and modo_efetivo.has_mode_color:
            cor = plano.cor or self._cor_unica(controlador, alvo, plano)
            quantidade = max(1, modo_efetivo.colors_min)
            modo = replace(modo_efetivo, colors=[protocol.RGB(*cor.as_tuple())] * quantidade)
            if plano.brilho is not None and modo.has_brightness:
                modo = replace(modo, brightness=_brilho_absoluto(modo, plano.brilho))
            cliente.update_mode(dispositivo, modo)
            return

        # Último recurso: o controlador não declara modo nenhum que aceite cor.
        cliente.set_custom_mode(dispositivo)
        cliente.update_leds(dispositivo, self._colorir(controlador, alvo, plano))

    def _colorir(
        self,
        controlador: protocol.Controller,
        alvo: Alvo,
        plano: Plano,
    ) -> list[protocol.RGB]:
        """Monta o vetor de cores do dispositivo inteiro.

        O protocolo não tem "mude só estes LEDs" (fora do UpdateSingleLED):
        o pacote leva todos. Por isso a montagem parte das cores atuais, que é
        o que sustenta ``padrao="manter"``.
        """
        cores = _cores_atuais(controlador)
        if not cores:
            return []

        if plano.padrao == APAGAR:
            cores = [PRETO] * len(cores)
        if plano.cor is not None:
            cores = [plano.cor] * len(cores)

        for pedido in plano.zonas:
            zona = zona_de(alvo, pedido.zona)
            if zona is None:
                continue
            if pedido.cor is not None:
                for indice in range(zona.inicio, min(zona.inicio + zona.total, len(cores))):
                    cores[indice] = pedido.cor
            for indice_led, cor in pedido.leds.items():
                posicao = zona.inicio + indice_led
                if 0 <= posicao < len(cores):
                    cores[posicao] = cor

        if plano.padrao == PINTAR and plano.cor is None:
            # "Pintar" sem cor explícita usa a cor escolhida do dispositivo.
            cores = [alvo.cor_atual] * len(cores)

        # Brilho onde o hardware não tem controle próprio: só resta escurecer
        # o RGB. O matiz é preservado.
        if plano.brilho is not None and not self._tem_brilho(controlador):
            cores = [cor.com_valor(plano.brilho) for cor in cores]

        return [protocol.RGB(*cor.as_tuple()) for cor in cores]

    @staticmethod
    def _tem_brilho(controlador: protocol.Controller) -> bool:
        modo = controlador.direct_mode or controlador.active
        return bool(modo and modo.has_brightness)

    def _cor_unica(
        self, controlador: protocol.Controller, alvo: Alvo, plano: Plano
    ) -> Cor:
        if plano.cor is not None:
            return plano.cor
        cores = _cores_atuais(controlador)
        return cores[0] if cores else alvo.cor_atual

    def restaurar(self, alvo: Alvo, estado: Estado) -> bool:
        controlador, _ = self._encontrar(alvo.chave)
        if controlador is None:
            # Dispositivo saiu: não há o que devolver, e insistir para sempre
            # deixaria o diário pendurado.
            return True
        cliente = self._conectar()
        if cliente is None:
            return False
        dispositivo = controlador.device_id
        try:
            modo = next(
                (modo for modo in controlador.modes if modo.name == estado.modo), None
            )
            if modo is None:
                modo = controlador.direct_mode
            if modo is not None:
                if estado.brilho is not None and modo.has_brightness:
                    modo = replace(modo, brightness=_brilho_absoluto(modo, estado.brilho))
                cliente.update_mode(dispositivo, modo)
            if estado.leds:
                total = _total_de_leds(controlador)
                cores = list(estado.leds)
                if total and len(cores) < total:
                    cores = cores + [cores[0]] * (total - len(cores))
                cliente.update_leds(
                    dispositivo,
                    [protocol.RGB(*cor.as_tuple()) for cor in (cores[:total] if total else cores)],
                )
        except (protocol.OpenRGBError, OSError) as erro:
            logging.warning("OpenRGB não devolveu %s ao estado anterior: %s", alvo.nome, erro)
            self.fechar()
            return False
        return True

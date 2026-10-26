# protocol.py
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

"""Cliente mínimo do SDK do OpenRGB, sem GTK e sem dependência externa.

O protocolo do OpenRGB é binário sobre TCP e está documentado em
<https://github.com/CalcProgrammer1/OpenRGB/blob/master/Documentation/OpenRGBSDK.md>.
Cada pacote é ``"ORGB"``, id do controlador, id do pacote e tamanho, todos
inteiros de 32 bits little-endian, seguidos de ``pkt_size`` bytes de dados.

Duas decisões que custam caro se erradas:

* O tamanho que vai no cabeçalho é o do bloco de dados *inteiro*, incluindo o
  campo ``data_size`` que abre quase todo bloco. Quem manda 4 a menos recebe
  um pacote truncado de volta, e o servidor fica com o resto no soquete.
* O servidor manda pacotes espontâneos (ACK, lista de dispositivos atualizada,
  progresso de detecção) no meio da conversa. ``_receber`` descarta esses
  até chegar a resposta pedida; ler "o próximo pacote" devolveria um ACK como
  se fosse a resposta de uma consulta de dispositivo.

O v6 troca o índice do controlador por um id único e encurta o bloco de dados
(``mode_value``/``led_value`` somem, entram mapa de matriz por segmento e
``display_name``). A mesma classe fala v0 a v6 e devolve sempre a mesma
estrutura, para a UI não precisar saber a versão do servidor.
"""

from __future__ import annotations

import logging
import socket
import struct
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Iterable, Optional, Sequence

#: Versão mais alta que este cliente implementa. O servidor negocia para
#: baixo; ``protocol_version`` é sempre o mínimo entre os dois.
_CLIENT_MAX_PROTOCOL = 6

_MAGIC = b"ORGB"
_HEADER = struct.Struct("<4sIII")

#: 8 MB é folgado para o maior bloco de dados plausível (um controlador com
#: milhares de LEDs) e barra qualquer resposta deformada antes de virar
#: memória. Sem o teto, um ``pkt_size`` corrompido travaria a thread.
_MAX_PACKET = 8 * 1024 * 1024

#: Porta convencional do servidor ("ORGB" num teclado de telefone).
DEFAULT_PORT = 6742
DEFAULT_HOST = "127.0.0.1"


class PacketType(IntEnum):
    """Ids de pacote do protocolo, só os que este cliente usa."""

    REQUEST_CONTROLLER_COUNT = 0
    REQUEST_CONTROLLER_DATA = 1
    ACK = 10
    REQUEST_PROTOCOL_VERSION = 40
    SET_CLIENT_NAME = 50
    SET_SERVER_NAME = 51
    SET_CLIENT_FLAGS = 52
    SET_SERVER_FLAGS = 53
    DEVICE_LIST_UPDATED = 100
    DETECTION_STARTED = 101
    DETECTION_PROGRESS_CHANGED = 102
    DETECTION_COMPLETE = 103
    REQUEST_RESCAN_DEVICES = 140
    RGBCONTROLLER_RESIZEZONE = 1000
    RGBCONTROLLER_CLEARSEGMENTS = 1001
    RGBCONTROLLER_ADDSEGMENT = 1002
    RGBCONTROLLER_UPDATELEDS = 1050
    RGBCONTROLLER_UPDATEZONELEDS = 1051
    RGBCONTROLLER_UPDATESINGLELED = 1052
    RGBCONTROLLER_SETCUSTOMMODE = 1100
    RGBCONTROLLER_UPDATEMODE = 1101
    RGBCONTROLLER_SAVEMODE = 1102


#: Pacotes que o servidor manda sem ninguém pedir. Recebidos no meio de uma
#: consulta, eles não são a resposta e precisam ser descartados.
_UNSOLICITED = frozenset(
    {
        PacketType.ACK,
        PacketType.SET_SERVER_NAME,
        PacketType.SET_SERVER_FLAGS,
        PacketType.DEVICE_LIST_UPDATED,
        PacketType.DETECTION_STARTED,
        PacketType.DETECTION_PROGRESS_CHANGED,
        PacketType.DETECTION_COMPLETE,
    }
)

#: Códigos de status do ACK (protocolo 6+).
ACK_STATUS = {
    0: "ok",
    1: "erro genérico",
    2: "não suportado",
    3: "não permitido",
    4: "id de dispositivo inválido",
    5: "dados inválidos",
}


class ZoneType(IntEnum):
    """Tipos de zona do SDK, para a UI escolher o editor."""

    SINGLE = 0
    LINEAR = 1
    MATRIX = 2
    LINEAR_LOOP = 3
    MATRIX_LOOP_X = 4
    MATRIX_LOOP_Y = 5
    SEGMENTED = 6


class DeviceType(IntEnum):
    """Tipos de controlador do SDK (v5+). Desconhecido vira ``UNKNOWN``."""

    MOTHERBOARD = 0
    DRAM = 1
    GPU = 2
    COOLER = 3
    LEDSTRIP = 4
    KEYBOARD = 5
    MOUSE = 6
    MOUSEMAT = 7
    HEADSET = 8
    HEADSET_STAND = 9
    GAMEPAD = 10
    LIGHT = 11
    SPEAKER = 12
    VIRTUAL = 13
    STORAGE = 14
    CASE = 15
    MICROPHONE = 16
    ACCESSORY = 17
    KEYPAD = 18
    UNKNOWN = 19


class ModeFlags(IntEnum):
    """Bits de ``ModeFlags`` do SDK."""

    HAS_SPEED = 1 << 0
    HAS_DIRECTION_LR = 1 << 1
    HAS_DIRECTION_UD = 1 << 2
    HAS_DIRECTION_HV = 1 << 3
    HAS_BRIGHTNESS = 1 << 4
    HAS_PER_LED_COLOR = 1 << 5
    HAS_MODE_SPECIFIC_COLOR = 1 << 6
    HAS_RANDOM_COLOR = 1 << 7


class ModeColorMode(IntEnum):
    NONE = 0
    PER_LED = 1
    MODE_SPECIFIC = 2
    RANDOM = 3


#: Bit de ``RGBController::flags`` (v5+): o controlador pode ser resized.
CONTROLLER_FLAG_MANUAL_SAVE = 1 << 0
CONTROLLER_FLAG_AUTO_SAVE = 1 << 1
CONTROLLER_FLAG_LOCAL_SAVE = 1 << 2


class OpenRGBError(Exception):
    """Falha ao falar com o servidor do SDK."""


class OpenRGBDisconnected(OpenRGBError):
    """O soquete caiu (servidor parado, reiniciado ou rede fora)."""


class ProtocolError(OpenRGBError):
    """Resposta fora do formato documentado."""


@dataclass(frozen=True)
class RGB:
    """Uma cor do SDK. O protocolo manda 4 bytes por cor; o quarto é reserva."""

    red: int = 0
    green: int = 0
    blue: int = 0

    def as_tuple(self) -> tuple[int, int, int]:
        return (self.red, self.green, self.blue)

    def pack(self) -> bytes:
        return struct.pack("<BBBx", self.red, self.green, self.blue)

    @classmethod
    def from_hex(cls, value: str) -> "RGB":
        """``"#9141ac"`` (ou sem ``#``) como cor; preto quando ilegível."""
        texto = (value or "").strip().lstrip("#")
        try:
            return cls(
                int(texto[0:2], 16), int(texto[2:4], 16), int(texto[4:6], 16)
            )
        except (ValueError, IndexError):
            return cls()

    def as_hex(self) -> str:
        return f"#{self.red:02x}{self.green:02x}{self.blue:02x}"


BLACK = RGB(0, 0, 0)


@dataclass
class Mode:
    """Um modo de um controlador, com os limites que o hardware declara."""

    index: int
    name: str
    value: int = 0
    flags: int = 0
    speed_min: int = 0
    speed_max: int = 0
    brightness_min: int = 0
    brightness_max: int = 0
    colors_min: int = 0
    colors_max: int = 0
    speed: int = 0
    brightness: int = 0
    direction: int = 0
    color_mode: int = ModeColorMode.NONE
    colors: list[RGB] = field(default_factory=list)

    @property
    def has_speed(self) -> bool:
        return bool(self.flags & ModeFlags.HAS_SPEED)

    @property
    def has_brightness(self) -> bool:
        return bool(self.flags & ModeFlags.HAS_BRIGHTNESS)

    @property
    def has_per_led(self) -> bool:
        return bool(self.flags & ModeFlags.HAS_PER_LED_COLOR)

    @property
    def has_mode_color(self) -> bool:
        return bool(self.flags & ModeFlags.HAS_MODE_SPECIFIC_COLOR)

    @property
    def is_direct(self) -> bool:
        """Modo em que o cliente manda as cores LED a LED.

        Só o nome e o ``color_mode`` contam. O bit ``HAS_PER_LED_COLOR``
        sozinho não serve: vários controladores o declaram em modos fixos
        (*Static*, *Breathing*), e escolher um deles faria o perfil colorir
        LEDs que o firmware ignora.
        """
        nome = self.name.strip().lower()
        return nome in {
            "direct",
            "direct control",
            "direct mode",
            "custom",
            "manual",
        } or self.color_mode == ModeColorMode.PER_LED

    @property
    def is_off(self) -> bool:
        return self.name.strip().lower() in {"off", "desligado"}


@dataclass
class Segment:
    """Um pedaço de uma zona (v4+), com os LEDs que ele ocupa."""

    name: str
    start_index: int
    leds_count: int
    zone_type: int = ZoneType.LINEAR
    matrix: Optional[list[list[Optional[int]]]] = None


@dataclass
class Zone:
    """Uma zona do controlador: a unidade que o hardware expõe."""

    index: int
    name: str
    zone_type: int
    leds_min: int
    leds_max: int
    leds_count: int
    start_index: int = 0
    matrix_height: int = 0
    matrix_width: int = 0
    matrix: Optional[list[list[Optional[int]]]] = None
    segments: list[Segment] = field(default_factory=list)
    flags: int = 0

    @property
    def is_matrix(self) -> bool:
        """A zona tem mapa de posições confiável (grade de LEDs)."""
        return bool(self.matrix) and self.matrix_width > 0

    @property
    def is_linear(self) -> bool:
        return self.zone_type in (
            ZoneType.LINEAR,
            ZoneType.LINEAR_LOOP,
            ZoneType.SEGMENTED,
        )


@dataclass
class Led:
    """Um LED endereçável, com o nome que o servidor deu a ele."""

    index: int
    name: str


@dataclass
class Controller:
    """Um controlador (dispositivo) do servidor, já normalizado."""

    device_id: int
    name: str
    vendor: str = ""
    description: str = ""
    version: str = ""
    serial: str = ""
    location: str = ""
    device_type: int = DeviceType.UNKNOWN
    active_mode: int = 0
    modes: list[Mode] = field(default_factory=list)
    zones: list[Zone] = field(default_factory=list)
    leds: list[Led] = field(default_factory=list)
    colors: list[RGB] = field(default_factory=list)
    led_display_names: list[str] = field(default_factory=list)
    flags: int = 0
    display_name: str = ""

    @property
    def display(self) -> str:
        """O melhor nome para mostrar: o apelido do servidor ou o físico."""
        return (self.display_name or self.name or "Controlador").strip()

    @property
    def vendor_and_name(self) -> str:
        partes = [parte for parte in (self.vendor, self.display) if parte]
        return " ".join(partes)

    @property
    def active(self) -> Optional[Mode]:
        if 0 <= self.active_mode < len(self.modes):
            return self.modes[self.active_mode]
        return None

    @property
    def direct_mode(self) -> Optional[Mode]:
        """O modo em que dá para mandar cor LED a LED, se houver um."""
        ativo = self.active
        if ativo is not None and ativo.is_per_led:
            return ativo
        for modo in self.modes:
            if modo.is_direct:
                return modo
        return None

    @property
    def leds_per_zone(self) -> list[int]:
        return [zona.leds_count for zona in self.zones]

    @property
    def has_matrix(self) -> bool:
        return any(zona.is_matrix for zona in self.zones)


class _Reader:
    """Leitor sequencial de um bloco de dados, com erro de formato claro."""

    __slots__ = ("_dados", "_posicao")

    def __init__(self, dados: bytes) -> None:
        self._dados = dados
        self._posicao = 0

    @property
    def restante(self) -> int:
        return len(self._dados) - self._posicao

    def _pegar(self, formato: str) -> Any:
        tamanho = struct.calcsize(formato)
        if self.restante < tamanho:
            raise ProtocolError(
                f"bloco curto: {tamanho} bytes pedidos, {self.restante} restantes"
            )
        valores = struct.unpack_from(formato, self._dados, self._posicao)
        self._posicao += tamanho
        return valores[0] if len(valores) == 1 else valores

    def u8(self) -> int:
        return int(self._pegar("<B"))

    def u16(self) -> int:
        return int(self._pegar("<H"))

    def u32(self) -> int:
        return int(self._pegar("<I"))

    def i32(self) -> int:
        return int(self._pegar("<i"))

    def raw(self, tamanho: int) -> bytes:
        if tamanho < 0 or self.restante < tamanho:
            raise ProtocolError(f"bloco curto: {tamanho} bytes pedidos")
        dados = self._dados[self._posicao : self._posicao + tamanho]
        self._posicao += tamanho
        return dados

    def text(self) -> str:
        """String precedida do tamanho, com o terminador nulo incluso."""
        tamanho = self.u16()
        if tamanho == 0:
            return ""
        return self.raw(tamanho).split(b"\x00", 1)[0].decode("utf-8", "replace")

    def color(self) -> RGB:
        return RGB(*self._pegar("<BBBx"))


def _parse_matrix(reader: _Reader, tamanho: int) -> tuple[int, int, list[list[Optional[int]]]]:
    """Lê um mapa de matriz. ``tamanho`` é o do bloco inteiro, já validado."""
    altura = reader.u32()
    largura = reader.u32()
    if altura * largura > (tamanho - 8) // 4:
        raise ProtocolError("mapa de matriz maior do que o bloco declara")
    linhas: list[list[Optional[int]]] = []
    for _ in range(altura):
        linha: list[Optional[int]] = []
        for _ in range(largura):
            valor = reader.u32()
            # 0xFFFFFFFF é "buraco": posição da grade sem LED.
            linha.append(None if valor == 0xFFFFFFFF else valor)
        linhas.append(linha)
    return altura, largura, linhas


def _parse_mode(reader: _Reader, index: int, versao: int) -> Mode:
    nome = reader.text()
    modo = Mode(index=index, name=nome)
    if versao < 6:
        modo.value = reader.i32()
    modo.flags = reader.u32()
    modo.speed_min = reader.u32()
    modo.speed_max = reader.u32()
    if versao >= 3:
        modo.brightness_min = reader.u32()
        modo.brightness_max = reader.u32()
    modo.colors_min = reader.u32()
    modo.colors_max = reader.u32()
    modo.speed = reader.u32()
    if versao >= 3:
        modo.brightness = reader.u32()
    modo.direction = reader.u32()
    modo.color_mode = reader.u32()
    quantidade = reader.u16()
    modo.colors = [reader.color() for _ in range(quantidade)]
    if not modo.has_speed:
        modo.speed_min = modo.speed_max = modo.speed = 0
    if not modo.has_brightness:
        modo.brightness_min = modo.brightness_max = modo.brightness = 0
    return modo


def _parse_zone(reader: _Reader, index: int, versao: int) -> Zone:
    nome = reader.text()
    tipo = reader.i32()
    zona = Zone(
        index=index,
        name=nome,
        zone_type=tipo,
        leds_min=reader.u32(),
        leds_max=reader.u32(),
        leds_count=reader.u32(),
    )
    tamanho_matriz = reader.u16()
    if tamanho_matriz > 0:
        # O tamanho declarado é o do bloco; o mapa não pode passar dele.
        inicio = reader.restante
        altura, largura, mapa = _parse_matrix(reader, tamanho_matriz)
        consumido = inicio - reader.restante
        if consumido < tamanho_matriz:
            reader.raw(tamanho_matriz - consumido)
        zona.matrix_height, zona.matrix_width, zona.matrix = altura, largura, mapa
    if versao >= 4:
        quantidade = reader.u16()
        for indice_segmento in range(quantidade):
            nome_segmento = reader.text()
            tipo_segmento = reader.i32()
            inicio = reader.u32()
            leds = reader.u32()
            matriz_segmento: Optional[list[list[Optional[int]]]] = None
            if versao >= 6:
                tamanho_segmento = reader.u16()
                if tamanho_segmento > 0:
                    _, _, matriz_segmento = _parse_matrix(reader, tamanho_segmento)
                reader.u32()  # flags do segmento
            zona.segments.append(
                Segment(nome_segmento, inicio, leds, tipo_segmento, matriz_segmento)
            )
            del indice_segmento
    if versao >= 5:
        zona.flags = reader.u32()
    if versao >= 6:
        reader.i32()  # active_mode da zona
        modos_zona = reader.u16()
        for _ in range(modos_zona):
            _parse_mode(reader, 0, versao)
        reader.text()  # display_name da zona
    return zona


def parse_controller(dados: bytes, versao: int) -> Controller:
    """Interpreta o bloco de Device Data do protocolo."""
    reader = _Reader(dados)
    if reader.restante >= 4:
        reader.u32()  # data_size, redundante com pkt_size
    tipo = reader.i32()
    try:
        tipo_dispositivo = DeviceType(tipo)
    except ValueError:
        tipo_dispositivo = DeviceType.UNKNOWN
    controlador = Controller(
        device_id=0, name=reader.text(), device_type=int(tipo_dispositivo)
    )
    if versao >= 1:
        controlador.vendor = reader.text()
    controlador.description = reader.text()
    controlador.version = reader.text()
    controlador.serial = reader.text()
    controlador.location = reader.text()

    quantidade_modos = reader.u16()
    controlador.active_mode = reader.i32()
    controlador.modes = [
        _parse_mode(reader, indice, versao) for indice in range(quantidade_modos)
    ]

    quantidade_zonas = reader.u16()
    controlador.zones = [
        _parse_zone(reader, indice, versao) for indice in range(quantidade_zonas)
    ]

    quantidade_leds = reader.u16()
    controlador.leds = [
        Led(indice, reader.text()) for indice in range(quantidade_leds)
    ]

    quantidade_cores = reader.u16()
    controlador.colors = [reader.color() for _ in range(quantidade_cores)]

    if versao >= 5:
        quantidade_nomes = reader.u16()
        controlador.led_display_names = [
            reader.text() for _ in range(quantidade_nomes)
        ]
        controlador.flags = reader.u32()
    if versao >= 6 and reader.restante >= 2:
        controlador.display_name = reader.text()
        if reader.restante >= 4:
            tamanho = reader.u32()
            if 0 < tamanho <= reader.restante:
                reader.raw(tamanho)  # configuração específica do dispositivo

    # O índice global de cada zona vem da soma dos LEDs das anteriores.
    inicio = 0
    for zona in controlador.zones:
        zona.start_index = inicio
        inicio += zona.leds_count
    return controlador


def leds_of(controlador: Controller) -> int:
    """Quantos LEDs o controlador realmente tem (zonas mandam, não a lista)."""
    total_zonas = sum(zona.leds_count for zona in controlador.zones)
    return total_zonas or len(controlador.leds)


class OpenRGBClient:
    """Conversa com um servidor OpenRGB local pelo SDK.

    Não é reentrante nem sincronizada: um cliente pertence a uma thread. O
    coordenador de iluminação serializa as chamadas, e é isso que mantém o
    soquete são.
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        nome: str = "Jolven",
        timeout: float = 5.0,
    ) -> None:
        self.host = host
        self.port = port
        self.name = nome
        self.timeout = timeout
        self.protocol_version = 0
        self._soquete: Optional[socket.socket] = None
        self._pending_device_list = False

    # -- conexão -----------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._soquete is not None

    def connect(self) -> "OpenRGBClient":
        if self._soquete is not None:
            return self
        self._soquete = socket.create_connection(
            (self.host, self.port), timeout=self.timeout
        )
        self._soquete.settimeout(self.timeout)
        try:
            self._negociar()
        except BaseException:
            self.close()
            raise
        return self

    def _negociar(self) -> None:
        """Negocia a versão do protocolo e se apresenta ao servidor."""
        self._enviar(
            0,
            PacketType.REQUEST_PROTOCOL_VERSION,
            struct.pack("<I", _CLIENT_MAX_PROTOCOL),
        )
        try:
            _, dados = self._receber(PacketType.REQUEST_PROTOCOL_VERSION)
        except (OpenRGBError, socket.timeout):
            # Servidor v0 não conhece o pacote: fica calado. É o protocolo dele.
            self.protocol_version = 0
        else:
            self.protocol_version = min(
                _CLIENT_MAX_PROTOCOL,
                struct.unpack("<I", dados[:4])[0],
            )
        logging.info(
            "OpenRGB: protocolo %s negociado em %s:%s",
            self.protocol_version,
            self.host,
            self.port,
        )
        self._enviar(0, PacketType.SET_CLIENT_NAME, self.name.encode("utf-8") + b"\x00")

    def close(self) -> None:
        soquete, self._soquete = self._soquete, None
        if soquete is None:
            return
        try:
            soquete.close()
        except OSError:
            pass

    def __enter__(self) -> "OpenRGBClient":
        return self.connect()

    def __exit__(self, *_args: Any) -> None:
        self.close()

    # -- transporte --------------------------------------------------

    def _enviar(self, device_id: int, pkt_id: int, dados: bytes = b"") -> None:
        if self._soquete is None:
            raise OpenRGBDisconnected("sem conexão com o OpenRGB")
        pacote = _HEADER.pack(_MAGIC, device_id, int(pkt_id), len(dados)) + dados
        if len(pacote) > _MAX_PACKET:
            raise ProtocolError("pacote grande demais para enviar")
        try:
            self._soquete.sendall(pacote)
        except OSError as erro:
            self.close()
            raise OpenRGBDisconnected(str(erro)) from erro

    def _ler_exato(self, tamanho: int) -> bytes:
        if self._soquete is None:
            raise OpenRGBDisconnected("sem conexão com o OpenRGB")
        pedacos = bytearray()
        while len(pedacos) < tamanho:
            try:
                pedaco = self._soquete.recv(tamanho - len(pedacos))
            except OSError as erro:
                self.close()
                raise OpenRGBDisconnected(str(erro)) from erro
            if not pedaco:
                self.close()
                raise OpenRGBDisconnected("o servidor fechou a conexão")
            pedacos.extend(pedaco)
        return bytes(pedacos)

    def _receber(self, esperado: int) -> tuple[int, bytes]:
        """Lê até chegar a resposta ``esperado``, descartando o resto.

        O servidor manda ACK e avisos de atualização de lista sem esperar
        nada; eles chegam entre o pedido e a resposta e não são a resposta.
        """
        while True:
            cabecalho = self._ler_exato(_HEADER.size)
            magia, device_id, pkt_id, tamanho = _HEADER.unpack(cabecalho)
            if magia != _MAGIC:
                self.close()
                raise ProtocolError("resposta sem a assinatura do SDK")
            if tamanho > _MAX_PACKET:
                self.close()
                raise ProtocolError(f"pacote de {tamanho} bytes recusado")
            dados = self._ler_exato(tamanho) if tamanho else b""
            if pkt_id in _UNSOLICITED:
                self._tratar_espontaneo(device_id, pkt_id, dados)
                continue
            if pkt_id != esperado:
                # Fora de ordem não deveria acontecer (o SDK é síncrono por
                # cliente); seguir em frente é melhor que travar a thread.
                logging.debug(
                    "OpenRGB: pacote %s ignorado enquanto se esperava %s",
                    pkt_id,
                    esperado,
                )
                continue
            return device_id, dados

    def _tratar_espontaneo(self, device_id: int, pkt_id: int, dados: bytes) -> None:
        if pkt_id == PacketType.DEVICE_LIST_UPDATED:
            self._pending_device_list = True
            logging.debug("OpenRGB: servidor sinalizou lista de dispositivos nova")
        elif pkt_id == PacketType.ACK:
            if len(dados) >= 8:
                pedido, status = struct.unpack("<II", dados[:8])
                if status != 0:
                    logging.warning(
                        "OpenRGB recusou o pacote %s (device %s): %s",
                        pedido,
                        device_id,
                        ACK_STATUS.get(status, status),
                    )
        elif pkt_id == PacketType.SET_SERVER_NAME and dados:
            logging.debug(
                "OpenRGB: servidor se apresentou como %s",
                dados.split(b"\x00", 1)[0].decode("utf-8", "replace"),
            )
        elif pkt_id in (
            PacketType.DETECTION_STARTED,
            PacketType.DETECTION_PROGRESS_CHANGED,
            PacketType.DETECTION_COMPLETE,
        ):
            self._pending_device_list = True

    # -- leitura -----------------------------------------------------

    @property
    def device_list_changed(self) -> bool:
        """O servidor avisou que a lista mudou desde a última consulta."""
        return self._pending_device_list

    def controllers(self) -> list[Controller]:
        """Todos os controladores do servidor, já com a versão negociada."""
        self._pending_device_list = False
        self._enviar(0, PacketType.REQUEST_CONTROLLER_COUNT)
        _, dados = self._receber(PacketType.REQUEST_CONTROLLER_COUNT)
        if len(dados) < 4:
            raise ProtocolError("contagem de controladores vazia")
        quantidade = struct.unpack("<I", dados[:4])[0]
        if quantidade > 4096:
            raise ProtocolError(f"contagem de controladores absurda: {quantidade}")

        ids: list[int] = []
        if self.protocol_version >= 6:
            # v6 responde a contagem seguida dos ids únicos; o tamanho diz
            # quantos vieram, e um servidor v5 jamais chega aqui.
            disponiveis = (len(dados) - 4) // 4
            ids = list(struct.unpack(f"<{min(disponiveis, quantidade)}I", dados[4:4 + 4 * min(disponiveis, quantidade)]))

        controladores: list[Controller] = []
        for indice in range(quantidade):
            device_id = ids[indice] if indice < len(ids) else indice
            controlador = self.controller(device_id)
            controlador.device_id = device_id
            controladores.append(controlador)
        return controladores

    def controller(self, device_id: int) -> Controller:
        pedido = (
            struct.pack("<I", self.protocol_version)
            if self.protocol_version >= 1
            else b""
        )
        self._enviar(device_id, PacketType.REQUEST_CONTROLLER_DATA, pedido)
        _, dados = self._receber(PacketType.REQUEST_CONTROLLER_DATA)
        controlador = parse_controller(dados, self.protocol_version)
        controlador.device_id = device_id
        return controlador

    def rescan(self) -> None:
        """Pede ao servidor que redescubra os dispositivos (protocolo 5+)."""
        if self.protocol_version < 5:
            return
        self._enviar(0, PacketType.REQUEST_RESCAN_DEVICES)

    # -- escrita -----------------------------------------------------

    def _comando(self, device_id: int, pkt_id: int, dados: bytes = b"") -> None:
        """Manda um comando de escrita.

        Em v6 o servidor confirma por ACK; nas versões antigas não confirma
        nada. Como não dá para saber quando a confirmação vem sem ler adiante
        (e um ACK lido na consulta seguinte viraria resposta errada), o ACK
        fica para o próximo ``_receber``, que o descarta.
        """
        self._enviar(device_id, pkt_id, dados)

    def set_custom_mode(self, device_id: int) -> None:
        """Põe o controlador em modo direto, sem gravar nada na EEPROM."""
        self._comando(device_id, PacketType.RGBCONTROLLER_SETCUSTOMMODE)

    def update_leds(self, device_id: int, colors: Sequence[RGB]) -> None:
        """Manda a cor de todos os LEDs do controlador de uma vez."""
        corpo = struct.pack("<H", len(colors)) + b"".join(
            cor.pack() for cor in colors
        )
        self._comando(
            device_id,
            PacketType.RGBCONTROLLER_UPDATELEDS,
            struct.pack("<I", len(corpo) + 4) + corpo,
        )

    def update_zone_leds(
        self, device_id: int, zone_index: int, colors: Sequence[RGB]
    ) -> None:
        """Manda a cor dos LEDs de uma zona só."""
        corpo = (
            struct.pack("<IH", zone_index, len(colors))
            + b"".join(cor.pack() for cor in colors)
        )
        self._comando(
            device_id,
            PacketType.RGBCONTROLLER_UPDATEZONELEDS,
            struct.pack("<I", len(corpo) + 4) + corpo,
        )

    def update_single_led(self, device_id: int, led_index: int, color: RGB) -> None:
        self._comando(
            device_id,
            PacketType.RGBCONTROLLER_UPDATESINGLELED,
            struct.pack("<i", led_index) + color.pack(),
        )

    @staticmethod
    def pack_mode(modo: Mode, versao: int) -> bytes:
        """Bloco de dados de um modo, como o UpdateMode espera."""
        corpo = struct.pack("<i", modo.index)
        if versao < 6:
            corpo += struct.pack("<i", modo.value)
        corpo += struct.pack("<I", modo.flags)
        corpo += struct.pack("<I", modo.speed_min)
        corpo += struct.pack("<I", modo.speed_max)
        if versao >= 3:
            corpo += struct.pack("<I", modo.brightness_min)
            corpo += struct.pack("<I", modo.brightness_max)
        corpo += struct.pack("<I", modo.colors_min)
        corpo += struct.pack("<I", modo.colors_max)
        corpo += struct.pack("<I", modo.speed)
        if versao >= 3:
            corpo += struct.pack("<I", modo.brightness)
        corpo += struct.pack("<I", modo.direction)
        corpo += struct.pack("<I", modo.color_mode)
        corpo += struct.pack("<H", len(modo.colors))
        corpo += b"".join(cor.pack() for cor in modo.colors)
        return struct.pack("<I", len(corpo) + 4) + corpo

    def update_mode(self, device_id: int, modo: Mode, *, save: bool = False) -> None:
        """Aplica um modo. ``save`` grava na memória do controlador — nunca
        usado por padrão: o Jolven só empresta a iluminação por uma sessão."""
        dados = self.pack_mode(modo, self.protocol_version)
        self._comando(device_id, PacketType.RGBCONTROLLER_UPDATEMODE, dados)
        if save:
            if self.protocol_version < 3:
                raise ProtocolError("SaveMode exige protocolo 3 ou mais novo")
            self._comando(device_id, PacketType.RGBCONTROLLER_SAVEMODE, dados)


#: Pacotes de escrita cujo sucesso o v6 confirma por ACK. Não é preciso
#: consultar a lista: ``_receber`` descarta qualquer ACK que apareça.


def splice_colors(
    base: Sequence[RGB], inicio: int, cores: Iterable[RGB]
) -> list[RGB]:
    """Devolve ``base`` com as cores de ``inicio`` em diante trocadas.

    Usado para montar o pacote completo que o UpdateLEDs exige a partir de uma
    edição por trecho: o protocolo manda o controlador inteiro, sempre.
    """
    lista = list(base)
    for deslocamento, cor in enumerate(cores):
        posicao = inicio + deslocamento
        if 0 <= posicao < len(lista):
            lista[posicao] = cor
    return lista

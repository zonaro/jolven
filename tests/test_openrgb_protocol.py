# test_openrgb_protocol.py
#
# Copyright 2026 Jolven contributors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O pacote do SDK do OpenRGB, montado byte a byte.

Os fixtures vêm de ``struct.pack`` escrito aqui, não do pacote da própria
implementação: se o formato que a gente escreveu estiver errado, o teste
precisa acusar, não confirmar o próprio erro.

O OpenRGB não é obrigatório nem instalado nesta máquina — nada aqui abre
conexão de rede de verdade. O transporte usa ``socket.socketpair``, que é um
túnel local de duas pontas.
"""

import socket
import struct
import unittest

from cartridges.integrations.openrgb import protocol
from cartridges.integrations.openrgb.protocol import (
    DeviceType,
    ModeColorMode,
    OpenRGBClient,
    OpenRGBDisconnected,
    PacketType,
    ProtocolError,
    RGB,
    leds_of,
    parse_controller,
    splice_colors,
)

#: Cabeçalho do SDK: assinatura + device id + packet id + tamanho dos dados.
#: Escrito à mão aqui de propósito.
CABECALHO = struct.Struct("<4sIII")
MAGIA = b"ORGB"


def texto(valor: str) -> bytes:
    """String do SDK: tamanho (u16) seguido dos bytes, com o NUL incluso."""
    bruto = valor.encode("utf-8") + b"\x00"
    return struct.pack("<H", len(bruto)) + bruto


def pacote(device_id: int, pkt_id: int, dados: bytes = b"") -> bytes:
    return CABECALHO.pack(MAGIA, device_id, pkt_id, len(dados)) + dados


def modo(nome: str, versao: int, flags: int = 0, color_mode: int = 0) -> bytes:
    """Um ``mode_t`` na ordem em que o SDK escreve (v6 perdeu ``mode_value``)."""
    dados = texto(nome)
    if versao < 6:
        dados += struct.pack("<i", 0)
    dados += struct.pack("<I", flags)
    dados += struct.pack("<II", 0, 0)  # speed_min, speed_max
    if versao >= 3:
        dados += struct.pack("<II", 0, 0)  # brightness_min, brightness_max
    dados += struct.pack("<II", 0, 0)  # colors_min, colors_max
    dados += struct.pack("<I", 0)  # speed
    if versao >= 3:
        dados += struct.pack("<I", 0)  # brightness
    dados += struct.pack("<I", 0)  # direction
    dados += struct.pack("<I", color_mode)
    dados += struct.pack("<H", 0)  # quantidade de cores do modo
    return dados


def zona(nome: str, leds: int, versao: int, tipo: int = 1) -> bytes:
    dados = texto(nome)
    dados += struct.pack("<i", tipo)
    dados += struct.pack("<III", leds, leds, leds)
    dados += struct.pack("<H", 0)  # tamanho do mapa de matriz
    if versao >= 4:
        dados += struct.pack("<H", 0)  # segmentos
    if versao >= 5:
        dados += struct.pack("<I", 0)  # flags da zona
    if versao >= 6:
        dados += struct.pack("<i", 0)  # active_mode da zona
        dados += struct.pack("<H", 0)  # modos da zona
        dados += texto("")
    return dados


def controlador(
    versao: int,
    *,
    nome: str = "Placa de teste",
    tipo: int = int(DeviceType.MOTHERBOARD),
    fabricante: str = "Acme",
    modos: tuple[bytes, ...] = (),
    zonas: tuple[bytes, ...] = (),
    leds: tuple[str, ...] = (),
    cores: tuple[tuple[int, int, int], ...] = (),
    display_name: str = "",
    cfg: bytes = b"",
) -> bytes:
    corpo = struct.pack("<i", tipo)
    corpo += texto(nome)
    if versao >= 1:
        corpo += texto(fabricante)
    corpo += texto("Descrição") + texto("1.0") + texto("SN123") + texto("Interno")
    corpo += struct.pack("<H", len(modos))
    corpo += struct.pack("<i", 0)  # active_mode
    for item in modos:
        corpo += item
    corpo += struct.pack("<H", len(zonas))
    for item in zonas:
        corpo += item
    corpo += struct.pack("<H", len(leds))
    for nome_led in leds:
        corpo += texto(nome_led)
    corpo += struct.pack("<H", len(cores))
    for vermelho, verde, azul in cores:
        corpo += struct.pack("<BBBx", vermelho, verde, azul)
    if versao >= 5:
        corpo += struct.pack("<H", 0)  # nomes de exibição dos LEDs
        corpo += struct.pack("<I", 0)  # flags do controlador
    if versao >= 6:
        corpo += texto(display_name)
        corpo += struct.pack("<I", len(cfg)) + cfg
    # O data_size vem primeiro e conta a si mesmo.
    return struct.pack("<I", len(corpo) + 4) + corpo


class TestParseController(unittest.TestCase):
    def test_v6_basico(self) -> None:
        bloco = controlador(
            6,
            nome="Memória",
            tipo=int(DeviceType.DRAM),
            modos=(modo("Direct", 6, color_mode=int(ModeColorMode.PER_LED)),),
            zonas=(zona("Módulo 1", 4, 6),),
            leds=("LED 1", "LED 2", "LED 3", "LED 4"),
            cores=((10, 20, 30), (40, 50, 60), (0, 0, 0), (1, 2, 3)),
            display_name="Memória RGB",
        )
        control = parse_controller(bloco, 6)
        self.assertEqual(control.name, "Memória")
        self.assertEqual(control.vendor, "Acme")
        self.assertEqual(control.device_type, int(DeviceType.DRAM))
        self.assertEqual(control.display, "Memória RGB", "o apelido do servidor vence")
        self.assertEqual(len(control.modes), 1)
        self.assertEqual(control.modes[0].name, "Direct")
        self.assertTrue(control.modes[0].is_direct)
        self.assertEqual(len(control.zones), 1)
        self.assertEqual(control.zones[0].leds_count, 4)
        self.assertEqual(len(control.leds), 4)
        self.assertEqual(control.colors[0].as_tuple(), (10, 20, 30))
        self.assertEqual(leds_of(control), 4)

    def test_v6_sem_display_name_ca_no_nome_fisico(self) -> None:
        control = controlador(
            6, nome="Teclado", tipo=int(DeviceType.KEYBOARD), display_name=""
        )
        self.assertEqual(parse_controller(control, 6).display, "Teclado")

    def test_v6_sem_zonas_usa_a_lista_de_leds(self) -> None:
        bloco = controlador(6, leds=("a", "b"), cores=((1, 1, 1), (2, 2, 2)))
        control = parse_controller(bloco, 6)
        self.assertEqual(leds_of(control), 2, "sem zona, a lista é o que sobra")

    def test_zonas_mandam_sobre_a_lista(self) -> None:
        bloco = controlador(
            6,
            zonas=(zona("A", 3, 6), zona("B", 5, 6)),
            leds=("ignorado",),
        )
        control = parse_controller(bloco, 6)
        self.assertEqual(leds_of(control), 8)

    def test_v6_perde_o_mode_value(self) -> None:
        # Em v6 o campo `mode_value` saiu do pacote: sobrar ele faria o leitor
        # andar errado e ler lixo como nome de modo.
        bloco = controlador(6, modos=(modo("Efeito", 6),), zonas=(zona("z", 1, 6),))
        control = parse_controller(bloco, 6)
        self.assertEqual(control.modes[0].name, "Efeito")
        self.assertEqual(control.zones[0].name, "z")

    def test_v5_ainda_tem_o_mode_value(self) -> None:
        bloco = controlador(5, modos=(modo("Efeito", 5),), zonas=(zona("z", 1, 5),))
        control = parse_controller(bloco, 5)
        self.assertEqual(control.modes[0].name, "Efeito")
        self.assertEqual(control.zones[0].name, "z")

    def test_v3_com_brilho(self) -> None:
        bloco = controlador(3, modos=(modo("Brilho", 3, flags=1 << 4),))
        control = parse_controller(bloco, 3)
        self.assertTrue(control.modes[0].has_brightness)
        self.assertFalse(control.modes[0].has_speed)

    def test_tipo_desconhecido_nao_estoura(self) -> None:
        bloco = controlador(6, tipo=9999)
        control = parse_controller(bloco, 6)
        self.assertEqual(control.device_type, int(DeviceType.UNKNOWN))

    def test_controlador_de_v0(self) -> None:
        # v0 não traz vendor nem os campos de v5/v6.
        bloco = controlador(0, nome="Antigo", zonas=(zona("z", 2, 0),))
        control = parse_controller(bloco, 0)
        self.assertEqual(control.name, "Antigo")
        self.assertEqual(control.vendor, "")
        self.assertEqual(control.zones[0].leds_count, 2)

    def test_truncado_e_protocol_error(self) -> None:
        bloco = controlador(6, modos=(modo("Direct", 6),))
        with self.assertRaises(ProtocolError):
            parse_controller(bloco[: len(bloco) // 2], 6)

    def test_bloco_de_matriz_maior_que_o_declarado(self) -> None:
        # Mapa diz 100x100 mas o bloco declara 8 bytes: recusar em vez de
        # ler até o infinito.
        zona_ruim = texto("m") + struct.pack("<i", 2)
        zona_ruim += struct.pack("<III", 1, 1, 1)
        zona_ruim += struct.pack("<H", 8)  # tamanho declarado
        zona_ruim += struct.pack("<II", 100, 100)  # altura, largura
        bloco = controlador(6, zonas=(zona_ruim,))
        with self.assertRaises(ProtocolError):
            parse_controller(bloco, 6)


class TestMontagem(unittest.TestCase):
    def test_splice_colors_troca_de_inicio_em_diante(self) -> None:
        base = [RGB(1, 1, 1), RGB(2, 2, 2), RGB(3, 3, 3)]
        saida = splice_colors(base, 1, [RGB(9, 9, 9)])
        self.assertEqual([c.as_tuple() for c in saida], [(1, 1, 1), (9, 9, 9), (3, 3, 3)])

    def test_splice_colors_fora_do_intervalo_e_ignorado(self) -> None:
        base = [RGB(1, 1, 1)]
        self.assertEqual(splice_colors(base, 5, [RGB(9, 9, 9)]), base)
        self.assertEqual(splice_colors(base, -3, [RGB(9, 9, 9)]), base)

    def test_rgb_de_hex(self) -> None:
        self.assertEqual(RGB.from_hex("#9141ac").as_hex(), "#9141ac")
        self.assertEqual(RGB.from_hex("lixo").as_hex(), "#000000")
        self.assertEqual(len(RGB(1, 2, 3).pack()), 4, "a cor do SDK tem 4 bytes")


class _DuasPontas(unittest.TestCase):
    """Um par de soquetes locais no lugar do servidor."""

    def setUp(self) -> None:
        self.esquerda, self.direita = socket.socketpair()
        self.addCleanup(self.esquerda.close)
        self.addCleanup(self.direita.close)
        self.cliente = OpenRGBClient(timeout=2.0)
        self.cliente._soquete = self.esquerda  # pylint: disable=protected-access

    def enviar_do_servidor(self, *pacotes: bytes) -> None:
        self.direita.sendall(b"".join(pacotes))


class TestTransporte(_DuasPontas):
    def test_enviar_monta_o_cabecalho_certinho(self) -> None:
        self.cliente._enviar(3, PacketType.REQUEST_CONTROLLER_COUNT, b"abc")  # pylint: disable=protected-access
        recebido = self.direita.recv(64)
        magia, device_id, pkt_id, tamanho = CABECALHO.unpack(recebido[:CABECALHO.size])
        self.assertEqual(magia, MAGIA)
        self.assertEqual(device_id, 3)
        self.assertEqual(pkt_id, int(PacketType.REQUEST_CONTROLLER_COUNT))
        self.assertEqual(tamanho, 3)
        self.assertEqual(recebido[CABECALHO.size :], b"abc")

    def test_receber_pula_os_pacotes_espontaneos(self) -> None:
        resposta = pacote(0, int(PacketType.REQUEST_CONTROLLER_COUNT), struct.pack("<I", 2))
        # ACK e aviso de lista nova chegam entre o pedido e a resposta.
        self.enviar_do_servidor(
            pacote(0, int(PacketType.ACK), struct.pack("<II", 1, 0)),
            pacote(0, int(PacketType.DEVICE_LIST_UPDATED)),
            resposta,
        )
        device_id, dados = self.cliente._receber(  # pylint: disable=protected-access
            PacketType.REQUEST_CONTROLLER_COUNT
        )
        self.assertEqual(device_id, 0)
        self.assertEqual(struct.unpack("<I", dados)[0], 2)
        self.assertTrue(self.cliente._pending_device_list)  # pylint: disable=protected-access

    def test_receber_ignora_resposta_de_outro_pedido(self) -> None:
        self.enviar_do_servidor(
            pacote(0, int(PacketType.REQUEST_CONTROLLER_DATA), b""),
            pacote(1, int(PacketType.REQUEST_CONTROLLER_COUNT), struct.pack("<I", 7)),
        )
        _, dados = self.cliente._receber(  # pylint: disable=protected-access
            PacketType.REQUEST_CONTROLLER_COUNT
        )
        self.assertEqual(struct.unpack("<I", dados)[0], 7)

    def test_resposta_sem_assinatura_e_erro(self) -> None:
        self.enviar_do_servidor(CABECALHO.pack(b"XXXX", 0, 1, 0))
        with self.assertRaises(ProtocolError):
            self.cliente._receber(PacketType.REQUEST_CONTROLLER_COUNT)  # pylint: disable=protected-access
        self.assertFalse(self.cliente.connected, "a conexão é derrubada no erro")

    def test_pacote_grande_demais_e_recusado(self) -> None:
        self.enviar_do_servidor(CABECALHO.pack(MAGIA, 0, 1, protocol._MAX_PACKET + 1))  # pylint: disable=protected-access
        with self.assertRaises(ProtocolError):
            self.cliente._receber(PacketType.REQUEST_CONTROLLER_COUNT)  # pylint: disable=protected-access

    def test_servidor_fechou_no_meio(self) -> None:
        self.direita.close()
        with self.assertRaises(OpenRGBDisconnected):
            self.cliente._receber(PacketType.REQUEST_CONTROLLER_COUNT)  # pylint: disable=protected-access

    def test_enviar_sem_conexao_e_erro_claro(self) -> None:
        cliente = OpenRGBClient()
        with self.assertRaises(OpenRGBDisconnected):
            cliente._enviar(0, PacketType.REQUEST_CONTROLLER_COUNT)  # pylint: disable=protected-access

    def test_ack_de_recusa_vira_aviso_nao_excecao(self) -> None:
        # Status 4 = "id de dispositivo inválido": o pacote saiu, o servidor
        # recusou, e a sessão não pode morrer por isso.
        self.enviar_do_servidor(
            pacote(
                0,
                int(PacketType.ACK),
                struct.pack("<II", 1100, 4),
            ),
            pacote(0, int(PacketType.REQUEST_CONTROLLER_COUNT), struct.pack("<I", 1)),
        )
        _, dados = self.cliente._receber(  # pylint: disable=protected-access
            PacketType.REQUEST_CONTROLLER_COUNT
        )
        self.assertEqual(struct.unpack("<I", dados)[0], 1)

    def test_fechamento_e_idempotente(self) -> None:
        self.cliente.close()
        self.cliente.close()
        self.assertFalse(self.cliente.connected)


if __name__ == "__main__":
    unittest.main()

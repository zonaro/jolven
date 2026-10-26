# test_openrgb_detection.py
#
# Copyright 2026 Jolven contributors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Descobrir se o servidor do OpenRGB está no ar, sem instalar o OpenRGB.

O caso mais importante é o servidor ausente: a pessoa abre as Preferências e
precisa ler "não instalado" ou "parado" em menos de um segundo — nunca "erro",
que a faria trocar a porta à toa. Para o caso presente, um servidor falso de
mentira fala o protocolo de verdade por TCP local: o aperto de mão inteiro é
verificado sem depender do hardware de ninguém.

O que existe nesta máquina não muda o resultado esperado: `sondar` numa porta
livre só pode dizer "não respondeu", com o rótulo certo para cada instalação.
"""

import socket
import struct
import threading
import time
import unittest

from cartridges.integrations.openrgb import detection

CABECALHO = struct.Struct("<4sIII")
MAGIA = b"ORGB"


def _porta_livre() -> int:
    """Uma porta vazia: sobe, anota e fecha, para o sistema não reutilizá-la."""
    soquete = socket.socket()
    soquete.bind(("127.0.0.1", 0))
    porta = soquete.getsockname()[1]
    soquete.close()
    return porta


def _exato(conexao: socket.socket, tamanho: int) -> bytes:
    pedacos = bytearray()
    while len(pedacos) < tamanho:
        pedaco = conexao.recv(tamanho - len(pedacos))
        if not pedaco:
            raise ConnectionError("cliente sumiu")
        pedacos.extend(pedaco)
    return bytes(pedacos)


def _ler(conexao: socket.socket) -> tuple[int, bytes]:
    magia, _dev, pkt, tamanho = CABECALHO.unpack(_exato(conexao, CABECALHO.size))
    if magia != MAGIA:
        raise ConnectionError("assinatura errada")
    return pkt, (_exato(conexao, tamanho) if tamanho else b"")


def _responder(
    conexao: socket.socket, pkt: int, dados: bytes = b"", magia: bytes = MAGIA
) -> None:
    conexao.sendall(CABECALHO.pack(magia, 0, pkt, len(dados)) + dados)


class ServidorFalso:
    """Um OpenRGB de mentira: o aperto de mão e a contagem (zero) de LEDs.

    Zero controladores é o suficiente para :func:`detection.sondar` devolver
    ``STATUS_VAZIO``, e evita fabricar um bloco de controlador inteiro só para
    provar que a conversa funciona.

    ``quebrar`` é o id do pacote cuja resposta sai com a assinatura trocada —
    o caso de "há algo na porta, mas não é o OpenRGB".
    """

    def __init__(self, protocolo: int = 6, quebrar: int | None = None) -> None:
        self.protocolo = protocolo
        self.quebrar = quebrar
        self.recebidos: list[int] = []
        self._ouvinte = socket.socket()
        self._ouvinte.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._ouvinte.bind(("127.0.0.1", 0))
        self._ouvinte.listen(1)
        self.porta = self._ouvinte.getsockname()[1]
        self._thread = threading.Thread(target=self._rodar, daemon=True)
        self._thread.start()

    def _rodar(self) -> None:
        try:
            conexao, _ = self._ouvinte.accept()
        except OSError:
            return
        with conexao:
            try:
                while True:
                    pkt, _dados = _ler(conexao)
                    self.recebidos.append(pkt)
                    magia = b"XXXX" if self.quebrar == pkt else MAGIA
                    if pkt == 40:  # REQUEST_PROTOCOL_VERSION
                        _responder(conexao, pkt, struct.pack("<I", self.protocolo), magia)
                    elif pkt == 0:  # REQUEST_CONTROLLER_COUNT
                        _responder(conexao, pkt, struct.pack("<I", 0), magia)
                        return
                    # SET_CLIENT_NAME não tem resposta.
            except (ConnectionError, OSError):
                return

    def fechar(self) -> None:
        try:
            self._ouvinte.close()
        except OSError:
            pass
        self._thread.join(timeout=3)


class TestPorta(unittest.TestCase):
    def test_faixa(self) -> None:
        self.assertFalse(detection.porta_valida(0))
        self.assertFalse(detection.porta_valida(1023))
        self.assertTrue(detection.porta_valida(1024))
        self.assertTrue(detection.porta_valida(6742))
        self.assertTrue(detection.porta_valida(65535))
        self.assertFalse(detection.porta_valida(65536))

    def test_porta_invalida_e_erro_e_nao_tenta_conectar(self) -> None:
        estado = detection.sondar("127.0.0.1", 0)
        self.assertEqual(estado.status, detection.STATUS_ERRO)
        self.assertEqual(estado.detalhe, "porta-invalida")


class TestServidorAusente(unittest.TestCase):
    def test_porta_livre_nunca_e_erro(self) -> None:
        # Regressão: a recusa de conexão chegava como `OSError` genérico e a
        # UI mostrava "falha ao falar com o servidor" para quem simplesmente
        # ainda não tinha instalado nada.
        estado = detection.sondar("127.0.0.1", _porta_livre())
        self.assertIn(
            estado.status,
            (detection.STATUS_AUSENTE, detection.STATUS_PARADO),
            "ninguém na porta não é erro do OpenRGB",
        )
        self.assertEqual(
            estado.instalado,
            estado.status == detection.STATUS_PARADO,
            "o rótulo precisa bater com o que está instalado",
        )

    def test_responde_rapido(self) -> None:
        # Sem servidor, o connect recusa na hora; abrir as Preferências não
        # pode esperar perto do prazo de leitura de um servidor que existe.
        inicio = time.monotonic()
        detection.sondar("127.0.0.1", _porta_livre())
        self.assertLess(time.monotonic() - inicio, 2.0)

    def test_algo_que_fecha_a_conexao_e_parado_ou_incompativel(self) -> None:
        # Uma porta aberta que aceita soquete e cai fora: o caso de "outro
        # programa morando na porta do SDK".
        ouvinte = socket.socket()
        ouvinte.bind(("127.0.0.1", 0))
        ouvinte.listen(1)
        porta = ouvinte.getsockname()[1]
        self.addCleanup(ouvinte.close)

        def cair() -> None:
            try:
                conexao, _ = ouvinte.accept()
                conexao.close()
            except OSError:
                pass

        threading.Thread(target=cair, daemon=True).start()
        estado = detection.sondar("127.0.0.1", porta)
        self.assertIn(
            estado.status,
            (
                detection.STATUS_AUSENTE,
                detection.STATUS_PARADO,
                detection.STATUS_INCOMPATIVEL,
            ),
        )

    def test_resposta_com_assinatura_trocada_e_incompativel(self) -> None:
        # O aperto de mão passa e a contagem de LEDs vem sem a assinatura do
        # SDK: é outro programa morando na porta, não a porta errada.
        servidor = ServidorFalso(quebrar=0)
        self.addCleanup(servidor.fechar)
        estado = detection.sondar("127.0.0.1", servidor.porta)
        self.assertEqual(estado.status, detection.STATUS_INCOMPATIVEL)

    def test_assinatura_errada_na_negociacao_le_como_nao_respondeu(self) -> None:
        # Resposta lixo logo no primeiro pacote: o cliente desiste e o texto
        # vira "não respondeu" (parado) em vez de "erro" — do mesmo jeito não
        # resolve trocar a porta, e a pessoa não é mandada a mexer nela à toa.
        servidor = ServidorFalso(quebrar=40)
        self.addCleanup(servidor.fechar)
        estado = detection.sondar("127.0.0.1", servidor.porta)
        self.assertNotEqual(estado.status, detection.STATUS_ERRO)
        self.assertNotEqual(estado.status, detection.STATUS_OK)


class TestServidorPresente(unittest.TestCase):
    def test_aperto_de_mao_completo(self) -> None:
        servidor = ServidorFalso(protocolo=6)
        self.addCleanup(servidor.fechar)
        estado = detection.sondar("127.0.0.1", servidor.porta)
        self.assertEqual(estado.status, detection.STATUS_VAZIO)
        self.assertEqual(estado.protocolo, 6)
        self.assertEqual(estado.quantidade, 0)
        # O cliente pergunta a versão, se apresenta e só então conta LEDs.
        self.assertEqual(servidor.recebidos[:2], [40, 50], "aperto de mão fora de ordem")
        self.assertIn(0, servidor.recebidos)

    def test_versao_mais_antiga_e_respeitada(self) -> None:
        servidor = ServidorFalso(protocolo=3)
        self.addCleanup(servidor.fechar)
        estado = detection.sondar("127.0.0.1", servidor.porta)
        self.assertEqual(estado.protocolo, 3)
        self.assertEqual(estado.status, detection.STATUS_VAZIO)


class TestInstalacao(unittest.TestCase):
    def test_um_dos_tres_estados(self) -> None:
        self.assertIn(
            detection.instalacao(),
            (
                detection.INSTALACAO_NATIVA,
                detection.INSTALACAO_FLATPAK,
                detection.INSTALACAO_AUSENTE,
            ),
        )

    def test_flatpak_e_o_id_da_flathub(self) -> None:
        self.assertEqual(detection.FLATPAK_ID, "org.openrgb.OpenRGB")

    def test_comando_do_servidor_nunca_abre_a_janela(self) -> None:
        comando = detection.comando_servidor()
        if not comando:
            # OpenRGB ausente: quem chama mostra o botão de instalar.
            self.assertEqual(comando, [])
            return
        self.assertIn("--server", comando)
        self.assertNotIn("--gui", comando)


if __name__ == "__main__":
    unittest.main()

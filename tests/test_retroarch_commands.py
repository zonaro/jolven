# test_retroarch_commands.py
#
# Copyright 2026 Jolven contributors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O cliente de comandos do RetroArch, contra um servidor UDP falso.

Nada aqui sai da máquina: o servidor é um soquete UDP de verdade preso em
``127.0.0.1:0``, rodando numa thread do próprio processo de teste, que
responde ao que o cliente manda. A thread é juntada e o soquete fechado no
``addCleanup`` — nenhum fio fica pendurado.

O formato da resposta do ``GET_STATUS`` é o que o parser define: as linhas
``CHAVE: valor`` são o contrato deste módulo, e o lixo tolerado faz parte
dele, porque a resposta chega pela rede e pode vir cortada.
"""

import socket
import threading
import time
import unittest

from cartridges.integrations.retroarch import (
    COMANDOS_PERMITIDOS,
    RetroarchCommandClient,
    parse_status,
)

#: Resposta padrão do servidor falso para qualquer comando com resposta.
RESPOSTA_PADRAO = b"GET_STATUS: 1\nCORE: snes9x\nCONTENT: Solar Fox (USA)\n"

#: Resposta com lixo de propósito: linha vazia, linha sem ':' e valor vazio.
RESPOSTA_COM_LIXO = (
    "GET_STATUS: 1\n"
    "\n"
    "CORE: snes9x\n"
    "linha sem dois pontos\n"
    "STATE_SLOT: 3\n"
    "CHAVE_SEM_VALOR:\n"
    ":valor_sem_chave\n"
)


class ServidorFalso:
    """Soquete UDP de teste: recebe datagramas e responde conforme o mapa.

    ``respostas`` mapeia os bytes recebidos para os bytes de resposta; um
    valor ``None`` significa "não responde" (para testar o timeout). O que
    não estiver no mapa recebe ``RESPOSTA_PADRAO``.
    """

    def __init__(self) -> None:
        self.soquete = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.soquete.bind(("127.0.0.1", 0))
        self.soquete.settimeout(0.05)
        self.porta: int = self.soquete.getsockname()[1]
        self.respostas: dict[bytes, bytes | None] = {}
        self.recebidos: list[bytes] = []
        self._parar = threading.Event()
        self.thread = threading.Thread(target=self._atender, daemon=True)

    def _atender(self) -> None:
        while not self._parar.is_set():
            try:
                dados, origem = self.soquete.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            self.recebidos.append(dados)
            resposta = self.respostas.get(dados, RESPOSTA_PADRAO)
            if resposta is not None:
                try:
                    self.soquete.sendto(resposta, origem)
                except OSError:
                    break

    def iniciar(self) -> "ServidorFalso":
        self.thread.start()
        return self

    def fechar(self) -> None:
        self._parar.set()
        self.thread.join(timeout=2.0)
        self.soquete.close()

    def porta_fechada(self) -> int:
        """Uma porta UDP garantidamente sem ninguém escutando."""
        soquete = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        soquete.bind(("127.0.0.1", 0))
        porta = soquete.getsockname()[1]
        soquete.close()
        return porta


class ServidorTestCase(unittest.TestCase):
    """Base com o servidor falso e um cliente apontado para ele."""

    def setUp(self) -> None:
        self.servidor = ServidorFalso().iniciar()
        self.addCleanup(self.servidor.fechar)
        self.cliente = RetroarchCommandClient(
            host="127.0.0.1", port=self.servidor.porta, timeout=1.0
        )


class EnvioTests(ServidorTestCase):
    def test_datagrama_exato_para_cada_comando(self) -> None:
        # A allowlist inteira sai como texto puro, byte a byte, sem sufixo
        # nem terminador: o datagrama É o nome do comando.
        for comando in sorted(COMANDOS_PERMITIDOS):
            with self.subTest(comando=comando):
                self.servidor.recebidos.clear()
                self.cliente.send(comando)
                self.assertEqual(
                    self.servidor.recebidos, [comando.encode("ascii")]
                )

    def test_normaliza_espacos_e_caixa(self) -> None:
        self.cliente.send("  pause_toggle ")
        self.assertEqual(self.servidor.recebidos, [b"PAUSE_TOGGLE"])

    def test_resposta_valida_retornada_e_decodificada(self) -> None:
        esperado = "GET_STATUS: 1\nCORE: snes9x\nCONTENT: Solar Fox (USA)\n"
        self.assertEqual(self.cliente.send("GET_STATUS"), esperado)

    def test_timeout_retorna_none(self) -> None:
        # O servidor recebe e fica calado: o cliente espera o próprio
        # timeout e devolve None, sem levantar.
        self.servidor.respostas[b"GET_STATUS"] = None
        cliente = RetroarchCommandClient(
            host="127.0.0.1", port=self.servidor.porta, timeout=0.1
        )
        comeco = time.monotonic()
        self.assertIsNone(cliente.send("GET_STATUS"))
        self.assertGreaterEqual(time.monotonic() - comeco, 0.1)

    def test_porta_fechada_retorna_none_sem_levantar(self) -> None:
        cliente = RetroarchCommandClient(
            host="127.0.0.1", port=self.servidor.porta_fechada(), timeout=0.2
        )
        self.assertIsNone(cliente.send("PAUSE_TOGGLE"))

    def test_comando_fora_da_lista_rejeitado_sem_transmissao(self) -> None:
        # Nada controlado pelo usuário passa reto pela allowlist: variação
        # parecida, comando concatenado e string vazia, tudo recusado antes
        # de existir soquete.
        for tentativa in (
            "PAUSE",
            "pause_toggle; SHUTDOWN",
            "PAUSE_TOGGLE EXTRA",
            "",
        ):
            with self.subTest(tentativa=tentativa):
                self.assertIsNone(self.cliente.send(tentativa))
        self.assertEqual(self.servidor.recebidos, [])


class DisponibilidadeTests(ServidorTestCase):
    def test_disponivel_com_servidor_vivo(self) -> None:
        self.assertTrue(self.cliente.is_available())

    def test_indisponivel_com_porta_fechada(self) -> None:
        cliente = RetroarchCommandClient(
            host="127.0.0.1", port=self.servidor.porta_fechada(), timeout=0.2
        )
        self.assertFalse(cliente.is_available())

    def test_sonda_e_get_status(self) -> None:
        # A sondagem de disponibilidade é o próprio GET_STATUS.
        self.cliente.is_available()
        self.assertEqual(self.servidor.recebidos, [b"GET_STATUS"])


class ParseStatusTests(unittest.TestCase):
    def test_resposta_realista(self) -> None:
        estado = parse_status(RESPOSTA_PADRAO.decode("ascii"))
        self.assertEqual(
            estado,
            {
                "GET_STATUS": "1",
                "CORE": "snes9x",
                "CONTENT": "Solar Fox (USA)",
            },
        )

    def test_tolerante_a_lixo_e_linhas_vazias(self) -> None:
        estado = parse_status(RESPOSTA_COM_LIXO)
        self.assertEqual(estado, {"GET_STATUS": "1", "CORE": "snes9x", "STATE_SLOT": "3"})

    def test_entrada_vazia(self) -> None:
        self.assertEqual(parse_status(""), {})

    def test_so_lixo(self) -> None:
        self.assertEqual(parse_status("sem dois pontos\n\n:valor\n"), {})

    def test_chave_repetida_fica_com_a_ultima(self) -> None:
        estado = parse_status("CORE: snes9x\nCORE: genesis_plus_gx\n")
        self.assertEqual(estado, {"CORE": "genesis_plus_gx"})

    def test_chaves_e_valores_sem_espacos_sobrando(self) -> None:
        estado = parse_status("  STATE_SLOT :   3  \n")
        self.assertEqual(estado, {"STATE_SLOT": "3"})


if __name__ == "__main__":
    unittest.main()

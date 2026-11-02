# test_telegram_adapter.py
#
# Copyright 2026 Jolven contributors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Adaptador do Telegram/TDLib sem rede e sem a biblioteca nativa.

Nada aqui instala nem chama a TDLib de verdade: a ``libtdjson`` não está
instalada nesta máquina e o objetivo é verificar que o adaptador se degrada
com elegância e que a máquina de estados de autorização transiciona corretamente
respostas simuladas da TDLib.
"""

from unittest.mock import MagicMock, patch

import unittest

from cartridges.integrations.telegram import disponivel
from cartridges.integrations.telegram.adapter import (
    EstadoAutorizacao,
    TelegramAdapter,
    _ClienteTdlib,
)
from cartridges.integrations.telegram.errors import (
    TelegramNetworkError,
    TelegramUnavailableError,
)

BIBLIOTECA = "cartridges.integrations.telegram.biblioteca"
DISPONIVEL = "cartridges.integrations.telegram.adapter.disponivel"
CLIENTE = "cartridges.integrations.telegram.adapter._ClienteTdlib"


def resposta_autorizacao(
    tipo_estado: str, **campos_estado: object
) -> dict:
    """Monta uma atualização ``updateAuthorizationState`` simulada."""
    estado = {"@type": tipo_estado, **campos_estado}
    return {"@type": "updateAuthorizationState", "authorization_state": estado}


class TestDisponibilidade(unittest.TestCase):
    """A integração nunca quebra o Jolven só porque a TDLib não está lá."""

    def test_nao_disponivel_sem_libtdjson(self):
        with patch(BIBLIOTECA, return_value=None):
            self.assertFalse(disponivel())

    def test_adapter_reporta_indisponibilidade(self):
        with patch(BIBLIOTECA, return_value=None):
            adapter = TelegramAdapter()
            self.assertFalse(adapter.esta_disponivel())
            self.assertEqual(adapter.estado, EstadoAutorizacao.DESLIGADO)
            with self.assertRaises(TelegramUnavailableError):
                adapter.conectar("12345", "abcdefhash")


class TestMaquinaDeEstados(unittest.TestCase):
    """Transições do fluxo de autorização a partir de respostas simuladas."""

    def setUp(self):
        # Simula a TDLib instalada: disponível e com cliente mockado.
        self.patcher_disp = patch(DISPONIVEL, return_value=True)
        self.patcher_disp.start()
        self.patcher_cli = patch(CLIENTE)
        self.mock_cliente_cls = self.patcher_cli.start()
        self.mock_cliente = MagicMock()
        self.mock_cliente_cls.return_value = self.mock_cliente

    def tearDown(self):
        self.patcher_cli.stop()
        self.patcher_disp.stop()

    def _enviadas(self):
        return [chamada.args[0] for chamada in self.mock_cliente.enviar.call_args_list]

    def test_conectar_inicia_cliente_e_pede_estado(self):
        adapter = TelegramAdapter()
        adapter.conectar("12345", "abcdefhash")
        self.mock_cliente.criar.assert_called_once()
        self.assertEqual(adapter.estado, EstadoAutorizacao.CONECTANDO)
        tipos = {req.get("@type") for req in self._enviadas()}
        # setTdlibParameters é enviado imediatamente (com a chave do cofre,
        # quando houver); getAuthorizationState consulta o estado atual.
        self.assertIn("setTdlibParameters", tipos)
        self.assertIn("getAuthorizationState", tipos)
        self.assertNotIn("checkDatabaseEncryptionKey", tipos)

    def test_recebe_tdlib_parametros_apos_wait(self):
        adapter = TelegramAdapter()
        adapter.conectar("12345", "abcdefhash")
        adapter._tratar_resposta(
            resposta_autorizacao("authorizationStateWaitTdlibParameters")
        )
        self.assertEqual(adapter.estado, EstadoAutorizacao.CONECTANDO)
        payloads = self._enviadas()
        self.assertTrue(
            any(req.get("@type") == "setTdlibParameters" for req in payloads)
        )

    def test_espera_telefone(self):
        adapter = TelegramAdapter()
        adapter.conectar("12345", "abcdefhash")
        adapter._tratar_resposta(resposta_autorizacao("authorizationStateWaitPhoneNumber"))
        self.assertEqual(adapter.estado, EstadoAutorizacao.AUTORIZANDO_TELEFONE)
        self.assertTrue(adapter.precisa_acao)
        self.assertFalse(adapter.conectado)

    def test_espera_codigo(self):
        adapter = TelegramAdapter()
        adapter.conectar("12345", "abcdefhash")
        adapter._tratar_resposta(
            resposta_autorizacao(
                "authorizationStateWaitCode",
                phone_number="+5511999999999",
                phone_number_hash="hash123",
            )
        )
        self.assertEqual(adapter.estado, EstadoAutorizacao.AUTORIZANDO_CODIGO)
        self.assertTrue(adapter.precisa_acao)
        self.assertEqual(adapter.telefone, "+5511999999999")
        self.assertEqual(adapter._codigo_hash, "hash123")

    def test_espera_senha_2fa(self):
        adapter = TelegramAdapter()
        adapter.conectar("12345", "abcdefhash")
        adapter._tratar_resposta(resposta_autorizacao("authorizationStateWaitPassword"))
        self.assertEqual(adapter.estado, EstadoAutorizacao.AUTORIZANDO_SENHA)
        self.assertTrue(adapter.precisa_acao)

    def test_espera_qr_code(self):
        adapter = TelegramAdapter()
        adapter.conectar("12345", "abcdefhash")
        adapter._tratar_resposta(resposta_autorizacao("authorizationStateWaitQrCode"))
        self.assertEqual(adapter.estado, EstadoAutorizacao.AUTORIZANDO_QR)
        self.assertTrue(adapter.precisa_acao)

    def test_autorizado(self):
        adapter = TelegramAdapter()
        adapter.conectar("12345", "abcdefhash")
        adapter._tratar_resposta(resposta_autorizacao("authorizationStateReady"))
        self.assertEqual(adapter.estado, EstadoAutorizacao.AUTORIZADO)
        self.assertTrue(adapter.conectado)
        self.assertFalse(adapter.precisa_acao)

    def test_desconectar_reseta_estado_e_fecha_cliente(self):
        adapter = TelegramAdapter()
        adapter.conectar("12345", "abcdefhash")
        adapter._tratar_resposta(resposta_autorizacao("authorizationStateReady"))
        adapter.desconectar()
        self.assertEqual(adapter.estado, EstadoAutorizacao.DESLIGADO)
        self.assertFalse(adapter.conectado)
        self.mock_cliente.fechar.assert_called_once()

    def test_erro_durante_conexao_vai_para_estado_erro(self):
        adapter = TelegramAdapter()
        adapter.conectar("12345", "abcdefhash")
        adapter._tratar_resposta(
            {"@type": "error", "message": "API_ID_INVALID"}
        )
        self.assertEqual(adapter.estado, EstadoAutorizacao.ERRO)

    def test_acoes_de_usuario_sem_cliente_lancam_erro_de_rede(self):
        adapter = TelegramAdapter()
        chamadas = [
            lambda: adapter.cadastrar_telefone("+5511999999999"),
            lambda: adapter.enviar_codigo("123456"),
            lambda: adapter.enviar_senha("senha123"),
        ]
        for chamada in chamadas:
            with self.assertRaises(TelegramNetworkError):
                chamada()


class TestLoopRecepcao(unittest.TestCase):
    """O loop de recepção em background processa atualizações e para limpo."""

    def setUp(self):
        self.patcher_disp = patch(DISPONIVEL, return_value=True)
        self.patcher_disp.start()
        self.patcher_cli = patch(CLIENTE)
        self.mock_cliente_cls = self.patcher_cli.start()
        self.mock_cliente = MagicMock()
        self.mock_cliente_cls.return_value = self.mock_cliente

    def tearDown(self):
        self.patcher_cli.stop()
        self.patcher_disp.stop()

    def test_iniciar_parar_recepcao(self):
        adapter = TelegramAdapter()
        adapter.conectar("12345", "abcdefhash")
        self.assertTrue(adapter.recebendo)
        adapter.parar_recepcao()
        self.assertFalse(adapter.recebendo)

    def test_loop_processa_atualizacoes_entao_para(self):
        # Simula: primeira chamada de receber devolve uma atualização, a
        # segunda devolve None (timeout) para sair do loop limpo. Chamadas
        # adicionais continuam devolvendo None para não esgotar o iterador
        # (o que lançaria StopIteration sob o loop de recepção).
        respostas = [resposta_autorizacao("authorizationStateWaitPhoneNumber"), None]
        indice = [0]

        def receber(timeout):
            if indice[0] < len(respostas):
                resposta = respostas[indice[0]]
                indice[0] += 1
                return resposta
            return None

        self.mock_cliente.receber.side_effect = receber

        adapter = TelegramAdapter()
        adapter.conectar("12345", "abcdefhash")
        # O loop já está rodando; aguarda processar a atualização.
        import time
        prazo = time.time() + 5.0
        while adapter.estado is not EstadoAutorizacao.AUTORIZANDO_TELEFONE:
            if time.time() > prazo:
                self.fail("Estado não chegou a AUTORIZANDO_TELEFONE a tempo")
            time.sleep(0.02)

        adapter.parar_recepcao()
        self.assertFalse(adapter.recebendo)
        self.assertEqual(adapter.estado, EstadoAutorizacao.AUTORIZANDO_TELEFONE)

    def test_parar_recepcao_sem_iniciar_nao_falha(self):
        adapter = TelegramAdapter()
        # Sem conectar, não há cliente nem thread.
        adapter.parar_recepcao()  # não deve levantar exceção
        self.assertFalse(adapter.recebendo)


if __name__ == "__main__":
    unittest.main()

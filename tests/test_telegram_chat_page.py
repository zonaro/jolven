# test_telegram_chat_page.py
#
# Copyright 2026 Jolven contributors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Testes da tela de chat do Telegram sem rede e sem a biblioteca nativa.

A instância do widget ``TelegramChatPage`` depende do recurso GResource
carregado (só disponível em tempo de execução do app), então aqui testamos:

* consistência entre o template (.blp) e a classe Python (widgets declarados);
* o ``GerenciadorChat`` com um adapter simulado (disponível/conectado):
  seleção de conversa, envio de mensagem, processamento de atualizações,
  proteção contra duplicatas e indisponibilidade.
"""

from datetime import datetime
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock

import unittest

ROOT = Path(__file__).parents[1]

from cartridges.integrations.telegram.chat import (
    Conversa,
    GerenciadorChat,
    Mensagem,
    ChatIndisponivelError,
)


class AdapterFake:
    """Adapter mínimo simulando o contrato usado pelo GerenciadorChat."""

    def __init__(self, *, disponivel: bool, conectado: bool) -> None:
        self._disponivel = disponivel
        self._conectado = conectado
        self.enviadas: list[dict] = []

    def esta_disponivel(self) -> bool:
        return self._disponivel

    @property
    def conectado(self) -> bool:
        return self._conectado

    def enviar(self, requisicao: dict) -> None:
        self.enviadas.append(requisicao)


class TestConsistenciaTemplate(unittest.TestCase):
    """O .blp e a classe Python declaram os mesmos widgets."""

    def test_widgets_declarados_em_ambos(self) -> None:
        py = (ROOT / "cartridges" / "telegram_chat_page.py").read_text(encoding="utf-8")
        blp = (ROOT / "data" / "gtk" / "telegram-chat.blp").read_text(encoding="utf-8")
        for widget in (
            "sem_conta",
            "sem_tdlib",
            "sem_conversa",
            "painel_principal",
            "campo_busca",
            "lista_conversas",
            "lista_mensagens",
            "scrolled_mensagens",
            "cabecalho_conversa",
            "botao_mais_antigas",
            "texto_entrada",
        ):
            self.assertIn(widget, py)
            self.assertIn(widget, blp)
        self.assertIn("def enviar_mensagem", py)


class TestGerenciadorChatDisponibilidade(unittest.TestCase):
    """O gerenciador só está disponível com TDLib e conta autorizada."""

    def test_indisponivel_sem_tdlib(self):
        adapter = AdapterFake(disponivel=False, conectado=True)
        gm = GerenciadorChat(adapter)
        self.assertFalse(gm.disponivel)
        with self.assertRaises(ChatIndisponivelError):
            gm.iniciar()

    def test_indisponivel_sem_conta_autorizada(self):
        adapter = AdapterFake(disponivel=True, conectado=False)
        gm = GerenciadorChat(adapter)
        self.assertFalse(gm.disponivel)
        with self.assertRaises(ChatIndisponivelError):
            gm.iniciar()

    def test_disponivel_quando_conectado(self):
        adapter = AdapterFake(disponivel=True, conectado=True)
        gm = GerenciadorChat(adapter)
        self.assertTrue(gm.disponivel)
        gm.iniciar()  # não levanta


class TestGerenciadorChatConversas(unittest.TestCase):
    """Seleção de conversa, mensagens e atualizações do TDLib."""

    def setUp(self):
        self.adapter = AdapterFake(disponivel=True, conectado=True)
        self.mensagens_recebidas: list[tuple[Mensagem, Conversa]] = []
        self.conversas_recebidas: list[list[Conversa]] = []
        self.erros: list[str] = []
        self.gm = GerenciadorChat(
            self.adapter,
            on_conversas=lambda c: self.conversas_recebidas.append(c),
            on_mensagem=lambda m, c: self.mensagens_recebidas.append((m, c)),
            on_erro=lambda e: self.erros.append(e),
        )

    def test_selecionar_conversa(self):
        c = Conversa(id=1, titulo="Zonaro")
        self.gm._conversas[1] = c
        selecionada = self.gm.selecionar_conversa(1)
        self.assertIs(selecionada, c)
        self.assertIs(self.gm.conversa_atual, c)
        self.assertEqual(c.nao_lidas, 0)

    def test_selecionar_conversa_inexistente_retorna_none(self):
        self.assertIsNone(self.gm.selecionar_conversa(999))
        self.assertIsNone(self.gm.conversa_atual)

    def test_enviar_mensagem_espelha_na_conversa(self):
        c = Conversa(id=1, titulo="Zonaro")
        self.gm._conversas[1] = c
        self.gm._conversa_atual = c
        agora = datetime.now()
        self.gm.enviar_mensagem(1, "Oi, tudo bem?")

        # A requisição foi enviada à TDLib.
        self.assertEqual(len(self.adapter.enviadas), 1)
        req = self.adapter.enviadas[0]
        self.assertEqual(req["@type"], "sendMessage")
        self.assertEqual(req["chat_id"], 1)
        self.assertEqual(
            req["input_message_content"]["text"], "Oi, tudo bem?"
        )

        # A mensagem foi espelhada na conversa (estado otimista).
        self.assertEqual(len(c.mensagens), 1)
        mensagem = c.mensagens[0]
        self.assertEqual(mensagem.texto, "Oi, tudo bem?")
        self.assertTrue(mensagem.entrada)
        self.assertTrue(mensagem.lida)
        self.assertEqual(c.ultima_mensagem, "Oi, tudo bem?")

        # O callback foi disparado.
        self.assertEqual(len(self.mensagens_recebidas), 1)
        self.assertIs(self.mensagens_recebidas[0][0], mensagem)
        self.assertIs(self.mensagens_recebidas[0][1], c)

    def test_enviar_mensagem_texto_vazio_nao_envia(self):
        c = Conversa(id=1, titulo="Zonaro")
        self.gm._conversas[1] = c
        self.gm._conversa_atual = c
        self.gm.enviar_mensagem(1, "   ")
        self.assertEqual(len(self.adapter.enviadas), 0)
        self.assertEqual(len(c.mensagens), 0)

    def test_enviar_mensagem_sem_conversa_atual_levanta_erro(self):
        self.gm._conversa_atual = None
        with self.assertRaises(ChatIndisponivelError):
            self.gm.enviar_mensagem(1, "oi")
        self.assertEqual(len(self.adapter.enviadas), 0)

    def test_processar_atualizacao_nova_mensagem(self):
        c = Conversa(id=1, titulo="Zonaro")
        self.gm._conversas[1] = c
        self.gm._conversa_atual = c
        agora = datetime.now()
        atualizacao = {
            "@type": "updateNewMessage",
            "message": {
                "id": 42,
                "chat_id": 1,
                "date": int(agora.timestamp()),
                "sender_user_id": 7,
                "content": {"@type": "messageText", "text": {"text": "Ola"}},
            },
        }
        self.gm.processar_atualizacao(atualizacao)

        self.assertEqual(len(c.mensagens), 1)
        mensagem = c.mensagens[0]
        self.assertEqual(mensagem.id, 42)
        self.assertEqual(mensagem.texto, "Ola")
        self.assertFalse(mensagem.entrada)
        # A conversa está aberta: a mensagem já foi lida e não conta como nova.
        self.assertEqual(c.nao_lidas, 0)
        self.assertTrue(mensagem.lida)
        self.assertEqual(len(self.mensagens_recebidas), 1)

    def test_nova_mensagem_em_conversa_fechada_conta_nao_lida(self):
        outra = Conversa(id=2, titulo="Outra")
        self.gm._conversas[2] = outra
        self.gm._conversa_atual = Conversa(id=1, titulo="Zonaro")
        self.gm.processar_atualizacao(
            {
                "@type": "updateNewMessage",
                "message": {
                    "id": 43,
                    "chat_id": 2,
                    "content": {"@type": "messageText", "text": {"text": "oi"}},
                },
            }
        )
        self.assertEqual(outra.nao_lidas, 1)

    def test_processar_atualizacao_nao_duplica_mensagem(self):
        c = Conversa(id=1, titulo="Zonaro")
        c.adicionar_mensagem(
            Mensagem(id=10, conversa_id=1, texto="ja existe", entrada=False)
        )
        self.gm._conversas[1] = c
        self.gm.processar_atualizacao(
            {
                "@type": "updateNewMessage",
                "message": {
                    "id": 10,
                    "chat_id": 1,
                    "content": {"@type": "messageText", "text": {"text": "X"}},
                },
            }
        )
        self.assertEqual(len(c.mensagens), 1)
        self.assertEqual(c.mensagens[0].texto, "ja existe")

    def test_processar_atualizacao_novo_chat(self):
        self.gm.processar_atualizacao(
            {
                "@type": "updateNewChat",
                "chat": {
                    "id": 5,
                    "type": {"@type": "chatTypePrivate"},
                    "first_name": "Ana",
                },
            }
        )
        self.assertIn(5, self.gm._conversas)
        self.assertEqual(self.gm._conversas[5].titulo, "Ana")
        self.assertEqual(self.gm._conversas[5].tipo, "privada")
        self.assertEqual(len(self.conversas_recebidas), 1)

    def test_processar_atualizacao_grupo(self):
        self.gm.processar_atualizacao(
            {
                "@type": "updateNewChat",
                "chat": {
                    "id": 6,
                    "type": {"@type": "chatTypeSupergroup"},
                    "title": "Gaming",
                },
            }
        )
        self.assertEqual(self.gm._conversas[6].tipo, "grupo")
        self.assertEqual(self.gm._conversas[6].titulo, "Gaming")

    def test_processar_atualizacao_canal(self):
        self.gm.processar_atualizacao(
            {
                "@type": "updateNewChat",
                "chat": {
                    "id": 7,
                    "type": {"@type": "chatTypeChannel"},
                    "title": "Novidades",
                },
            }
        )
        self.assertEqual(self.gm._conversas[7].tipo, "canal")

    def test_conversas_ordenadas_por_ultima_mensagem(self):
        agora = datetime.now()
        mais_velha = Conversa(
            id=1, titulo="A", data_ultima=datetime.fromtimestamp(100)
        )
        mais_nova = Conversa(
            id=2, titulo="B", data_ultima=datetime.fromtimestamp(200)
        )
        meio = Conversa(
            id=3, titulo="C", data_ultima=datetime.fromtimestamp(150)
        )
        for c in (mais_velha, meio, mais_nova):
            self.gm._conversas[c.id] = c
        ordem = [c.id for c in self.gm.conversas]
        self.assertEqual(ordem, [2, 3, 1])

    def test_estado_erro_nao_quebra_fluxo(self):
        # Enviar quando indisponível levanta, mas não corrompe o gerenciador.
        self.adapter._disponivel = False
        with self.assertRaises(ChatIndisponivelError):
            self.gm.enviar_mensagem(1, "oi")
        self.assertEqual(len(self.adapter.enviadas), 0)


class TestGerenciadorChatHistorico(unittest.TestCase):
    """Histórico paginado, busca, leitura e estados de envio."""

    def setUp(self):
        self.adapter = AdapterFake(disponivel=True, conectado=True)
        self.mensagens: list[tuple[Optional[Mensagem], Conversa]] = []
        self.gm = GerenciadorChat(
            self.adapter,
            on_mensagem=lambda m, c: self.mensagens.append((m, c)),
        )
        self.gm._conversas[1] = Conversa(id=1, titulo="Zonaro")

    def test_carregar_conversas_envia_getchats(self):
        self.gm.carregar_conversas()
        req = self.adapter.enviadas[-1]
        self.assertEqual(req["@type"], "getChats")
        self.assertEqual(req["chat_list"]["@type"], "chatListMain")

    def test_carregar_historico_envia_getchathistory(self):
        self.gm.carregar_historico(1)
        req = self.adapter.enviadas[-1]
        self.assertEqual(req["@type"], "getChatHistory")
        self.assertEqual(req["chat_id"], 1)
        self.assertEqual(req["limit"], 50)

    def test_resposta_de_historico_anexa_mensagens(self):
        extra = {"tipo": "historico", "chat_id": 1}
        self.gm.processar_atualizacao(
            {
                "@type": "messages",
                "@extra": extra,
                "messages": [
                    {
                        "id": 20,
                        "chat_id": 1,
                        "date": 1700000000,
                        "content": {"@type": "messageText", "text": {"text": "nova"}},
                    },
                    {
                        "id": 10,
                        "chat_id": 1,
                        "date": 1600000000,
                        "content": {"@type": "messageText", "text": {"text": "antiga"}},
                    },
                ],
            }
        )
        conversa = self.gm._conversas[1]
        self.assertEqual([m.id for m in conversa.mensagens], [10, 20])
        self.assertTrue(conversa.historico_carregado)
        self.assertEqual(conversa.id_mais_antiga, 10)

    def test_selecionar_conversa_carrega_historico_e_marca_lida(self):
        self.gm._conversas[1].mensagens = [
            Mensagem(id=5, conversa_id=1, texto="oi", entrada=False)
        ]
        self.gm.selecionar_conversa(1)
        tipos = [r["@type"] for r in self.adapter.enviadas]
        self.assertIn("getChatHistory", tipos)
        self.assertIn("viewMessages", tipos)

    def test_busca_conversas_por_titulo(self):
        self.gm._conversas[2] = Conversa(id=2, titulo="Gaming")
        self.assertEqual([c.id for c in self.gm.buscar_conversas("gam")], [2])
        self.assertEqual(
            [c.id for c in self.gm.buscar_conversas("")], [1, 2]
        )
        self.assertEqual(self.gm.buscar_conversas("nada"), [])

    def test_update_chat_last_message(self):
        self.gm.processar_atualizacao(
            {
                "@type": "updateChatLastMessage",
                "chat_id": 1,
                "last_message": {
                    "date": 1700000000,
                    "content": {"@type": "messageText", "text": {"text": "última"}},
                },
            }
        )
        conversa = self.gm._conversas[1]
        self.assertEqual(conversa.ultima_mensagem, "última")

    def test_resposta_de_envio_confirma_id_otimista(self):
        self.gm.enviar_mensagem(1, "oi")
        conversa = self.gm._conversas[1]
        otimista = conversa.mensagens[0]
        extra = self.adapter.enviadas[-1]["@extra"]
        self.gm.processar_atualizacao(
            {
                "@type": "message",
                "@extra": extra,
                "id": 777,
                "chat_id": 1,
                "date": 1700000000,
                "content": {"@type": "messageText", "text": {"text": "oi"}},
            }
        )
        self.assertEqual(otimista.id, 777)
        self.assertFalse(otimista.enviando)
        self.assertTrue(otimista.lida)

    def test_update_chat_action_digitando(self):
        self.gm.processar_atualizacao(
            {
                "@type": "updateChatAction",
                "chat_id": 1,
                "action": {"@type": "chatActionTyping"},
            }
        )
        self.assertIsNotNone(self.gm._conversas[1].digitando)
        self.gm.processar_atualizacao(
            {
                "@type": "updateChatAction",
                "chat_id": 1,
                "action": {"@type": "chatActionCancel"},
            }
        )
        self.assertIsNone(self.gm._conversas[1].digitando)

    def test_mensagens_apagadas_saem_da_conversa(self):
        self.gm._conversas[1].mensagens = [
            Mensagem(id=1, conversa_id=1, texto="a"),
            Mensagem(id=2, conversa_id=1, texto="b"),
        ]
        self.gm.processar_atualizacao(
            {
                "@type": "updateDeleteMessages",
                "chat_id": 1,
                "message_ids": [1],
            }
        )
        self.assertEqual([m.id for m in self.gm._conversas[1].mensagens], [2])

    def test_resolve_nome_do_remetente(self):
        self.gm.processar_atualizacao(
            {
                "@type": "updateNewMessage",
                "message": {
                    "id": 50,
                    "chat_id": 1,
                    "sender_user_id": 99,
                    "content": {"@type": "messageText", "text": {"text": "oi"}},
                },
            }
        )
        pedidos = [
            r for r in self.adapter.enviadas if r["@type"] == "getUser"
        ]
        self.assertEqual(len(pedidos), 1)
        self.assertEqual(pedidos[0]["user_id"], 99)

        self.gm.processar_atualizacao(
            {
                "@type": "user",
                "@extra": {"tipo": "usuario", "user_id": 99},
                "id": 99,
                "first_name": "Ana",
                "last_name": "Souza",
            }
        )
        conversa = self.gm._conversas[1]
        self.assertEqual(conversa.mensagens[0].remetente_nome, "Ana Souza")

    def test_nao_pede_o_mesmo_usuario_duas_vezes(self):
        for _ in range(2):
            self.gm._pedir_usuario(99)
        pedidos = [
            r for r in self.adapter.enviadas if r["@type"] == "getUser"
        ]
        self.assertEqual(len(pedidos), 1)


if __name__ == "__main__":
    unittest.main()

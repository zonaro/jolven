# chat.py
#
# Copyright 2026 Jolven contributors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Modelos e gerenciador de chat do Telegram.

Conversas e mensagens são espelhos do que a TDLib reporta: nunca inventamos
identidades nem histórico local próprio. Quando a TDLib não está disponível
ou a conta não está autorizada, o gerenciador se declara indisponível e a UI
mostra o estado apropriado.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

import builtins

from cartridges.integrations.telegram.adapter import (
    EstadoAutorizacao,
    TelegramAdapter,
)
from cartridges.integrations.telegram.errors import (
    TelegramIntegrationError,
    TelegramNotAuthorizedError,
    TelegramUnavailableError,
)

if not hasattr(builtins, "_"):
    builtins._ = lambda text: text  # type: ignore[attr-defined]

log = logging.getLogger(__name__)


@dataclass
class Mensagem:
    """Uma mensagem de uma conversa do Telegram."""

    id: int
    conversa_id: int
    remetente_id: Optional[int] = None
    remetente_nome: Optional[str] = None
    texto: str = ""
    data: Optional[datetime] = None
    entrada: bool = False  # True se enviada pelo usuário local
    lida: bool = False


@dataclass
class Conversa:
    """Uma conversa (privada ou grupo) do Telegram."""

    id: int
    titulo: str = ""
    tipo: str = "privada"  # "privada" | "grupo" | "canal"
    avatar_url: Optional[str] = None
    ultima_mensagem: str = ""
    data_ultima: Optional[datetime] = None
    nao_lidas: int = 0
    mensagens: list[Mensagem] = field(default_factory=list)

    def adicionar_mensagem(self, mensagem: Mensagem) -> None:
        """Acrescenta uma mensagem, evitando duplicatas por id."""
        if any(m.id == mensagem.id for m in self.mensagens):
            return
        self.mensagens.append(mensagem)
        self.mensagens.sort(key=lambda m: m.data or datetime.min)


class ChatIndisponivelError(TelegramIntegrationError):
    """O chat não pode ser usado (TDLib ausente ou conta não autorizada)."""


class GerenciadorChat:
    """Coordena conversas e mensagens através do adapter TDLib.

    Não toca GTK: resultados chegam aos callbacks do construtor ou são
    entregues à tela pelo chamador via ``entregar_na_tela``.
    """

    def __init__(
        self,
        adapter: TelegramAdapter,
        *,
        on_conversas: Optional[Callable[[list[Conversa]], None]] = None,
        on_mensagem: Optional[Callable[[Mensagem, Conversa], None]] = None,
        on_erro: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._adapter = adapter
        self._on_conversas = on_conversas
        self._on_mensagem = on_mensagem
        self._on_erro = on_erro
        self._conversas: dict[int, Conversa] = {}
        self._conversa_atual: Optional[Conversa] = None

    # -- propriedades -----------------------------------------------------

    @property
    def disponivel(self) -> bool:
        """Se o chat pode ser usado (TDLib instalada e conta autorizada)."""
        return (
            self._adapter.esta_disponivel()
            and self._adapter.conectado
        )

    @property
    def conversas(self) -> list[Conversa]:
        """Todas as conversas, ordenadas pela data da última mensagem."""
        return sorted(
            self._conversas.values(),
            key=lambda c: c.data_ultima or datetime.min,
            reverse=True,
        )

    @property
    def conversa_atual(self) -> Optional[Conversa]:
        return self._conversa_atual

    # -- ciclo de vida ----------------------------------------------------

    def iniciar(self) -> None:
        """Prepara o gerenciador. Chama-se após o adapter estar conectado."""
        if not self.disponivel:
            raise ChatIndisponivelError(
                "Telegram não está autorizado ou a TDLib não está instalada."
            )

    def parar(self) -> None:
        self._conversa_atual = None

    # -- ações ------------------------------------------------------------

    def selecionar_conversa(self, conversa_id: int) -> Optional[Conversa]:
        conversa = self._conversas.get(conversa_id)
        if conversa is None:
            return None
        self._conversa_atual = conversa
        conversa.nao_lidas = 0
        return conversa

    def enviar_mensagem(self, conversa_id: int, texto: str) -> None:
        """Envia uma mensagem de texto para a conversa.

        Apenas por gesto explícito do usuário: nunca envia automaticamente.
        """
        if not self.disponivel:
            raise ChatIndisponivelError("Chat indisponível")
        conversa = self._conversas.get(conversa_id)
        if conversa is None:
            raise ChatIndisponivelError("Conversa não encontrada")
        if not texto.strip():
            return
        # @type sendMessage: mensagem de texto simples.
        mensagem_otima = {
            "@type": "sendMessage",
            "@extra": None,
            "chat_id": conversa_id,
            "input_message_content": {
                "@type": "inputMessageText",
                "text": texto,
                "disable_web_page_preview": False,
                "clear_draft": False,
            },
        }
        self._adapter.enviar(mensagem_otima)

        # Espelha imediatamente na UI (estado otimista).
        agora = datetime.now()
        mensagem = Mensagem(
            id=-abs(hash((conversa_id, texto, agora.isoformat()))),
            conversa_id=conversa_id,
            remetente_nome=_("Eu"),
            texto=texto,
            data=agora,
            entrada=True,
            lida=True,
        )
        conversa.adicionar_mensagem(mensagem)
        conversa.ultima_mensagem = texto
        conversa.data_ultima = agora
        if self._on_mensagem is not None:
            try:
                self._on_mensagem(mensagem, conversa)
            except Exception:  # pylint: disable=broad-exception-caught
                logging.exception("Callback de nova mensagem falhou")

    # -- atualizações da TDLib -------------------------------------------

    def processar_atualizacao(self, atualizacao: dict) -> None:
        """Processa uma atualização recebida da TDLib (nova mensagem etc.)."""
        tipo = atualizacao.get("@type")
        if tipo == "updateNewMessage":
            mensagem = atualizacao.get("message", {}) or {}
            self._tratar_nova_mensagem(mensagem)
        elif tipo == "updateNewChat":
            chat = atualizacao.get("chat", {}) or {}
            self._tratar_novo_chat(chat)
        elif tipo == "updateChatTitle":
            self._tratar_titulo_chat(atualizacao)
        elif self._on_conversas is not None:
            # Outras atualizações ainda sinalizam que a lista pode ter mudado.
            try:
                self._on_conversas(self.conversas)
            except Exception:  # pylint: disable=broad-exception-caught
                logging.exception("Callback de conversas falhou")

    def _tratar_novo_chat(self, chat: dict) -> None:
        chat_id = chat.get("id")
        if chat_id is None:
            return
        tipo = self._tipo_chat(chat)
        conversa = Conversa(
            id=int(chat_id),
            titulo=chat.get("title") or chat.get("first_name") or _("Sem título"),
            tipo=tipo,
            avatar_url=None,
        )
        self._conversas[int(chat_id)] = conversa
        if self._on_conversas is not None:
            try:
                self._on_conversas(self.conversas)
            except Exception:  # pylint: disable=broad-exception-caught
                logging.exception("Callback de conversas falhou")

    def _tratar_nova_mensagem(self, mensagem: dict) -> None:
        chat_id = mensagem.get("chat_id")
        if chat_id is None:
            return
        conteudo = mensagem.get("content", {}) or {}
        texto = ""
        if conteudo.get("@type") == "messageText":
            texto = (conteudo.get("text", {}) or {}).get("text", "")
        data_ts = mensagem.get("date")
        data = datetime.fromtimestamp(data_ts) if data_ts else None
        remetente_id = mensagem.get("sender_user_id")
        remetente_nome = None
        # outgoing indica que a mensagem partiu do usuário local; quando não
        # há essa informação, trata-se de uma mensagem recebida (não entrada).
        entrada = bool(mensagem.get("outgoing"))

        nova = Mensagem(
            id=int(mensagem.get("id", 0)),
            conversa_id=int(chat_id),
            remetente_id=remetente_id,
            texto=texto,
            data=data,
            entrada=entrada,
        )
        conversa = self._conversas.get(int(chat_id))
        if conversa is None:
            conversa = Conversa(
                id=int(chat_id),
                titulo=_("Conversa"),
                tipo="privada",
            )
            self._conversas[int(chat_id)] = conversa
        conversa.adicionar_mensagem(nova)
        conversa.ultima_mensagem = texto or _("(mídia)")
        conversa.data_ultima = data or datetime.now()
        if not entrada:
            conversa.nao_lidas += 1

        if self._on_mensagem is not None:
            try:
                self._on_mensagem(nova, conversa)
            except Exception:  # pylint: disable=broad-exception-caught
                logging.exception("Callback de nova mensagem falhou")
        if self._on_conversas is not None:
            try:
                self._on_conversas(self.conversas)
            except Exception:  # pylint: disable=broad-exception-caught
                logging.exception("Callback de conversas falhou")

    def _tratar_titulo_chat(self, atualizacao: dict) -> None:
        chat_id = atualizacao.get("chat_id")
        titulo = atualizacao.get("title")
        if chat_id is None or titulo is None:
            return
        conversa = self._conversas.get(int(chat_id))
        if conversa is not None:
            conversa.titulo = titulo

    @staticmethod
    def _tipo_chat(chat: dict) -> str:
        tipo = chat.get("type", {}) or {}
        tipo_nome = tipo.get("@type", "").lower()
        if "group" in tipo_nome or "supergroup" in tipo_nome:
            return "grupo"
        if "channel" in tipo_nome:
            return "canal"
        return "privada"


__all__ = [
    "Mensagem",
    "Conversa",
    "GerenciadorChat",
    "ChatIndisponivelError",
]

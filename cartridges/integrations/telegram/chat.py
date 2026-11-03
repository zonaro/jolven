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

O gerenciador não toca GTK. Toda chamada de rede acontece no adapter (thread
de background) e os resultados são entregues pelos callbacks registrados.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

import builtins

from cartridges.integrations.telegram.adapter import TelegramAdapter
from cartridges.integrations.telegram.errors import TelegramIntegrationError

if not hasattr(builtins, "_"):
    builtins._ = lambda text: text  # type: ignore[attr-defined]

log = logging.getLogger(__name__)

#: Limite padrão de mensagens carregadas por página de histórico.
TAMANHO_PAGINA = 50


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
    enviando: bool = False  # estado otimista, antes do update de confirmação


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
    digitando: Optional[str] = None
    mensagens: list[Mensagem] = field(default_factory=list)
    #: Id da mensagem mais antiga já carregada; 0 quando não há mais histórico.
    id_mais_antiga: int = 0
    historico_carregado: bool = False

    def adicionar_mensagem(self, mensagem: Mensagem) -> None:
        """Acrescenta uma mensagem, evitando duplicatas por id."""
        if any(m.id == mensagem.id for m in self.mensagens):
            return
        self.mensagens.append(mensagem)
        self.mensagens.sort(key=lambda m: m.data or datetime.min)
        if mensagem.id > 0:
            if self.id_mais_antiga == 0 or mensagem.id < self.id_mais_antiga:
                self.id_mais_antiga = mensagem.id


class ChatIndisponivelError(TelegramIntegrationError):
    """O chat não pode ser usado (TDLib ausente ou conta não autorizada)."""


class GerenciadorChat:
    """Coordena conversas e mensagens através do adapter TDLib.

    Não toca GTK: resultados chegam aos callbacks do construtor ou são
    entregues à tela pelo chamador via ``entregar_na_tela``. Os callbacks podem
    ser trocados em runtime com ``definir_listeners`` — a página de chat faz
    isso ao abrir e ao fechar.
    """

    def __init__(
        self,
        adapter: TelegramAdapter,
        *,
        on_conversas: Optional[Callable[[list[Conversa]], None]] = None,
        on_mensagem: Optional[Callable[[Optional[Mensagem], Conversa], None]] = None,
        on_erro: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._adapter = adapter
        self._on_conversas = on_conversas
        self._on_mensagem = on_mensagem
        self._on_erro = on_erro
        self._conversas: dict[int, Conversa] = {}
        self._conversa_atual: Optional[Conversa] = None
        self._usuarios: dict[int, str] = {}
        self._usuarios_pedidos: set[int] = set()
        self._contador_extra = 0

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

    def definir_listeners(
        self,
        *,
        on_conversas: Optional[Callable[[list[Conversa]], None]] = None,
        on_mensagem: Optional[Callable[[Optional[Mensagem], Conversa], None]] = None,
        on_erro: Optional[Callable[[str], None]] = None,
    ) -> None:
        """Troca os callbacks de UI sem recriar o gerenciador."""
        self._on_conversas = on_conversas
        self._on_mensagem = on_mensagem
        self._on_erro = on_erro

    # -- ciclo de vida ----------------------------------------------------

    def iniciar(self) -> None:
        """Prepara o gerenciador. Chama-se após o adapter estar conectado."""
        if not self.disponivel:
            raise ChatIndisponivelError(
                "Telegram não está autorizado ou a TDLib não está instalada."
            )
        # Registra o gerenciador como processador das atualizações da TDLib.
        definir = getattr(self._adapter, "definir_processador_atualizacao", None)
        if callable(definir):
            definir(self.processar_atualizacao)

    def parar(self) -> None:
        self._conversa_atual = None
        definir = getattr(self._adapter, "definir_processador_atualizacao", None)
        if callable(definir):
            definir(None)

    # -- ações ------------------------------------------------------------

    def carregar_conversas(self, limite: int = 100) -> None:
        """Pede à TDLib a lista de conversas principais.

        A TDLib responde com ``ok`` e emite ``updateNewChat`` para cada chat;
        o gerenciador mantém um dicionário por id e notifica a UI quando a
        lista muda.
        """
        if not self.disponivel:
            return
        try:
            self._adapter.enviar(
                {
                    "@type": "getChats",
                    "@extra": self._proximo_extra("conversas"),
                    "chat_list": {"@type": "chatListMain"},
                    "limit": limite,
                }
            )
        except Exception as erro:  # pylint: disable=broad-exception-caught
            self._reportar_erro(f"Não foi possível carregar as conversas: {erro}")

    def selecionar_conversa(self, conversa_id: int) -> Optional[Conversa]:
        """Seleciona a conversa e marca as mensagens como lidas."""
        conversa = self._conversas.get(conversa_id)
        if conversa is None:
            return None
        self._conversa_atual = conversa
        conversa.nao_lidas = 0
        conversa.digitando = None
        if not conversa.historico_carregado:
            conversa.historico_carregado = True
            self.carregar_historico(conversa_id)
        self.marcar_como_lida(conversa_id)
        return conversa

    def carregar_historico(
        self, conversa_id: int, *, limite: int = TAMANHO_PAGINA, antes_de: int = 0
    ) -> None:
        """Carrega uma página de histórico e a anexa à conversa.

        ``antes_de`` é o id da mensagem mais antiga já exibida (0 para a página
        mais recente). A UI usa esse valor para paginar ao rolar para cima.
        """
        if not self.disponivel:
            return
        try:
            self._adapter.enviar(
                {
                    "@type": "getChatHistory",
                    "@extra": self._proximo_extra(
                        "historico", conversa_id
                    ),
                    "chat_id": conversa_id,
                    "from_message_id": antes_de,
                    "offset": 0,
                    "limit": limite,
                    "only_local": False,
                }
            )
        except Exception as erro:  # pylint: disable=broad-exception-caught
            self._reportar_erro(f"Não foi possível carregar o histórico: {erro}")

    def marcar_como_lida(self, conversa_id: int) -> None:
        """Marca como lidas apenas as mensagens recebidas da conversa."""
        if not self.disponivel:
            return
        conversa = self._conversas.get(conversa_id)
        if conversa is None:
            return
        ids = [m.id for m in conversa.mensagens if not m.entrada and m.id > 0]
        if not ids:
            return
        conversa.nao_lidas = 0
        for mensagem in conversa.mensagens:
            mensagem.lida = True
        try:
            self._adapter.enviar(
                {
                    "@type": "viewMessages",
                    "@extra": self._proximo_extra("lidas"),
                    "chat_id": conversa_id,
                    "message_ids": ids,
                    "force_read": True,
                }
            )
        except Exception as erro:  # pylint: disable=broad-exception-caught
            self._reportar_erro(f"Não foi possível marcar como lida: {erro}")

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
        agora = datetime.now()
        id_otimista = -abs(hash((conversa_id, texto, agora.isoformat())))
        mensagem_otima = {
            "@type": "sendMessage",
            "@extra": {
                **self._proximo_extra("envio", conversa_id),
                "id_otimista": id_otimista,
            },
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
        mensagem = Mensagem(
            id=id_otimista,
            conversa_id=conversa_id,
            remetente_nome=_("Eu"),
            texto=texto,
            data=agora,
            entrada=True,
            lida=True,
            enviando=True,
        )
        conversa.adicionar_mensagem(mensagem)
        conversa.ultima_mensagem = texto
        conversa.data_ultima = agora
        self._notificar_mensagem(mensagem, conversa)

    def enviar_acao_digitando(self, conversa_id: int) -> None:
        """Informa ao Telegram que o usuário está digitando (sem texto)."""
        if not self.disponivel:
            return
        try:
            self._adapter.enviar(
                {
                    "@type": "sendChatAction",
                    "chat_id": conversa_id,
                    "action": {"@type": "chatActionTyping"},
                }
            )
        except Exception:  # pylint: disable=broad-exception-caught
            # Indicador de digitação nunca é crítico: falha silenciosa.
            logging.debug("Não foi possível enviar o indicador de digitação")

    def buscar_conversas(self, texto: str) -> list[Conversa]:
        """Filtra as conversas carregadas por título (case-insensitive).

        A busca é local de propósito: não dispara request à rede a cada tecla e
        mantém o comportamento previsível quando offline.
        """
        termo = (texto or "").strip().casefold()
        if not termo:
            return self.conversas
        return [
            conversa
            for conversa in self.conversas
            if termo in conversa.titulo.casefold()
            or termo in conversa.ultima_mensagem.casefold()
        ]

    # -- atualizações da TDLib -------------------------------------------

    def processar_atualizacao(self, atualizacao: dict) -> None:
        """Processa uma atualização recebida da TDLib.

        Chamado na thread de recepção; os callbacks entregam à UI pela thread
        principal (``entregar_na_tela`` no chamador).
        """
        tipo = atualizacao.get("@type")
        if tipo == "updateNewMessage":
            self._tratar_nova_mensagem(atualizacao.get("message", {}) or {})
        elif tipo == "updateNewChat":
            self._tratar_novo_chat(atualizacao.get("chat", {}) or {})
        elif tipo == "updateChatTitle":
            self._tratar_titulo_chat(atualizacao)
        elif tipo == "updateChatLastMessage":
            self._tratar_ultima_mensagem(atualizacao)
        elif tipo == "updateChatReadInbox":
            self._tratar_lida_atualizacao(atualizacao)
        elif tipo == "updateMessageSendSucceeded":
            self._tratar_envio_confirmado(atualizacao)
        elif tipo == "updateMessageSendFailed":
            self._tratar_envio_falhou(atualizacao)
        elif tipo == "updateDeleteMessages":
            self._tratar_mensagens_apagadas(atualizacao)
        elif tipo == "updateChatAction":
            self._tratar_acao_chat(atualizacao)
        elif tipo == "messages":
            self._tratar_historico(atualizacao)
        elif tipo == "message":
            self._tratar_mensagem_enviada(atualizacao)
        elif tipo == "user":
            self._tratar_usuario(atualizacao)
        elif tipo == "updateUser":
            self._guardar_usuario(atualizacao.get("user", {}) or {})
        elif self._on_conversas is not None:
            # Outras atualizações ainda sinalizam que a lista pode ter mudado.
            self._notificar_conversas()

    def _tratar_novo_chat(self, chat: dict) -> None:
        chat_id = chat.get("id")
        if chat_id is None:
            return
        conversa = self._conversas.get(int(chat_id))
        if conversa is None:
            conversa = Conversa(id=int(chat_id))
            self._conversas[int(chat_id)] = conversa
        conversa.titulo = (
            chat.get("title")
            or chat.get("first_name")
            or conversa.titulo
            or _("Sem título")
        )
        conversa.tipo = self._tipo_chat(chat)
        ultima = chat.get("last_message") or {}
        if ultima:
            conversa.ultima_mensagem = self._texto_da_mensagem(ultima) or conversa.ultima_mensagem
            data_ts = ultima.get("date")
            if data_ts:
                conversa.data_ultima = datetime.fromtimestamp(data_ts)
        self._notificar_conversas()

    def _tratar_nova_mensagem(self, mensagem: dict) -> None:
        chat_id = mensagem.get("chat_id")
        if chat_id is None:
            return
        texto = self._texto_da_mensagem(mensagem)
        data_ts = mensagem.get("date")
        data = datetime.fromtimestamp(data_ts) if data_ts else None
        remetente_id = self._id_remetente(mensagem)
        remetente_nome = self._nome_remetente(remetente_id)
        # outgoing indica que a mensagem partiu do usuário local; quando não
        # há essa informação, trata-se de uma mensagem recebida (não entrada).
        entrada = bool(mensagem.get("outgoing"))

        nova = Mensagem(
            id=int(mensagem.get("id", 0)),
            conversa_id=int(chat_id),
            remetente_id=remetente_id,
            remetente_nome=remetente_nome,
            texto=texto,
            data=data,
            entrada=entrada,
            lida=entrada,
        )
        conversa = self._obter_ou_criar_conversa(int(chat_id))
        conversa.adicionar_mensagem(nova)
        conversa.ultima_mensagem = texto or _("(mídia)")
        conversa.data_ultima = data or datetime.now()
        if not entrada:
            conversa.nao_lidas += 1
            # Conversa aberta: o usuário já está vendo a mensagem.
            if self._conversa_atual is not None and self._conversa_atual.id == conversa.id:
                conversa.nao_lidas = 0
                nova.lida = True
                self.marcar_como_lida(conversa.id)

        self._notificar_mensagem(nova, conversa)
        self._notificar_conversas()

    def _tratar_historico(self, resposta: dict) -> None:
        """Anexa as mensagens devolvidas por ``getChatHistory``."""
        extra = self._ler_extra(resposta)
        if not extra or extra.get("tipo") != "historico":
            return
        chat_id = int(extra["chat_id"])
        conversa = self._obter_ou_criar_conversa(chat_id)
        mensagens = resposta.get("messages", []) or []
        for bruta in reversed(mensagens):
            conversa.adicionar_mensagem(
                self._mensagem_de_tdlib(bruta, chat_id)
            )
        conversa.historico_carregado = True
        # id da mensagem mais antiga devolvida vira o cursor da próxima página.
        ids = [int(m.get("id", 0)) for m in mensagens if m.get("id")]
        if ids:
            conversa.id_mais_antiga = min(ids)
        self._notificar_mensagem(None, conversa)
        self._notificar_conversas()

    def _tratar_mensagem_enviada(self, resposta: dict) -> None:
        """Troca o id otimista pelo id real devolvido por ``sendMessage``."""
        extra = self._ler_extra(resposta)
        if not extra or extra.get("tipo") != "envio":
            return
        chat_id = resposta.get("chat_id")
        id_otimista = extra.get("id_otimista")
        if chat_id is None or id_otimista is None:
            return
        conversa = self._conversas.get(int(chat_id))
        if conversa is None:
            return
        for existente in conversa.mensagens:
            if existente.id == id_otimista:
                existente.id = int(resposta.get("id", existente.id))
                existente.enviando = False
                existente.lida = True
                if resposta.get("date"):
                    existente.data = datetime.fromtimestamp(resposta["date"])
                self._notificar_mensagem(existente, conversa)
                break
        self._notificar_conversas()

    def _tratar_titulo_chat(self, atualizacao: dict) -> None:
        chat_id = atualizacao.get("chat_id")
        titulo = atualizacao.get("title")
        if chat_id is None or titulo is None:
            return
        conversa = self._conversas.get(int(chat_id))
        if conversa is not None:
            conversa.titulo = titulo
            self._notificar_conversas()

    def _tratar_ultima_mensagem(self, atualizacao: dict) -> None:
        chat_id = atualizacao.get("chat_id")
        if chat_id is None:
            return
        conversa = self._obter_ou_criar_conversa(int(chat_id))
        ultima = atualizacao.get("last_message") or {}
        if ultima:
            conversa.ultima_mensagem = (
                self._texto_da_mensagem(ultima) or conversa.ultima_mensagem
            )
            data_ts = ultima.get("date")
            if data_ts:
                conversa.data_ultima = datetime.fromtimestamp(data_ts)
        self._notificar_conversas()

    def _tratar_lida_atualizacao(self, atualizacao: dict) -> None:
        chat_id = atualizacao.get("chat_id")
        if chat_id is None:
            return
        conversa = self._conversas.get(int(chat_id))
        if conversa is not None:
            conversa.nao_lidas = int(atualizacao.get("unread_count", 0) or 0)
            self._notificar_conversas()

    def _tratar_envio_confirmado(self, atualizacao: dict) -> None:
        """Troca o id otimista pelo id real devolvido pela TDLib."""
        conversa_id = atualizacao.get("old_message_id")
        mensagem = atualizacao.get("message") or {}
        chat_id = mensagem.get("chat_id")
        if chat_id is None:
            return
        conversa = self._conversas.get(int(chat_id))
        if conversa is None:
            return
        for existente in conversa.mensagens:
            if existente.id == conversa_id:
                existente.id = int(mensagem.get("id", existente.id))
                existente.enviando = False
                existente.lida = True
                if mensagem.get("date"):
                    existente.data = datetime.fromtimestamp(mensagem["date"])
                self._notificar_mensagem(existente, conversa)
                break

    def _tratar_envio_falhou(self, atualizacao: dict) -> None:
        chat_id = (atualizacao.get("message") or {}).get("chat_id")
        if chat_id is None:
            return
        conversa = self._conversas.get(int(chat_id))
        if conversa is None:
            return
        antigo = atualizacao.get("old_message_id")
        for existente in conversa.mensagens:
            if existente.id == antigo:
                existente.enviando = False
                existente.lida = False
                self._notificar_mensagem(existente, conversa)
                break

    def _tratar_mensagens_apagadas(self, atualizacao: dict) -> None:
        chat_id = atualizacao.get("chat_id")
        if chat_id is None:
            return
        conversa = self._conversas.get(int(chat_id))
        if conversa is None:
            return
        apagadas = set(atualizacao.get("message_ids", []) or [])
        conversa.mensagens = [
            m for m in conversa.mensagens if m.id not in apagadas
        ]
        self._notificar_mensagem(None, conversa)

    def _tratar_acao_chat(self, atualizacao: dict) -> None:
        chat_id = atualizacao.get("chat_id")
        if chat_id is None:
            return
        conversa = self._conversas.get(int(chat_id))
        if conversa is None:
            return
        acao = (atualizacao.get("action") or {}).get("@type", "")
        conversa.digitando = (
            _("digitando…") if acao == "chatActionTyping" else None
        )
        self._notificar_conversas()

    # -- helpers internos -------------------------------------------------

    def _proximo_extra(self, tipo: str, chat_id: Optional[int] = None) -> dict:
        self._contador_extra += 1
        extra = {"tipo": tipo, "n": self._contador_extra}
        if chat_id is not None:
            extra["chat_id"] = chat_id
        return extra

    @staticmethod
    def _ler_extra(resposta: dict) -> Optional[dict]:
        extra = resposta.get("@extra")
        return extra if isinstance(extra, dict) else None

    def _obter_ou_criar_conversa(self, chat_id: int) -> Conversa:
        conversa = self._conversas.get(chat_id)
        if conversa is None:
            conversa = Conversa(id=chat_id, titulo=_("Conversa"))
            self._conversas[chat_id] = conversa
        return conversa

    def _mensagem_de_tdlib(self, bruta: dict, chat_id: int) -> Mensagem:
        data_ts = bruta.get("date")
        remetente_id = self._id_remetente(bruta)
        return Mensagem(
            id=int(bruta.get("id", 0)),
            conversa_id=chat_id,
            remetente_id=remetente_id,
            remetente_nome=self._nome_remetente(remetente_id),
            texto=self._texto_da_mensagem(bruta),
            data=datetime.fromtimestamp(data_ts) if data_ts else None,
            entrada=bool(bruta.get("outgoing")),
            lida=bool(bruta.get("outgoing")),
        )

    @staticmethod
    def _id_remetente(mensagem: dict) -> Optional[int]:
        """Extrai o id do usuário remetente nos dois formatos da TDLib."""
        direto = mensagem.get("sender_user_id")
        if direto:
            return int(direto)
        remetente = mensagem.get("sender_id") or {}
        if remetente.get("@type") == "messageSenderUser":
            user_id = remetente.get("user_id")
            return int(user_id) if user_id else None
        return None

    def _nome_remetente(self, user_id: Optional[int]) -> Optional[str]:
        if user_id is None:
            return None
        nome = self._usuarios.get(user_id)
        if nome is None:
            self._pedir_usuario(user_id)
        return nome

    def _pedir_usuario(self, user_id: int) -> None:
        """Pede à TDLib o nome do remetente (uma vez por usuário)."""
        if user_id in self._usuarios or user_id in self._usuarios_pedidos:
            return
        self._usuarios_pedidos.add(user_id)
        try:
            self._adapter.enviar(
                {
                    "@type": "getUser",
                    "@extra": {"tipo": "usuario", "user_id": user_id},
                    "user_id": user_id,
                }
            )
        except Exception:  # pylint: disable=broad-exception-caught
            logging.debug("Não foi possível pedir o usuário %s", user_id)

    def _tratar_usuario(self, resposta: dict) -> None:
        extra = self._ler_extra(resposta)
        if not extra or extra.get("tipo") != "usuario":
            return
        self._guardar_usuario(resposta)

    def _guardar_usuario(self, usuario: dict) -> None:
        """Atualiza o nome do remetente e as mensagens que já o usavam."""
        user_id = usuario.get("id")
        if user_id is None:
            return
        nome = " ".join(
            parte
            for parte in (
                usuario.get("first_name") or "",
                usuario.get("last_name") or "",
            )
            if parte
        ).strip()
        if not nome:
            return
        self._usuarios[int(user_id)] = nome
        self._usuarios_pedidos.discard(int(user_id))
        mudou = False
        for conversa in self._conversas.values():
            for mensagem in conversa.mensagens:
                if (
                    mensagem.remetente_id == int(user_id)
                    and mensagem.remetente_nome != nome
                ):
                    mensagem.remetente_nome = nome
                    mudou = True
        if mudou and self._conversa_atual is not None:
            self._notificar_mensagem(None, self._conversa_atual)

    @staticmethod
    def _texto_da_mensagem(mensagem: dict) -> str:
        conteudo = mensagem.get("content", {}) or {}
        tipo = conteudo.get("@type")
        if tipo == "messageText":
            return (conteudo.get("text", {}) or {}).get("text", "")
        if tipo == "messagePhoto":
            legenda = (conteudo.get("caption", {}) or {}).get("text", "")
            return legenda or _("(foto)")
        if tipo == "messageDocument":
            legenda = (conteudo.get("caption", {}) or {}).get("text", "")
            return legenda or _("(documento)")
        if tipo == "messageSticker":
            return _("(figurinha)")
        if tipo == "messageVoiceNote":
            return _("(mensagem de voz)")
        return ""

    def _notificar_conversas(self) -> None:
        if self._on_conversas is None:
            return
        try:
            self._on_conversas(self.conversas)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.exception("Callback de conversas falhou")

    def _notificar_mensagem(
        self, mensagem: Optional[Mensagem], conversa: Conversa
    ) -> None:
        """Notifica a UI. ``mensagem`` None significa "recarregar a conversa"."""
        if self._on_mensagem is None:
            return
        try:
            self._on_mensagem(mensagem, conversa)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.exception("Callback de nova mensagem falhou")

    def _reportar_erro(self, mensagem: str) -> None:
        log.error("%s", mensagem)
        if self._on_erro is not None:
            try:
                self._on_erro(mensagem)
            except Exception:  # pylint: disable=broad-exception-caught
                logging.exception("Callback de erro do chat falhou")

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
    "TAMANHO_PAGINA",
]

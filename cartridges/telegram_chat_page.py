# telegram_chat_page.py
#
# Copyright 2026 Jolven contributors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Página de chat do Telegram: lista de conversas e painel de mensagens.

A página só funciona quando a integração está ativada e a conta autorizada
(adapter conectado). Caso contrário, mostra um estado de erro orientativo.

Toda atualização da TDLib chega em thread de background; a UI só é tocada na
thread principal via ``entregar_na_tela``.
"""

import logging
from typing import Any, Optional

import builtins

from gi.repository import Adw, Gdk, GLib, Gtk

from cartridges import shared
from cartridges.integrations.telegram.adapter import EstadoAutorizacao, TelegramAdapter
from cartridges.integrations.telegram.chat import (
    Conversa,
    GerenciadorChat,
    Mensagem,
)
from cartridges.utils.na_tela import entregar_na_tela

if not hasattr(builtins, "_"):
    builtins._ = lambda text: text  # type: ignore[attr-defined]

log = logging.getLogger(__name__)


@Gtk.Template(resource_path=shared.PREFIX + "/gtk/telegram-chat.ui")
class TelegramChatPage(Adw.NavigationPage):
    """Lista de conversas e painel de mensagens do Telegram."""

    __gtype_name__ = "TelegramChatPage"

    sem_conta: Adw.StatusPage = Gtk.Template.Child()
    sem_tdlib: Adw.StatusPage = Gtk.Template.Child()
    sem_conversa: Adw.StatusPage = Gtk.Template.Child()
    painel_principal: Gtk.Box = Gtk.Template.Child()
    lista_conversas: Gtk.ListBox = Gtk.Template.Child()
    lista_mensagens: Gtk.ListBox = Gtk.Template.Child()
    texto_entrada: Adw.EntryRow = Gtk.Template.Child()

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self._gerenciador: Optional[GerenciadorChat] = None
        self._adapter: Optional[TelegramAdapter] = None
        _row_por_conversa: dict[int, Gtk.Widget] = {}
        _widget_por_conversa: dict[int, Adw.ActionRow] = {}

        # Inicializa quando o adapter estiver disponível.
        self._tentar_inicializar()

        self.texto_entrada.connect("activate", self._ao_ativar_entrada)

    # -- ciclo de vida ----------------------------------------------------

    def _tentar_inicializar(self) -> None:
        adapter = self._obter_adapter()
        if adapter is None:
            return
        if self._gerenciador is not None:
            return
        self._adapter = adapter
        self._gerenciador = GerenciadorChat(
            adapter,
            on_conversas=self._ao_conversas_atualizadas,
            on_mensagem=self._ao_nova_mensagem,
            on_erro=self._ao_erro,
        )
        self._atualizar_visibilidade()
        if adapter.conectado:
            self._gerenciador.iniciar()
            self._carregar_conversas()

    def _obter_adapter(self) -> Optional[TelegramAdapter]:
        app = shared.win.get_application() if shared.win is not None else None
        if app is None:
            return None
        return getattr(app, "telegram_adapter", None)

    # -- atualizações do estado ------------------------------------------

    def _atualizar_visibilidade(self) -> None:
        adapter = self._adapter
        if adapter is None:
            self.sem_tdlib.set_visible(True)
            self.sem_conta.set_visible(False)
            self.sem_conversa.set_visible(False)
            self.painel_principal.set_visible(False)
            return

        if not adapter.esta_disponivel():
            self.sem_tdlib.set_visible(True)
            self.sem_conta.set_visible(False)
            self.sem_conversa.set_visible(False)
            self.painel_principal.set_visible(False)
            return

        if not adapter.conectado:
            self.sem_tdlib.set_visible(False)
            self.sem_conta.set_visible(True)
            self.sem_conversa.set_visible(False)
            self.painel_principal.set_visible(False)
            return

        # Conta autorizada: mostra o painel principal.
        self.sem_tdlib.set_visible(False)
        self.sem_conta.set_visible(False)
        self.painel_principal.set_visible(True)
        if self._gerenciador.conversa_atual is None:
            self.sem_conversa.set_visible(True)
        else:
            self.sem_conversa.set_visible(False)

    def _ao_estado_telegram(self, estado: EstadoAutorizacao) -> None:
        entregar_na_tela(self._atualizar_visibilidade)
        if estado is EstadoAutorizacao.AUTORIZADO and self._gerenciador is not None:
            self._gerenciador.iniciar()
            entregar_na_tela(self._carregar_conversas)

    # -- conversas ---------------------------------------------------------

    def _carregar_conversas(self) -> None:
        if self._gerenciador is None:
            return
        # Solicita a lista de conversas via TDLib (getChats).
        try:
            self._adapter.enviar(
                {
                    "@type": "getChats",
                    "@extra": None,
                    "chat_list": {"@type": "chatListMain"},
                    "limit": 100,
                }
            )
        except Exception:  # pylint: disable=broad-exception-caught
            logging.exception("Não foi possível solicitar a lista de conversas")

    def _ao_conversas_atualizadas(self, conversas: list[Conversa]) -> None:
        entregar_na_tela(self._montar_lista_conversas, conversas)

    def _montar_lista_conversas(self, conversas: list[Conversa]) -> None:
        # Limpa a lista atual.
        while child := self.lista_conversas.get_row_at_index(0):
            self.lista_conversas.remove(child)

        for conversa in conversas:
            row = Adw.ActionRow(activatable=True)
            row.set_title(conversa.titulo)
            subtitulo = conversa.ultima_mensagem or _("Sem mensagens")
            if conversa.nao_lidas > 0:
                subtitulo = f"[{conversa.nao_lidas}] {subtitulo}"
            row.set_subtitle(subtitulo)
            row.set_activatable(True)
            row.connect("activated", self._ao_clicar_conversa, conversa.id)
            self.lista_conversas.append(row)

    def _ao_clicar_conversa(self, _row: Any, conversa_id: int) -> None:
        if self._gerenciador is None:
            return
        conversa = self._gerenciador.selecionar_conversa(conversa_id)
        if conversa is None:
            return
        self._atualizar_visibilidade()
        self._montar_mensagens(conversa)

    # -- mensagens ---------------------------------------------------------

    def _montar_mensagens(self, conversa: Conversa) -> None:
        while child := self.lista_mensagens.get_row_at_index(0):
            self.lista_mensagens.remove(child)

        for mensagem in conversa.mensagens:
            row = Adw.ActionRow(activatable=False)
            nome = mensagem.remetente_nome or _("Desconhecido")
            prefixo = f"{nome}: " if not mensagem.entrada else ""
            row.set_title(prefixo + mensagem.texto)
            row.set_use_markup(False)
            if mensagem.entrada:
                row.add_css_class("suggested-action")
            else:
                row.add_css_class("dim-label")
            self.lista_mensagens.append(row)

        # Rola para o fim.
        def rolar() -> None:
            adjustment = self.lista_mensagens.get_vadjustment()
            adjustment.set_value(adjustment.get_upper())

        GLib.idle_add(rolar)

    def _ao_nova_mensagem(self, mensagem: Mensagem, conversa: Conversa) -> None:
        entregar_na_tela(self._ao_nova_mensagem_na_tela, mensagem, conversa)

    def _ao_nova_mensagem_na_tela(
        self, mensagem: Mensagem, conversa: Conversa
    ) -> None:
        if self._gerenciador is None:
            return
        # Se for da conversa atual, adiciona ao painel de mensagens.
        if (
            self._gerenciador.conversa_atual is not None
            and self._gerenciador.conversa_atual.id == conversa.id
        ):
            row = Adw.ActionRow(activatable=False)
            nome = mensagem.remetente_nome or _("Desconhecido")
            prefixo = f"{nome}: " if not mensagem.entrada else ""
            row.set_title(prefixo + mensagem.texto)
            row.set_use_markup(False)
            if mensagem.entrada:
                row.add_css_class("suggested-action")
            else:
                row.add_css_class("dim-label")
            self.lista_mensagens.append(row)
            # Rola para o fim.
            def rolar() -> None:
                adjustment = self.lista_mensagens.get_vadjustment()
                adjustment.set_value(adjustment.get_upper())

            GLib.idle_add(rolar)

        # Atualiza a lista de conversas.
        if self._gerenciador is not None:
            self._montar_lista_conversas(self._gerenciador.conversas)

    # -- envio -------------------------------------------------------------

    def _ao_ativar_entrada(self, _entry: Any) -> None:
        self._enviar_mensagem()

    def _ao_erro(self, mensagem: str) -> None:
        log.error("Telegram chat: %s", mensagem)

    def enviar_mensagem(self) -> None:
        """Envia o texto digitado na entrada para a conversa atual."""
        if self._gerenciador is None:
            return
        conversa = self._gerenciador.conversa_atual
        if conversa is None:
            return
        texto = (self.texto_entrada.get_text() or "").strip()
        if not texto:
            return
        try:
            self._gerenciador.enviar_mensagem(conversa.id, texto)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.exception("Não foi possível enviar a mensagem")
        else:
            self.texto_entrada.set_text("")

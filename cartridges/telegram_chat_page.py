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
import time
from typing import Any, Optional

import builtins

from gi.repository import Adw, GLib, Gtk

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

#: Intervalo mínimo entre dois indicadores de "digitando" para o Telegram.
_INTERVALO_DIGITANDO = 4.0


@Gtk.Template(resource_path=shared.PREFIX + "/gtk/telegram-chat.ui")
class TelegramChatPage(Adw.NavigationPage):
    """Lista de conversas e painel de mensagens do Telegram."""

    __gtype_name__ = "TelegramChatPage"

    sem_conta: Adw.StatusPage = Gtk.Template.Child()
    sem_tdlib: Adw.StatusPage = Gtk.Template.Child()
    sem_conversa: Adw.StatusPage = Gtk.Template.Child()
    painel_principal: Gtk.Box = Gtk.Template.Child()
    campo_busca: Gtk.SearchEntry = Gtk.Template.Child()
    lista_conversas: Gtk.ListBox = Gtk.Template.Child()
    lista_mensagens: Gtk.ListBox = Gtk.Template.Child()
    scrolled_mensagens: Gtk.ScrolledWindow = Gtk.Template.Child()
    cabecalho_conversa: Adw.ActionRow = Gtk.Template.Child()
    botao_mais_antigas: Gtk.Button = Gtk.Template.Child()
    texto_entrada: Gtk.Entry = Gtk.Template.Child()

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self._gerenciador: Optional[GerenciadorChat] = None
        self._adapter: Optional[TelegramAdapter] = None
        self._ultimo_digitando = 0.0

        self._tentar_inicializar()

        self.texto_entrada.connect("activate", self._ao_ativar_entrada)
        self.texto_entrada.connect("changed", self._ao_digitar)
        self.campo_busca.connect("search-changed", self._ao_buscar)
        self.botao_mais_antigas.connect("clicked", self._ao_carregar_antigas)

    # -- ciclo de vida ----------------------------------------------------

    def _tentar_inicializar(self) -> None:
        gerenciador = self._obter_gerenciador()
        if gerenciador is None:
            self._atualizar_visibilidade()
            return
        self._adapter = getattr(gerenciador, "_adapter", None)
        if self._adapter is not None:
            definir = getattr(self._adapter, "definir_callbacks", None)
            if callable(definir):
                definir(
                    on_estado=self._ao_estado_telegram,
                    on_erro=self._ao_erro,
                )
        if self._gerenciador is not gerenciador:
            self._gerenciador = gerenciador
            gerenciador.definir_listeners(
                on_conversas=self._ao_conversas_atualizadas,
                on_mensagem=self._ao_nova_mensagem,
                on_erro=self._ao_erro,
            )
        self._atualizar_visibilidade()
        if self._adapter is not None and self._adapter.conectado:
            try:
                gerenciador.iniciar()
            except Exception:  # pylint: disable=broad-exception-caught
                log.exception("Não foi possível iniciar o chat do Telegram")
                return
            gerenciador.carregar_conversas()

    def _obter_gerenciador(self) -> Optional[GerenciadorChat]:
        """Gerenciador compartilhado do app; cria um local como fallback."""
        app = shared.win.get_application() if shared.win is not None else None
        if app is not None:
            gerenciador = getattr(app, "telegram_chat", None)
            if gerenciador is not None:
                return gerenciador
            adapter = getattr(app, "telegram_adapter", None)
            if adapter is not None:
                gerenciador = GerenciadorChat(adapter)
                app.telegram_chat = gerenciador
                return gerenciador
        return None

    # -- atualizações do estado ------------------------------------------

    def _atualizar_visibilidade(self) -> None:
        adapter = self._adapter
        if adapter is None:
            # Integração desligada ou ainda não criada: orienta a vinculação
            # em vez de acusar uma TDLib ausente que pode estar instalada.
            self.sem_tdlib.set_visible(False)
            self.sem_conta.set_visible(True)
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
        if self._gerenciador is None or self._gerenciador.conversa_atual is None:
            self.sem_conversa.set_visible(True)
        else:
            self.sem_conversa.set_visible(False)

    def _ao_estado_telegram(self, estado: EstadoAutorizacao) -> None:
        entregar_na_tela(self._atualizar_visibilidade)
        if estado is EstadoAutorizacao.AUTORIZADO and self._gerenciador is not None:
            try:
                self._gerenciador.iniciar()
            except Exception:  # pylint: disable=broad-exception-caught
                log.exception("Não foi possível iniciar o chat do Telegram")
                return
            entregar_na_tela(self._gerenciador.carregar_conversas)

    # -- conversas ---------------------------------------------------------

    def _ao_buscar(self, _entry: Gtk.SearchEntry) -> None:
        if self._gerenciador is None:
            return
        self._montar_lista_conversas(
            self._gerenciador.buscar_conversas(self.campo_busca.get_text())
        )

    def _ao_conversas_atualizadas(self, conversas: list[Conversa]) -> None:
        entregar_na_tela(self._montar_lista_conversas, conversas)
        if self._gerenciador is not None and self._gerenciador.conversa_atual:
            entregar_na_tela(
                self._atualizar_cabecalho, self._gerenciador.conversa_atual
            )

    def _atualizar_cabecalho(self, conversa: Conversa) -> None:
        self.cabecalho_conversa.set_title(conversa.titulo)
        self.cabecalho_conversa.set_subtitle(conversa.digitando or "")

    def _montar_lista_conversas(self, conversas: list[Conversa]) -> None:
        while child := self.lista_conversas.get_row_at_index(0):
            self.lista_conversas.remove(child)

        for conversa in conversas:
            row = Adw.ActionRow(activatable=True)
            row.set_title(conversa.titulo)
            subtitulo = conversa.ultima_mensagem or _("Sem mensagens")
            if conversa.digitando:
                subtitulo = conversa.digitando
            elif conversa.nao_lidas > 0:
                subtitulo = f"({conversa.nao_lidas}) {subtitulo}"
            row.set_subtitle(subtitulo)
            avatar = Adw.Avatar.new(32, conversa.titulo or "?", True)
            avatar.set_show_initials(True)
            row.add_prefix(avatar)
            row.connect("activated", self._ao_clicar_conversa, conversa.id)
            self.lista_conversas.append(row)

    def _ao_clicar_conversa(self, _row: Any, conversa_id: int) -> None:
        if self._gerenciador is None:
            return
        conversa = self._gerenciador.selecionar_conversa(conversa_id)
        if conversa is None:
            return
        self.sem_conversa.set_visible(False)
        self.cabecalho_conversa.set_title(conversa.titulo)
        self.cabecalho_conversa.set_visible(True)
        self._montar_mensagens(conversa)

    # -- mensagens ---------------------------------------------------------

    def _montar_mensagens(self, conversa: Conversa) -> None:
        while child := self.lista_mensagens.get_row_at_index(0):
            self.lista_mensagens.remove(child)

        self.cabecalho_conversa.set_title(conversa.titulo)
        self.cabecalho_conversa.set_subtitle(conversa.digitando or "")
        self.cabecalho_conversa.set_visible(True)
        self.botao_mais_antigas.set_visible(bool(conversa.id_mais_antiga))

        for mensagem in conversa.mensagens:
            self.lista_mensagens.append(self._criar_row_mensagem(mensagem))

        self._rolar_para_o_fim()

    def _criar_row_mensagem(self, mensagem: Mensagem) -> Adw.ActionRow:
        row = Adw.ActionRow(activatable=False)
        nome = mensagem.remetente_nome or _("Desconhecido")
        prefixo = f"{nome}: " if not mensagem.entrada else ""
        titulo = prefixo + (mensagem.texto or _("(mídia)"))
        if mensagem.enviando:
            titulo = f"{titulo}  ·  {_('enviando…')}"
        elif mensagem.entrada and not mensagem.lida:
            titulo = f"{titulo}  ·  {_('falhou')}"
        row.set_title(titulo)
        row.set_use_markup(False)
        if mensagem.entrada:
            row.add_css_class("suggested-action")
        else:
            row.add_css_class("dim-label")
        return row

    def _rolar_para_o_fim(self) -> None:
        def rolar() -> None:
            adjustment = self.scrolled_mensagens.get_vadjustment()
            adjustment.set_value(adjustment.get_upper())

        GLib.idle_add(rolar)

    def _ao_carregar_antigas(self, _botao: Gtk.Button) -> None:
        if self._gerenciador is None:
            return
        conversa = self._gerenciador.conversa_atual
        if conversa is None or not conversa.id_mais_antiga:
            return
        self._gerenciador.carregar_historico(
            conversa.id, antes_de=conversa.id_mais_antiga
        )

    def _ao_nova_mensagem(
        self, mensagem: Optional[Mensagem], conversa: Conversa
    ) -> None:
        entregar_na_tela(self._ao_nova_mensagem_na_tela, mensagem, conversa)

    def _ao_nova_mensagem_na_tela(
        self, mensagem: Optional[Mensagem], conversa: Conversa
    ) -> None:
        if self._gerenciador is None:
            return
        atual = self._gerenciador.conversa_atual
        if atual is not None and atual.id == conversa.id:
            if mensagem is None:
                # Histórico recarregado ou mensagens apagadas: remonta tudo.
                self._montar_mensagens(conversa)
            else:
                self.lista_mensagens.append(
                    self._criar_row_mensagem(mensagem)
                )
                self.botao_mais_antigas.set_visible(bool(conversa.id_mais_antiga))
                self._rolar_para_o_fim()
        # A lista de conversas sempre reflete a última mensagem.
        self._montar_lista_conversas(self._gerenciador.conversas)

    # -- envio -------------------------------------------------------------

    def _ao_ativar_entrada(self, _entry: Any) -> None:
        self._enviar_mensagem()

    def _ao_digitar(self, _entry: Any) -> None:
        """Envia o indicador de digitação com throttling."""
        if self._gerenciador is None:
            return
        conversa = self._gerenciador.conversa_atual
        if conversa is None:
            return
        agora = time.monotonic()
        if agora - self._ultimo_digitando < _INTERVALO_DIGITANDO:
            return
        self._ultimo_digitando = agora
        self._gerenciador.enviar_acao_digitando(conversa.id)

    def _ao_erro(self, mensagem: str) -> None:
        log.error("Telegram chat: %s", mensagem)

    def enviar_mensagem(self) -> None:
        """Envia o texto digitado na entrada para a conversa atual."""
        self._enviar_mensagem()

    def _enviar_mensagem(self) -> None:
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
            return
        self.texto_entrada.set_text("")
        self._montar_mensagens(conversa)

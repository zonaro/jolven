# integrations_page.py
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

"""Página Integrações: o que o Jolven usa e o que falta instalar.

Cada programa de :mod:`cartridges.utils.integrations` vira uma
:class:`Adw.ActionRow` no grupo da sua categoria. A detecção de status
(``which`` e ``flatpak info``) e a instalação Flatpak (até dez minutos)
rodam sempre em thread separada; a thread principal só monta as linhas
via :func:`cartridges.utils.na_tela.entregar_na_tela`.
"""

import builtins
import logging
import threading
from typing import Any, Optional

from gi.repository import Adw, GLib, Gtk

from cartridges import shared
from cartridges.utils.integrations import (
    CATEGORIAS,
    Integracao,
    instalar_flatpak,
    listar_integracoes,
    obter_status,
)
from cartridges.utils.na_tela import entregar_na_tela

# O launcher roda ``gettext.install`` antes de importar qualquer módulo do
# app; o fallback mantém este módulo importável em testes e ferramentas sem
# catálogo — o mesmo guarda de ``cartridges/utils/integrations.py``.
if not hasattr(builtins, "_"):
    builtins._ = lambda text: text  # type: ignore[attr-defined]

#: Mensagens de status mais longas que isto viram o aviso genérico, para o
#: toast não virar um parágrafo com o stderr do Flatpak.
_MAXIMO_AVISO = 90


@Gtk.Template(resource_path=shared.PREFIX + "/gtk/integrations.ui")
class IntegrationsPage(Adw.NavigationPage):
    """Lista as integrações conhecidas, com status e instalação Flatpak."""

    __gtype_name__ = "IntegrationsPage"

    grupo_streaming: Adw.PreferencesGroup = Gtk.Template.Child()
    grupo_launchadores: Adw.PreferencesGroup = Gtk.Template.Child()
    grupo_emuladores: Adw.PreferencesGroup = Gtk.Template.Child()
    grupo_ferramentas: Adw.PreferencesGroup = Gtk.Template.Child()
    carregando_spinner: Gtk.Spinner = Gtk.Template.Child()
    erro_status: Adw.StatusPage = Gtk.Template.Child()
    integrations_stack: Gtk.Stack = Gtk.Template.Child()
    integrations_refresh_button: Gtk.Button = Gtk.Template.Child()

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self._carregando = False
        self._instalando: set[str] = set()
        self._linhas: list[tuple[Adw.PreferencesGroup, Adw.ActionRow]] = []
        self._por_chave: dict[str, Adw.ActionRow] = {}
        self._grupos: dict[str, Adw.PreferencesGroup] = {
            "streaming": self.grupo_streaming,
            "launchadores": self.grupo_launchadores,
            "emuladores": self.grupo_emuladores,
            "ferramentas": self.grupo_ferramentas,
        }
        for chave, grupo in self._grupos.items():
            grupo.set_title(CATEGORIAS.get(chave, chave))

        self.integrations_refresh_button.connect("clicked", self.atualizar)
        self.connect("map", self._ao_montar)

    def _ao_montar(self, *_args: Any) -> None:
        """Recarrega os status toda vez que a página volta a aparecer."""
        self.atualizar()

    def atualizar(self, *_args: Any) -> None:
        """Detecção em worker; a thread principal só recebe as linhas prontas."""
        if self._carregando:
            return
        self._carregando = True
        self.integrations_refresh_button.set_sensitive(False)
        if not self._linhas:
            self.integrations_stack.set_visible_child_name("loading")
        threading.Thread(target=self._carregar, daemon=True).start()

    def _carregar(self) -> None:
        try:
            estados = [
                (integracao, obter_status(integracao))
                for integracao in listar_integracoes()
            ]
            falha = ""
        except Exception:  # pylint: disable=broad-exception-caught
            logging.exception("Não foi possível listar as integrações")
            estados = []
            falha = _("Não foi possível carregar as integrações")
        entregar_na_tela(self._aplicar, estados, falha)

    def _aplicar(
        self, estados: list[tuple[Integracao, str]], falha: str
    ) -> bool:
        self._carregando = False
        self.integrations_refresh_button.set_sensitive(True)
        if falha:
            # Com linhas na tela, um refresh falhado mantém o que já se sabe.
            if self._linhas:
                self._aviso(falha)
            else:
                self.erro_status.set_description(falha)
                self.integrations_stack.set_visible_child_name("error")
            return GLib.SOURCE_REMOVE

        chave_focada = self._chave_com_foco()
        self._limpar_linhas()
        for integracao, estado in estados:
            grupo = self._grupos.get(integracao.categoria, self.grupo_ferramentas)
            linha = self._montar_linha(integracao, estado)
            grupo.add(linha)
            self._linhas.append((grupo, linha))
            self._por_chave[integracao.chave] = linha
        self.integrations_stack.set_visible_child_name("list")
        if chave_focada:
            self._focar_linha(chave_focada)
        return GLib.SOURCE_REMOVE

    def _limpar_linhas(self) -> None:
        for grupo, linha in self._linhas:
            grupo.remove(linha)
        self._linhas.clear()
        self._por_chave.clear()

    def _montar_linha(self, integracao: Integracao, estado: str) -> Adw.ActionRow:
        """Uma linha por integração: status pronto ou botão Instalar."""
        linha = Adw.ActionRow(title=integracao.titulo, subtitle=integracao.descricao)

        if estado == "nativo":
            linha.add_suffix(self._rotulo_status(_("Instalado (nativo)")))
            return linha
        if estado == "flatpak":
            linha.add_suffix(self._rotulo_status(_("Instalado via Flatpak")))
            return linha
        if not integracao.app_id_flatpak:
            # Entradas sem app id (Flatpak, GameMode, Waydroid…) só informam.
            linha.add_suffix(self._rotulo_status(_("Não instalado")))
            return linha

        espinha = Gtk.Spinner(
            width_request=16,
            height_request=16,
            valign=Gtk.Align.CENTER,
            visible=False,
        )
        botao = Gtk.Button(
            label=_("Instalar"),
            valign=Gtk.Align.CENTER,
            css_classes=["suggested-action"],
        )
        botao.connect("clicked", self._instalar, integracao, botao, espinha)
        # A linha inteira também instala: no modo sessão o alvo de foco
        # precisa ser maior que um botão de sufixo.
        linha.set_activatable(True)
        linha.connect("activated", self._instalar, integracao, botao, espinha)
        linha.add_suffix(espinha)
        linha.add_suffix(botao)
        return linha

    @staticmethod
    def _rotulo_status(texto: str) -> Gtk.Label:
        return Gtk.Label(
            label=texto,
            valign=Gtk.Align.CENTER,
            wrap=True,
            xalign=1,
            css_classes=["dim-label"],
        )

    def _instalar(
        self,
        _origem: Gtk.Widget,
        integracao: Integracao,
        botao: Gtk.Button,
        espinha: Gtk.Spinner,
    ) -> None:
        app_id = integracao.app_id_flatpak
        if not app_id or integracao.chave in self._instalando:
            return
        self._instalando.add(integracao.chave)
        botao.set_sensitive(False)
        espinha.set_visible(True)
        espinha.start()
        threading.Thread(
            target=self._executar_instalacao,
            args=(integracao, app_id),
            daemon=True,
        ).start()

    def _executar_instalacao(self, integracao: Integracao, app_id: str) -> None:
        try:
            instalar_flatpak(app_id)
            falha = ""
        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error("Falha ao instalar %s: %s", app_id, error)
            falha = str(error).strip()
        entregar_na_tela(self._instalacao_pronta, integracao, falha)

    def _instalacao_pronta(self, integracao: Integracao, falha: str) -> bool:
        self._instalando.discard(integracao.chave)
        if falha:
            self._aviso(
                falha
                if 0 < len(falha) <= _MAXIMO_AVISO
                else _("Não foi possível instalar {}").format(integracao.titulo)
            )
        else:
            self._aviso(_("{} instalado").format(integracao.titulo))
        # O status pode ter mudado para nativo/flatpak: recarrega as linhas.
        self.atualizar()
        return GLib.SOURCE_REMOVE

    def _chave_com_foco(self) -> Optional[str]:
        """Integração cuja linha está sob o foco, se o foco está numa linha."""
        try:
            widget = self.get_focus()
        except Exception:  # pylint: disable=broad-exception-caught
            return None
        while widget is not None:
            for chave, linha in self._por_chave.items():
                if widget is linha:
                    return chave
            widget = widget.get_parent()
        return None

    def _focar_linha(self, chave: str) -> None:
        try:
            if (linha := self._por_chave.get(chave)) is not None:
                linha.grab_focus()
        except Exception:  # pylint: disable=broad-exception-caught
            pass

    def _aviso(self, mensagem: str) -> None:
        if (janela := getattr(shared, "win", None)) is None:
            return
        try:
            janela.toast_queue.add(Adw.Toast.new(mensagem))
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Não foi possível exibir o aviso: %s", mensagem)

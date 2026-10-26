# lighting_page.py
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

"""Página Perfis de iluminação: o que cada jogo veste e em que dispositivo.

Duas listas e nada além disso: os perfis (à esquerda do olhar, no topo) e os
dispositivos do perfil selecionado. Toda alteração é gravada na hora — não há
botão "Salvar", porque uma preferência que se perde ao fechar a página é uma
preferência que o usuário não sabe que existe.

Duas regras de thread valem aqui, as mesmas de toda a base:

* a leitura dos dispositivos do servidor OpenRGB e das fitas é pesada e roda
  em thread própria, com o resultado entregue pela
  :func:`cartridges.utils.na_tela.entregar_na_tela`;
* nenhuma dessas funções é chamada da thread principal — a janela não espera
  um hardware que pode estar desligado.
"""

from __future__ import annotations

import builtins
import logging
import threading
from typing import Any, Optional

from gi.repository import Adw, Gdk, Gtk

from cartridges import shared
from cartridges.iluminacao import coordenador
from cartridges.iluminacao.cores import PRETO, Cor, do_app
from cartridges.iluminacao.modelo import Alvo, CoresDaZona, Plano
from cartridges.iluminacao.perfis import Perfil, Repositorio
from cartridges.utils.na_tela import entregar_na_tela

# O launcher instala o gettext antes de importar o app; o fallback mantém
# este módulo importável em testes e ferramentas sem catálogo.
if not hasattr(builtins, "_"):
    builtins._ = lambda text: text  # type: ignore[attr-defined]

#: Tamanho do quadradinho de cor, em pixels.
_AMOSTRA = 22


def _rgba_de(cor: Optional[Cor]) -> Gdk.RGBA:
    """Uma cor do Jolven como o seletor do GTK a entende."""
    base = cor or do_app()
    rgba = Gdk.RGBA()
    rgba.red = base.vermelho / 255
    rgba.green = base.verde / 255
    rgba.blue = base.azul / 255
    rgba.alpha = 1.0
    return rgba


def _cor_de(rgba: Gdk.RGBA) -> Cor:
    """O caminho de volta. Alfa ignorado: iluminação não tem transparência."""
    return Cor(
        round(max(0.0, min(1.0, rgba.red)) * 255),
        round(max(0.0, min(1.0, rgba.green)) * 255),
        round(max(0.0, min(1.0, rgba.blue)) * 255),
    )


def _subtitulo_do_alvo(alvo: Alvo, plano: Optional[Plano]) -> str:
    """Linha de baixo do dispositivo: categoria, modo e o que o perfil faz."""
    partes = [alvo.rotulo_categoria]
    modo = (plano.modo if plano and plano.modo else alvo.modo_atual) or ""
    if modo:
        partes.append(modo)
    if alvo.total_leds:
        partes.append(_("{} LEDs").format(alvo.total_leds))
    if plano is None:
        partes.append(_("não altera"))
    elif plano.cor is not None:
        partes.append(plano.cor.como_hex())
    return " · ".join(partes)


@Gtk.Template(resource_path=shared.PREFIX + "/gtk/lighting-profiles.ui")
class LightingPage(Adw.NavigationPage):
    """Os perfis de iluminação e o que cada um manda em cada dispositivo."""

    __gtype_name__ = "LightingPage"

    lighting_stack = Gtk.Template.Child()
    lighting_perfis_list = Gtk.Template.Child()
    lighting_dispositivos_group = Gtk.Template.Child()
    lighting_novo_button = Gtk.Template.Child()
    lighting_testar_button = Gtk.Template.Child()
    lighting_atualizar_button = Gtk.Template.Child()

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._repositorio = Repositorio()
        self._perfis: list[Perfil] = []
        self._alvos: list[Alvo] = []
        self._atual_id = ""
        self._lendo = False
        self._testando: Optional[str] = None
        self._linhas_perfis: list[Adw.ActionRow] = []
        self._linhas_dispositivos: list[Adw.ActionRow] = []

        self.lighting_novo_button.connect("clicked", self._novo_perfil)
        self.lighting_atualizar_button.connect("clicked", lambda *_: self.atualizar())
        self.lighting_testar_button.connect("clicked", self._testar)
        self.lighting_perfis_list.connect("row-selected", self._selecionar)

    # -- leitura -----------------------------------------------------

    def atualizar(self) -> None:
        """Recarrega perfis e dispositivos. Sempre em thread de trabalho."""
        if self._lendo:
            return
        self._lendo = True
        self.lighting_stack.set_visible_child_name("loading")
        threading.Thread(target=self._ler_tudo, name="perfis-iluminacao").start()

    def _ler_tudo(self) -> None:
        perfis = self._repositorio.carregar()
        try:
            alvos = coordenador.instancia().alvos()
        except Exception:  # pylint: disable=broad-except
            logging.exception("Não foi possível listar os dispositivos de iluminação")
            alvos = []
        entregar_na_tela(self._apresentar, perfis, alvos)

    def _apresentar(self, perfis: list[Perfil], alvos: list[Alvo]) -> None:
        self._lendo = False
        self._perfis = perfis
        self._alvos = sorted(alvos, key=lambda a: (a.rotulo_categoria, a.nome.lower()))
        self._remover_perfis()
        self._remover_dispositivos()

        if not perfis:
            self.lighting_stack.set_visible_child_name("empty")
            self.lighting_testar_button.set_visible(False)
            return

        if self._atual_id not in {perfil.id for perfil in perfis}:
            self._atual_id = perfis[0].id
        self.lighting_stack.set_visible_child_name("edit")
        self.lighting_testar_button.set_visible(True)
        self._desenhar_perfis()
        self._desenhar_dispositivos()

    def _remover_perfis(self) -> None:
        for linha in self._linhas_perfis:
            self.lighting_perfis_list.remove(linha)
        self._linhas_perfis.clear()

    def _remover_dispositivos(self) -> None:
        for linha in self._linhas_dispositivos:
            self.lighting_dispositivos_group.remove(linha)
        self._linhas_dispositivos.clear()

    # -- perfis ------------------------------------------------------

    def _desenhar_perfis(self) -> None:
        self._remover_perfis()
        for perfil in self._perfis:
            linha = Adw.ActionRow(title=perfil.nome)
            linha.set_subtitle(self._subtitulo_do_perfil(perfil))
            linha.connect("activated", self._ativar_perfil, perfil)

            renomear = Gtk.Button(
                icon_name="document-edit-symbolic",
                valign=Gtk.Align.CENTER,
                css_classes=["flat"],
                tooltip_text=_("Renomear"),
            )
            renomear.connect("clicked", self._renomear, perfil)
            linha.add_suffix(renomear)

            duplicar = Gtk.Button(
                icon_name="edit-copy-symbolic",
                valign=Gtk.Align.CENTER,
                css_classes=["flat"],
                tooltip_text=_("Duplicar"),
            )
            duplicar.connect("clicked", self._duplicar, perfil)
            linha.add_suffix(duplicar)

            excluir = Gtk.Button(
                icon_name="user-trash-symbolic",
                valign=Gtk.Align.CENTER,
                css_classes=["flat"],
                tooltip_text=_("Excluir"),
            )
            excluir.connect("clicked", self._excluir, perfil)
            linha.add_suffix(excluir)

            self.lighting_perfis_list.append(linha)
            self._linhas_perfis.append(linha)
            if perfil.id == self._atual_id:
                self.lighting_perfis_list.select_row(linha)

        # Sem seleção nenhuma (primeira carga) o ListBox não emite
        # ``row-selected``: selecionar explicitamente resolve.
        if self.lighting_perfis_list.get_selected_row() is None and self._linhas_perfis:
            self.lighting_perfis_list.select_row(self._linhas_perfis[0])

    @staticmethod
    def _subtitulo_do_perfil(perfil: Perfil) -> str:
        quantidade = len(perfil.dispositivos)
        if quantidade == 0:
            return _("nenhum dispositivo")
        if quantidade == 1:
            return _("1 dispositivo")
        return _("{} dispositivos").format(quantidade)

    def _ativar_perfil(self, linha: Adw.ActionRow, perfil: Perfil) -> None:
        self._selecionar(self.lighting_perfis_list, linha)

    def _selecionar(
        self, lista: Gtk.ListBox, linha: Optional[Gtk.ListBoxRow]
    ) -> None:
        if linha is None:
            return
        indice = lista.row_index(linha)
        if indice < 0 or indice >= len(self._perfis):
            return
        perfil = self._perfis[indice]
        if perfil.id == self._atual_id:
            return
        self._atual_id = perfil.id
        self._parar_teste()
        self._desenhar_dispositivos()

    def _perfil(self) -> Optional[Perfil]:
        for perfil in self._perfis:
            if perfil.id == self._atual_id:
                return perfil
        return None

    def _salvar(self, perfil: Perfil) -> None:
        perfil.tocar()
        if not self._repositorio.salvar(self._perfis):
            self._aviso(_("Não foi possível gravar o perfil"))
        for linha in self._linhas_perfis:
            if linha.get_title() == perfil.nome:
                linha.set_subtitle(self._subtitulo_do_perfil(perfil))
                break

    # -- ações de perfil ---------------------------------------------

    def _novo_perfil(self, *_args: Any) -> None:
        self._pedir_nome(_("Novo perfil de iluminação"), "", self._criar_perfil)

    def _criar_perfil(self, nome: str) -> None:
        perfil = self._repositorio.criar(nome)
        self._perfis.append(perfil)
        if not self._repositorio.salvar(self._perfis):
            self._perfis.remove(perfil)
            self._aviso(_("Não foi possível gravar o perfil"))
            return
        self._atual_id = perfil.id
        self.lighting_stack.set_visible_child_name("edit")
        self.lighting_testar_button.set_visible(True)
        self._desenhar_perfis()
        self._desenhar_dispositivos()

    def _renomear(self, _botao: Gtk.Button, perfil: Perfil) -> None:
        self._pedir_nome(
            _("Renomear perfil"), perfil.nome, lambda nome: self._aplicar_renomear(perfil, nome)
        )

    def _aplicar_renomear(self, perfil: Perfil, nome: str) -> None:
        perfil.nome = nome
        self._salvar(perfil)
        self._desenhar_perfis()

    def _duplicar(self, _botao: Gtk.Button, perfil: Perfil) -> None:
        copia = self._repositorio.duplicar(perfil.id)
        if copia is None:
            self._aviso(_("Não foi possível duplicar o perfil"))
            return
        self._perfis.append(copia)
        self._atual_id = copia.id
        self._desenhar_perfis()
        self._desenhar_dispositivos()

    def _excluir(self, botao: Gtk.Button, perfil: Perfil) -> None:
        dialogo = Adw.AlertDialog.new(
            _("Excluir o perfil {}?").format(perfil.nome),
            _("Os jogos que usam este perfil voltam a não ter iluminação especial."),
        )
        dialogo.add_response("cancel", _("Cancelar"))
        dialogo.add_response("excluir", _("Excluir"))
        dialogo.set_response_appearance("excluir", Adw.ResponseAppearance.DESTRUCTIVE)
        dialogo.set_default_response("cancel")
        dialogo.set_close_response("cancel")
        dialogo.connect("response", self._respondeu_excluir, perfil)
        dialogo.present(self)

    def _respondeu_excluir(
        self, dialogo: Adw.AlertDialog, resposta: str, perfil: Perfil
    ) -> None:
        if resposta != "excluir":
            return
        if not self._repositorio.excluir(perfil.id):
            self._aviso(_("Não foi possível excluir o perfil"))
            return
        self._perfis = [item for item in self._perfis if item.id != perfil.id]
        if self._atual_id == perfil.id:
            self._atual_id = self._perfis[0].id if self._perfis else ""
        if self._perfis:
            self._desenhar_perfis()
            self._desenhar_dispositivos()
        else:
            self.lighting_stack.set_visible_child_name("empty")
            self.lighting_testar_button.set_visible(False)

    def _testar(self, *_args: Any) -> None:
        perfil = self._perfil()
        if perfil is None:
            return
        instancia = coordenador.instancia()
        if self._testando == perfil.id:
            self._parar_teste()
            return
        instancia.previa(perfil)
        self._testando = perfil.id
        self.lighting_testar_button.set_icon_name("media-playback-stop-symbolic")
        self.lighting_testar_button.set_tooltip_text(_("Voltar ao estado anterior"))

    def _parar_teste(self) -> None:
        if self._testando is None:
            return
        self._testando = None
        self.lighting_testar_button.set_icon_name("media-playback-start-symbolic")
        self.lighting_testar_button.set_tooltip_text(_("Ver o perfil nos dispositivos"))
        coordenador.instancia().restaurar_previa()

    def _pedir_nome(self, titulo: str, inicial: str, ao_confirmar: Any) -> None:
        """Caixa de texto de um nome, com Cancelar e Confirmar."""
        dialogo = Adw.Dialog(title=titulo, content_width=380)
        cabecalho = Adw.HeaderBar(
            show_start_title_buttons=False, show_end_title_buttons=False
        )
        cancelar = Gtk.Button(label=_("Cancelar"))
        confirmar = Gtk.Button(label=_("Confirmar"), css_classes=["suggested-action"])
        cabecalho.pack_start(cancelar)
        cabecalho.pack_end(confirmar)

        campo = Adw.EntryRow(title=_("Nome"))
        campo.set_text(inicial)
        campo.set_show_apply_button(True)

        conteudo = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        conteudo.append(cabecalho)
        conteudo.append(campo)
        dialogo.set_child(conteudo)

        def confirmar_nome(*_args: Any) -> None:
            nome = campo.get_text().strip()
            if not nome:
                campo.add_css_class("error")
                return
            dialogo.close()
            ao_confirmar(nome)

        cancelar.connect("clicked", lambda *_: dialogo.close())
        confirmar.connect("clicked", confirmar_nome)
        campo.connect("entry-activated", confirmar_nome)
        dialogo.connect("closed", lambda *_: campo.remove_css_class("error"))
        dialogo.present(self)
        campo.grab_focus()

    # -- dispositivos ------------------------------------------------

    def _desenhar_dispositivos(self) -> None:
        self._remover_dispositivos()
        perfil = self._perfil()
        if perfil is None:
            return
        if not self._alvos:
            self.lighting_dispositivos_group.set_description(
                _(
                    "Nenhum dispositivo encontrado. Abra as Preferências para "
                    "ligar o OpenRGB ou configurar as fitas inteligentes."
                )
            )
            return
        self.lighting_dispositivos_group.set_description(
            _("Só os dispositivos incluídos mudam; os demais continuam como estão.")
        )
        for alvo in self._alvos:
            linha = self._linha_do_dispositivo(alvo, perfil)
            self.lighting_dispositivos_group.add(linha)
            self._linhas_dispositivos.append(linha)

    def _linha_do_dispositivo(
        self, alvo: Alvo, perfil: Perfil
    ) -> Adw.ActionRow:
        plano = perfil.plano(alvo.identificador)
        incluido = plano is not None

        # Dispositivo com mais de uma zona vira expansível: cada zona ganha a
        # sua própria cor, que é como a pessoa descreve o hardware
        # ("a fita de cima", "o lado direito da memória").
        com_zonas = len(alvo.zonas) > 1
        if com_zonas:
            linha: Adw.ActionRow = Adw.ExpanderRow(title=alvo.nome)
        else:
            linha = Adw.ActionRow(title=alvo.nome)
        linha.set_subtitle(_subtitulo_do_alvo(alvo, plano))

        cor = (plano.cor if plano and plano.cor else alvo.cor_atual) or do_app()
        sensores: list[Gtk.Widget] = []

        botao_cor = self._botao_de_cor(cor)
        botao_cor.connect("clicked", self._pedir_cor_do_alvo, alvo, perfil, None)
        botao_cor.set_sensitive(incluido)
        linha.add_suffix(botao_cor)
        sensores.append(botao_cor)

        brilho = Gtk.SpinButton.new_with_range(1, 100, 1)
        brilho.set_valign(Gtk.Align.CENTER)
        brilho.set_width_chars(3)
        brilho.set_value(plano.brilho if plano and plano.brilho else 100)
        brilho.set_sensitive(incluido)
        brilho.connect("value-changed", self._mudar_brilho, alvo, perfil)
        linha.add_suffix(brilho)
        sensores.append(brilho)

        rotulo_brilho = Gtk.Label(label="%", valign=Gtk.Align.CENTER, xalign=0)
        rotulo_brilho.add_css_class("dim-label")
        linha.add_suffix(rotulo_brilho)

        if alvo.modos:
            seletor_modo = Gtk.DropDown.new_from_strings(list(alvo.modos))
            seletor_modo.set_valign(Gtk.Align.CENTER)
            modo_atual = plano.modo if plano and plano.modo else ""
            indice = (
                list(alvo.modos).index(modo_atual) if modo_atual in alvo.modos else 0
            )
            seletor_modo.set_selected(indice)
            seletor_modo.set_sensitive(incluido)
            seletor_modo.connect("notify::selected", self._mudar_modo, alvo, perfil)
            linha.add_suffix(seletor_modo)
            sensores.append(seletor_modo)

        incluir = Gtk.Switch(valign=Gtk.Align.CENTER, active=incluido)
        incluir.connect(
            "notify::active", self._alternar_dispositivo, alvo, perfil, linha
        )
        linha.add_suffix(incluir)
        # O ``ExpanderRow`` não tem ``activatable_widget``: o clique no corpo
        # dele abre e fecha as zonas, e deixar o interruptor como alvo disso
        # abriria a linha toda toda vez que a cor fosse mudada.
        if not isinstance(linha, Adw.ExpanderRow):
            linha.set_activatable_widget(incluir)
        linha._sensores = sensores  # type: ignore[attr-defined]

        if isinstance(linha, Adw.ExpanderRow):
            for zona in alvo.zonas:
                pedido = self._zona_de_plano(plano, zona.chave)
                linha_zona = Adw.ActionRow(
                    title=zona.nome,
                    subtitle=(
                        _("{} LEDs").format(zona.total) if zona.total else _("zona")
                    ),
                )
                cor_zona = pedido.cor if pedido and pedido.cor else cor
                botao_zona = self._botao_de_cor(cor_zona)
                botao_zona.set_sensitive(incluido)
                botao_zona.connect(
                    "clicked", self._pedir_cor_do_alvo, alvo, perfil, zona.chave
                )
                linha_zona.add_suffix(botao_zona)
                linha.add_row(linha_zona)  # type: ignore[attr-defined]
        return linha

    @staticmethod
    def _zona_de_plano(plano: Optional[Plano], chave: str) -> Optional[CoresDaZona]:
        if plano is None:
            return None
        for pedido in plano.zonas:
            if pedido.zona == chave:
                return pedido
        return None

    @staticmethod
    def _botao_de_cor(cor: Cor) -> Gtk.Button:
        """Botão quadrado com a cor dentro, como um tinta de guache."""
        botao = Gtk.Button(css_classes=["flat"], valign=Gtk.Align.CENTER)
        area = Gtk.DrawingArea(
            content_width=_AMOSTRA, content_height=_AMOSTRA, hexpand=False
        )
        area._cor_jolven = cor  # type: ignore[attr-defined]
        area.set_draw_func(lambda desenho, cairo, largura, altura: _pintar(
            desenho, cairo, largura, altura
        ))
        botao.set_child(area)
        return botao

    def _plano_de(
        self, alvo: Alvo, perfil: Perfil, incluir: bool = True
    ) -> Optional[Plano]:
        plano = perfil.plano(alvo.identificador)
        if plano is None:
            if not incluir:
                return None
            plano = Plano(
                provedor=alvo.provedor,
                chave=alvo.chave,
                nome=alvo.nome,
                cor=do_app(),
            )
            perfil.definir(plano)
        return plano

    def _alternar_dispositivo(
        self,
        chaveiro: Gtk.Switch,
        _pspec: Any,
        alvo: Alvo,
        perfil: Perfil,
        linha: Adw.ActionRow,
    ) -> None:
        ativo = chaveiro.get_active()
        if ativo:
            self._plano_de(alvo, perfil, incluir=True)
        else:
            perfil.remover(alvo.identificador)
            self._testar_se_para(perfil)
        self._salvar(perfil)
        # Só esta linha muda: redesenhar o grupo aqui destruiria o widget que
        # está no meio do clique.
        for controle in getattr(linha, "_sensores", []):
            controle.set_sensitive(ativo)
        linha.set_subtitle(_subtitulo_do_alvo(alvo, perfil.plano(alvo.identificador)))

    def _mudar_brilho(
        self, brilho: Gtk.SpinButton, alvo: Alvo, perfil: Perfil
    ) -> None:
        plano = self._plano_de(alvo, perfil)
        if plano is None:
            return
        plano.brilho = int(brilho.get_value())
        self._salvar(perfil)

    def _mudar_modo(
        self, seletor: Gtk.DropDown, _pspec: Any, alvo: Alvo, perfil: Perfil
    ) -> None:
        plano = self._plano_de(alvo, perfil)
        if plano is None:
            return
        indice = seletor.get_selected()
        if indice >= len(alvo.modos):
            plano.modo = ""
        else:
            plano.modo = alvo.modos[indice]
        self._salvar(perfil)

    def _pedir_cor_do_alvo(
        self, botao: Gtk.Button, alvo: Alvo, perfil: Perfil, chave_zona: Optional[str]
    ) -> None:
        plano = perfil.plano(alvo.identificador)
        if plano is None:
            return
        if chave_zona:
            pedido = self._zona_de_plano(plano, chave_zona)
            atual = pedido.cor if pedido and pedido.cor else (plano.cor or do_app())
        else:
            atual = plano.cor or alvo.cor_atual or do_app()
        dialogo = Gtk.ColorChooserDialog(title=_("Cor"), modal=True)
        if shared.win is not None:
            dialogo.set_transient_for(shared.win)
        dialogo.set_rgba(_rgba_de(atual))
        dialogo.connect(
            "response",
            self._respondeu_cor,
            botao,
            alvo,
            perfil,
            chave_zona,
        )
        dialogo.present()

    def _respondeu_cor(
        self,
        dialogo: Gtk.ColorChooserDialog,
        resposta: int,
        botao: Gtk.Button,
        alvo: Alvo,
        perfil: Perfil,
        chave_zona: Optional[str],
    ) -> None:
        if resposta == Gtk.ResponseType.OK:
            cor = _cor_de(dialogo.get_rgba())
            plano = self._plano_de(alvo, perfil)
            if plano is not None:
                if chave_zona:
                    pedido = self._zona_de_plano(plano, chave_zona)
                    if pedido is None:
                        pedido = CoresDaZona(zona=chave_zona)
                        plano.zonas.append(pedido)
                    pedido.cor = cor
                else:
                    plano.cor = cor
                self._salvar(perfil)
                self._atualizar_amostra(botao, cor)
                linha = botao.get_parent()
                if isinstance(linha, Adw.ActionRow):
                    linha.set_subtitle(_subtitulo_do_alvo(alvo, plano))
        dialogo.destroy()

    @staticmethod
    def _atualizar_amostra(botao: Gtk.Button, cor: Cor) -> None:
        area = botao.get_child()
        if area is not None:
            area._cor_jolven = cor  # type: ignore[attr-defined]
            area.queue_draw()

    def _testar_se_para(self, perfil: Perfil) -> None:
        if self._testando == perfil.id:
            self._parar_teste()

    def _aviso(self, texto: str) -> None:
        if shared.win is not None:
            shared.win.toast_queue.add(Adw.Toast.new(texto))

    # -- ciclo da página ---------------------------------------------

    def do_unmap(self) -> None:  # pylint: disable=arguments-differ
        """Ao sair da página, o teste em andamento volta ao estado anterior."""
        self._parar_teste()
        super().do_unmap()


def _pintar(area: Gtk.DrawingArea, cairo: Any, largura: int, altura: int) -> None:
    """Desenha o quadradinho de cor de um botão."""
    cor: Cor = getattr(area, "_cor_jolven", None) or PRETO
    cairo.set_source_rgb(cor.vermelho / 255, cor.verde / 255, cor.azul / 255)
    cairo.rectangle(0, 0, largura, altura)
    cairo.fill()
    cairo.set_line_width(1)
    cairo.set_source_rgba(0, 0, 0, 0.4)
    cairo.rectangle(0.5, 0.5, max(0, largura - 1), max(0, altura - 1))
    cairo.stroke()


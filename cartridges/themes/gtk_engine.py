"""Motor de CSS do GTK4 — aplica a paleta do Jolven à interface.

Responsabilidades
-----------------
1. Gerar um ``Gtk.CssProvider`` dedicado a partir de uma :class:`Palette`.
2. Instalar/remover o provider no display padrão, em
   ``Gtk.STYLE_PROVIDER_PRIORITY_USER``, para a cor mudar ao vivo, sem restart.
3. Emitir apenas as variáveis de destaque (``--accent-color`` e
   ``--accent-bg-color``), deixando os fundos claros/escuros para o libadwaita.
4. Resolver o modo ``auto`` pelo :class:`Adw.StyleManager`, com fallback.

Notas de projeto
----------------
* Nenhum CSS do Steam é carregado no GTK.
* A aplicação é idempotente: reaplicar o mesmo estado não reescreve o provider
  (debounce mínimo). O agendamento com ``GLib.timeout`` fica no ``ThemeManager``.
* Nada aqui bloqueia a thread principal do GTK — só há carga de CSS em memória.
"""

from __future__ import annotations

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gtk

from cartridges.themes.catalog import obter_tema, tema_padrao
from cartridges.themes.palette import Palette, validar_hex

_LOG = logging.getLogger(__name__)

#: Prioridade do provider: vence o padrão do Adw/libadwaita, mas ainda pode ser
#: sobrescrito por um tema instalado pelo usuário fora do Jolven.
_PRIORIDADE = Gtk.STYLE_PROVIDER_PRIORITY_USER

#: Estado aplicado na última chamada, para o debounce idempotente.
#: (slug, modo_efetivo, glows, acento_custom)
_estado_aplicado: tuple[str, str, bool, str | None] | None = None

#: Provider dedicado do tema (um só por processo, reutilizado a cada troca).
_provider: Gtk.CssProvider | None = None

#: Brilho opt-in do tema Jolven. As classes vivem no ``data/gtk/style.css``;
#: aqui só reforçamos o foco, sem duplicar as regras visuais.
_GLOW_CSS = """\
/* Jolven: brilho RGB opt-in (só no tema jolven) */
.jolven-glow-accent:focus-visible,
.jolven-glow-card:focus-visible,
.jolven-rgb-border:focus-visible {
  box-shadow: 0 0 0 2px var(--accent-color, #813d9c);
}
"""


def _resolver_modo(modo: str) -> str:
    """Resolve ``light``/``dark``; ``auto`` segue o esquema efetivo do sistema."""
    if modo in ("light", "dark"):
        return modo
    try:
        style_manager = Adw.StyleManager.get_default()
        if style_manager is not None:
            return "dark" if style_manager.get_dark() else "light"
    except Exception:  # pylint: disable=broad-exception-caught
        pass
    try:
        settings = Gtk.Settings.get_default()
        if settings is not None and settings.get_gtk_application_prefer_dark_theme():
            return "dark"
    except Exception:  # pylint: disable=broad-exception-caught
        pass
    return "dark"


def _gerar_css(
    paleta: Palette,
    modo: str,
    glows: bool,
    acento_custom: str | None,
) -> str:
    """Monta o CSS ``:root`` determinístico para a paleta e o modo."""
    variaveis = dict(paleta.css_variables())
    acento = validar_hex(acento_custom)
    if acento:
        variaveis["--accent-bg-color"] = acento
        variaveis["--accent-color"] = acento

    linhas = "\n".join(f"  {chave}: {valor};" for chave, valor in variaveis.items())
    partes = [f":root {{\n{linhas}\n}}\n"]

    # O brilho é exclusivo da identidade Jolven; em qualquer outro tema ele é
    # ignorado mesmo que a preferência esteja ligada.
    if glows and paleta.slug == tema_padrao().slug:
        partes.append(_GLOW_CSS)

    # ``modo`` já está resolvido; o comentário ajuda a depurar o CSS gerado.
    partes.append(f"/* modo: {modo} */\n")
    return "\n".join(partes)


def aplicar(
    slug: str,
    modo: str,
    glows: bool = False,
    acento_custom: str | None = None,
) -> None:
    """Aplica a paleta *slug* no modo *modo* à aplicação GTK.

    Seguro para chamar repetidamente: quando o estado não mudou, nada é
    reescrito. Nunca levanta exceção — falhas caem no log e o Jolven continua
    com as cores padrão do libadwaita.
    """
    global _provider, _estado_aplicado

    try:
        paleta = obter_tema(slug)
        modo_efetivo = _resolver_modo(modo)
        acento = validar_hex(acento_custom)

        estado = (paleta.slug, modo_efetivo, bool(glows), acento)
        if estado == _estado_aplicado and _provider is not None:
            return

        display = Gdk.Display.get_default()
        if display is None:
            _LOG.debug("Sem Gdk.Display — tema adiado (%s)", paleta.slug)
            return

        css = _gerar_css(paleta, modo_efetivo, glows, acento)
        provider = Gtk.CssProvider()
        provider.load_from_string(css)

        _remover_provider_instalado(display)
        Gtk.StyleContext.add_provider_for_display(display, provider, _PRIORIDADE)

        _provider = provider
        _estado_aplicado = estado
        _LOG.info(
            "Tema aplicado: %s (modo=%s, glows=%s)", paleta.slug, modo_efetivo, glows
        )
    except Exception:  # pylint: disable=broad-exception-caught
        _LOG.exception("Falha ao aplicar o tema %r — mantendo o padrão", slug)


def remover() -> None:
    """Remove o provider do tema, voltando às cores padrão do Adw/libadwaita."""
    global _provider, _estado_aplicado

    display = Gdk.Display.get_default()
    if display is not None:
        _remover_provider_instalado(display)
    _provider = None
    _estado_aplicado = None


def _remover_provider_instalado(display: Gdk.Display) -> None:
    """Desinstala o provider dedicado do display, se houver."""
    if _provider is None:
        return
    try:
        Gtk.StyleContext.remove_provider_for_display(display, _provider, _PRIORIDADE)
    except Exception:  # pylint: disable=broad-exception-caught
        pass

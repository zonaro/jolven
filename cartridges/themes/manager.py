"""ThemeManager — coordena a personalização visual do Jolven.

Responsabilidades
-----------------
1. Guardar a paleta, o modo e o brilho atuais.
2. Observar as chaves GSettings (``theme-slug``, ``theme-mode``,
   ``theme-accent-custom``, ``steam-skin-enabled``) e reaplicar o tema.
3. Aplicar via ``cartridges.themes.gtk_engine`` (um provider dedicado).
4. Expor :meth:`perfil_compartilhado` para a integração de skin do Steam.
5. Nunca bloquear a thread do GTK e nunca derrubar a aplicação: toda a
   sincronização roda na thread principal e qualquer falha é registrada.

A API é intencionalmente simples (``set_palette``/``set_mode``/``set_glows`` +
``bind_to_schema``) em vez de ``GObject.Property`` com setters — as mudanças
rápidas são coalescidas por um ``GLib.timeout`` curto.
"""

from __future__ import annotations

import logging

import gi

gi.require_version("GObject", "2.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, GObject

from cartridges.themes import gtk_engine
from cartridges.themes.catalog import CATALOGO, obter_tema, tema_padrao
from cartridges.themes.palette import Palette, validar_hex

_LOG = logging.getLogger(__name__)

_SLUG_PADRAO = tema_padrao().slug
_MODO_PADRAO = "auto"
_MODOS_VALIDOS = ("light", "dark", "auto")

#: Janela de coalescência (ms) para rajadas de mudanças vindas da UI.
_DEBOUNCE_MS = 80

#: Singleton do processo.
_instancia: "ThemeManager | None" = None


class ThemeManager(GObject.Object):
    """Gerencia a paleta, o modo e o brilho RGB do Jolven."""

    __gsignals__ = {
        "theme-changed": (GObject.SignalFlags.RUN_LAST, None, (str, str, bool)),
        "mode-changed": (GObject.SignalFlags.RUN_LAST, None, (str,)),
        "glows-changed": (GObject.SignalFlags.RUN_LAST, None, (bool,)),
    }

    def __init__(self) -> None:
        super().__init__()
        self._slug: str = _SLUG_PADRAO
        self._modo: str = _MODO_PADRAO
        self._glows: bool = False
        self._acento_custom: str = ""
        self._steam_skin: bool = False
        self._schema: Gio.Settings | None = None
        self._debounce_id: int = 0
        self._style_notify_id: int = 0

    # ── Acesso somente-leitura ────────────────────────────────────────────

    @property
    def slug(self) -> str:
        """Slug do tema atual."""
        return self._slug

    @property
    def modo(self) -> str:
        """Modo atual: ``light``, ``dark`` ou ``auto``."""
        return self._modo

    @property
    def glows(self) -> bool:
        """``True`` quando o brilho RGB está ligado."""
        return self._glows

    @property
    def paleta(self) -> Palette:
        """A :class:`Palette` do tema atual."""
        return obter_tema(self._slug)

    @property
    def steam_skin_ativo(self) -> bool:
        """``True`` quando o usuário pediu para aplicar o tema na skin do Steam."""
        return self._steam_skin

    # ── GSettings ─────────────────────────────────────────────────────────

    def bind_to_schema(self, schema: Gio.Settings) -> None:
        """Observa *schema* e aplica o tema atual.

        Conecta em ``changed::`` em vez de ``Gio.Settings.bind`` para não criar
        laço de escrita/leitura com os valores derivados da paleta.
        """
        try:
            self._schema = schema
            schema.connect("changed::theme-slug", self._on_schema_changed)
            schema.connect("changed::theme-mode", self._on_schema_changed)
            schema.connect("changed::theme-accent-custom", self._on_schema_changed)
            schema.connect("changed::steam-skin-enabled", self._on_steam_skin_changed)

            # No modo "auto" o tema precisa acompanhar o esquema do sistema.
            try:
                style_manager = Adw.StyleManager.get_default()
                if style_manager is not None and self._style_notify_id == 0:
                    self._style_notify_id = style_manager.connect(
                        "notify::dark", self._on_system_scheme_changed
                    )
            except Exception:  # pylint: disable=broad-exception-caught
                _LOG.debug("Adw.StyleManager indisponível para o modo automático")

            self._ler_schema()
            self._aplicar()
        except Exception:  # pylint: disable=broad-exception-caught
            _LOG.exception("ThemeManager: falha ao vincular ao schema GSettings")

    def _ler_schema(self) -> None:
        if self._schema is None:
            return
        self._slug = self._schema.get_string("theme-slug") or _SLUG_PADRAO
        self._modo = self._schema.get_string("theme-mode") or _MODO_PADRAO
        self._acento_custom = self._schema.get_string("theme-accent-custom") or ""
        self._steam_skin = self._schema.get_boolean("steam-skin-enabled")

    def _on_schema_changed(self, *_args: object) -> None:
        self._ler_schema()
        self._agendar()

    def _on_steam_skin_changed(self, *_args: object) -> None:
        self._steam_skin = bool(
            self._schema and self._schema.get_boolean("steam-skin-enabled")
        )
        # A skin do Steam é acionada por outra lane; aqui só sinalizamos a
        # mudança para quem estiver escutando.
        self.emit("theme-changed", self._slug, self._modo, self._glows)

    def _on_system_scheme_changed(self, *_args: object) -> None:
        if self._modo == "auto":
            self._agendar()

    # ── API de mutação ────────────────────────────────────────────────────

    def set_palette(self, slug: str) -> None:
        """Troca o tema, mantendo o modo e o brilho atuais."""
        self._slug = slug if slug in CATALOGO else _SLUG_PADRAO
        self._agendar()

    def set_mode(self, modo: str) -> None:
        """Troca o modo (``light``/``dark``/``auto``)."""
        self._modo = modo if modo in _MODOS_VALIDOS else _MODO_PADRAO
        self._agendar()

    def set_glows(self, ativo: bool) -> None:
        """Liga/desliga o brilho RGB (efetivo apenas no tema ``jolven``)."""
        self._glows = bool(ativo)
        self._agendar()

    def set_acento_custom(self, cor: str | None) -> None:
        """Define uma cor de destaque personalizada (``#RRGGBB``) ou limpa."""
        self._acento_custom = validar_hex(cor) or ""
        self._agendar()

    # ── Agendamento e aplicação ───────────────────────────────────────────

    def _agendar(self) -> None:
        """Coalesce mudanças rápidas num único apply na thread principal."""
        if self._debounce_id:
            GLib.source_remove(self._debounce_id)
        self._debounce_id = GLib.timeout_add(_DEBOUNCE_MS, self._aplicar_pendente)

    def _aplicar_pendente(self) -> bool:
        self._debounce_id = 0
        self._aplicar()
        return GLib.SOURCE_REMOVE

    def _aplicar(self) -> None:
        try:
            paleta = obter_tema(self._slug)
            self._slug = paleta.slug

            gtk_engine.aplicar(
                paleta.slug,
                self._modo,
                self._glows,
                self._acento_custom or None,
            )
            self._sincronizar_color_scheme()

            self.emit("theme-changed", paleta.slug, self._modo, self._glows)
            self.emit("mode-changed", self._modo)
            self.emit("glows-changed", self._glows)
            _LOG.info(
                "ThemeManager: %s (modo=%s, glows=%s)", paleta.slug, self._modo, self._glows
            )
        except Exception:  # pylint: disable=broad-exception-caught
            _LOG.exception("ThemeManager: falha ao aplicar o tema")

    def _sincronizar_color_scheme(self) -> None:
        """Alinha o ``Adw.StyleManager`` ao modo escolhido no Jolven."""
        try:
            style_manager = Adw.StyleManager.get_default()
            if style_manager is None:
                return
            if self._modo == "dark":
                style_manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
            elif self._modo == "light":
                style_manager.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
            else:
                style_manager.set_color_scheme(Adw.ColorScheme.DEFAULT)
        except Exception:  # pylint: disable=broad-exception-caught
            _LOG.debug("Não foi possível sincronizar o Adw.ColorScheme")

    # ── Integração com a skin do Steam ────────────────────────────────────

    def perfil_compatilhado(self) -> dict[str, str | bool]:
        """Perfil consumido pelo ``SteamSkinManager``.

        Chaves: ``theme_slug``, ``accent``, ``accent_custom``, ``mode`` e
        ``glows``. ``accent`` já resolve o valor efetivo (custom quando válido,
        senão o destaque da paleta).
        """
        paleta = obter_tema(self._slug)
        acento = validar_hex(self._acento_custom) or (paleta.accent_bg or "")
        return {
            "theme_slug": paleta.slug,
            "accent": acento,
            "accent_custom": self._acento_custom,
            "mode": self._modo,
            "glows": self._glows,
        }

    #: Alias com a grafia correta de "compartilhado".
    perfil_compartilhado = perfil_compatilhado

    # ── Singleton e helpers ───────────────────────────────────────────────

    @classmethod
    def instance(cls) -> "ThemeManager":
        """Devolve o ``ThemeManager`` único do processo, criando-o se preciso."""
        global _instancia
        if _instancia is None:
            _instancia = cls()
        return _instancia

    @staticmethod
    def listar_catalogo() -> list[str]:
        """Slugs do catálogo, para popular combos/abas de preferências."""
        return list(CATALOGO)

    @staticmethod
    def info_do_tema(slug: str) -> dict[str, str | bool | None]:
        """Informações resumidas de um tema (nome, dark-only, destaques)."""
        paleta = obter_tema(slug)
        return {
            "name": paleta.name,
            "is_dark_only": paleta.is_dark_only,
            "accent_bg": paleta.accent_bg,
            "accent_fg": paleta.accent_fg,
        }

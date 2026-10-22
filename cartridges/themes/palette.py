"""Representação de uma paleta de cores e helpers de validação.

Módulo puro: não importa GTK/GObject e não faz E/S no carregamento. As paletas
são dataclasses imutáveis construídas a partir dos esquemas de cor do
Adwaita-for-Steam mais a identidade lilás do Jolven.

Convenção de nomes (mantém a semântica já usada em ``data/gtk/style.css``):

* ``accent_bg`` -> ``--accent-bg-color`` (fundo sólido de destaque).
* ``accent_fg`` -> ``--accent-color`` (destaque para texto, bordas e brilho).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# Aceita #RGB, #RGBA, #RRGGBB e #RRGGBBAA (maiúsculas ou minúsculas).
_HEX_RE = re.compile(r"^#(?:[0-9A-Fa-f]{3,4}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$")

# Captura variáveis hex de um arquivo .css: tanto as do Adwaita-for-Steam
# (``--adw-window-bg``) quanto as mínimas do Jolven (``--accent-color``).
# Só valores hex são lidos; qualquer outro valor é ignorado.
_HEX_VAR_RE = re.compile(
    r"--(?:adw-)?([a-z0-9-]+)\s*:\s*"
    r"(#[0-9A-Fa-f]{8}|#[0-9A-Fa-f]{6}|#[0-9A-Fa-f]{4}|#[0-9A-Fa-f]{3})",
    re.IGNORECASE,
)

#: Nomes normalizados (sem o prefixo ``adw-``) consumidos diretamente.
_CAMPOS_CONHECIDOS = {
    "window-bg",
    "window",
    "bg",
    "headerbar-bg",
    "accent-bg",
    "accent-bg-color",
    "accent",
    "accent-color",
    "accent-fg",
    "accent-fg-color",
}


def validar_hex(valor: str | None) -> str | None:
    """Devolve *valor* quando é um hex válido, senão ``None``.

    Aceita ``#RGB``, ``#RGBA``, ``#RRGGBB`` e ``#RRGGBBAA``; espaços em volta
    são ignorados.
    """
    if not isinstance(valor, str):
        return None
    valor = valor.strip()
    return valor if _HEX_RE.match(valor) else None


#: Fundos de recuo quando a paleta não informa ``bg`` (ex.: CSS mínimo só com
#: destaque). Espelham os tons neutros padrão do libadwaita.
_FUNDO_CLARO = "#fafafa"
_FUNDO_ESCURO = "#242424"

#: Destaque de recuo quando a paleta não informa ``accent_bg`` (azul Adwaita).
_ACENTO_FALLBACK = "#3584e4"

#: Texto sobre fundo escuro / sobre fundo claro (contraste máximo, legível em
#: qualquer paleta do catálogo).
_FG_SOBRE_ESCURO = "white"
_FG_SOBRE_CLARO = "black"


def _rgb_de_hex(cor: str) -> tuple[int, int, int] | None:
    """Decompõe um hex (``#RGB``/``#RRGGBB`` e variantes com alfa) em RGB."""
    texto = cor.strip().lstrip("#")
    if len(texto) in (3, 4):
        texto = "".join(caractere * 2 for caractere in texto[:3])
    if len(texto) < 6:
        return None
    try:
        return (int(texto[0:2], 16), int(texto[2:4], 16), int(texto[4:6], 16))
    except ValueError:
        return None


def _luminancia(cor: str) -> float | None:
    """Luminância sRGB aproximada (0 = preto, 1 = branco) ou ``None``."""
    rgb = _rgb_de_hex(cor)
    if rgb is None:
        return None
    vermelho, verde, azul = rgb
    return (0.2126 * vermelho + 0.7152 * verde + 0.0722 * azul) / 255


def cor_contraste(fundo: str) -> str:
    """Cor de texto legível sobre *fundo*: ``"white"`` ou ``"black"``.

    Decide pela luminância do fundo; um valor irreconhecível é tratado como
    escuro (texto claro), que é o caso dominante do catálogo.
    """
    luminancia = _luminancia(fundo)
    if luminancia is not None and luminancia >= 0.5:
        return _FG_SOBRE_CLARO
    return _FG_SOBRE_ESCURO


def _escurecer(cor: str, fator: float) -> str:
    """Escurece *cor* multiplicando os canais por *fator* (0–1).

    Usado para derivar ``backdrop``/``shade``/``darker-shade`` do fundo
    correspondente. Devolve ``"#808080"`` quando a cor não pode ser lida,
    para o CSS gerado nunca carregar um valor inválido.
    """
    rgb = _rgb_de_hex(cor)
    if rgb is None:
        return "#808080"
    r, g, b = (max(0, min(255, round(canal * fator))) for canal in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def _suplementar(supplementary: dict[str, str | None], *nomes: str) -> str | None:
    """Lê uma cor complementar aceitando chave com ``_`` ou ``-``.

    O catálogo usa ``card_bg`` enquanto CSS externos podem trazer
    ``card-bg``; ambas as grafias valem. Só devolve hex válido.
    """
    for nome in nomes:
        for variante in {nome, nome.replace("_", "-"), nome.replace("-", "_")}:
            cor = validar_hex(supplementary.get(variante))
            if cor is not None:
                return cor
    return None


@dataclass(frozen=True)
class Palette:
    """Paleta imutável de um tema.

    Todos os campos de cor são strings hex (ex.: ``"#1e1e2e"``) ou ``None``.
    ``is_dark_only`` marca paletas que só fazem sentido no modo escuro, para a
    interface esconder/desabilitar a opção no modo claro.
    """

    #: Identificador estável do tema (ex.: ``"catppuccin-mocha"``).
    slug: str
    #: Nome legível (ex.: ``"Catppuccin Mocha"``).
    name: str
    #: ``True`` quando a paleta é pensada apenas para o modo escuro.
    is_dark_only: bool = False
    #: Cor de fundo da janela principal.
    bg: str | None = None
    #: Cor de fundo da barra de título / barra superior.
    headerbar_bg: str | None = None
    #: Fundo sólido de destaque (vira ``--accent-bg-color``).
    accent_bg: str | None = None
    #: Destaque para texto/borda/brilho (vira ``--accent-color``).
    accent_fg: str | None = None
    #: Cores complementares (cards, bordas, brilho) usadas por previews/skin.
    supplementary: dict[str, str | None] = field(default_factory=dict)

    def css_variables(self) -> dict[str, str]:
        """Variáveis ``:root`` que esta paleta injeta no GTK.

        Somente as variáveis de destaque são emitidas, para não sobrescrever os
        fundos claros/escuros que o libadwaita e o ``style.css`` já resolvem por
        ``prefers-color-scheme``.
        """
        variaveis: dict[str, str] = {}
        if self.accent_bg:
            variaveis["--accent-bg-color"] = self.accent_bg
        accent_texto = self.accent_fg or self.accent_bg
        if accent_texto:
            variaveis["--accent-color"] = accent_texto
        return variaveis

    @property
    def modo_sugerido(self) -> str:
        """Modo natural do tema: ``"dark"`` ou ``"light"``.

        Escolher um tema no Jolven leva o esquema junto: uma paleta de fundo
        escuro pede modo escuro e vice-versa. Quando a cor do fundo não pode
        ser lida, prevalece o escuro (identidade do tema ``jolven``).
        """
        luminancia = _luminancia(self.bg or self.headerbar_bg or "")
        if luminancia is None:
            return "dark"
        return "dark" if luminancia < 0.5 else "light"

    def gtk_variables(self, modo: str) -> dict[str, str]:
        """Paleta COMPLETA do libadwaita a partir dos campos desta ``Palette``.

        Devolve as variáveis ``:root`` que pintam janela, headerbar, sidebars,
        cards, diálogos, popovers e destaques — o conjunto que o
        ``gtk_engine`` instala ao vivo no display. ``modo`` é o modo efetivo
        (``"light"`` ou ``"dark"``); qualquer outro valor é tratado como
        escuro, igual ao fallback do motor de GTK.

        Regras de derivação (determinísticas, sem GTK nesta camada):

        * Fundos: ``window``/``view``/``dialog`` usam ``bg``;
          ``headerbar``/``sidebar`` usam ``headerbar_bg``;
          ``card``/``popover``/``secondary-sidebar``/``thumbnail`` usam
          ``supplementary["card_bg"]`` com recuo para ``bg``.
        * Textos (``*-fg-color``): ``"white"`` sobre fundo escuro e
          ``"black"`` sobre fundo claro, por luminância — nunca se confia no
          fg do modo, pois o catálogo tem temas claros e escuros.
        * ``--accent-bg-color`` = ``accent_bg``; ``--accent-fg-color`` = o
          contraste sobre ele. ``--accent-color`` NÃO é emitido: o libadwaita
          deriva o acento "standalone" do NOSSO ``--accent-bg-color``
          (``oklab(from var(--accent-bg-color) ...)``), com contraste
          adequado em claro e escuro.
        * ``--border-color`` = ``supplementary["border"]``;
          ``--shade-color`` = ``rgba(0,0,0,0.36)`` no escuro e
          ``rgba(0,0,0,0.12)`` no claro.
        * ``backdrop``/``shade``/``darker-shade`` escurecem o fundo
          correspondente por fatores fixos.
        * Cores semânticas (``--destructive-*``, ``--success-*``,
          ``--warning-*``, ``--error-*``) NUNCA são emitidas: a UI exige
          respeitar as do libadwaita.
        """
        escuro = modo != "light"

        bg = validar_hex(self.bg) or (_FUNDO_ESCURO if escuro else _FUNDO_CLARO)
        headerbar_bg = validar_hex(self.headerbar_bg) or bg
        card_bg = _suplementar(self.supplementary, "card_bg", "card-bg") or bg
        border = _suplementar(self.supplementary, "border") or _escurecer(bg, 0.75)
        accent_bg = validar_hex(self.accent_bg) or _ACENTO_FALLBACK
        shade = "rgba(0, 0, 0, 0.36)" if escuro else "rgba(0, 0, 0, 0.12)"

        return {
            "--window-bg-color": bg,
            "--window-fg-color": cor_contraste(bg),
            "--view-bg-color": bg,
            "--view-fg-color": cor_contraste(bg),
            "--headerbar-bg-color": headerbar_bg,
            "--headerbar-fg-color": cor_contraste(headerbar_bg),
            "--headerbar-backdrop-color": _escurecer(headerbar_bg, 0.92),
            "--headerbar-border-color": border,
            "--headerbar-shade-color": _escurecer(headerbar_bg, 0.85),
            "--headerbar-darker-shade-color": _escurecer(headerbar_bg, 0.75),
            "--sidebar-bg-color": headerbar_bg,
            "--sidebar-fg-color": cor_contraste(headerbar_bg),
            "--sidebar-backdrop-color": _escurecer(headerbar_bg, 0.92),
            "--sidebar-border-color": border,
            "--sidebar-shade-color": _escurecer(headerbar_bg, 0.85),
            "--secondary-sidebar-bg-color": card_bg,
            "--secondary-sidebar-fg-color": cor_contraste(card_bg),
            "--secondary-sidebar-backdrop-color": _escurecer(card_bg, 0.92),
            "--secondary-sidebar-border-color": border,
            "--secondary-sidebar-shade-color": _escurecer(card_bg, 0.85),
            "--card-bg-color": card_bg,
            "--card-fg-color": cor_contraste(card_bg),
            "--card-shade-color": _escurecer(card_bg, 0.88),
            "--dialog-bg-color": bg,
            "--dialog-fg-color": cor_contraste(bg),
            "--popover-bg-color": card_bg,
            "--popover-fg-color": cor_contraste(card_bg),
            "--popover-shade-color": _escurecer(card_bg, 0.8),
            "--thumbnail-bg-color": card_bg,
            "--thumbnail-fg-color": cor_contraste(card_bg),
            "--accent-bg-color": accent_bg,
            "--accent-fg-color": cor_contraste(accent_bg),
            "--border-color": border,
            "--shade-color": shade,
        }


def _parece_escuro(cor: str | None) -> bool:
    """Heurística de luminância sRGB para inferir o modo de uma paleta."""
    if not cor:
        return False
    valor = cor.lstrip("#")
    if len(valor) in (3, 4):
        valor = "".join(caractere * 2 for caractere in valor[:3])
    try:
        vermelho = int(valor[0:2], 16)
        verde = int(valor[2:4], 16)
        azul = int(valor[4:6], 16)
    except ValueError:
        return False
    luminancia = (0.2126 * vermelho + 0.7152 * verde + 0.0722 * azul) / 255
    return luminancia < 0.2


def load_palette_from_css(caminho: Path) -> Palette | None:
    """Extrai uma :class:`Palette` de um ``.css`` mínimo de paleta.

    Lê somente valores hex (das variáveis ``--adw-*`` do Adwaita-for-Steam ou
    das ``--accent-*``/``--window-bg`` usadas pelas paletas do Jolven). Qualquer
    seletor de UI, media query ou CSS específico do Steam é ignorado — em
    nenhum caso carrega CSS do Steam no GTK. Devolve ``None`` quando o arquivo
    não pode ser lido ou não contém nenhuma cor reconhecível.
    """
    try:
        texto = caminho.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    variaveis: dict[str, str] = {}
    for nome, valor in _HEX_VAR_RE.findall(texto):
        cor = validar_hex(valor)
        if cor is not None:
            variaveis.setdefault(nome.lower(), cor)

    if not variaveis:
        return None

    bg = variaveis.get("window-bg") or variaveis.get("window") or variaveis.get("bg")
    accent_bg = variaveis.get("accent-bg") or variaveis.get("accent-bg-color")
    if bg is None and accent_bg is None:
        return None

    accent_fg = (
        variaveis.get("accent-fg")
        or variaveis.get("accent-color")
        or variaveis.get("accent")
    )
    headerbar_bg = variaveis.get("headerbar-bg")

    slug = caminho.stem
    nome = slug.replace("-", " ").replace("_", " ").title()

    return Palette(
        slug=slug,
        name=nome,
        is_dark_only=_parece_escuro(bg),
        bg=bg,
        headerbar_bg=headerbar_bg or bg,
        accent_bg=accent_bg,
        accent_fg=accent_fg,
        supplementary={
            chave: valor
            for chave, valor in variaveis.items()
            if chave not in _CAMPOS_CONHECIDOS
        },
    )

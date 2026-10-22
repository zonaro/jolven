"""Catálogo de temas do Jolven — 23 paletas + o tema padrão ``jolven``.

Módulo puro (sem GTK): a interface e o motor de CSS consultam o catálogo por
aqui. Não há registro em ``ClassVar`` privado — o catálogo é um dicionário
explícito, definido uma única vez e imutável na prática.
"""

from __future__ import annotations

import logging

from cartridges.themes.palette import Palette

# ── Definições das paletas ────────────────────────────────────────────────
#
# Cada paleta carrega a identidade do tema: fundo da janela, fundo da barra de
# título e o par de destaque (``accent_bg`` -> --accent-bg-color,
# ``accent_fg`` -> --accent-color). As cores complementares alimentam previews
# e a skin do Steam.

ADWAITA = Palette(
    slug="adwaita",
    name="Adwaita",
    is_dark_only=False,
    bg="#fafafa",
    headerbar_bg="#ffffff",
    accent_bg="#c9a7f5",
    accent_fg="#813d9c",
    supplementary={"card_bg": "#ffffff", "border": "#cccccc", "glow": "#c9a7f5"},
)

ADWAITA_GRAY = Palette(
    slug="adwaita-gray",
    name="Adwaita Gray",
    is_dark_only=False,
    bg="#252526",
    headerbar_bg="#2d2d2d",
    accent_bg="#5a5a5a",
    accent_fg="#d8d8d8",
    supplementary={"card_bg": "#2d2d2d", "border": "#5a5a5a", "glow": "#5a5a5a"},
)

BREEZE = Palette(
    slug="breeze",
    name="Breeze",
    is_dark_only=False,
    bg="#f0f9ff",
    headerbar_bg="#e8f0fe",
    accent_bg="#7da1d1",
    accent_fg="#1d3a5c",
    supplementary={"card_bg": "#ffffff", "border": "#a3c1db", "glow": "#7da1d1"},
)

CANTA = Palette(
    slug="canta",
    name="Canta",
    is_dark_only=False,
    bg="#ffffff",
    headerbar_bg="#f5f5f5",
    accent_bg="#6a5acd",
    accent_fg="#2f2a5c",
    supplementary={"card_bg": "#fafafa", "border": "#a090c0", "glow": "#6a5acd"},
)

CATPPUCCIN_FRAPPE = Palette(
    slug="catppuccin-frappe",
    name="Catppuccin Frappé",
    is_dark_only=True,
    bg="#303446",
    headerbar_bg="#292c3c",
    accent_bg="#ca9ee6",
    accent_fg="#c6d0f5",
    supplementary={"card_bg": "#414559", "border": "#51576d", "glow": "#ca9ee6"},
)

CATPPUCCIN_LATTE = Palette(
    slug="catppuccin-latte",
    name="Catppuccin Latte",
    is_dark_only=False,
    bg="#eff1f5",
    headerbar_bg="#e6e9ef",
    accent_bg="#8839ef",
    accent_fg="#4c4f69",
    supplementary={"card_bg": "#ffffff", "border": "#bcc0cc", "glow": "#8839ef"},
)

CATPPUCCIN_MACCHIATO = Palette(
    slug="catppuccin-macchiato",
    name="Catppuccin Macchiato",
    is_dark_only=True,
    bg="#24273a",
    headerbar_bg="#1e2030",
    accent_bg="#c6a0f6",
    accent_fg="#cad3f5",
    supplementary={"card_bg": "#363a4f", "border": "#494d64", "glow": "#c6a0f6"},
)

CATPPUCCIN_MOCHA = Palette(
    slug="catppuccin-mocha",
    name="Catppuccin Mocha",
    is_dark_only=True,
    bg="#1e1e2e",
    headerbar_bg="#181825",
    accent_bg="#cba6f7",
    accent_fg="#cdd6f4",
    supplementary={"card_bg": "#313244", "border": "#45475a", "glow": "#cba6f7"},
)

DRACULA = Palette(
    slug="dracula",
    name="Dracula",
    is_dark_only=True,
    bg="#282a36",
    headerbar_bg="#21222c",
    accent_bg="#bd93f9",
    accent_fg="#f8f8f2",
    supplementary={"card_bg": "#44475a", "border": "#6272a4", "glow": "#bd93f9"},
)

EVERFOREST = Palette(
    slug="everforest",
    name="Everforest",
    is_dark_only=True,
    bg="#2b3339",
    headerbar_bg="#232a2e",
    accent_bg="#a7c080",
    accent_fg="#d3c6aa",
    supplementary={"card_bg": "#333c43", "border": "#4c5b5f", "glow": "#a7c080"},
)

GRUVBOX = Palette(
    slug="gruvbox",
    name="Gruvbox",
    is_dark_only=True,
    bg="#282828",
    headerbar_bg="#1d2021",
    accent_bg="#d79921",
    accent_fg="#ebdbb2",
    supplementary={"card_bg": "#3c3836", "border": "#504945", "glow": "#d79921"},
)

KATE = Palette(
    slug="kate",
    name="Kate",
    is_dark_only=False,
    bg="#ffffff",
    headerbar_bg="#f0f0f0",
    accent_bg="#e9e4d2",
    accent_fg="#5c5c5c",
    supplementary={"card_bg": "#ffffff", "border": "#c0c0c0", "glow": "#b8a06a"},
)

METRO = Palette(
    slug="metro",
    name="Metro",
    is_dark_only=False,
    bg="#ffffff",
    headerbar_bg="#e0e0e0",
    accent_bg="#0078d7",
    accent_fg="#004578",
    supplementary={"card_bg": "#f8f8f8", "border": "#718cc2", "glow": "#0078d7"},
)

NORD = Palette(
    slug="nord",
    name="Nord",
    is_dark_only=False,
    bg="#2e3440",
    headerbar_bg="#3b4252",
    accent_bg="#88c0d0",
    accent_fg="#d8dee9",
    supplementary={"card_bg": "#3b4252", "border": "#4c566a", "glow": "#88c0d0"},
)

OLED = Palette(
    slug="oled",
    name="OLED",
    is_dark_only=True,
    bg="#000000",
    headerbar_bg="#0a0a0a",
    accent_bg="#ff6e4a",
    accent_fg="#ffb4a0",
    supplementary={"card_bg": "#111111", "border": "#222222", "glow": "#ff6e4a"},
)

ONE_DARK = Palette(
    slug="one-dark",
    name="One Dark",
    is_dark_only=True,
    bg="#282c34",
    headerbar_bg="#21252b",
    accent_bg="#61afef",
    accent_fg="#abb2bf",
    supplementary={"card_bg": "#2c3e50", "border": "#3e4451", "glow": "#61afef"},
)

POP = Palette(
    slug="pop",
    name="Pop",
    is_dark_only=False,
    bg="#fafafa",
    headerbar_bg="#f5f5f5",
    accent_bg="#7f99cf",
    accent_fg="#2b3a66",
    supplementary={"card_bg": "#ffffff", "border": "#a0b0c0", "glow": "#7f99cf"},
)

ROSE_PINE = Palette(
    slug="rose-pine",
    name="Rosé Pine",
    is_dark_only=True,
    bg="#191724",
    headerbar_bg="#1f1d2e",
    accent_bg="#ebbcba",
    accent_fg="#e0def4",
    supplementary={"card_bg": "#26233a", "border": "#403d52", "glow": "#ebbcba"},
)

TOKYO_NIGHT = Palette(
    slug="tokyo-night",
    name="Tokyo Night",
    is_dark_only=True,
    bg="#1a1b26",
    headerbar_bg="#16161e",
    accent_bg="#7aa2f7",
    accent_fg="#c0caf5",
    supplementary={"card_bg": "#24283b", "border": "#414868", "glow": "#7aa2f7"},
)

TOMORROW_NIGHT = Palette(
    slug="tomorrow-night",
    name="Tomorrow Night",
    is_dark_only=True,
    bg="#1d1f21",
    headerbar_bg="#161719",
    accent_bg="#b294bb",
    accent_fg="#c5c8c6",
    supplementary={"card_bg": "#262730", "border": "#3b3f42", "glow": "#b294bb"},
)

VAPOR = Palette(
    slug="vapor",
    name="Vapor",
    is_dark_only=False,
    bg="#f0f7ff",
    headerbar_bg="#e8eff5",
    accent_bg="#4287f5",
    accent_fg="#1b4a99",
    supplementary={"card_bg": "#ffffff", "border": "#7da1d1", "glow": "#4287f5"},
)

VGUI2 = Palette(
    slug="vgui2",
    name="VGUI2",
    is_dark_only=False,
    bg="#1e1e1e",
    headerbar_bg="#303030",
    accent_bg="#00e5a0",
    accent_fg="#a8f0d4",
    supplementary={"card_bg": "#252525", "border": "#505050", "glow": "#00e5a0"},
)

YARU = Palette(
    slug="yaru",
    name="Yaru",
    is_dark_only=False,
    bg="#fafafa",
    headerbar_bg="#f0f0f0",
    accent_bg="#5a94d7",
    accent_fg="#1c4d86",
    supplementary={"card_bg": "#ffffff", "border": "#a0b0c0", "glow": "#5a94d7"},
)

#: Identidade lilás do Jolven — espelha o ``--purple-3``/``--purple-5`` que o
#: ``data/gtk/style.css`` usava como padrão.
JOLVEN = Palette(
    slug="jolven",
    name="Jolven",
    is_dark_only=False,
    bg="#1e1e2e",
    headerbar_bg="#11111b",
    accent_bg="#c9a7f5",
    accent_fg="#813d9c",
    supplementary={"card_bg": "#252526", "border": "#404043", "glow": "#813d9c"},
)


# ── Registo explícito do catálogo ─────────────────────────────────────────

#: ``{slug: Palette}`` com todos os temas disponíveis, em ordem de exibição.
CATALOGO: dict[str, Palette] = {
    paleta.slug: paleta
    for paleta in (
        ADWAITA,
        ADWAITA_GRAY,
        BREEZE,
        CANTA,
        CATPPUCCIN_FRAPPE,
        CATPPUCCIN_LATTE,
        CATPPUCCIN_MACCHIATO,
        CATPPUCCIN_MOCHA,
        DRACULA,
        EVERFOREST,
        GRUVBOX,
        KATE,
        METRO,
        NORD,
        OLED,
        ONE_DARK,
        POP,
        ROSE_PINE,
        TOKYO_NIGHT,
        TOMORROW_NIGHT,
        VAPOR,
        VGUI2,
        YARU,
        JOLVEN,
    )
}

#: Slug do tema padrão do Jolven.
DEFAULT_SLUG: str = JOLVEN.slug


# ── API pública ───────────────────────────────────────────────────────────

def carregar_catalogo() -> dict[str, Palette]:
    """Devolve o catálogo completo ``{slug: Palette}``.

    Idempotente e sem E/S: as paletas já estão montadas em memória no import.
    """
    return CATALOGO


def obter_tema(slug: str) -> Palette:
    """Devolve a paleta de *slug*.

    Um slug desconhecido (inclusive ``None`` ou vazio) nunca derruba a
    aplicação: registra um aviso e devolve a paleta padrão ``jolven``.
    """
    paleta = CATALOGO.get(slug) if isinstance(slug, str) else None
    if paleta is None:
        logging.getLogger(__name__).warning(
            "Tema desconhecido %r — usando %s", slug, DEFAULT_SLUG
        )
        return CATALOGO[DEFAULT_SLUG]
    return paleta


def tema_padrao() -> Palette:
    """Devolve a :class:`Palette` padrão do Jolven (``jolven``)."""
    return CATALOGO[DEFAULT_SLUG]


def slug_é_dark_only(slug: str) -> bool:
    """``True`` quando o tema só funciona bem no modo escuro."""
    return obter_tema(slug).is_dark_only


def nome_do_tema(slug: str) -> str:
    """Nome legível do tema (usado em menus e toasts)."""
    return obter_tema(slug).name


def modo_do_tema(slug: str) -> str:
    """Modo natural do tema: ``"dark"`` ou ``"light"``.

    A página Aparência aplica este modo ao escolher o tema, para o esquema de
    cor acompanhar a paleta clicada.
    """
    return obter_tema(slug).modo_sugerido


# ── Aliases de compatibilidade (outras lanes já consumiam estes nomes) ────

CATALOG_SLUGS: list[str] = list(CATALOGO)
NAMES_BY_SLUG: dict[str, str] = {slug: paleta.name for slug, paleta in CATALOGO.items()}
IS_DARK_ONLY_BY_SLUG: dict[str, bool] = {
    slug: paleta.is_dark_only for slug, paleta in CATALOGO.items()
}


def get_palette(slug: str) -> Palette:
    """Alias retrocompatível de :func:`obter_tema`."""
    return obter_tema(slug)


def palette_for_mode(slug: str, mode: str) -> Palette:
    """Alias retrocompatível: devolve a paleta do tema *slug*.

    O modo não altera a identidade da paleta; o motor de GTK decide as
    variáveis efetivas a partir de ``mode``.
    """
    return obter_tema(slug)

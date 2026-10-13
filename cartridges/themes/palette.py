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

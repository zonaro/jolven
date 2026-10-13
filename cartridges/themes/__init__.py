"""Sistema de temas do Jolven.

Camadas:

* :mod:`cartridges.themes.palette` — dataclass ``Palette`` e parsing de ``.css``.
* :mod:`cartridges.themes.catalog` — registro explícito dos 23 temas + jolven.
* :mod:`cartridges.themes.gtk_engine` — aplica/remove o CSS no GTK.
* :mod:`cartridges.themes.manager` — ``ThemeManager`` (GSettings + sinais).
"""

from cartridges.themes.catalog import (
    CATALOGO,
    DEFAULT_SLUG,
    carregar_catalogo,
    nome_do_tema,
    obter_tema,
    slug_é_dark_only,
    tema_padrao,
)
from cartridges.themes.palette import Palette, load_palette_from_css, validar_hex

__all__ = [
    "CATALOGO",
    "DEFAULT_SLUG",
    "Palette",
    "carregar_catalogo",
    "load_palette_from_css",
    "nome_do_tema",
    "obter_tema",
    "slug_é_dark_only",
    "tema_padrao",
    "validar_hex",
]

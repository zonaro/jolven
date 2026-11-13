# gschema.py
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
"""Diz se um schema do GSettings existe antes de abri-lo.

``Gio.Settings.new`` com um schema ausente e fatal dentro do GLib: um
``g_error`` que aborta o processo, e nao uma excecao que o Python possa
capturar. Um ``try/except`` em volta nao protege nada.

Uma integracao opcional que dependa de schemas que nao sao nossos (o acento do
sistema, o papel de parede, os atalhos do GNOME) pergunta antes, para degradar
para o fallback em vez de derrubar o aplicativo em uma maquina que nao os tem.
"""

from __future__ import annotations


def schema_available(schema_id: str) -> bool:
    """True quando ``schema_id`` esta instalado nesta maquina.

    Sem ``gi`` disponivel a resposta e False: quem chama segue pelo mesmo
    caminho de fallback de uma maquina sem o schema.
    """
    try:
        from gi.repository import Gio  # noqa: PLC0415

        source = Gio.SettingsSchemaSource.get_default()
        return bool(source is not None and source.lookup(schema_id, True))
    except Exception:  # pylint: disable=broad-exception-caught
        return False

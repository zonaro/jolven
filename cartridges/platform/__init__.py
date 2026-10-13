# __init__.py
#
# Copyright 2026 zonaro
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

"""Primitivas que mudam entre plataformas.

Camada de baixo nivel e **sem `gi`**: cada modulo expoe a mesma interface no
Linux e no Windows. So o que realmente diverge mora aqui; o modo de execucao
continua em `cartridges.runtime` e nao deve ser reimplementado.
"""

from __future__ import annotations

import os
import sys

IS_WINDOWS = os.name == "nt"
IS_LINUX = sys.platform.startswith("linux")

__all__ = ["IS_WINDOWS", "IS_LINUX"]

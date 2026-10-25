# system_integration.py
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

"""Resolução dos helpers privilegiados a partir das policies polkit.

Camada de baixo nível e **sem ``gi``**: só ``pathlib``, ``os`` e XML da
stdlib. As actions polkit do Jolven seguem ``auth_admin_keep`` e anotam
``org.freedesktop.policykit.exec.path`` com o binário autorizado. O
``pkexec`` NÃO valida a propriedade desse binário: se o app executasse um
helper num caminho gravável pelo usuário (``~/.local/libexec/...``),
qualquer processo do usuário poderia sobrescrevê-lo e obter root dentro
da janela do ``keep``.

Por isso o ÚNICO caminho privilegiado aceitável é o ``exec_path``
declarado na policy instalada no sistema (``helper_for``): policy ou
binário ausente significa recurso indisponível (fail-closed), nunca a
execução de um caminho derivado do prefixo de instalação.

Todas as leituras são tolerantes a erro: diretório/arquivo ilegível ou
XML quebrado resulta em ``None``, nunca em exceção.
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path

GAME_MODE_ACTION_ID = "io.github.zonaro.Jolven.configure-game-mode"

EXEC_PATH_ANNOTATION = "org.freedesktop.policykit.exec.path"

# Diretórios que o polkitd realmente lê, nesta ordem. Atributo de módulo
# (não constante imutável) para que testes o substituam por diretórios
# temporários. Mesma fonte usada por `authentication.policy_installed`.
POLKIT_ACTION_DIRS: tuple[Path, ...] = (
    Path("/usr/local/share/polkit-1/actions"),
    Path("/usr/share/polkit-1/actions"),
    Path("/etc/polkit-1/actions"),
    Path("/run/polkit-1/actions"),
)

__all__ = [
    "EXEC_PATH_ANNOTATION",
    "GAME_MODE_ACTION_ID",
    "POLKIT_ACTION_DIRS",
    "exec_path",
    "find_policy",
    "helper_for",
    "unavailable_message",
]


def _iter_policy_files() -> Iterator[Path]:
    """Arquivos ``*.policy`` dos diretórios do polkitd, em ordem."""
    for directory in POLKIT_ACTION_DIRS:
        try:
            candidates = sorted(directory.glob("*.policy"))
        except OSError:
            continue
        yield from candidates


def _local(tag: str) -> str:
    """Nome local de uma tag, ignorando namespace eventual."""
    return tag.rsplit("}", 1)[-1]


def _actions_in(policy_file: Path) -> list[ET.Element]:
    """Elementos ``<action>`` do arquivo; lista vazia em qualquer erro."""
    try:
        text = policy_file.read_text(encoding="utf-8")
    except (OSError, ValueError, UnicodeDecodeError):
        return []
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    return [el for el in root.iter() if _local(el.tag) == "action"]


def _locate(action_id: str) -> tuple[Path, ET.Element] | None:
    """``(arquivo, elemento)`` da action; ``None`` quando não declarada."""
    if not action_id:
        return None
    for candidate in _iter_policy_files():
        for action in _actions_in(candidate):
            try:
                if action.get("id") == action_id:
                    return (candidate, action)
            except (AttributeError, ValueError):
                continue
    return None


def find_policy(action_id: str) -> Path | None:
    """Primeiro arquivo de policy que declara aquele ``action id``.

    Não confia no nome do arquivo: parseia o conteúdo (o arquivo pode se
    chamar ``...Devel.ConfigureGameMode.policy`` enquanto a action id é a base).
    ``None`` quando ausente ou ilegível.
    """
    located = _locate(action_id)
    return located[0] if located is not None else None


def exec_path(action_id: str) -> Path | None:
    """Valor da anotação ``org.freedesktop.policykit.exec.path`` da action.

    ``None`` quando a policy/action/anotação não existe ou está ilegível.
    """
    located = _locate(action_id)
    if located is None:
        return None
    _policy_file, action = located
    try:
        annotates = [
            el for el in action if _local(el.tag) == "annotate"
        ]
    except (AttributeError, ValueError):
        return None
    for annotate in annotates:
        try:
            if annotate.get("key") != EXEC_PATH_ANNOTATION:
                continue
            raw = (annotate.text or "").strip()
        except (AttributeError, ValueError):
            continue
        if raw:
            return Path(raw)
    return None


def helper_for(action_id: str) -> Path | None:
    """O ``exec_path`` resolvido SE seguro para ``pkexec``; senão ``None``.

    Este é o ÚNICO caminho privilegiado aceitável para ``pkexec``. O
    caminho só é aceito se existir, for executável e NÃO for gravável
    pelo usuário que invoca o app (``not os.access(path, os.W_OK)``).
    Num install correto o helper pertence a root com modo 0755, então o
    usuário do app não tem permissão de escrita; se tiver, a integração
    está comprometida e o certo é fail-closed (recurso indisponível).

    Esta checagem é defesa em profundidade: a garantia autoritativa é o
    helper ser root-owned, instalado pelo ``install.sh`` — o ``pkexec``
    não valida propriedade, então sem este filtro o app executaria como
    root um arquivo sob controle do usuário.
    """
    path = exec_path(action_id)
    if path is None:
        return None
    try:
        if (
            path.is_file()
            and os.access(path, os.X_OK)
            and not os.access(path, os.W_OK)
        ):
            return path
    except (OSError, ValueError):
        return None
    return None


def unavailable_message() -> str:
    """Texto da indisponibilidade da integração de sistema.

    Fonte única para a UI: nunca orienta a rodar script.
    """
    return _("Integração de sistema ausente — reinstale o Jolven")

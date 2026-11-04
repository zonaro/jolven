# file_hash.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Hash de ficheiros para identidade canônica de jogos (Taiga F1).

Permite reconhecer o mesmo jogo vindo de fontes diferentes (Steam, Heroic,
Flatpak, AppImage, …) mesmo que o título ou o caminho do executável mudem,
comparando o hash do ficheiro de instalação e, quando disponível, o número de
série do jogo.
"""

import hashlib
from pathlib import Path
from typing import Optional

# Lê o ficheiro em blocos para não carregar inteiros na memória de jogos
# grandes (dezenas de GB).
_BLOCK_SIZE = 1 << 20  # 1 MiB


def sha256_of_file(path: Path) -> Optional[str]:
    """Devolve o SHA-256 do ficheiro, ou ``None`` se não puder ser lido."""
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(_BLOCK_SIZE), b""):
                digest.update(block)
        return digest.hexdigest()
    except (OSError, PermissionError):
        return None


def sha256_of_first_matching(
    paths: list[Path],
    extensions: tuple[str, ...] = (".exe", ".bin", ".app", ".x86_64"),
) -> Optional[str]:
    """Devolve o SHA-256 do primeiro ficheiro existente entre *paths*.

    Útil quando a fonte sabe a lista de candidatos (executável principal,
    binário do jogo, …) mas não tem um caminho único garantido.
    """
    for path in paths:
        if path.is_file():
            return sha256_of_file(path)
    return None

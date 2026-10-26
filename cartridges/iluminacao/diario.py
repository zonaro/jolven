# diario.py
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

"""O diário da sessão: o que a iluminação mostrava antes do Jolven mexer.

Existe em disco, e não só em memória, pela mesma razão que o estado das fitas
mora no GSettings: o app morto no meio de uma sessão (queda de energia, kill,
travamento) deixaria os periféricos vestindo a cor de um jogo que já acabou, e
só o arranque seguinte pode desfazer isso.

O arquivo guarda **estados**, nunca planos:

```json
{
  "schema_version": 1,
  "sessao": "…",
  "iniciado": 1761000000,
  "ativos": [{"jogo": "…", "perfil": "…", "fitas": true}],
  "base": {"openrgb:…": {"provedor": "openrgb", "chave": "…", …}}
}
```

``base`` é capturado uma vez por dispositivo, na primeira vez que uma sessão o
toca, e é o alvo da devolução. ``ativos`` é a pilha de jogos: quando o último
sai, ``base`` é reaplicado e o arquivo é apagado.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from cartridges.iluminacao.modelo import Estado

#: Versão do formato.
VERSAO = 1

#: Nome do arquivo dentro de ``shared.iluminacao_dir``.
ARQUIVO = "sessao.json"


def caminho_padrao() -> Path:
    from cartridges import shared  # noqa: PLC0415

    return shared.iluminacao_dir / ARQUIVO


@dataclass
class Ativo:
    """Um jogo usando a iluminação agora, e se ele tomou as fitas Tuya."""

    jogo: str
    perfil: str = ""
    fitas: bool = False

    def para_json(self) -> dict[str, Any]:
        return {"jogo": self.jogo, "perfil": self.perfil, "fitas": self.fitas}

    @classmethod
    def de_json(cls, dados: object) -> Optional["Ativo"]:
        if not isinstance(dados, dict):
            return None
        jogo = str(dados.get("jogo", "")).strip()
        if not jogo:
            return None
        return cls(jogo, str(dados.get("perfil", "")), bool(dados.get("fitas", False)))


@dataclass
class Diario:
    """O conteúdo do arquivo, já validado."""

    sessao: str = ""
    iniciado: float = 0.0
    ativos: list[Ativo] = field(default_factory=list)
    base: dict[str, Estado] = field(default_factory=dict)

    @property
    def pendente(self) -> bool:
        return bool(self.base)

    def estado(self, identificador: str) -> Optional[Estado]:
        return self.base.get(identificador)

    def guardar_base(self, estado: Estado) -> None:
        """Grava o estado de antes, sem sobrescrever um já gravado.

        O primeiro estado é o único que vale: o segundo seria a cor que o
        próprio Jolven acabou de pintar, e a devolução deixaria o dispositivo
        com a cor do jogo para sempre.
        """
        self.base.setdefault(estado.identificador, estado)

    def jogo_ativo(self, jogo: str) -> Optional[Ativo]:
        for ativo in self.ativos:
            if ativo.jogo == jogo:
                return ativo
        return None

    def para_json(self) -> dict[str, Any]:
        return {
            "schema_version": VERSAO,
            "sessao": self.sessao,
            "iniciado": self.iniciado,
            "ativos": [ativo.para_json() for ativo in self.ativos],
            "base": {chave: estado.para_json() for chave, estado in self.base.items()},
        }

    @classmethod
    def de_json(cls, dados: object) -> Optional["Diario"]:
        if not isinstance(dados, dict):
            return None
        base: dict[str, Estado] = {}
        bruto = dados.get("base")
        if isinstance(bruto, dict):
            for chave, item in bruto.items():
                estado = Estado.de_json(item)
                if estado is not None:
                    base[str(chave)] = estado
        ativos: list[Ativo] = []
        bruto_ativos = dados.get("ativos")
        if isinstance(bruto_ativos, list):
            for item in bruto_ativos:
                ativo = Ativo.de_json(item)
                if ativo is not None:
                    ativos.append(ativo)
        return cls(
            sessao=str(dados.get("sessao", "")),
            iniciado=_numero(dados.get("iniciado")),
            ativos=ativos,
            base=base,
        )


def _numero(valor: object) -> float:
    try:
        return float(valor)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


class Arquivo:
    """Leitura e escrita do diário. Atômica, como a dos perfis."""

    def __init__(self, caminho: Optional[Path] = None) -> None:
        self._caminho = caminho

    @property
    def caminho(self) -> Path:
        return self._caminho or caminho_padrao()

    def ler(self) -> Diario:
        """O diário em disco. Sem arquivo (ou ilegível) devolve um vazio.

        Ilegível não pode virar exceção: o arranque do app chama isto antes de
        qualquer janela, e um JSON torto não pode impedir o Jolven de abrir.
        """
        caminho = self.caminho
        try:
            texto = caminho.read_text(encoding="utf-8")
        except FileNotFoundError:
            return Diario()
        except OSError as erro:
            logging.warning("Diário de iluminação ilegível (%s): %s", caminho, erro)
            return Diario()
        try:
            dados = json.loads(texto)
        except ValueError as erro:
            logging.warning("Diário de iluminação com JSON inválido: %s", erro)
            return Diario()
        diario = Diario.de_json(dados)
        if diario is None:
            return Diario()
        if not diario.sessao:
            diario.sessao = uuid.uuid4().hex
        if not diario.iniciado:
            diario.iniciado = time.time()
        return diario

    def gravar(self, diario: Diario) -> bool:
        """Grava o diário. Devolve se conseguiu; nunca levanta."""
        if not diario.sessao:
            diario.sessao = uuid.uuid4().hex
        if not diario.iniciado:
            diario.iniciado = time.time()
        caminho = self.caminho
        temporario = caminho.with_name(caminho.name + ".tmp")
        try:
            caminho.parent.mkdir(parents=True, exist_ok=True)
            temporario.write_text(
                json.dumps(diario.para_json(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporario.replace(caminho)
        except OSError as erro:
            logging.warning("Não foi possível gravar o diário de iluminação: %s", erro)
            try:
                temporario.unlink(missing_ok=True)
            except OSError:
                pass
            return False
        return True

    def limpar(self) -> None:
        """Apaga o diário. Sem diário não há troca pendente."""
        try:
            self.caminho.unlink(missing_ok=True)
        except OSError as erro:
            logging.warning("Não foi possível apagar o diário de iluminação: %s", erro)

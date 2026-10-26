# perfis.py
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

"""Os perfis de iluminação: o que cada jogo veste, e não o hardware em si.

O arquivo é ``iluminacao/perfis.json`` dentro da pasta de dados do Jolven:

```json
{
  "schema_version": 1,
  "perfis": [
    {
      "id": "6f0c...",
      "nome": "WASD roxo",
      "descricao": "",
      "criado": 1761000000,
      "alterado": 1761000000,
      "dispositivos": [
        {"provedor": "openrgb", "chave": "...", "zonas": [...]},
        {"provedor": "tuya", "chave": "...", "cor": "#9141ac", "brilho": 40}
      ]
    }
  ]
}
```

Três garantias que valem o código extra:

* **Escrita atômica.** Temporário + ``replace``. Um perfil perdido no meio de
  uma gravação custa horas de configuração, e a sessão do jogo não pode
  esperar por isso.
* **Campos desconhecidos sobrevivem.** Versão mais nova do Jolven, ou uma
  chave escrita à mão, não pode perder dados ao ser regravada por esta versão.
  Por isso cada perfil e cada plano guardam o que não reconhecem e devolvem
  intacto.
* **Arquivo ilegível não é apagado.** Antes da primeira gravação depois de uma
  leitura com erro, o original é copiado para ``perfis.json.corrompido``. Sem
  isso, o primeiro "salvar" transformaria um JSON torto em "nenhum perfil".
"""

from __future__ import annotations

import json
import logging
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from cartridges.iluminacao.modelo import Plano

#: Versão do formato deste arquivo. Só sobe quando uma versão antiga do Jolven
#: não puder ler o arquivo sem entender errado — campo novo opcional não conta.
VERSAO = 1

#: Nome do arquivo dentro de ``shared.iluminacao_dir``.
ARQUIVO = "perfis.json"

#: Cópia de segurança de um arquivo que não pôde ser lido.
ARQUIVO_CORROMPIDO = "perfis.json.corrompido"


def caminho_padrao() -> Path:
    """O caminho real do arquivo, resolvido tarde para os testes poderem
    trabalhar sem GSettings nem a pasta do usuário."""
    from cartridges import shared  # noqa: PLC0415

    return shared.iluminacao_dir / ARQUIVO


@dataclass
class Perfil:
    """Um conjunto nomeado de planos: o que o jogo veste."""

    id: str
    nome: str
    descricao: str = ""
    criado: float = 0.0
    alterado: float = 0.0
    dispositivos: list[Plano] = field(default_factory=list)
    extras: dict[str, Any] = field(default_factory=dict)

    # -- consulta ----------------------------------------------------

    def por_chave(self) -> dict[str, Plano]:
        """Planos indexados por ``provedor:chave``."""
        return {plano.identificador: plano for plano in self.dispositivos}

    def plano(self, identificador: str) -> Optional[Plano]:
        for plano in self.dispositivos:
            if plano.identificador == identificador:
                return plano
        return None

    def definir(self, plano: Plano) -> None:
        """Grava o plano do dispositivo, substituindo o que houver."""
        for indice, existente in enumerate(self.dispositivos):
            if existente.identificador == plano.identificador:
                self.dispositivos[indice] = plano
                return
        self.dispositivos.append(plano)

    def remover(self, identificador: str) -> bool:
        antes = len(self.dispositivos)
        self.dispositivos = [
            plano for plano in self.dispositivos if plano.identificador != identificador
        ]
        return len(self.dispositivos) != antes

    def usa(self, provedor: str) -> bool:
        return any(plano.provedor == provedor for plano in self.dispositivos)

    @property
    def vazio(self) -> bool:
        return not self.dispositivos

    def tocar(self) -> None:
        self.alterado = time.time()

    # -- JSON --------------------------------------------------------

    def para_json(self) -> dict[str, Any]:
        dados: dict[str, Any] = {
            "id": self.id,
            "nome": self.nome,
            "descricao": self.descricao,
            "criado": self.criado,
            "alterado": self.alterado,
            "dispositivos": [plano.para_json() for plano in self.dispositivos],
        }
        dados.update(self.extras)
        return dados

    @classmethod
    def de_json(cls, dados: object) -> Optional["Perfil"]:
        if not isinstance(dados, dict):
            return None
        identificador = str(dados.get("id", "")).strip()
        nome = str(dados.get("nome", "")).strip()
        if not identificador or not nome:
            return None
        planos: list[Plano] = []
        bruto = dados.get("dispositivos")
        if isinstance(bruto, list):
            for item in bruto:
                plano = Plano.de_json(item)
                if plano is not None:
                    planos.append(plano)
        conhecidos = {"id", "nome", "descricao", "criado", "alterado", "dispositivos"}
        extras = {chave: valor for chave, valor in dados.items() if chave not in conhecidos}
        return cls(
            id=identificador,
            nome=nome,
            descricao=str(dados.get("descricao", "")),
            criado=_numero(dados.get("criado")),
            alterado=_numero(dados.get("alterado")),
            dispositivos=planos,
            extras=extras,
        )


def _numero(valor: object) -> float:
    try:
        return float(valor)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


class Repositorio:
    """Leitura e escrita dos perfis, sem GTK e sem estado global.

    Uma instância por uso (a UI cria a sua, o coordenador cria a dele). Não há
    cache: o arquivo é pequeno, e reler sempre faz uma edição externa ou uma
    restauração de backup aparecer sem reiniciar o app.
    """

    def __init__(self, caminho: Optional[Path] = None) -> None:
        self._caminho = caminho
        self._corrompido_preservado = False

    @property
    def caminho(self) -> Path:
        return self._caminho or caminho_padrao()

    # -- leitura -----------------------------------------------------

    def carregar(self) -> list[Perfil]:
        """Todos os perfis, do arquivo. Lista vazia quando não há arquivo.

        Arquivo ilegível também devolve lista vazia, mas deixa o original
        copiado antes de qualquer gravação (ver :meth:`salvar`).
        """
        caminho = self.caminho
        try:
            texto = caminho.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        except OSError as erro:
            logging.warning("Perfis de iluminação ilegíveis (%s): %s", caminho, erro)
            self._corrompido_preservado = True
            return []
        try:
            dados = json.loads(texto)
        except ValueError as erro:
            logging.warning("Perfis de iluminação com JSON inválido: %s", erro)
            self._preservar_corrompido(caminho)
            return []
        if not isinstance(dados, dict):
            self._preservar_corrompido(caminho)
            return []
        versao = dados.get("schema_version")
        if isinstance(versao, int) and versao > VERSAO:
            logging.warning(
                "Perfis de iluminação na versão %s; esta versão do Jolven entende %s",
                versao,
                VERSAO,
            )
        brutos = dados.get("perfis")
        if not isinstance(brutos, list):
            return []
        perfis = [Perfil.de_json(item) for item in brutos]
        return [perfil for perfil in perfis if perfil is not None]

    def obter(self, identificador: str) -> Optional[Perfil]:
        for perfil in self.carregar():
            if perfil.id == identificador:
                return perfil
        return None

    # -- escrita -----------------------------------------------------

    def salvar(self, perfis: Iterable[Perfil]) -> bool:
        """Grava a lista inteira. Devolve se conseguiu; nunca levanta."""
        caminho = self.caminho
        if self._corrompido_preservado:
            self._preservar_corrompido(caminho)
        dados = {
            "schema_version": VERSAO,
            "perfis": [perfil.para_json() for perfil in perfis],
        }
        temporario = caminho.with_name(caminho.name + ".tmp")
        try:
            caminho.parent.mkdir(parents=True, exist_ok=True)
            temporario.write_text(
                json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            temporario.replace(caminho)
        except OSError as erro:
            logging.warning(
                "Não foi possível gravar %s: %s", caminho.name, erro
            )
            try:
                temporario.unlink(missing_ok=True)
            except OSError:
                pass
            return False
        self._corrompido_preservado = False
        return True

    def _preservar_corrompido(self, caminho: Path) -> None:
        """Guarda uma cópia do arquivo que não deu para ler, uma vez só."""
        if self._corrompido_preservado:
            return
        if not caminho.is_file():
            self._corrompido_preservado = True
            return
        destino = caminho.with_name(ARQUIVO_CORROMPIDO)
        try:
            shutil.copy2(caminho, destino)
            logging.warning("Cópia dos perfis ilegíveis guardada em %s", destino)
        except OSError as erro:
            logging.warning("Não foi possível guardar a cópia dos perfis: %s", erro)
        self._corrompido_preservado = True

    # -- operações ---------------------------------------------------

    def criar(self, nome: str) -> Perfil:
        """Um perfil novo, ainda não gravado."""
        agora = time.time()
        return Perfil(id=uuid.uuid4().hex, nome=nome.strip(), criado=agora, alterado=agora)

    def duplicar(self, identificador: str, nome: Optional[str] = None) -> Optional[Perfil]:
        original = self.obter(identificador)
        if original is None:
            return None
        agora = time.time()
        copia = Perfil(
            id=uuid.uuid4().hex,
            nome=(nome or _nome_de_copia(original.nome)).strip(),
            descricao=original.descricao,
            criado=agora,
            alterado=agora,
            dispositivos=[
                Plano.de_json(plano.para_json()) or plano
                for plano in original.dispositivos
            ],
            extras=dict(original.extras),
        )
        perfis = self.carregar()
        perfis.append(copia)
        return copia if self.salvar(perfis) else None

    def renomear(self, identificador: str, nome: str) -> bool:
        limpo = nome.strip()
        if not limpo:
            return False
        perfis = self.carregar()
        for perfil in perfis:
            if perfil.id == identificador:
                perfil.nome = limpo
                perfil.tocar()
                return self.salvar(perfis)
        return False

    def excluir(self, identificador: str) -> bool:
        perfis = self.carregar()
        restantes = [perfil for perfil in perfis if perfil.id != identificador]
        if len(restantes) == len(perfis):
            return False
        return self.salvar(restantes)

    def gravar(self, perfil: Perfil) -> bool:
        """Grava um perfil, criando ou substituindo pelo id."""
        perfil.tocar()
        perfis = self.carregar()
        for indice, existente in enumerate(perfis):
            if existente.id == perfil.id:
                perfis[indice] = perfil
                break
        else:
            perfis.append(perfil)
        return self.salvar(perfis)

    def nome_em_uso(self, nome: str, ignorar: str = "") -> bool:
        alvo = nome.strip().casefold()
        return any(
            perfil.nome.strip().casefold() == alvo and perfil.id != ignorar
            for perfil in self.carregar()
        )


def _nome_de_copia(nome: str) -> str:
    """``Perfil`` -> ``Perfil (cópia)``, sem acumular sufixos."""
    base = nome.strip() or "Perfil"
    if base.endswith(" (cópia)"):
        return base
    return f"{base} (cópia)"

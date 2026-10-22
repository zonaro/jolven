# sunshine_servico.py
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

"""Liga/desliga o autostart do Sunshine via systemd de usuario.

O nome da unidade NAO e fixado: o empacotamento do LizardByte usa o AppId
(``app-dev.lizardbyte.app.Sunshine.service``) em versoes recentes e
``sunshine.service`` em outras. Por isso a unidade e descoberta listando
as unidades de usuario e validando o ``ExecStart`` de cada candidata.

Este modulo e propositalmente puro (pathlib/subprocess/shutil/typing,
sem gi) e nunca levanta para a UI: indisponibilidade vira ``None``,
``False`` ou ``(False, mensagem)``. Todas as funcoes que falam com o
systemd sao bloqueantes; a UI deve chama-las em worker.

A fonte autoritativa do estado e o proprio systemd; nao ha chave de
GSettings aqui.
"""

from __future__ import annotations

import re
import shutil
import subprocess

from pathlib import Path
from typing import Sequence

#: Alias historico do Sunshine. Usado como ultimo recurso (quando a
#: listagem de unidades falha) e como nome da unidade criada pelo Jolven
#: no fallback, nunca como nome fixo da unidade do distro.
UNIDADE_ALIAS = "sunshine.service"

#: Marcador que identifica a unidade criada pelo Jolven. Um arquivo
#: existente sem esse marcador nunca e sobrescrito (pode ser do usuario
#: ou do distro).
_MARCADOR_JOLVEN = "X-Jolven-Managed=true"

_TIMEOUT_SEGUNDOS = 15

_CAMINHO_EXEC_RE = re.compile(r"path=([^ ;}]+)")


def _systemctl() -> str | None:
    """O caminho do systemctl, ou None quando indisponivel."""
    return shutil.which("systemctl")


def _executar(
    argv: Sequence[str],
    timeout: int = _TIMEOUT_SEGUNDOS,
) -> subprocess.CompletedProcess[str] | None:
    """Roda um comando e devolve o resultado, ou None em qualquer falha.

    Ponto de costura para os testes: substitua esta funcao para simular
    o systemd sem tocar na maquina.
    """
    try:
        return subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def binario_sunshine() -> Path | None:
    """O caminho do binario do Sunshine, ou None quando ausente."""
    caminho = shutil.which("sunshine")
    return Path(caminho) if caminho else None


def _caminhos_execstart(saida: str) -> list[str]:
    """Extrai os executaveis de uma saida de ``show -p ExecStart``."""
    caminhos: list[str] = []
    for linha in saida.splitlines():
        if not linha.startswith("ExecStart="):
            continue
        valor = linha.partition("=")[2].strip()
        if not valor:
            continue
        achados = _CAMINHO_EXEC_RE.findall(valor)
        if achados:
            caminhos.extend(achados)
            continue
        # Formato simples sem chaves (``ExecStart=/caminho ...``):
        # primeiro token, sem prefixos do systemd (-!:+@?).
        primeiro = valor.split()[0].lstrip("-!: +@?")
        if primeiro:
            caminhos.append(primeiro)
    return caminhos


def _execstart_e_sunshine(saida: str, binario: Path | None) -> bool:
    """Diz se algum ExecStart aponta para o binario do Sunshine."""
    for bruto in _caminhos_execstart(saida):
        try:
            caminho = Path(bruto)
        except (OSError, ValueError):
            continue
        if caminho.name != "sunshine":
            continue
        if binario is None:
            return True
        if caminho == binario:
            return True
        try:
            if caminho.resolve() == binario.resolve():
                return True
        except OSError:
            # Sem como comparar no disco: o nome ja basta.
            return True
    return False


def _validar_unidade(
    systemctl: str, unidade: str, binario: Path | None
) -> bool:
    """Diz se ``unidade`` existe e tem ExecStart do Sunshine."""
    resultado = _executar([systemctl, "--user", "show", "-p", "ExecStart", unidade])
    if resultado is None:
        return False
    return _execstart_e_sunshine(resultado.stdout, binario)


def _listar_candidatas(systemctl: str) -> list[str] | None:
    """Nomes de unidades de usuario com "sunshine" no nome.

    Devolve None quando a listagem falha (o chamador tenta o alias).
    """
    resultado = _executar(
        [systemctl, "--user", "list-unit-files", "--type=service", "--no-legend"]
    )
    if resultado is None or resultado.returncode != 0:
        return None
    candidatas: list[str] = []
    for linha in resultado.stdout.splitlines():
        partes = linha.split()
        if not partes:
            continue
        nome = partes[0]
        if "sunshine" in nome.lower():
            candidatas.append(nome)
    return candidatas


def _caminho_unidade_jolven() -> Path:
    """Onde o fallback do Jolven cria a unidade (nunca um caminho fixo)."""
    return Path.home() / ".config" / "systemd" / "user" / UNIDADE_ALIAS


def _arquivo_tem_marcador(caminho: Path) -> bool:
    """Diz se o arquivo contem o marcador de unidade gerenciada."""
    try:
        return _MARCADOR_JOLVEN in caminho.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return False


def _unidade_e_jolven(unidade: str) -> bool:
    """Diz se ``unidade`` e a criada pelo Jolven (tem o marcador)."""
    if unidade != UNIDADE_ALIAS:
        return False
    return _arquivo_tem_marcador(_caminho_unidade_jolven())


def unidade_sunshine() -> str | None:
    """O nome da unidade de usuario do Sunshine, ou None.

    Lista as unidades, valida o ExecStart de cada candidata e prefere
    uma unidade do distro a criada pelo Jolven. Nunca levanta.
    """
    systemctl = _systemctl()
    if systemctl is None:
        return None
    try:
        binario = binario_sunshine()
        candidatas = _listar_candidatas(systemctl)
        if candidatas is not None:
            validadas = [
                nome
                for nome in candidatas
                if _validar_unidade(systemctl, nome, binario)
            ]
            for nome in validadas:
                if not _unidade_e_jolven(nome):
                    return nome
            if validadas:
                return validadas[0]
            return None
        # A listagem falhou: ultima chance e o alias historico.
        if _validar_unidade(systemctl, UNIDADE_ALIAS, binario):
            return UNIDADE_ALIAS
        return None
    except Exception:  # Nunca estoura para a UI.
        return None


def autostart_disponivel() -> bool:
    """Diz se da para gerenciar o autostart (ha unidade OU binario)."""
    try:
        if _systemctl() is None:
            return False
        return unidade_sunshine() is not None or binario_sunshine() is not None
    except Exception:
        return False


def autostart_habilitado() -> bool:
    """Diz se o autostart esta ativo. Erro/indisponibilidade e False."""
    try:
        systemctl = _systemctl()
        if systemctl is None:
            return False
        unidade = unidade_sunshine()
        if unidade is None:
            return False
        resultado = _executar([systemctl, "--user", "is-enabled", unidade])
        if resultado is None:
            return False
        return (
            resultado.returncode == 0
            and resultado.stdout.strip() == "enabled"
        )
    except Exception:
        return False


def _resumir_erro(resultado: subprocess.CompletedProcess[str]) -> str:
    """Primeira linha util do stderr, curta e de uma linha so."""
    for linha in (resultado.stderr or "").splitlines():
        limpa = " ".join(linha.split())
        if limpa:
            return limpa[:200]
    return ""


def _criar_unidade_jolven(
    systemctl: str, binario: Path
) -> tuple[str | None, str]:
    """Cria a unidade de fallback gerenciada pelo Jolven.

    So chamada quando nenhuma unidade do Sunshine existe. Nunca
    sobrescreve um arquivo existente sem o marcador.
    """
    destino = _caminho_unidade_jolven()
    try:
        if destino.exists():
            if not _arquivo_tem_marcador(destino):
                return None, _(
                    "Já existe um arquivo de autostart do Sunshine que "
                    "não foi criado pelo Jolven; nada foi alterado."
                )
        else:
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(
                "# X-Jolven-Managed=true\n"
                "[Unit]\n"
                "Description=Sunshine (autostart gerenciado pelo Jolven)\n"
                "After=graphical-session.target\n"
                "[Service]\n"
                f"ExecStart={binario}\n"
                "Restart=on-failure\n"
                "[Install]\n"
                "WantedBy=default.target\n",
                encoding="utf-8",
            )
    except OSError:
        return None, _(
            "Não foi possível criar o autostart do Sunshine "
            "na pasta do usuário."
        )
    _executar([systemctl, "--user", "daemon-reload"])
    return UNIDADE_ALIAS, ""


def _mensagem_falha(ativar: bool) -> str:
    """Mensagem generica de falha do enable/disable, sem detalhe."""
    if ativar:
        return _("Não foi possível ativar o autostart do Sunshine.")
    return _("Não foi possível desativar o autostart do Sunshine.")


def _aplicar_acao(systemctl: str, verbo: str, unidade: str) -> tuple[bool, str]:
    """Roda ``systemctl --user enable|disable <unidade>``.

    ``verbo`` e ``"enable"`` ou ``"disable"``. Devolve ``(ok, mensagem)``
    em pt-BR e nunca levanta.
    """
    ativar = verbo == "enable"
    if ativar:
        com_detalhe = _("Não foi possível ativar o autostart do Sunshine: {}")
        concluido = _("Autostart do Sunshine ativado.")
    else:
        com_detalhe = _("Não foi possível desativar o autostart do Sunshine: {}")
        concluido = _("Autostart do Sunshine desativado.")
    resultado = _executar([systemctl, "--user", verbo, unidade])
    if resultado is None:
        return False, _mensagem_falha(ativar)
    if resultado.returncode != 0:
        detalhe = _resumir_erro(resultado)
        if detalhe:
            return False, com_detalhe.format(detalhe)
        return False, _mensagem_falha(ativar)
    return True, concluido


def definir_autostart(habilitar: bool) -> tuple[bool, str]:
    """Liga/desliga o autostart. Bloqueante: chamar em worker.

    Devolve ``(ok, mensagem)`` em pt-BR, nunca levanta.
    """
    try:
        systemctl = _systemctl()
        if systemctl is None:
            return False, _(
                "O autostart do Sunshine não está disponível "
                "neste sistema."
            )
        if habilitar:
            unidade = unidade_sunshine()
            if unidade is None:
                binario = binario_sunshine()
                if binario is None:
                    return False, _(
                        "O Sunshine não foi encontrado; não é possível "
                        "ativar o autostart."
                    )
                unidade, erro = _criar_unidade_jolven(systemctl, binario)
                if unidade is None:
                    return False, erro
            return _aplicar_acao(systemctl, "enable", unidade)
        unidade = unidade_sunshine()
        if unidade is None:
            return False, _(
                "Não há autostart do Sunshine para desativar."
            )
        return _aplicar_acao(systemctl, "disable", unidade)
    except Exception:
        return False, _mensagem_falha(habilitar)

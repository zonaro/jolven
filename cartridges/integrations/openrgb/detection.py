# detection.py
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

"""Descobrir se o OpenRGB está instalado e se o servidor responde.

Nada aqui toca GTK: a página de Integrações, as Preferências e o coordenador
de iluminação chamam estas funções de threads de trabalho, onde abrir soquete
ou rodar ``flatpak info`` é aceitável e no thread principal não seria.

A ordem de detecção é a de :mod:`cartridges.utils.integrations`: binário
nativo primeiro, Flatpak depois. Um Flatpak do OpenRGB compartilha o
``localhost`` do sistema (o sandbox não separa a rede por padrão), então o
servidor dele é alcançável do Jolven nativo; o que muda é o comando usado
para iniciá-lo.
"""

from __future__ import annotations

import logging
import shutil
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from cartridges.integrations.openrgb import protocol
from cartridges.launchers import flatpak_installed

#: Id na Flathub. É o mesmo que a página de Integrações oferece para instalar.
FLATPAK_ID = "org.openrgb.OpenRGB"

#: Binário nativo procurado no ``PATH``.
BINARIO = "openrgb"

#: ``instalacao`` results, iguais aos de ``utils.integrations``.
INSTALACAO_NATIVA = "nativo"
INSTALACAO_FLATPAK = "flatpak"
INSTALACAO_AUSENTE = "ausente"

#: ``EstadoServidor.status`` values.
STATUS_AUSENTE = "ausente"
STATUS_PARADO = "parado"
STATUS_OK = "ok"
STATUS_VAZIO = "sem-dispositivos"
STATUS_INCOMPATIVEL = "incompativel"
STATUS_SEM_PERMISSAO = "sem-permissao"
STATUS_ERRO = "erro"

#: Portas fora desta faixa nunca são tentadas, para um valor corrompido no
#: GSettings não virar uma varredura de portas.
PORTA_MINIMA = 1024
PORTA_MAXIMA = 65535

#: Onde as regras udev do pacote nativo se instalam. Sem elas o servidor
#: lista os dispositivos mas recusa escrever — o erro mais comum no Linux.
_CAMINHOS_UDEV = (
    Path("/usr/lib/udev/rules.d/60-openrgb.rules"),
    Path("/lib/udev/rules.d/60-openrgb.rules"),
    Path("/etc/udev/rules.d/60-openrgb.rules"),
)

#: Tempo curto: a sonda roda enquanto o usuário olha a tela de Preferências.
PRAZO_SONDA = 2.5


@dataclass(frozen=True)
class EstadoServidor:
    """Retrato do que o OpenRGB respondeu, pronto para virar texto na UI."""

    status: str
    instalacao: str = INSTALACAO_AUSENTE
    detalhe: str = ""
    protocolo: int = 0
    quantidade: int = 0
    host: str = protocol.DEFAULT_HOST
    porta: int = protocol.DEFAULT_PORT

    @property
    def conectado(self) -> bool:
        return self.status in (STATUS_OK, STATUS_VAZIO)

    @property
    def instalado(self) -> bool:
        return self.instalacao != INSTALACAO_AUSENTE


def porta_valida(porta: int) -> bool:
    return PORTA_MINIMA <= int(porta) <= PORTA_MAXIMA


def instalacao() -> str:
    """``nativo``, ``flatpak`` ou ``ausente``, com a precedência do projeto."""
    if shutil.which(BINARIO):
        return INSTALACAO_NATIVA
    try:
        if flatpak_installed(FLATPAK_ID):
            return INSTALACAO_FLATPAK
    except Exception as erro:  # pylint: disable=broad-exception-caught
        logging.debug("OpenRGB: flatpak info falhou: %s", erro)
    return INSTALACAO_AUSENTE


def comando(*, host: Optional[str] = None, porta: Optional[int] = None) -> list[str]:
    """Argumentos para rodar o OpenRGB instalado, nativo ou Flatpak.

    Devolve lista vazia quando não há nenhuma instalação: quem chama decide o
    que dizer ao usuário sem precisar repetir a detecção.
    """
    tipo = instalacao()
    if tipo == INSTALACAO_NATIVA:
        base = [shutil.which(BINARIO) or BINARIO]
    elif tipo == INSTALACAO_FLATPAK:
        base = ["flatpak", "run", FLATPAK_ID]
    else:
        return []
    extra: list[str] = []
    if host and host not in ("127.0.0.1", "localhost", "::1"):
        extra.append(f"--server-host={host}")
    if porta:
        extra.append(f"--server-port={int(porta)}")
    return base + extra


def comando_servidor(
    *, host: Optional[str] = None, porta: Optional[int] = None
) -> list[str]:
    """Comando que sobe o servidor do SDK sem abrir a janela do OpenRGB.

    ``--server`` sem ``--gui`` sobe só o servidor; ``--startminimized`` evita
    que a janela apareça caso a versão instalada decida mostrá-la de todo.
    ``--noautoconnect`` impede que ela se conecte a outro servidor já ativo e
    brigue pela porta.
    """
    base = comando(host=host, porta=porta)
    if not base:
        return []
    return base + ["--server", "--startminimized", "--noautoconnect"]


def versao() -> str:
    """Versão do OpenRGB instalado, quando dá para perguntar sem abrir janela.

    Roda em thread de trabalho. O timeout é curto porque um Flatpak frio pode
    demorar; nesse caso a UI mostra o estado da instalação sem número.
    """
    argumentos = comando()
    if not argumentos:
        return ""
    try:
        resultado = subprocess.run(
            argumentos + ["--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as erro:
        logging.debug("OpenRGB: --version falhou: %s", erro)
        return ""
    texto = (resultado.stdout or resultado.stderr or "").strip()
    return texto.splitlines()[0].strip() if texto else ""


def regras_udev() -> bool:
    """As regras udev do pacote nativo estão instaladas?

    Sem elas o servidor só funciona como root. A UI usa isto para explicar o
    problema em vez de mostrar um erro genérico na hora de aplicar a cor.
    """
    return any(caminho.is_file() for caminho in _CAMINHOS_UDEV)


def porta_aberta(
    host: str = protocol.DEFAULT_HOST,
    porta: int = protocol.DEFAULT_PORT,
    timeout: float = 1.0,
) -> bool:
    """Há alguém escutando na porta? Não valida o protocolo, só o soquete."""
    if not porta_valida(porta):
        return False
    try:
        with socket.create_connection((host, int(porta)), timeout=timeout):
            return True
    except OSError:
        return False


def sondar(
    host: str = protocol.DEFAULT_HOST, porta: int = protocol.DEFAULT_PORT
) -> EstadoServidor:
    """Fala o protocolo de verdade e devolve o estado do servidor.

    Uma conexão que aceita soquete mas não responde ao SDK é o caso do
    servidor de outra versão ou de outro programa na mesma porta; distinguir
    os dois poupa o usuário de trocar a porta à toa.
    """
    tipo = instalacao()
    if not porta_valida(porta):
        return EstadoServidor(
            STATUS_ERRO,
            tipo,
            detalhe="porta-invalida",
            host=host,
            porta=int(porta or 0),
        )

    cliente = protocol.OpenRGBClient(host, int(porta), timeout=PRAZO_SONDA)
    try:
        cliente.connect()
        controladores = cliente.controllers()
    except protocol.OpenRGBDisconnected as erro:
        if tipo == INSTALACAO_AUSENTE:
            return EstadoServidor(
                STATUS_AUSENTE, tipo, detalhe=str(erro), host=host, porta=int(porta)
            )
        return EstadoServidor(
            STATUS_PARADO, tipo, detalhe=str(erro), host=host, porta=int(porta)
        )
    except protocol.ProtocolError as erro:
        return EstadoServidor(
            STATUS_INCOMPATIVEL,
            tipo,
            detalhe=str(erro),
            host=host,
            porta=int(porta),
        )
    except OSError as erro:
        # Recusa de conexão, timeout ou host inalcançável: ninguém está
        # ouvindo a porta. É o caso comum de "o servidor não está no ar" e
        # não uma falha do OpenRGB — dizer "erro" mandaria a pessoa trocar a
        # porta sem motivo. `STATUS_ERRO` fica para o resto.
        ninguem_respondeu = isinstance(erro, (ConnectionRefusedError, TimeoutError))
        if not ninguem_respondeu:
            return EstadoServidor(
                STATUS_ERRO, tipo, detalhe=str(erro), host=host, porta=int(porta)
            )
        return EstadoServidor(
            STATUS_AUSENTE if tipo == INSTALACAO_AUSENTE else STATUS_PARADO,
            tipo,
            detalhe=str(erro),
            host=host,
            porta=int(porta),
        )
    else:
        estado = EstadoServidor(
            STATUS_OK if controladores else STATUS_VAZIO,
            tipo,
            protocolo=cliente.protocol_version,
            quantidade=len(controladores),
            host=host,
            porta=int(porta),
        )
        return estado
    finally:
        cliente.close()


def abrir_cliente(
    host: str = protocol.DEFAULT_HOST,
    porta: int = protocol.DEFAULT_PORT,
    timeout: float = 5.0,
) -> protocol.OpenRGBClient:
    """Cliente conectado e pronto para uso; quem chama deve fechá-lo."""
    if not porta_valida(porta):
        raise ValueError(f"porta do OpenRGB fora da faixa: {porta}")
    return protocol.OpenRGBClient(host, int(porta), timeout=timeout).connect()

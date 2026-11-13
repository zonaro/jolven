# commands.py
#
# Copyright 2026 Jolven contributors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Cliente do Network Command Interface do RetroArch sobre UDP.

O RetroArch expõe uma interface de comandos por rede: um datagrama UDP com o
nome do comando em texto puro, por padrão em ``127.0.0.1:55355``, ativado pela
opção ``network_cmd_enable`` (Documentação oficial: ``Network Command
Interface'', em docs/rmp.md e no menu ``Settings > Network``). A resposta,
quando o comando produz uma, volta como datagrama para a porta de origem.

Duas decisões que custam caro se erradas:

* **Allowlist local.** Só sai daqui comando que estiver em
  ``COMANDOS_PERMITIDOS``. Nada de string crua controlada pelo usuário: um
  comando fora da lista é recusado antes de qualquer soquete existir.
* **Nunca levanta.** Rede ausente, porta fechada, timeout e datagrama
  Inválido são estados normais de um emulador que nem está rodando. Tudo
  vira ``None`` com um log em nível debug; quem chama decide o que mostrar.

**Importante: a chamada é bloqueante (``timeout`` de soquete).** Quem usar
este cliente deve chamá-lo de uma thread de trabalho, nunca da thread
principal do GTK — o mesmo contrato dos outros pacotes de integração.

O pacote não importa GTK em nenhum nível.
"""

from __future__ import annotations

import logging
import socket
from typing import Optional

#: Endereço e porta convencionais da interface de comandos do RetroArch.
#: A porta real vem da opção ``network_cmd_port`` do core.cfg; aqui vale o
#: padrão do projeto.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 55355

#: Timeout padrão, em segundos. Curto de propósito: um datagrama que não volta
#: em meio segundo na máquina local significa "não está respondendo".
DEFAULT_TIMEOUT = 0.5

#: Comandos que este cliente aceita enviar. Qualquer coisa fora da lista é
#: recusada localmente, sem tocar a rede — inclusive strings arbitrárias que
#: venham de UI ou de entrada do usuário.
COMANDOS_PERMITIDOS = frozenset(
    {
        "PAUSE_TOGGLE",
        "RESET",
        "SAVE_STATE",
        "LOAD_STATE",
        "SCREENSHOT",
        "FAST_FORWARD",
        "SLOWMOTION",
        "MUTE",
        "VOLUME_UP",
        "VOLUME_DOWN",
        "FULLSCREEN_TOGGLE",
        "MENU_TOGGLE",
        "STATE_SLOT_PLUS",
        "STATE_SLOT_MINUS",
        "GET_STATUS",
        "SHUTDOWN",
    }
)

#: Comando barato que o RetroArch responde quando a interface está de pé.
_COMANDO_SONDA = "GET_STATUS"

#: Teto da resposta, em bytes. O GET_STATUS descreve o estado atual e cabe
#: folgado aqui; datagramas UDP acima disso são truncados pelo kernel de
#: qualquer forma.
_MAX_RESPOSTA = 8192


def parse_status(resposta: str) -> dict[str, str]:
    """Converte a resposta do ``GET_STATUS`` em um mapa ``chave -> valor``.

    O RetroArch responde em linhas ``CHAVE: valor``. Linhas vazias, linhas
    sem ``:`` ou com chave/valor vazios são lixo tolerado e simplesmente
    ignoradas — a resposta vem pela rede e pode vir cortada.

    Devolve um ``dict`` novo a cada chamada. Uma chave repetida na resposta
    fica com o último valor.

    Atenção: a interface de comandos **não** informa capacidades do núcleo.
    Se o jogo suporta rewind, save state, replay ou qualquer outra coisa não
    dá para saber por aqui — quem consumir este mapa deve tratar capacidades
    como desconhecidas, nunca como ausentes.
    """
    estado: dict[str, str] = {}
    if not resposta:
        return estado
    for linha in resposta.splitlines():
        linha = linha.strip()
        if not linha or ":" not in linha:
            continue
        chave, _, valor = linha.partition(":")
        chave = chave.strip()
        valor = valor.strip()
        if not chave or not valor:
            continue
        estado[chave] = valor
    return estado


class RetroarchCommandClient:
    """Cliente UDP de comandos do RetroArch.

    ``send`` valida contra ``COMANDOS_PERMITIDOS``, envia um datagrama e
    devolve a resposta decodificada (ou ``None``). ``is_available`` faz uma
    sondagem barata com ``GET_STATUS``.

    **Nunca chame da thread principal do GTK:** cada envio pode esperar até
    ``timeout`` segundos por uma resposta. Use uma thread de trabalho e
    entregue o resultado à UI com os helpers existentes.
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout

    def send(self, command: str) -> Optional[str]:
        """Envia ``command`` e devolve a resposta decodificada, ou ``None``.

        ``None`` significa qualquer uma destas coisas e o chamador não deve
        distinguir: comando fora da allowlist, RetroArch desligado, porta
        fechada, timeout ou resposta vazia. Erros de rede/OS são logados em
        nível debug e nunca chegam ao chamador como exceção.
        """
        comando = command.strip().upper()
        if comando not in COMANDOS_PERMITIDOS:
            logging.debug(
                "RetroArch: comando %r fora da lista permitida, descartado",
                command,
            )
            return None
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as soquete:
                soquete.settimeout(self.timeout)
                # connect() num soquete UDP prende o destino, faz o kernel
                # reportar ICMP "porta fechada" como erro de leitura e filtra
                # datagramas de outra origem.
                soquete.connect((self.host, self.port))
                soquete.send(comando.encode("ascii"))
                dados = soquete.recv(_MAX_RESPOSTA)
        except OSError as erro:
            # socket.timeout é subclasse de OSError: timeout cai aqui também.
            logging.debug(
                "RetroArch: %r para %s:%d falhou: %s",
                comando,
                self.host,
                self.port,
                erro,
            )
            return None
        return dados.decode("utf-8", errors="replace")

    def is_available(self) -> bool:
        """Se a interface de comandos responde a uma sondagem ``GET_STATUS``.

        Barata e sem exceção: uma sondagem que não volta em ``timeout``
        segundos já vale "indisponível".
        """
        return self.send(_COMANDO_SONDA) is not None

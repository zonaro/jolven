# coordenador.py
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

"""Quem manda a iluminação vestir a cor do jogo — e desvestir depois.

O coordenador existe por causa de três exigências que não se resolvem sozinhas:

1. **Uma thread só.** O servidor do OpenRGB atende um pedido por vez no mesmo
   soquete e as fitas Tuya têm trava por dispositivo; dois jogos abrindo juntos
   não podem intercalar pacotes. Tudo passa por uma fila e por uma thread de
   trabalho, nunca pela thread do GTK.
2. **Uma pilha.** Fechar o jogo A com o jogo B ainda aberto não pode devolver o
   hardware ao estado de antes do Jolven: o topo da pilha volta a valer.
3. **Um diário em disco.** O estado de antes é gravado *antes* de a primeira
   cor ser mandada. Um app morto no meio da sessão deixa o diário para o
   arranque seguinte desfazer (:meth:`Coordenador.restaurar_orfaos`), e a
   configuração permanente do usuário nunca é tocada porque nada é salvo na
   memória do controlador.

O que conta como "estado de antes" é o primeiro retrato de cada dispositivo
dentro de uma sessão do Jolven. É esse retrato, e não a cor do app, que a
devolução reaplica.

``comecar``/``terminar`` são chamados da thread principal e devolvem de
imediato o que ela precisa saber: se o perfil tomou as fitas Tuya para si. O
trabalho de hardware é enfileirado e concluído depois.
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Callable, Optional

from cartridges.iluminacao import diario as diario_mod
from cartridges.iluminacao import perfis as perfis_mod
from cartridges.iluminacao.modelo import Alvo, Estado
from cartridges.iluminacao.provedores.base import Provedor
from cartridges.iluminacao.provedores.openrgb import ProvedorOpenRGB
from cartridges.iluminacao.provedores.tuya import ProvedorTuya

#: Quanto esperar por uma consulta de dispositivos pedida pela interface.
#: Três fitas mudas a cinco segundos cada já estouram isto, e é de propósito:
#: a janela não pode ficar presa esperando hardware.
PRAZO_CONSULTA = 12.0

#: Quanto esperar pela devolução no fechamento do app. Passado isso, o diário
#: fica para o próximo arranque — melhor que um encerramento travado.
PRAZO_FECHAMENTO = 6.0


def criar_provedores() -> list[Provedor]:
    """Os provedores, com a configuração que estiver nas Preferências."""
    from cartridges import shared  # noqa: PLC0415
    from cartridges.integrations.openrgb import protocol  # noqa: PLC0415

    host = (shared.schema.get_string("openrgb-host") or "").strip()
    porta = shared.schema.get_int("openrgb-port")
    return [
        ProvedorOpenRGB(host or protocol.DEFAULT_HOST, porta or protocol.DEFAULT_PORT),
        ProvedorTuya(),
    ]


class Coordenador:
    """A fila, a pilha e o diário da iluminação por jogo."""

    def __init__(
        self,
        provedores: Optional[list[Provedor]] = None,
        repositorio: Optional[perfis_mod.Repositorio] = None,
        arquivo: Optional[diario_mod.Arquivo] = None,
    ) -> None:
        self._provedores = {
            provedor.chave: provedor for provedor in (provedores or criar_provedores())
        }
        self._repositorio = repositorio or perfis_mod.Repositorio()
        self._arquivo = arquivo or diario_mod.Arquivo()
        self._fila: "queue.Queue[Optional[tuple[Callable[[], None], Optional[threading.Event]]]]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._trava = threading.Lock()
        #: ``game_id`` -> o perfil tomou as fitas Tuya nesta sessão?
        self._gerencia_fitas: dict[str, bool] = {}
        #: Retrato de antes de uma prévia, só em memória: prévia não é sessão e
        #: não pode sujar o diário.
        self._previa: dict[str, Estado] = {}

    # -- fila ---------------------------------------------------------

    def _garantir_thread(self) -> None:
        with self._trava:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._laco, name="jolven-iluminacao", daemon=True
            )
            self._thread.start()

    def _laco(self) -> None:
        while True:
            item = self._fila.get()
            if item is None:
                return
            tarefa, pronto = item
            try:
                tarefa()
            except Exception:  # pylint: disable=broad-exception-caught
                # Um enfeite não derruba a sessão, e a thread não pode morrer:
                # o próximo jogo ainda vai precisar dela.
                logging.exception("Iluminação: falha inesperada na thread de trabalho")
            finally:
                if pronto is not None:
                    pronto.set()

    def _enfileirar(
        self, tarefa: Callable[[], None], pronto: Optional[threading.Event] = None
    ) -> None:
        self._garantir_thread()
        self._fila.put((tarefa, pronto))

    def _provedor(self, chave: str) -> Optional[Provedor]:
        return self._provedores.get(chave)

    # -- sessão -------------------------------------------------------

    def perfil_do_jogo(self, game: object) -> Optional[perfis_mod.Perfil]:
        """O perfil ligado a este jogo, ou ``None``."""
        identificador = str(getattr(game, "rgb_profile_id", "") or "").strip()
        if not identificador:
            return None
        perfil = self._repositorio.obter(identificador)
        if perfil is None:
            logging.info(
                "Iluminação: o perfil %s deste jogo não existe mais", identificador
            )
            return None
        return None if perfil.vazio else perfil

    def comecar(self, game: object) -> bool:
        """Aplica o perfil do jogo. Devolve ``True`` se tomou as fitas Tuya.

        O retorno existe para o chamador saber se ainda deve rodar o ciclo
        normal das fitas (cor da capa). Quando o perfil cita fita, ele manda
        nelas e o ciclo antigo ficaria brigando pelo mesmo módulo.
        """
        perfil = self.perfil_do_jogo(game)
        if perfil is None:
            return False
        tuya = self._provedor("tuya")
        gerencia = bool(
            perfil.usa("tuya") and tuya is not None and tuya.ativo()
        )
        jogo = str(getattr(game, "game_id", "") or "")
        with self._trava:
            if jogo:
                self._gerencia_fitas[jogo] = gerencia
        self._enfileirar(lambda: self._aplicar(perfil, jogo, gerencia))
        return gerencia

    def terminar(self, game: object) -> bool:
        """Desfaz o perfil do jogo. Mesmo retorno de :meth:`comecar`."""
        jogo = str(getattr(game, "game_id", "") or "")
        with self._trava:
            gerencia = self._gerencia_fitas.pop(jogo, False)
        self._enfileirar(lambda: self._terminar(jogo))
        return gerencia

    def _aplicar(
        self, perfil: perfis_mod.Perfil, jogo: str, gerencia_fitas: bool
    ) -> None:
        registro = self._arquivo.ler()
        registro.ativos = [
            ativo for ativo in registro.ativos if ativo.jogo != jogo
        ]
        if jogo:
            registro.ativos.append(
                diario_mod.Ativo(jogo=jogo, perfil=perfil.id, fitas=gerencia_fitas)
            )
        self._aplicar_perfil(perfil, registro)

    def _aplicar_perfil(
        self, perfil: perfis_mod.Perfil, registro: diario_mod.Diario
    ) -> None:
        """Veste o perfil, guardando antes o estado de todo dispositivo tocado."""
        disponiveis: dict[str, dict[str, Alvo]] = {}
        for plano in perfil.dispositivos:
            if plano.vazio:
                continue
            provedor = self._provedor(plano.provedor)
            if provedor is None:
                logging.info("Iluminação: provedor %s desconhecido", plano.provedor)
                continue
            if not provedor.ativo():
                logging.info(
                    "Iluminação: provedor %s desligado; %s fica como está",
                    plano.provedor,
                    plano.nome or plano.chave,
                )
                continue
            if plano.provedor not in disponiveis:
                disponiveis[plano.provedor] = provedor.por_chave()
            alvo = disponiveis[plano.provedor].get(plano.chave)
            if alvo is None:
                logging.info(
                    "Iluminação: %s não está presente; plano ignorado",
                    plano.nome or plano.chave,
                )
                continue

            if plano.identificador not in registro.base:
                estado = provedor.ler(alvo)
                if estado is None:
                    logging.warning(
                        "Iluminação: não foi possível ler %s; o plano não será aplicado "
                        "porque não haveria como devolvê-lo",
                        alvo.nome,
                    )
                    continue
                registro.base[plano.identificador] = estado
                # Gravar antes de pintar: se o app morrer no meio da aplicação,
                # o estado de antes já está em disco para o próximo arranque.
                self._arquivo.gravar(registro)

            if not provedor.aplicar(alvo, plano):
                logging.warning("Iluminação: %s recusou o plano", alvo.nome)

        self._arquivo.gravar(registro)

    def _terminar(self, jogo: str) -> None:
        registro = self._arquivo.ler()
        registro.ativos = [ativo for ativo in registro.ativos if ativo.jogo != jogo]

        if registro.ativos:
            # Outro jogo continua aberto: o topo da pilha volta a valer, e o
            # estado de antes continua guardado para quando ele sair.
            proximo = registro.ativos[-1]
            perfil = self._repositorio.obter(proximo.perfil)
            if perfil is not None and not perfil.vazio:
                self._aplicar_perfil(perfil, registro)
                return
            # Perfil apagado no meio da sessão: sem plano, o certo é devolver.

        self._devolver(registro)

    def _devolver(self, registro: diario_mod.Diario) -> None:
        """Reaplica o estado de antes no que der; mantém o resto pendente.

        Dispositivo ausente sai do diário (não há o que devolver e insistir
        deixaria a pendência para sempre). Provedor desligado ou servidor fora
        do ar fica: a próxima abertura do app tenta de novo.
        """
        if not registro.base:
            self._arquivo.limpar()
            return

        alvos: dict[str, dict[str, Alvo]] = {}
        restantes: dict[str, Estado] = {}
        for identificador, estado in registro.base.items():
            provedor = self._provedor(estado.provedor)
            if provedor is None or not provedor.ativo():
                restantes[identificador] = estado
                continue
            if estado.provedor not in alvos:
                alvos[estado.provedor] = provedor.por_chave()
            alvo = alvos[estado.provedor].get(estado.chave)
            if alvo is None:
                logging.info(
                    "Iluminação: %s não está mais presente; nada a devolver",
                    estado.nome or estado.chave,
                )
                continue
            if not provedor.restaurar(alvo, estado):
                restantes[identificador] = estado

        if restantes:
            logging.info(
                "Iluminação: %s dispositivo(s) continuam pendentes de devolução",
                len(restantes),
            )
            registro.base = restantes
            self._arquivo.gravar(registro)
        else:
            self._arquivo.limpar()

    def restaurar_orfaos(self) -> None:
        """Desfaz a troca que uma execução anterior não desfez."""
        registro = self._arquivo.ler()
        if not registro.base:
            return
        with self._trava:
            self._gerencia_fitas.clear()
        logging.info(
            "Iluminação: devolvendo %s dispositivo(s) de uma sessão anterior",
            len(registro.base),
        )
        self._enfileirar(lambda: self._devolver(registro))

    # -- prévia -------------------------------------------------------

    def previa(self, perfil: perfis_mod.Perfil) -> None:
        """Aplica o perfil sem virar sessão, guardando o retrato em memória."""

        def tarefa() -> None:
            if self._previa:
                self._restaurar_previa()
            disponiveis: dict[str, dict[str, Alvo]] = {}
            for plano in perfil.dispositivos:
                if plano.vazio:
                    continue
                provedor = self._provedor(plano.provedor)
                if provedor is None or not provedor.ativo():
                    continue
                if plano.provedor not in disponiveis:
                    disponiveis[plano.provedor] = provedor.por_chave()
                alvo = disponiveis[plano.provedor].get(plano.chave)
                if alvo is None:
                    continue
                estado = provedor.ler(alvo)
                if estado is None:
                    continue
                self._previa[plano.identificador] = estado
                provedor.aplicar(alvo, plano)

        self._enfileirar(tarefa)

    def restaurar_previa(self) -> None:
        self._enfileirar(self._restaurar_previa)

    def _restaurar_previa(self) -> None:
        if not self._previa:
            return
        disponiveis: dict[str, dict[str, Alvo]] = {}
        for identificador, estado in list(self._previa.items()):
            provedor = self._provedor(estado.provedor)
            if provedor is None or not provedor.ativo():
                continue
            if estado.provedor not in disponiveis:
                disponiveis[estado.provedor] = provedor.por_chave()
            alvo = disponiveis[estado.provedor].get(estado.chave)
            if alvo is None:
                continue
            provedor.restaurar(alvo, estado)
        self._previa.clear()

    # -- consulta -----------------------------------------------------

    def alvos(self, prazo: float = PRAZO_CONSULTA) -> list[Alvo]:
        """Os dispositivos disponíveis. **Chamar de thread de trabalho.**

        A janela recebe a lista por ``entregar_na_tela``; chamar da thread do
        GTK trava a interface pelo tempo do timeout das fitas mudas.
        """
        if threading.current_thread() is threading.main_thread():
            logging.warning(
                "Iluminação: alvos() chamado na thread principal; use uma thread"
            )
        pronto = threading.Event()
        caixa: list[Alvo] = []

        def tarefa() -> None:
            for provedor in self._provedores.values():
                try:
                    if provedor.ativo():
                        caixa.extend(provedor.alvos())
                except Exception:  # pylint: disable=broad-exception-caught
                    logging.exception(
                        "Iluminação: provedor %s falhou ao listar", provedor.chave
                    )

        self._enfileirar(tarefa, pronto)
        if not pronto.wait(prazo):
            logging.warning("Iluminação: consulta de dispositivos não terminou a tempo")
        return caixa

    def ativos(self) -> list[diario_mod.Ativo]:
        """Os jogos que estão usando a iluminação agora (para diagnóstico)."""
        return self._arquivo.ler().ativos

    # -- encerramento -------------------------------------------------

    def fechar(self, prazo: float = PRAZO_FECHAMENTO) -> None:
        """Devolve o que estiver pendente e encerra a thread de trabalho.

        Chamado no encerramento do app. Se o hardware não responder dentro do
        prazo, o diário continua em disco e o próximo arranque termina o
        serviço — travar o fechamento seria pior.
        """
        pronto = threading.Event()

        def tarefa() -> None:
            registro = self._arquivo.ler()
            if registro.base:
                self._devolver(registro)
            for provedor in self._provedores.values():
                try:
                    provedor.fechar()
                except Exception:  # pylint: disable=broad-exception-caught
                    logging.exception("Iluminação: falha ao fechar %s", provedor.chave)

        self._enfileirar(tarefa, pronto)
        pronto.wait(prazo)
        self._fila.put(None)


# -- instância única --------------------------------------------------

_instancia: Optional[Coordenador] = None
_trava_instancia = threading.Lock()


def instancia() -> Coordenador:
    """O coordenador do processo, criado na primeira chamada."""
    global _instancia
    with _trava_instancia:
        if _instancia is None:
            _instancia = Coordenador()
        return _instancia


def comecar(game: object) -> bool:
    return instancia().comecar(game)


def terminar(game: object) -> bool:
    return instancia().terminar(game)


def restaurar_orfaos() -> None:
    instancia().restaurar_orfaos()


def fechar() -> None:
    with _trava_instancia:
        atual = _instancia
    if atual is not None:
        atual.fechar()


def alvos() -> list[Alvo]:
    return instancia().alvos()

# test_iluminacao_coordenador.py
#
# Copyright 2026 Jolven contributors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O coordenador: pilha de sessões, diário antes de pintar, devolução parcial.

O coordenador tem uma thread de trabalho própria. Os testes esperam por ela
com um marcador no fim da fila — o mesmo truque que a UI usa — para nunca
interferir com a ordem das tarefas.
"""

import builtins
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Optional

if not hasattr(builtins, "_"):
    builtins._ = lambda s: s  # type: ignore[attr-defined]

from cartridges.iluminacao.coordenador import Coordenador
from cartridges.iluminacao.cores import Cor
from cartridges.iluminacao.diario import Arquivo
from cartridges.iluminacao.modelo import Alvo, Estado, Plano
from cartridges.iluminacao.perfis import Perfil, Repositorio
from cartridges.iluminacao.provedores.base import Provedor

#: Chave do provedor falso, usada nos planos e no diário.
CHAVE = "falso"


class ProvedorFalso(Provedor):
    """Um hardware de mentira, com estado gravado em memória.

    Devolve ``False`` de ``restaurar`` quando ``falhar_restaurar`` está
    ligado, que é o caso que o diário precisa manter pendente.
    """

    chave = CHAVE
    nome = "Falso"

    def __init__(self, ligado: bool = True) -> None:
        self.ligado = ligado
        self.falhar_restaurar = False
        self.estado: Optional[Estado] = Estado(
            provedor=self.chave,
            chave="luz-1",
            nome="Luz",
            cor=Cor(1, 2, 3),
            brilho=80,
        )
        self.pinturas: list[Cor] = []
        self.devolucoes: list[Estado] = []
        self.atual: Optional[Estado] = None

    def ativo(self) -> bool:
        return self.ligado

    def alvos(self) -> list[Alvo]:
        return [Alvo(provedor=self.chave, chave="luz-1", nome="Luz")]

    def ler(self, alvo: Alvo) -> Optional[Estado]:
        return self.atual if self.atual is not None else self.estado

    def aplicar(self, alvo: Alvo, plano: Plano) -> bool:
        self.pinturas.append(plano.cor or Cor(0, 0, 0))
        self.atual = Estado(
            provedor=self.chave, chave=alvo.chave, nome=alvo.nome, cor=plano.cor
        )
        return True

    def restaurar(self, alvo: Alvo, estado: Estado) -> bool:
        if self.falhar_restaurar:
            return False
        self.devolucoes.append(estado)
        self.atual = estado
        return True


class ProvedorTuyaFalso(ProvedorFalso):
    """Mesma coisa, mas respondendo pela chave ``tuya`` — só para a pilha."""

    chave = "tuya"


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.pasta = Path(tempfile.mkdtemp(prefix="jolven-coordenador-"))
        self.addCleanup(shutil.rmtree, self.pasta, True)
        self.repositorio = Repositorio(self.pasta / "perfis.json")
        self.arquivo = Arquivo(self.pasta / "sessao.json")
        self.provedor = ProvedorFalso()
        self.coord = Coordenador(
            provedores=[self.provedor],
            repositorio=self.repositorio,
            arquivo=self.arquivo,
        )

    def esperar(self) -> None:
        """Espera todas as tarefas enfileiradas terminarem."""
        pronto = threading.Event()
        self.coord._enfileirar(lambda: None, pronto)  # pylint: disable=protected-access
        self.assertTrue(pronto.wait(10), "a thread de iluminação não respondeu")

    def perfil(self, nome: str, *identificadores: str) -> Perfil:
        perfil = self.repositorio.criar(nome)
        for identificador in identificadores:
            provedor, _, chave = identificador.partition(":")
            perfil.dispositivos.append(
                Plano(provedor=provedor, chave=chave, nome=chave, cor=Cor(9, 9, 9))
            )
        self.repositorio.salvar(self.repositorio.carregar() + [perfil])
        return perfil

    def jogo(self, game_id: str, perfil_id: str):
        class Jogo:
            pass

        jogo = Jogo()
        jogo.game_id = game_id  # type: ignore[attr-defined]
        jogo.rgb_profile_id = perfil_id  # type: ignore[attr-defined]
        return jogo


class TestAplicarDevolver(Base):
    def test_jogo_sem_perfil_nao_mexe_em_nada(self) -> None:
        self.assertFalse(self.coord.comecar(self.jogo("g1", "")))
        self.esperar()
        self.assertEqual(self.provedor.pinturas, [])
        self.assertFalse(self.arquivo.ler().pendente)

    def test_perfil_apagado_nao_mexe_em_nada(self) -> None:
        self.assertFalse(self.coord.comecar(self.jogo("g1", "sumiu")))
        self.esperar()
        self.assertEqual(self.provedor.pinturas, [])

    def test_perfil_vazio_nao_mexe_em_nada(self) -> None:
        perfil = self.repositorio.criar("Vazio")
        self.repositorio.salvar([perfil])
        self.assertFalse(self.coord.comecar(self.jogo("g1", perfil.id)))
        self.esperar()
        self.assertEqual(self.provedor.pinturas, [])

    def test_aplicar_guarda_a_base_antes_de_pintar(self) -> None:
        perfil = self.perfil("Roxo", "falso:luz-1")
        self.coord.comecar(self.jogo("g1", perfil.id))
        self.esperar()

        self.assertEqual(self.provedor.pinturas, [Cor(9, 9, 9)])
        registro = self.arquivo.ler()
        self.assertTrue(registro.pendente)
        base = registro.estado("falso:luz-1")
        self.assertEqual(base.cor, Cor(1, 2, 3))  # type: ignore[union-attr]
        self.assertEqual(base.brilho, 80)  # type: ignore[union-attr]
        self.assertEqual([a.jogo for a in registro.ativos], ["g1"])

    def test_devolver_restaura_e_limpa(self) -> None:
        perfil = self.perfil("Roxo", "falso:luz-1")
        self.coord.comecar(self.jogo("g1", perfil.id))
        self.esperar()
        self.coord.terminar(self.jogo("g1", perfil.id))
        self.esperar()

        self.assertEqual(len(self.provedor.devolucoes), 1)
        self.assertEqual(self.provedor.devolucoes[0].cor, Cor(1, 2, 3))
        registro = self.arquivo.ler()
        self.assertFalse(registro.pendente)
        self.assertEqual(registro.ativos, [])

    def test_devolucao_que_falha_fica_pendente(self) -> None:
        perfil = self.perfil("Roxo", "falso:luz-1")
        self.coord.comecar(self.jogo("g1", perfil.id))
        self.esperar()
        self.provedor.falhar_restaurar = True
        self.coord.terminar(self.jogo("g1", perfil.id))
        self.esperar()

        registro = self.arquivo.ler()
        self.assertTrue(registro.pendente, "a pendência precisa sobreviver")
        self.assertIn("falso:luz-1", registro.base)

    def test_devolucao_com_provedor_desligado_tambem_fica(self) -> None:
        perfil = self.perfil("Roxo", "falso:luz-1")
        self.coord.comecar(self.jogo("g1", perfil.id))
        self.esperar()
        self.provedor.ligado = False
        self.coord.terminar(self.jogo("g1", perfil.id))
        self.esperar()
        self.assertTrue(self.arquivo.ler().pendente)

    def test_dispositivo_sumido_sai_do_diario(self) -> None:
        perfil = self.perfil("Roxo", "falso:luz-1")
        self.coord.comecar(self.jogo("g1", perfil.id))
        self.esperar()
        self.provedor.estado = None
        self.provedor.alvos = lambda: []  # type: ignore[method-assign]
        self.coord.terminar(self.jogo("g1", perfil.id))
        self.esperar()
        self.assertFalse(
            self.arquivo.ler().pendente, "sem o que devolver, insistir é para sempre"
        )

    def test_provedor_desligado_deixa_o_plano_de_lado(self) -> None:
        self.provedor.ligado = False
        perfil = self.perfil("Roxo", "falso:luz-1")
        self.coord.comecar(self.jogo("g1", perfil.id))
        self.esperar()
        self.assertEqual(self.provedor.pinturas, [])
        self.assertFalse(self.arquivo.ler().pendente)


class TestPilhaDeSessoes(Base):
    def test_terminar_um_jogo_reaplica_o_anterior(self) -> None:
        um = self.perfil("Um", "falso:luz-1")
        dois = self.repositorio.criar("Dois")
        dois.dispositivos.append(
            Plano(provedor=CHAVE, chave="luz-1", nome="luz", cor=Cor(50, 50, 50))
        )
        self.repositorio.salvar([um, dois])

        self.coord.comecar(self.jogo("a", um.id))
        self.esperar()
        self.coord.comecar(self.jogo("b", dois.id))
        self.esperar()
        self.coord.terminar(self.jogo("b", dois.id))
        self.esperar()

        # O topo saiu: o de baixo volta a valer, e a base continua guardada.
        self.assertEqual(self.provedor.pinturas[-1], Cor(9, 9, 9))
        self.assertEqual(self.provedor.devolucoes, [])
        self.assertTrue(self.arquivo.ler().pendente)

        self.coord.terminar(self.jogo("a", um.id))
        self.esperar()
        self.assertEqual(len(self.provedor.devolucoes), 1)
        self.assertFalse(self.arquivo.ler().pendente)

    def test_terminar_o_unico_restaura(self) -> None:
        um = self.perfil("Um", "falso:luz-1")
        self.coord.comecar(self.jogo("a", um.id))
        self.esperar()
        self.coord.terminar(self.jogo("a", um.id))
        self.esperar()
        self.assertEqual(len(self.provedor.devolucoes), 1)

    def test_terminar_jogo_que_nao_comecou_e_inocente(self) -> None:
        self.coord.terminar(self.jogo("nunca-visto", ""))
        self.esperar()
        self.assertEqual(self.provedor.devolucoes, [])

    def test_perfil_apagado_no_meio_da_pilha_devolve(self) -> None:
        um = self.perfil("Um", "falso:luz-1")
        dois = self.perfil("Dois", "falso:luz-1")
        self.coord.comecar(self.jogo("a", um.id))
        self.esperar()
        self.coord.comecar(self.jogo("b", dois.id))
        self.esperar()
        # Quem sobra no topo perdeu o perfil: não há mais o que vestir, e a
        # única saída honesta é devolver o estado de antes.
        self.repositorio.excluir(um.id)
        self.coord.terminar(self.jogo("b", dois.id))
        self.esperar()
        self.assertEqual(len(self.provedor.devolucoes), 1)
        self.assertFalse(self.arquivo.ler().pendente)

    def test_perfil_de_baixo_continua_valendo(self) -> None:
        um = self.perfil("Um", "falso:luz-1")
        dois = self.perfil("Dois", "falso:luz-1")
        self.coord.comecar(self.jogo("a", um.id))
        self.esperar()
        self.coord.comecar(self.jogo("b", dois.id))
        self.esperar()
        self.repositorio.excluir(dois.id)
        self.coord.terminar(self.jogo("b", dois.id))
        self.esperar()
        # O de baixo tem perfil: ele volta a valer, sem devolver nada ainda.
        self.assertEqual(self.provedor.devolucoes, [])
        self.assertEqual(self.provedor.pinturas[-1], Cor(9, 9, 9))
        self.assertTrue(self.arquivo.ler().pendente)


class TestOrfaosEPrevia(Base):
    def test_restaurar_orfaos_devolve_o_que_uma_sessao_deixou(self) -> None:
        perfil = self.perfil("Roxo", "falso:luz-1")
        self.coord.comecar(self.jogo("g1", perfil.id))
        self.esperar()
        # Simula o app morrer no meio: o diário fica, a memória não.
        outro = Coordenador(
            provedores=[self.provedor],
            repositorio=self.repositorio,
            arquivo=self.arquivo,
        )
        outro.restaurar_orfaos()
        pronto = threading.Event()
        outro._enfileirar(lambda: None, pronto)  # pylint: disable=protected-access
        self.assertTrue(pronto.wait(10))
        self.assertEqual(len(self.provedor.devolucoes), 1)
        self.assertFalse(self.arquivo.ler().pendente)

    def test_previa_nao_suja_o_diario(self) -> None:
        perfil = self.perfil("Roxo", "falso:luz-1")
        self.coord.previa(perfil)
        self.esperar()
        self.assertEqual(self.provedor.pinturas, [Cor(9, 9, 9)])
        self.assertFalse(
            self.arquivo.ler().pendente, "prévia não é sessão e não tem o que devolver"
        )

    def test_previa_devolve_o_estado_antigo(self) -> None:
        perfil = self.perfil("Roxo", "falso:luz-1")
        self.coord.previa(perfil)
        self.esperar()
        self.coord.restaurar_previa()
        self.esperar()
        self.assertEqual(len(self.provedor.devolucoes), 1)
        self.assertEqual(self.provedor.devolucoes[0].cor, Cor(1, 2, 3))

    def test_duas_previas_em_seguida_devolvem_somente_a_ultima(self) -> None:
        perfil = self.perfil("Roxo", "falso:luz-1")
        self.coord.previa(perfil)
        self.esperar()
        self.coord.previa(perfil)
        self.esperar()
        # A segunda prévia restaura a primeira antes de aplicar de novo.
        self.assertEqual(len(self.provedor.devolucoes), 1)
        self.assertEqual(self.provedor.pinturas, [Cor(9, 9, 9), Cor(9, 9, 9)])
        self.coord.restaurar_previa()
        self.esperar()
        self.assertEqual(len(self.provedor.devolucoes), 2)


class TestFitasTuya(Base):
    def setUp(self) -> None:
        super().setUp()
        self.tuya = ProvedorTuyaFalso()
        self.coord = Coordenador(
            provedores=[self.provedor, self.tuya],
            repositorio=self.repositorio,
            arquivo=self.arquivo,
        )

    def test_perfil_sem_tuya_nao_toma_as_fitas(self) -> None:
        perfil = self.perfil("Roxo", "falso:luz-1")
        self.assertFalse(self.coord.comecar(self.jogo("g1", perfil.id)))
        self.esperar()

    def test_perfil_com_tuya_toma_as_fitas(self) -> None:
        perfil = self.perfil("Roxo", "tuya:luz-1")
        self.assertTrue(self.coord.comecar(self.jogo("g1", perfil.id)))
        self.esperar()
        self.assertEqual(self.tuya.pinturas, [Cor(9, 9, 9)])
        registro = self.arquivo.ler()
        self.assertTrue(registro.ativos[0].fitas)

    def test_perfil_com_tuya_mas_provedor_desligado_nao_toma(self) -> None:
        self.tuya.ligado = False
        perfil = self.perfil("Roxo", "tuya:luz-1")
        self.assertFalse(self.coord.comecar(self.jogo("g1", perfil.id)))
        self.esperar()
        self.assertEqual(self.tuya.pinturas, [])

    def test_terminar_devolve_o_registro_de_fitas(self) -> None:
        perfil = self.perfil("Roxo", "tuya:luz-1")
        self.assertTrue(self.coord.comecar(self.jogo("g1", perfil.id)))
        self.esperar()
        # Mesma resposta de ``comecar``: quem abriu a sessão precisa saber se
        # as fitas estavam sob controle do perfil ou do ciclo antigo.
        self.assertTrue(self.coord.terminar(self.jogo("g1", perfil.id)))
        self.esperar()
        self.assertEqual(self.arquivo.ler().ativos, [])


class TestProvedorAusente(Base):
    def test_plano_de_provedor_que_nao_existe_e_ignorado(self) -> None:
        perfil = self.perfil("Misto", "falso:luz-1", "outro:luz-2")
        self.coord.comecar(self.jogo("g1", perfil.id))
        self.esperar()
        self.assertEqual(self.provedor.pinturas, [Cor(9, 9, 9)])
        self.assertTrue(self.arquivo.ler().pendente)


if __name__ == "__main__":
    unittest.main()

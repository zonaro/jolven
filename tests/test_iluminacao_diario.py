# test_iluminacao_diario.py
#
# Copyright 2026 Jolven contributors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O diário da sessão: o que o Jolven emprestou e de quem era antes.

Pasta temporária explícita: este arquivo é lido na abertura e no fechamento e
não pode depender de ``shared.iluminacao_dir`` existir.
"""

import builtins
import json
import shutil
import tempfile
import unittest
from pathlib import Path

if not hasattr(builtins, "_"):
    builtins._ = lambda s: s  # type: ignore[attr-defined]

from cartridges.iluminacao.cores import Cor
from cartridges.iluminacao.diario import ARQUIVO, Arquivo, Ativo, Diario
from cartridges.iluminacao.modelo import Estado


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.pasta = Path(tempfile.mkdtemp(prefix="jolven-diario-"))
        self.addCleanup(shutil.rmtree, self.pasta, True)
        self.caminho = self.pasta / ARQUIVO
        self.arquivo = Arquivo(self.caminho)

    def estado(self, chave: str = "luz-1", **kwargs) -> Estado:
        padrao = {
            "provedor": "openrgb",
            "chave": chave,
            "nome": "Luz",
            "cor": Cor(1, 2, 3),
            "brilho": 55,
            "modo": "Direct",
        }
        padrao.update(kwargs)
        return Estado(**padrao)  # type: ignore[arg-type]


class TestDiarioEmMemoria(Base):
    def test_vazio_por_padrao(self) -> None:
        diario = Diario()
        self.assertFalse(diario.pendente)
        self.assertIsNone(diario.estado("openrgb:luz-1"))
        self.assertIsNone(diario.jogo_ativo("jogo"))

    def test_guardar_base(self) -> None:
        diario = Diario()
        diario.guardar_base(self.estado())
        self.assertTrue(diario.pendente)
        self.assertIsNotNone(diario.estado("openrgb:luz-1"))

    def test_guardar_base_nao_sobrescreve_o_primeiro(self) -> None:
        # O gravado é o estado de antes do Jolven mexer; o segundo seria a
        # própria cor do jogo e a devolução deixaria o dispositivo preso nela.
        diario = Diario()
        diario.guardar_base(self.estado(cor=Cor(10, 10, 10)))
        diario.guardar_base(self.estado(cor=Cor(200, 200, 200)))
        self.assertEqual(
            diario.estado("openrgb:luz-1").cor,  # type: ignore[union-attr]
            Cor(10, 10, 10),
        )

    def test_ativo_por_jogo(self) -> None:
        diario = Diario()
        diario.ativos.append(Ativo(jogo="g1", perfil="p1", fitas=True))
        ativo = diario.jogo_ativo("g1")
        self.assertIsNotNone(ativo)
        self.assertEqual(ativo.perfil, "p1")  # type: ignore[union-attr]
        self.assertTrue(ativo.fitas)  # type: ignore[union-attr]
        self.assertIsNone(diario.jogo_ativo("g2"))

    def test_ativo_sem_jogo_nao_entra(self) -> None:
        self.assertIsNone(Ativo.de_json({"perfil": "p1"}))
        self.assertIsNone(Ativo.de_json("não é dict"))

    def test_json_ida_e_volta(self) -> None:
        diario = Diario()
        diario.guardar_base(self.estado())
        diario.ativos.append(Ativo(jogo="g1", perfil="p1"))
        de_volta = Diario.de_json(diario.para_json())
        self.assertIsNotNone(de_volta)
        self.assertEqual(de_volta.para_json(), diario.para_json())  # type: ignore[union-attr]

    def test_estado_sem_provedor_nao_entra_na_base(self) -> None:
        diario = Diario.de_json({"base": {"x": {"chave": "sem provedor"}}})
        self.assertIsNotNone(diario)
        self.assertFalse(diario.pendente)  # type: ignore[union-attr]

    def test_json_torto_nao_vira_excecao(self) -> None:
        for bruto in (
            '[1,2]',
            '{"base": "não é dict"}',
            '{"base": {"k": 3}}',
            '{"ativos": "não é lista"}',
            '{"ativos": [3, {"jogo": ""}]}',
            "{}",
        ):
            with self.subTest(bruto=bruto):
                diario = Diario.de_json(json.loads(bruto))
                if diario is not None:
                    self.assertFalse(diario.pendente)
                    self.assertEqual(diario.ativos, [])


class TestArquivo(Base):
    def test_sem_arquivo_e_diario_vazio(self) -> None:
        self.assertFalse(self.arquivo.ler().pendente)
        self.assertFalse(self.caminho.exists())

    def test_gravar_e_ler(self) -> None:
        diario = Diario()
        diario.guardar_base(self.estado())
        diario.ativos.append(Ativo(jogo="g1", perfil="p1", fitas=True))
        self.assertTrue(self.arquivo.gravar(diario))
        lido = self.arquivo.ler()
        self.assertTrue(lido.pendente)
        self.assertEqual(lido.ativos[0].jogo, "g1")
        self.assertEqual(lido.estado("openrgb:luz-1").cor, Cor(1, 2, 3))  # type: ignore[union-attr]
        self.assertTrue(lido.sessao, "a sessão precisa ser identificada na gravação")

    def test_gravacao_e_atomica(self) -> None:
        self.arquivo.gravar(Diario())
        self.assertFalse((self.pasta / (ARQUIVO + ".tmp")).exists())

    def test_limpar_apaga_o_arquivo(self) -> None:
        self.arquivo.gravar(Diario())
        self.assertTrue(self.caminho.exists())
        self.arquivo.limpar()
        self.assertFalse(self.caminho.exists())
        self.assertFalse(self.arquivo.ler().pendente)

    def test_arquivo_corrompido_nao_levanta(self) -> None:
        self.caminho.write_text("{quebrado", encoding="utf-8")
        self.assertFalse(self.arquivo.ler().pendente)
        self.assertTrue(
            self.caminho.exists(), "o diário torto não é apagado na leitura"
        )

    def test_gravar_depois_de_leitura_torta_conserta(self) -> None:
        self.caminho.write_text("{quebrado", encoding="utf-8")
        self.arquivo.ler()
        self.assertTrue(self.arquivo.gravar(Diario()))
        dados = json.loads(self.caminho.read_text(encoding="utf-8"))
        self.assertEqual(dados["base"], {})
        self.assertEqual(dados["ativos"], [])

    def test_pasta_criada_na_hora(self) -> None:
        alvo = self.pasta / "nova" / "pasta" / ARQUIVO
        arquivo = Arquivo(alvo)
        self.assertTrue(arquivo.gravar(Diario()))
        self.assertTrue(alvo.is_file())

    def test_gravar_em_pasta_somente_leitura_nao_levanta(self) -> None:
        alvo = self.pasta / "so-leitura" / ARQUIVO
        alvo.parent.mkdir()
        alvo.parent.chmod(0o500)
        self.addCleanup(alvo.parent.chmod, 0o700)
        self.assertFalse(Arquivo(alvo).gravar(Diario()))

    def test_bruto_do_provedor_sobrevive(self) -> None:
        diario = Diario()
        diario.guardar_base(
            self.estado(provedor="tuya", chave="fita-1", bruto={"hsv": "120000100010"})
        )
        self.arquivo.gravar(diario)
        estado = self.arquivo.ler().estado("tuya:fita-1")
        self.assertEqual(estado.bruto, {"hsv": "120000100010"})  # type: ignore[union-attr]


if __name__ == "__main__":
    unittest.main()

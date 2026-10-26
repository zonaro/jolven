# test_iluminacao_perfis.py
#
# Copyright 2026 Jolven contributors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O repositório de perfis: gravação atômica, campos que sobrevivem, arquivo torto.

Tudo em pasta temporária explícita — nada aqui pode tocar
``shared.iluminacao_dir``, que só existe depois da instalação.
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
from cartridges.iluminacao.modelo import CoresDaZona, Plano
from cartridges.iluminacao.perfis import (
    ARQUIVO_CORROMPIDO,
    Perfil,
    Repositorio,
)


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.pasta = Path(tempfile.mkdtemp(prefix="jolven-perfis-"))
        self.addCleanup(shutil.rmtree, self.pasta, True)
        self.arquivo = self.pasta / "perfis.json"
        self.repo = Repositorio(self.arquivo)

    def perfil(self, nome: str = "WASD roxo", **kwargs) -> Perfil:
        perfil = self.repo.criar(nome)
        perfil.dispositivos.append(
            Plano(
                provedor="openrgb",
                chave="teclado-1",
                nome="Teclado",
                cor=Cor(0x91, 0x41, 0xAC),
                brilho=40,
                zonas=[CoresDaZona(zona="w", cor=Cor(1, 2, 3))],
            )
        )
        for chave, valor in kwargs.items():
            setattr(perfil, chave, valor)
        return perfil


class TestLeituraEscrita(Base):
    def test_sem_arquivo_e_lista_vazia(self) -> None:
        self.assertEqual(self.repo.carregar(), [])
        self.assertFalse(self.arquivo.exists())

    def test_criar_nao_grava_sozinho(self) -> None:
        perfil = self.repo.criar("Novo")
        self.assertFalse(self.arquivo.exists())
        self.assertEqual(perfil.nome, "Novo")
        self.assertEqual(len(perfil.id), 32)

    def test_gravar_e_reler(self) -> None:
        perfil = self.perfil()
        self.assertTrue(self.repo.salvar([perfil]))
        relidos = self.repo.carregar()
        self.assertEqual(len(relidos), 1)
        self.assertEqual(relidos[0].nome, "WASD roxo")
        self.assertEqual(relidos[0].dispositivos[0].cor, Cor(0x91, 0x41, 0xAC))
        self.assertEqual(relidos[0].dispositivos[0].zonas[0].cor, Cor(1, 2, 3))

    def test_gravacao_e_atomica(self) -> None:
        self.assertTrue(self.repo.salvar([self.perfil()]))
        self.assertFalse(
            (self.pasta / (self.arquivo.name + ".tmp")).exists(),
            "o temporário precisa sumir depois da troca",
        )

    def test_obter_por_id(self) -> None:
        perfil = self.perfil()
        self.repo.salvar([perfil])
        self.assertIsNotNone(self.repo.obter(perfil.id))
        self.assertIsNone(self.repo.obter("não-existe"))

    def test_gravar_substitui_pelo_id(self) -> None:
        perfil = self.perfil()
        self.repo.salvar([perfil])
        perfil.nome = "Outro nome"
        self.assertTrue(self.repo.gravar(perfil))
        relidos = self.repo.carregar()
        self.assertEqual(len(relidos), 1)
        self.assertEqual(relidos[0].nome, "Outro nome")

    def test_pasta_criada_na_hora(self) -> None:
        alvo = self.pasta / "aninhada" / "mais" / "perfis.json"
        repo = Repositorio(alvo)
        self.assertTrue(repo.salvar([Perfil(id="a", nome="A")]))
        self.assertTrue(alvo.is_file())


class TestOperacoes(Base):
    def test_duplicar_guarda_no_arquivo(self) -> None:
        original = self.perfil("Base")
        self.repo.salvar([original])
        copia = self.repo.duplicar(original.id)
        self.assertIsNotNone(copia)
        self.assertNotEqual(copia.id, original.id)  # type: ignore[union-attr]
        self.assertEqual(copia.nome, "Base (cópia)")  # type: ignore[union-attr]
        self.assertEqual(len(self.repo.carregar()), 2)
        # Os planos são copiados, não compartilhados.
        copia.dispositivos[0].cor = Cor(0, 0, 0)  # type: ignore[union-attr]
        self.assertEqual(self.repo.obter(original.id).dispositivos[0].cor, Cor(0x91, 0x41, 0xAC))  # type: ignore[union-attr]

    def test_duplicar_de_algo_que_nao_existe(self) -> None:
        self.assertIsNone(self.repo.duplicar("sumiu"))

    def test_renomear(self) -> None:
        perfil = self.perfil()
        self.repo.salvar([perfil])
        self.assertTrue(self.repo.renomear(perfil.id, "  Outro  "))
        self.assertEqual(self.repo.obter(perfil.id).nome, "Outro")  # type: ignore[union-attr]

    def test_renomear_para_vazio_e_recusado(self) -> None:
        perfil = self.perfil()
        self.repo.salvar([perfil])
        self.assertFalse(self.repo.renomear(perfil.id, "   "))
        self.assertEqual(self.repo.obter(perfil.id).nome, "WASD roxo")  # type: ignore[union-attr]

    def test_excluir(self) -> None:
        perfil = self.perfil()
        self.repo.salvar([perfil])
        self.assertTrue(self.repo.excluir(perfil.id))
        self.assertEqual(self.repo.carregar(), [])
        self.assertFalse(self.repo.excluir(perfil.id))

    def test_nome_em_uso_e_case_insensitive(self) -> None:
        self.repo.salvar([self.perfil("WASD roxo")])
        self.assertTrue(self.repo.nome_em_uso("  wasd ROXO  "))
        self.assertFalse(self.repo.nome_em_uso("Outro"))


class TestCamposDesconhecidos(Base):
    def test_chave_futura_no_perfil_sobrevive(self) -> None:
        bruto = {
            "schema_version": 1,
            "perfis": [
                {
                    "id": "abc",
                    "nome": "Futuro",
                    "descricao": "",
                    "criado": 1,
                    "alterado": 2,
                    "dispositivos": [],
                    "efeito_especial": "piscar",
                }
            ],
        }
        self.arquivo.write_text(json.dumps(bruto), encoding="utf-8")
        perfis = self.repo.carregar()
        self.assertEqual(perfis[0].extras.get("efeito_especial"), "piscar")
        self.assertTrue(self.repo.salvar(perfis))
        depois = json.loads(self.arquivo.read_text(encoding="utf-8"))
        self.assertEqual(depois["perfis"][0]["efeito_especial"], "piscar")

    def test_chave_futura_no_plano_sobrevive(self) -> None:
        bruto = {
            "perfis": [
                {
                    "id": "abc",
                    "nome": "Futuro",
                    "dispositivos": [
                        {"provedor": "openrgb", "chave": "k", "gama": 1.4}
                    ],
                }
            ],
        }
        self.arquivo.write_text(json.dumps(bruto), encoding="utf-8")
        perfil = self.repo.carregar()[0]
        self.assertEqual(perfil.dispositivos[0].extras.get("gama"), 1.4)
        self.assertTrue(self.repo.salvar([perfil]))
        depois = json.loads(self.arquivo.read_text(encoding="utf-8"))
        self.assertEqual(depois["perfis"][0]["dispositivos"][0]["gama"], 1.4)

    def test_versao_mais_nova_nao_e_regravada_por_engano(self) -> None:
        bruto = {"schema_version": 99, "perfis": [{"id": "a", "nome": "A"}]}
        self.arquivo.write_text(json.dumps(bruto), encoding="utf-8")
        # Lê o que entende e não toca no arquivo.
        self.assertEqual(len(self.repo.carregar()), 1)
        self.assertEqual(
            json.loads(self.arquivo.read_text(encoding="utf-8"))["schema_version"],
            99,
        )

    def test_perfil_sem_id_ou_nome_e_descartado(self) -> None:
        bruto = {
            "perfis": [
                {"id": "", "nome": "sem id"},
                {"id": "ok", "nome": ""},
                {"id": "ok", "nome": "bom"},
                "não é dict",
            ]
        }
        self.arquivo.write_text(json.dumps(bruto), encoding="utf-8")
        self.assertEqual([p.nome for p in self.repo.carregar()], ["bom"])


class TestArquivoTorto(Base):
    def test_json_invalido_devolve_vazio_sem_apagar(self) -> None:
        self.arquivo.write_text("{isso não é json", encoding="utf-8")
        self.assertEqual(self.repo.carregar(), [])
        self.assertTrue(self.arquivo.exists())
        # A cópia sai na leitura, antes de qualquer gravação.
        copia = self.pasta / ARQUIVO_CORROMPIDO
        self.assertTrue(copia.exists())
        self.assertEqual(copia.read_text(encoding="utf-8"), "{isso não é json")

    def test_primeira_gravacao_apos_leitura_torta_nao_destruiu_a_original(self) -> None:
        original = "{isso não é json"
        self.arquivo.write_text(original, encoding="utf-8")
        self.assertEqual(self.repo.carregar(), [])
        self.assertTrue(self.repo.salvar([self.perfil("novo")]))
        self.assertEqual(
            (self.pasta / ARQUIVO_CORROMPIDO).read_text(encoding="utf-8"), original
        )

    def test_nao_dict_tambem_e_preservado(self) -> None:
        self.arquivo.write_text("[1, 2, 3]", encoding="utf-8")
        self.assertEqual(self.repo.carregar(), [])
        self.assertTrue((self.pasta / ARQUIVO_CORROMPIDO).exists())

    def test_bloco_perfis_faltando_e_lista_vazia(self) -> None:
        self.arquivo.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
        self.assertEqual(self.repo.carregar(), [])

    def test_pasta_de_somente_leitura_nao_levanta(self) -> None:
        # Um repositório que não consegue gravar devolve False e é isso.
        alvo = self.pasta / "so-leitura" / "perfis.json"
        alvo.parent.mkdir()
        alvo.parent.chmod(0o500)
        self.addCleanup(alvo.parent.chmod, 0o700)
        repo = Repositorio(alvo)
        self.assertFalse(repo.salvar([Perfil(id="a", nome="A")]))


if __name__ == "__main__":
    unittest.main()

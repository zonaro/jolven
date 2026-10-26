# test_iluminacao_modelo.py
#
# Copyright 2026 Jolven contributors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O modelo de iluminação: cores, planos e as chaves estáveis.

Sem GTK, sem rede, sem GSettings: só as estruturas que atravessam perfil,
diário e provedores.
"""

import builtins
import unittest

if not hasattr(builtins, "_"):
    builtins._ = lambda s: s  # type: ignore[attr-defined]

from cartridges.iluminacao.cores import BRANCO, PRETO, Cor, do_app
from cartridges.iluminacao.modelo import (
    APAGAR,
    CATEGORIAS,
    MANTER,
    PINTAR,
    Alvo,
    CoresDaZona,
    Estado,
    Plano,
    Zona,
    chave_do_dispositivo,
    desempatar_chaves,
    zona_de,
)


class TestCor(unittest.TestCase):
    def test_hex_ida_e_volta(self) -> None:
        self.assertEqual(Cor(0x91, 0x41, 0xAC).como_hex(), "#9141ac")
        self.assertEqual(Cor.de_hex("#9141ac"), Cor(0x91, 0x41, 0xAC))
        self.assertEqual(Cor.de_hex("9141ac"), Cor(0x91, 0x41, 0xAC))

    def test_hex_curto_e_lixo(self) -> None:
        self.assertEqual(Cor.de_hex("#f0a"), Cor(0xFF, 0x00, 0xAA))
        self.assertEqual(Cor.de_hex("não é cor"), PRETO)
        self.assertEqual(Cor.de_hex(None, BRANCO), BRANCO)

    def test_canais_sao_apertados_para_0_255(self) -> None:
        self.assertEqual(Cor(900, -3, 12.7), Cor(255, 0, 12))

    def test_hsv_usa_o_brilho_do_plano_nao_da_cor(self) -> None:
        matiz, saturacao, valor = Cor(255, 0, 0).como_hsv(50)
        self.assertEqual(matiz, 0)
        self.assertEqual(saturacao, 1000)
        self.assertEqual(valor, 500)

    def test_hsv_zero_e_apagado(self) -> None:
        # 0% do plano é luz desligada, não uma sombra: a Tuya não tem "meio off".
        self.assertEqual(Cor(255, 0, 0).como_hsv(0)[2], 0)
        self.assertEqual(Cor(255, 0, 0).como_hsv(100)[2], 1000)

    def test_com_valor_preserva_o_matiz(self) -> None:
        metade = Cor(200, 100, 50).com_valor(50)
        self.assertEqual(metade, Cor(100, 50, 25))

    def test_distante_de(self) -> None:
        self.assertTrue(Cor(0, 0, 0).distante_de(Cor(255, 255, 255)) > 0)
        self.assertEqual(Cor(1, 1, 1).distante_de(Cor(1, 1, 1)), 0)

    def test_cor_do_app_e_a_do_jolven(self) -> None:
        self.assertEqual(do_app(), Cor(0x91, 0x41, 0xAC))


class TestChaves(unittest.TestCase):
    def test_chave_do_dispositivo_e_estavel(self) -> None:
        uma = chave_do_dispositivo(
            "openrgb", tipo="placa-mae", fabricante="ASUS", nome="Prime B550"
        )
        outra = chave_do_dispositivo(
            "openrgb", tipo="placa-mae", fabricante="ASUS", nome="Prime B550"
        )
        self.assertEqual(uma, outra)
        self.assertTrue(uma.startswith("openrgb:"))
        # A localização só é passada para desempatar dois iguais; quem não a
        # passa continua com a chave de antes, ou seja, o perfil salvo não cai.
        self.assertNotEqual(
            uma,
            chave_do_dispositivo(
                "openrgb",
                tipo="placa-mae",
                fabricante="ASUS",
                nome="Prime B550",
                localizacao="PCIe 1",
            ),
        )

    def test_chave_com_serie_e_outra_coisa(self) -> None:
        com_serie = chave_do_dispositivo("openrgb", nome="Teclado", serie="ABC")
        sem_serie = chave_do_dispositivo("openrgb", nome="Teclado")
        self.assertNotEqual(com_serie, sem_serie)

    def test_plano_identificador_e_provedor_dois_pontos_chave(self) -> None:
        self.assertEqual(Plano("openrgb", "MB-01").identificador, "openrgb:MB-01")

    def test_desempatar_sai_do_caminho_quando_nao_ha_choque(self) -> None:
        chaves = ["openrgb:1", "openrgb:2"]
        self.assertEqual(desempatar_chaves(chaves), chaves)

    def test_desempatar_sufixa_so_o_que_repete(self) -> None:
        self.assertEqual(
            desempatar_chaves(["k", "k", "outro", "k"]),
            ["k#1", "k#2", "outro", "k#3"],
        )

    def test_zona_de(self) -> None:
        zonas = (
            _zona("cima", 10),
            _zona("baixo", 5),
        )
        self.assertEqual(zona_de(_alvo(zonas=zonas), "baixo").total, 5)  # type: ignore[union-attr]
        self.assertIsNone(zona_de(_alvo(zonas=zonas), "inexistente"))


class TestPlano(unittest.TestCase):
    def test_vazio_so_quando_nao_manda_nada(self) -> None:
        self.assertTrue(Plano("openrgb", "x").vazio)
        self.assertFalse(Plano("openrgb", "x", cor=PRETO).vazio)
        self.assertFalse(Plano("openrgb", "x", brilho=40).vazio)
        self.assertFalse(Plano("openrgb", "x", modo="Direct").vazio)
        self.assertFalse(Plano("openrgb", "x", padrao=APAGAR).vazio)
        self.assertFalse(
            Plano("openrgb", "x", zonas=[CoresDaZona(zona="a", cor=PRETO)]).vazio
        )

    def test_brilho_efetivo(self) -> None:
        self.assertEqual(Plano("t", "x").brilho_efetivo(), 100)
        self.assertEqual(Plano("t", "x", brilho=40).brilho_efetivo(), 40)
        self.assertEqual(Plano("t", "x", brilho=999).brilho_efetivo(), 100)
        self.assertEqual(Plano("t", "x", brilho=0).brilho_efetivo(), 1)

    def test_json_ida_e_volta(self) -> None:
        plano = Plano(
            provedor="openrgb",
            chave="MB-01",
            nome="Placa-mãe",
            cor=Cor(1, 2, 3),
            brilho=70,
            modo="Direct",
            padrao=PINTAR,
            zonas=[CoresDaZona(zona="z1", cor=Cor(4, 5, 6), leds={2: Cor(7, 8, 9)})],
        )
        de_volta = Plano.de_json(plano.para_json())
        self.assertIsNotNone(de_volta)
        self.assertEqual(de_volta.para_json(), plano.para_json())  # type: ignore[union-attr]
        self.assertEqual(de_volta.zonas[0].leds[2], Cor(7, 8, 9))  # type: ignore[union-attr]

    def test_json_preserva_chaves_desconhecidas(self) -> None:
        bruto = {
            "provedor": "openrgb",
            "chave": "x",
            "futuro": {"novo": True},
            "zonas": [{"zona": "a", "futuro_zona": 1}],
        }
        plano = Plano.de_json(bruto)
        self.assertEqual(plano.para_json()["futuro"], {"novo": True})  # type: ignore[union-attr]
        self.assertEqual(plano.para_json()["zonas"][0]["futuro_zona"], 1)  # type: ignore[union-attr]

    def test_json_sem_provedor_ou_chave_e_lixo(self) -> None:
        self.assertIsNone(Plano.de_json({}))
        self.assertIsNone(Plano.de_json({"provedor": "openrgb"}))
        self.assertIsNone(Plano.de_json("não é um dict"))

    def test_brilho_torto_nao_explode(self) -> None:
        plano = Plano.de_json({"provedor": "t", "chave": "x", "brilho": "muito"})
        self.assertIsNone(plano.brilho)  # type: ignore[union-attr]

    def test_constantes_de_padrao(self) -> None:
        self.assertEqual((MANTER, APAGAR, PINTAR), ("manter", "apagar", "pintar"))


class TestEstado(unittest.TestCase):
    def test_estado_json_ida_e_volta(self) -> None:
        estado = Estado(
            provedor="tuya",
            chave="f1",
            nome="Fita",
            cor=Cor(9, 9, 9),
            brilho=30,
            modo="Direct",
            leds=[Cor(1, 1, 1), Cor(2, 2, 2)],
            bruto={"hsv": "1200001000"},
        )
        de_volta = Estado.de_json(estado.para_json())
        self.assertEqual(de_volta.para_json(), estado.para_json())  # type: ignore[union-attr]
        self.assertEqual(de_volta.bruto, {"hsv": "1200001000"})  # type: ignore[union-attr]

    def test_estado_sem_provedor_nao_entra_no_diario(self) -> None:
        self.assertIsNone(Estado.de_json({"chave": "x"}))


class TestAlvo(unittest.TestCase):
    def test_rotulo_de_categoria_desconhecia_cai_em_outro(self) -> None:
        self.assertEqual(_alvo(categoria="categoria-nova").rotulo_categoria, "Outro")

    def test_categorias_sao_traduziveis_e_estaveis(self) -> None:
        chaves = [chave for chave, _rotulo in CATEGORIAS]
        self.assertIn("memoria", chaves)
        self.assertIn("gabinete", chaves)
        self.assertEqual(len(chaves), len(set(chaves)), "chave de categoria repetida")

    def test_total_leds_prefere_as_zonas(self) -> None:
        alvo = _alvo(zonas=(_zona("a", 10), _zona("b", 5)))
        self.assertEqual(alvo.total_leds, 15)
        self.assertTrue(alvo.por_led)
        self.assertFalse(_alvo().por_led)


def _zona(chave: str, total: int) -> "Zona":
    return Zona(chave=chave, nome=chave, leds=tuple(f"led{i}" for i in range(total)))


def _alvo(**kwargs) -> Alvo:
    padrao = {"provedor": "openrgb", "chave": "k", "nome": "Dispositivo"}
    padrao.update(kwargs)
    return Alvo(**padrao)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()

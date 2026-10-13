"""Rótulos de estado da skin da Steam (sem GTK: só o backend).

A página de preferências deriva seus rótulos de ``recovery.TEXTOS_ESTADO``;
estes testes garantem que os oito :class:`Estado` têm rótulo, que entradas
legadas (dicts e chaves em inglês) ainda resolvem e que o desconhecido tem
recuo. A Steam real nunca é tocada.
"""

import unittest

from cartridges.integrations.steam_skin.recovery import (
    Estado,
    texto_do_estado,
)


class RotulosTests(unittest.TestCase):
    ESPERADOS = {
        Estado.NAO_ENCONTRADA: "Steam não encontrada",
        Estado.NAO_INSTALADA: "Skin não instalada",
        Estado.SINCRONIZADA: "Sincronizada",
        Estado.ATUALIZACAO_NECESSARIA: "Atualização necessária",
        Estado.AGUARDANDO_REINICIO: "Aguarde reiniciar a Steam",
        Estado.INCOMPATIVEL: "Instalação incompatível",
        Estado.PERMISSAO: "Erro de permissão",
        Estado.CONFLITO_TERCEIROS: "Há outra personalização na Steam",
    }

    def test_todos_os_oito_estados_tem_rotulo(self):
        self.assertEqual(len(self.ESPERADOS), 8)
        for estado, rotulo in self.ESPERADOS.items():
            with self.subTest(estado=estado):
                self.assertEqual(texto_do_estado(estado), rotulo)

    def test_rotulos_sao_distintos_e_conhecidos(self):
        rotulos = [texto_do_estado(estado) for estado in Estado]
        self.assertEqual(len(set(rotulos)), len(list(Estado)))
        self.assertNotIn("Estado desconhecido", rotulos)

    def test_valores_crus_resolvem(self):
        for estado in Estado:
            with self.subTest(estado=estado):
                self.assertEqual(
                    texto_do_estado(estado.value),
                    texto_do_estado(estado),
                )

    def test_chaves_legadas_em_ingles_resolvem(self):
        legadas = {
            "not_found": Estado.NAO_ENCONTRADA,
            "not_installed": Estado.NAO_INSTALADA,
            "synced": Estado.SINCRONIZADA,
            "update_needed": Estado.ATUALIZACAO_NECESSARIA,
            "awaiting_restart": Estado.AGUARDANDO_REINICIO,
            "incompatible": Estado.INCOMPATIVEL,
            "permission_error": Estado.PERMISSAO,
            "conflict": Estado.CONFLITO_TERCEIROS,
        }
        self.assertEqual(len(legadas), 8)
        for chave, estado in legadas.items():
            with self.subTest(chave=chave):
                self.assertEqual(texto_do_estado(chave), texto_do_estado(estado))

    def test_dicts_legados_resolvem(self):
        self.assertEqual(
            texto_do_estado({"estado": Estado.SINCRONIZADA}),
            texto_do_estado(Estado.SINCRONIZADA),
        )
        self.assertEqual(
            texto_do_estado({"state": "synced"}),
            texto_do_estado(Estado.SINCRONIZADA),
        )
        self.assertEqual(
            texto_do_estado({"status": "incompativel"}),
            texto_do_estado(Estado.INCOMPATIVEL),
        )
        self.assertEqual(
            texto_do_estado({"message": "texto livre do backend"}),
            "texto livre do backend",
        )
        self.assertEqual(
            texto_do_estado({"mensagem": "outro texto livre"}),
            "outro texto livre",
        )

    def test_desconhecido_tem_recuo(self):
        for estranho in ("xyz", "", None, 42, {}, {"estado": None}):
            with self.subTest(entrada=estranho):
                self.assertEqual(texto_do_estado(estranho), "Estado desconhecido")


if __name__ == "__main__":
    unittest.main()

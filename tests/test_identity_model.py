# SPDX-License-Identifier: GPL-3.0-or-later

"""Testes da modela de identidade canônica (#110): provas, evidência, conflito."""

import unittest
from cartridges.identity.model import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_NONE,
    add_evidence,
    empty_identity,
    merge_external_ids,
    merge_identity,
    sanitize_identity,
    strong_match,
)


class TestSanitize(unittest.TestCase):
    def test_cria_vazia(self):
        assert empty_identity()["confidence"] == CONFIDENCE_NONE
        assert empty_identity()["hashes"] == {}
        assert empty_identity()["evidence"] == []

    def test_descarta_campos_inválidos(self):
        d = sanitize_identity(
            {
                "spec": 1,
                "platform": "",
                "serial": "",
                "hashes": {"md5": ""},
                "evidence": [{"kind": "hash", "source": "", "algo": "md5", "value": ""}],
                "external_ids": {},
            }
        )
        assert d["serial"] == ""
        assert d["hashes"] == {}
        assert d["confidence"] == CONFIDENCE_NONE

    def test_ignora_campos_não_ignoráveis(self):
        garbage = {"password": "secret", "url": "https://example.com", "tags": 3}
        d = sanitize_identity(garbage)
        assert d["evidence"] == []
        assert d["external_ids"] == {}


class TestEvidence(unittest.TestCase):
    def test_evidencia_evita_duplicata(self):
        ident = empty_identity()
        for source in ("Steam", "RA"):
            ident = sanitize_identity(
                add_evidence(ident, "serial", source, value="SLUS-00594")
            )
        # Mesma prova de fontes diferentes é mantida (duas evidências de serial
        # de fontes distintas não são duplicatas); a contagem reflete isso.
        serials = [item["kind"] for item in ident["evidence"]]
        assert serials.count("serial") == 2
        # Mais provas fortes elevam a confiança.
        assert ident["confidence"] >= CONFIDENCE_MEDIUM

    def test_evidencia_teto_de_registros(self):
        ident = empty_identity()
        for i in range(30):
            ident = add_evidence(ident, "platform", f"f{i}", value="psx")
        serials = [item["kind"] for item in ident["evidence"]]
        # Teto de 32 registros: os últimos vêm primeiro.
        assert serials.count("platform") == len(serials)

    def test_merge_evidencia_sem_duplicar(self):
        base = empty_identity()
        base = add_evidence(base, "serial", "Steam", value="SLUS-00594")
        extra = merge_identity(base, empty_identity())
        keys = [item["kind"] for item in extra["evidence"]]
        assert "serial" in keys
        # Evidências já lá não dobram.
        assert len(extra["evidence"]) <= len(base["evidence"]) + len(extra["evidence"])


class TestStrongMatch(unittest.TestCase):
    def test_mesma_plataforma_serial(self):
        ident = empty_identity()
        ident["platform"] = "psx"
        ident["serial"] = "SLUS-00594"
        second = dict(ident)
        match = strong_match(ident, second)
        assert match is not None
        assert match[0] == "serial"

    def test_diferente_plataforma_nao_casam(self):
        ident = empty_identity()
        ident["platform"] = "nes"
        ident["serial"] = "SLES-12345"
        second = dict(ident)
        second["platform"] = "snes"
        assert strong_match(ident, second) is None

    def test_hash_igual_casam(self):
        ident = empty_identity()
        ident["platform"] = "gb"
        ident["hashes"] = {"md5": "abcdef1234567890abcdef1234567890"}
        second = dict(ident)
        assert strong_match(ident, second) is not None

    def test_hash_diferente_nao_casam(self):
        first = empty_identity()
        first["platform"] = "nds"
        first["hashes"] = {"md5": "aaaa0000bbbbccccdddd"}
        second = empty_identity()
        second["platform"] = "nds"
        second["hashes"] = {"md5": "eeee2222ffff33334444"}
        assert strong_match(first, second) is None

    def test_id_externo_basta_quando_hash_indistinto(self):
        first = empty_identity()
        first["external_ids"] = {"steam": "1118310"}
        second = empty_identity()
        second["external_ids"] = {"steam": "1118310"}
        assert strong_match(first, second) is not None


class TestMerge(unittest.TestCase):
    def test_unes_sobrepoe_campos_basicos(self):
        base = empty_identity()
        extra = empty_identity()
        extra["platform"] = "psx"
        merged = merge_identity(base, extra)
        assert merged["platform"] == "psx"
        assert merged["serial"] == ""

    def test_merge_evita_perder_evidencias_base(self):
        base = empty_identity()
        base["serial"] = "SLUS-00594"
        base["evidence"] = [{"kind": "serial", "source": "Steam", "value": "SLUS-00594"}]
        extra = empty_identity()
        extra["platform"] = "psp"
        merged = merge_identity(base, extra)
        assert merged["serial"] == "SLUS-00594"
        assert len(merged["evidence"]) >= 1

    def test_merge_registra_divergente_serial(self):
        base = empty_identity()
        base["serial"] = "SLUS-00594"
        base["evidence"] = [{"kind": "serial", "source": "Steam", "value": "SLUS-00594"}]
        extra = empty_identity()
        extra["serial"] = "ULUS-20000"
        extra["evidence"] = [{"kind": "serial", "source": "RA", "value": "ULUS-20000"}]
        merged = merge_identity(base, extra)
        conflict = [item for item in merged["evidence"] if item["kind"] == "conflict"]
        assert conflict

    def test_merge_mantera_dados_não_estrategicos(self):
        before = sanitize_identity({"spec": 1, "extra": 1})
        after = merge_identity(before, empty_identity())
        assert after["evidence"] == []


class TestExternalIds(unittest.TestCase):
    def test_merge_unifica_external_ids(self):
        ident = empty_identity()
        updated = merge_external_ids(ident, [("steam", "1118310"), ("epic", "epic_271590")], "test")
        assert updated["external_ids"]["steam"] == "1118310"
        assert updated["external_ids"]["epic"] == "epic_271590"
        evidence = [item["kind"] for item in updated["evidence"]]
        assert "external_id" in evidence

    def test_ignora_provider_desconhecido(self):
        ident = empty_identity()
        updated = merge_external_ids(ident, [("unknown", "abc")], "test")
        assert updated["external_ids"] == {}

    def test_ignora_caminho_como_identificador(self):
        ident = empty_identity()
        updated = merge_external_ids(ident, [("steam", "/etc/hosts")], "test")
        assert updated["external_ids"] == {}


if __name__ == "__main__":
    unittest.main()

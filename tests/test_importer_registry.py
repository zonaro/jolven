"""Registro central das fontes de importação e callback de conclusão (#71).

O botão Atualizar passou a reimportar todas as plataformas; para isso a lista
de fontes que o importador usa e a que a tela de Preferências mostra precisam
ser a mesma. Estes testes fixam a lista, o filtro pelo schema e o gancho que
encadeia o catálogo do xCloud depois da importação.

Importar o importador puxa a cadeia de widgets do GTK, que carrega texturas do
GResource compilado no import. Sem o app compilado o processo aborta, então o
recurso é registrado primeiro e o teste é pulado quando ele não existe.
"""

import builtins
import unittest
from pathlib import Path

if not hasattr(builtins, "_"):
    builtins._ = lambda s: s  # type: ignore[attr-defined]

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gio  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def _register_gresource():
    """Registra o GResource compilado; sem ele, pula o teste."""
    candidates = [
        ROOT / "build" / "data" / "jolven.gresource",
        Path.home() / ".local" / "share" / "jolven" / "jolven.gresource",
        Path("/usr/local/share/jolven/jolven.gresource"),
        Path("/usr/share/jolven/jolven.gresource"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            Gio.Resource.load(str(candidate))._register()
            return
    raise unittest.SkipTest(
        "needs the built app: no jolven.gresource found"
    )


class SourceRegistryTests(unittest.TestCase):
    def setUp(self):
        _register_gresource()
        from cartridges.importer import registry

        self.registry = registry

    def test_every_supported_source_is_registered_once(self):
        ids = [klass.source_id for klass in self.registry.SOURCE_CLASSES]
        self.assertEqual(len(ids), len(set(ids)), "fonte registrada em duplicidade")
        self.assertIn("waydroid", ids)
        self.assertIn("steam", ids)

    def test_registered_ids_are_schema_keys(self):
        """O ``source_id`` é a chave que liga a fonte nas preferências."""
        schema = (ROOT / "data" / "io.github.zonaro.Jolven.gschema.xml.in").read_text(
            encoding="utf-8"
        )
        for klass in self.registry.SOURCE_CLASSES:
            self.assertIn(
                f'<key name="{klass.source_id}" type="b">',
                schema,
                f"{klass.source_id} não tem chave no schema",
            )

    def test_enabled_sources_follow_the_schema(self):
        class _Schema:
            def __init__(self, enabled):
                self.enabled = enabled

            def get_boolean(self, key):
                return key in self.enabled

        classes = self.registry.enabled_source_classes(_Schema({"steam", "lutris"}))
        self.assertEqual(
            sorted(klass.source_id for klass in classes), ["lutris", "steam"]
        )

    def test_build_sources_instantiates_only_enabled_sources(self):
        class _Schema:
            def get_boolean(self, key):
                return key == "steam"

        sources = self.registry.build_sources(_Schema())
        self.assertEqual([source.source_id for source in sources], ["steam"])

    def test_a_broken_source_does_not_drop_the_others(self):
        class _Broken:
            source_id = "broken"

            def __init__(self):
                raise RuntimeError("boom")

        class _Schema:
            def get_boolean(self, _key):
                return True

        original = self.registry.SOURCE_CLASSES
        self.registry.SOURCE_CLASSES = (*original, _Broken)
        self.addCleanup(setattr, self.registry, "SOURCE_CLASSES", original)

        sources = self.registry.build_sources(_Schema())
        self.assertEqual(len(sources), len(original))


class ImporterFinishedCallbackTests(unittest.TestCase):
    def setUp(self):
        _register_gresource()
        from cartridges.errors.error_producer import ErrorProducer
        from cartridges.importer.importer import Importer

        self.Importer = Importer
        self.importer = Importer.__new__(Importer)
        ErrorProducer.__init__(self.importer)

    def test_callback_runs_once(self):
        chamadas = []
        self.importer.on_finished = lambda: chamadas.append("fim")

        self.importer.notify_finished()
        self.importer.notify_finished()

        self.assertEqual(chamadas, ["fim"])

    def test_callback_errors_do_not_escape_the_importer(self):
        def explode():
            raise RuntimeError("callback quebrado")

        self.importer.on_finished = explode
        self.importer.notify_finished()
        self.assertIsNone(self.importer.on_finished)

    def test_without_callback_nothing_happens(self):
        importer = self.Importer.__new__(self.Importer)
        importer.notify_finished()

    def test_finish_import_notifies_after_the_ui_settles(self):
        """O gancho fica no fim de ``finish_import``, não no meio.

        Sem isso o trabalho encadeado rodaria com o diálogo modal ainda aberto
        e o estado da aplicação ainda em ``IMPORT``.
        """
        fonte = (ROOT / "cartridges" / "importer" / "importer.py").read_text(
            encoding="utf-8"
        )
        corpo = fonte[
            fonte.index("def finish_import(") : fonte.index("def remove_games(")
        ]
        self.assertIn("state = shared.AppState.DEFAULT", corpo)
        self.assertLess(
            corpo.index("state = shared.AppState.DEFAULT"),
            corpo.index("self.notify_finished()"),
        )


class ImportActionWiringTests(unittest.TestCase):
    def setUp(self):
        _register_gresource()
        from cartridges.importer import registry

        self.registry = registry

    def test_import_action_uses_the_registry(self):
        fonte = (ROOT / "cartridges" / "main.py").read_text(encoding="utf-8")
        corpo = fonte[
            fonte.index("def on_import_action(")
            : fonte.index("def on_remove_game_action(")
        ]
        self.assertIn("build_sources()", corpo)
        self.assertIn("on_finished=on_finished", corpo)
        # Nada de lista paralela escrita à mão.
        self.assertNotIn("add_source(", corpo)

    def test_preferences_reuses_the_registry(self):
        fonte = (ROOT / "cartridges" / "preferences.py").read_text(encoding="utf-8")
        self.assertIn("for source_class in SOURCE_CLASSES:", fonte)
        self.assertIn(
            "from cartridges.importer.registry import SOURCE_CLASSES", fonte
        )

    def test_every_source_but_desktop_has_a_preferences_row(self):
        """Registrar uma fonte nova exige a expander row correspondente.

        O laço das preferências lê o registro e ignora quem não tem linha, então
        sem esta checagem uma fonte nova passaria despercebida na tela.
        """
        blp = (ROOT / "data" / "gtk" / "preferences.blp").read_text(
            encoding="utf-8"
        )
        sem_linha = [
            klass.source_id
            for klass in self.registry.SOURCE_CLASSES
            if klass.source_id != "desktop"
            and f"Adw.ExpanderRow {klass.source_id}_expander_row" not in blp
        ]
        self.assertEqual(sem_linha, [])


if __name__ == "__main__":
    unittest.main()

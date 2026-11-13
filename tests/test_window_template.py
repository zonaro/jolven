import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]


class WindowLibraryRefreshTests(unittest.TestCase):
    """O botão Atualizar reimporta plataformas e jogos, não só o xCloud (#71)."""

    def test_refresh_widgets_declared_and_in_blueprint(self) -> None:
        py = (ROOT / "cartridges" / "window.py").read_text(encoding="utf-8")
        blp = (ROOT / "data" / "gtk" / "window.blp").read_text(encoding="utf-8")
        for widget in ("library_refresh_button", "library_refresh_spinner"):
            self.assertIn(widget, py)
            self.assertIn(widget, blp)
        self.assertIn("_on_library_refresh_clicked", py)
        self.assertIn("_on_library_refresh_imported", py)
        self.assertIn("_xcloud_sync_done", py)
        self.assertIn("_xcloud_sync_failed", py)

    def test_refresh_button_is_always_visible(self) -> None:
        """Antes ele só existia para o xCloud; agora vale para toda a biblioteca."""
        blp = (ROOT / "data" / "gtk" / "window.blp").read_text(encoding="utf-8")
        start = blp.index("Button library_refresh_button {")
        bloco = blp[start : blp.index("}", start)]
        self.assertNotIn("visible: false", bloco)

    def test_refresh_runs_an_import_and_chains_the_xcloud_sync(self) -> None:
        py = (ROOT / "cartridges" / "window.py").read_text(encoding="utf-8")
        self.assertIn(
            "on_import_action(on_finished=self._on_library_refresh_imported)", py
        )
        # Sem importação disparada pelo botão, nada de catálogo é sincronizado.
        self.assertIn("sync_async(", py)

    def test_filter_func_does_not_touch_library_child(self) -> None:
        py = (ROOT / "cartridges" / "window.py").read_text(encoding="utf-8")
        start = py.index("def filter_func(")
        end = py.index("def set_active_game(")
        body = py[start:end]
        self.assertNotIn("set_library_child", body)


class WindowRecorderToggleTests(unittest.TestCase):
    def test_recorder_wiring_and_fallback(self) -> None:
        py = (ROOT / "cartridges" / "window.py").read_text(encoding="utf-8")
        blp = (ROOT / "data" / "gtk" / "window.blp").read_text(encoding="utf-8")
        self.assertIn("from cartridges.utils.na_tela import entregar_na_tela", py)
        self.assertIn("RecorderService", py)
        self.assertIn("_recorder_action", py)
        self.assertIn("on_save_recorder_replay", py)
        self.assertNotIn("_launch_external_recorder", py)
        self.assertNotIn("gpu_screen_recorder.launch", py)
        self.assertIn("_valid_stream_url", py)
        self.assertNotIn("shell=True", py)
        self.assertIn("gpu_screen_recorder_button", blp)
        self.assertNotIn("Abrir o GPU Screen Recorder", blp)


class WindowNewsPortalTests(unittest.TestCase):
    """A página de Novidades é um portal: carrossel, grade de cards e lista."""

    PORTAL_WIDGETS = (
        "news_sources_button",
        "news_highlights_section",
        "news_highlights_title",
        "news_highlights_carousel",
        "news_highlights_indicator",
        "news_recent_section",
        "news_recent_title",
        "news_recent_flowbox",
        "news_list_section",
        "news_list_title",
    )

    def test_portal_widgets_declared_and_in_blueprint(self) -> None:
        py = (ROOT / "cartridges" / "window.py").read_text(encoding="utf-8")
        blp = (ROOT / "data" / "gtk" / "window.blp").read_text(encoding="utf-8")
        for widget in self.PORTAL_WIDGETS:
            self.assertIn(widget, py)
            self.assertIn(widget, blp)

    def test_blueprint_uses_a_carousel_with_indicator(self) -> None:
        blp = (ROOT / "data" / "gtk" / "window.blp").read_text(encoding="utf-8")
        self.assertIn("Adw.Carousel news_highlights_carousel", blp)
        self.assertIn("Adw.CarouselIndicatorDots", blp)
        self.assertIn("carousel: news_highlights_carousel", blp)

    def test_three_tiers_are_built_from_the_cached_posts(self) -> None:
        py = (ROOT / "cartridges" / "window.py").read_text(encoding="utf-8")
        for method in (
            "rebuild_news_highlights",
            "rebuild_news_cards",
            "rebuild_news_list",
        ):
            self.assertIn(method, py)
        self.assertIn("_NEWS_HIGHLIGHTS", py)
        self.assertIn("_NEWS_RECENT", py)

    def test_source_filter_uses_stateful_actions(self) -> None:
        py = (ROOT / "cartridges" / "window.py").read_text(encoding="utf-8")
        # Um item de menu só vira caixinha de seleção se a ação tiver estado.
        self.assertIn("Gio.SimpleAction.new_stateful", py)
        self.assertIn("set_source_enabled", py)
        self.assertIn("rebuild_news_sources_menu", py)

    def test_source_filter_menu_items_use_qualified_action_names(self) -> None:
        """O muxer do GTK só resolve "grupo.ação"; um nome cru nasce morto.

        Sem o prefixo "win." o GtkMenuTracker deixa a ação "missing from
        the start": a linha nasce insensível e o clique nunca chega ao
        change-state — o menu parece não ligar nem desligar nada. Os
        demais menus do arquivo já usam "win."/"app.".
        """
        py = (ROOT / "cartridges" / "window.py").read_text(encoding="utf-8")
        self.assertIn('section.append(source, f"win.{name}")', py)

    def test_news_css_avoids_properties_gtk_css_rejects(self) -> None:
        """O CSS do GTK recusa propriedades de widget e quebra o arquivo.

        max-width, overflow, xalign e ellipsize não existem no CSS do GTK: se
        aparecerem, o provedor loga erro de parsing e descarta a regra inteira
        (os cards perdem raio, borda e hover sem que nada quebre em código).
        """
        css = (ROOT / "data" / "gtk" / "style.css").read_text(encoding="utf-8")
        marker = "── Novidades: cards"
        self.assertIn(marker, css)
        # Só as declarações valem: o próprio comentário do bloco avisa contra
        # essas propriedades e citaria os nomes. O marcador fica dentro do
        # comentário, então a referência é a primeira regra real do bloco.
        declaracoes = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        news_css = declaracoes[declaracoes.index(".news-hero-card {") :]
        for rejected in ("max-width", "overflow:", "xalign", "ellipsize"):
            self.assertNotIn(rejected, news_css)

    def test_news_sections_are_vertical_boxes(self) -> None:
        """Gtk.Box é horizontal por padrão: sem orientation as seções ficam lado a lado."""
        blp = (ROOT / "data" / "gtk" / "window.blp").read_text(encoding="utf-8")
        for section in (
            "news_highlights_section",
            "news_recent_section",
            "news_list_section",
        ):
            start = blp.index(f"Box {section} {{")
            bloco = blp[start : blp.index("}", start)]
            self.assertIn("orientation: vertical", bloco, section)

    def test_hero_page_fills_the_carousel(self) -> None:
        """O Adw.Carousel centraliza página mais estreita que ele.

        Com largura fixa, a folga (largura - página)/2 vira espaço morto nas
        pontas e o card seguinte aparece cortado na borda do carrossel: a
        página precisa expandir para ocupar a faixa inteira. A altura fica
        fixa para a altura da foto mais alta não crescer o carrossel.
        """
        py = (ROOT / "cartridges" / "window.py").read_text(encoding="utf-8")
        self.assertIn(
            "Gtk.Box(hexpand=True, height_request=_NEWS_HERO_HEIGHT)", py
        )
        self.assertNotIn("width_request=_NEWS_HERO_WIDTH", py)
        self.assertNotIn("_NEWS_HERO_WIDTH =", py)

    def test_cards_cap_their_natural_size(self) -> None:
        """Sem teto de largura natural a grade FlowBox vira coluna única.

        O Gtk.Picture devolve a largura da foto baixada (por vezes 800 px) e o
        Gtk.Label a largura do texto inteiro; os dois inflam o card e o FlowBox
        deixa de caber mais de um card por linha.
        """
        py = (ROOT / "cartridges" / "window.py").read_text(encoding="utf-8")
        # A moldura da imagem mede pelo filho de trás, não pela foto.
        self.assertIn("Gtk.Overlay", py)
        self.assertIn("max_width_chars=max_title_chars", py)
        # Quebra só em espaços: o padrão parte a palavra no meio da linha.
        self.assertIn("wrap_mode=Pango.WrapMode.WORD", py)


class WindowRegroupActionTests(unittest.TestCase):
    """O desagrupamento manual é reversível pelo menu do próprio card."""

    def test_reagrupar_wired_and_offered_on_ungrouped_card(self) -> None:
        py = (ROOT / "cartridges" / "window.py").read_text(encoding="utf-8")
        ag = (ROOT / "cartridges" / "utils" / "agrupamento.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('Gio.SimpleAction.new("reagrupar"', py)
        self.assertIn("def on_reagrupar_action", py)
        self.assertIn('"win.reagrupar"', py)
        self.assertIn('_("Agrupar novamente")', py)
        self.assertIn("agrupamento.desagrupada(chave)", py)
        self.assertIn("def reagrupar_chave", ag)


class WindowRetroarchControlsTests(unittest.TestCase):
    """Comandos do RetroArch no bloqueador da sessão (issue #156)."""

    @staticmethod
    def _metodo(py: str, nome: str) -> str:
        """O texto do método ``nome`` da CartridgesWindow, do def ao próximo."""
        inicio = py.index(f"def {nome}(")
        fim = py.find("\n    def ", inicio + 1)
        return py[inicio:fim if fim != -1 else None]

    def test_new_children_declared_in_python_and_blueprint(self) -> None:
        py = (ROOT / "cartridges" / "window.py").read_text(encoding="utf-8")
        blp = (ROOT / "data" / "gtk" / "window.blp").read_text(encoding="utf-8")
        ids = [
            "session_blocker_retroarch_button",
            "session_retroarch_popover",
            "retroarch_cmd_pause",
            "retroarch_cmd_fast_forward",
            "retroarch_cmd_slowmotion",
            "retroarch_cmd_mute",
            "retroarch_cmd_volume_up",
            "retroarch_cmd_volume_down",
            "retroarch_cmd_save_state",
            "retroarch_cmd_load_state",
            "retroarch_cmd_slot_plus",
            "retroarch_cmd_slot_minus",
            "retroarch_cmd_screenshot",
            "retroarch_cmd_menu",
            "retroarch_cmd_fullscreen",
            "retroarch_cmd_reset",
            "retroarch_cmd_shutdown",
        ]
        for id_widget in ids:
            self.assertIn(f"{id_widget}: Gtk.", py, id_widget)
            self.assertIn(f"{id_widget} {{", blp, id_widget)

    def test_retroarch_actions_map_only_to_allowed_commands(self) -> None:
        from cartridges.integrations.retroarch import COMANDOS_PERMITIDOS

        py = (ROOT / "cartridges" / "window.py").read_text(encoding="utf-8")
        tree = ast.parse(py)
        mapeamento = None
        for node in tree.body:
            alvo = None
            if (
                isinstance(node, ast.Assign)
                and any(
                    isinstance(t, ast.Name) and t.id == "_RETROARCH_ACOES"
                    for t in node.targets
                )
            ):
                alvo = node.value
            elif (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == "_RETROARCH_ACOES"
            ):
                alvo = node.value
            if alvo is not None:
                mapeamento = ast.literal_eval(alvo)
        self.assertIsInstance(mapeamento, dict)
        self.assertTrue(mapeamento)
        for widget, comando in mapeamento.items():
            self.assertIn(comando, COMANDOS_PERMITIDOS, widget)
        # Nenhum botão aponta para string fora da allowlist: os ids do mapa
        # são exatamente os widgets do template, e o dispatcher só envia o
        # comando que veio do mapa.
        self.assertEqual(len(mapeamento), 15)
        # Slow motion e tela cheia fazem parte do escopo do #156 e precisam
        # estar no menu, não só na allowlist.
        self.assertEqual(mapeamento["retroarch_cmd_slowmotion"], "SLOWMOTION")
        self.assertEqual(
            mapeamento["retroarch_cmd_fullscreen"], "FULLSCREEN_TOGGLE"
        )

    def test_button_hidden_by_default_and_driven_by_game_source(self) -> None:
        py = (ROOT / "cartridges" / "window.py").read_text(encoding="utf-8")
        blp = (ROOT / "data" / "gtk" / "window.blp").read_text(encoding="utf-8")
        self.assertIn("session_blocker_retroarch_button {", blp)
        self.assertIn("visible: false", blp)
        mostrar = self._metodo(py, "show_session_blocker")
        self.assertIn('base_source == "retroarch"', mostrar)
        self.assertIn("session_blocker_retroarch_button.set_visible", mostrar)
        esconder = self._metodo(py, "hide_session_blocker")
        self.assertIn("session_blocker_retroarch_button.set_visible(False)", esconder)

    def test_send_is_off_thread_and_honest_about_silence(self) -> None:
        py = (ROOT / "cartridges" / "window.py").read_text(encoding="utf-8")
        worker = self._metodo(py, "_retroarch_worker")
        self.assertIn("threading.Thread", py)
        self.assertIn("entregar_na_tela", worker)
        self.assertIn("is_available()", worker)
        resultado = self._metodo(py, "_retroarch_resultado_na_tela")
        self.assertIn("RetroArch não respondeu", resultado)

    def test_reset_and_shutdown_ask_before_sending(self) -> None:
        py = (ROOT / "cartridges" / "window.py").read_text(encoding="utf-8")
        confirmar = self._metodo(py, "_pedir_confirmacao_retroarch")
        self.assertIn("SHUTDOWN", confirmar)
        self.assertIn("AlertDialog", confirmar)
        self.assertIn("DESTRUCTIVE", confirmar)
        # Confirmar antes de enviar: o envio só acontece na resposta positiva.
        acao = self._metodo(py, "_ao_confirmar_retroarch")
        self.assertIn("_retroarch_enviar", acao)


if __name__ == "__main__":
    unittest.main()

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]


class WindowXCloudRefreshTests(unittest.TestCase):
    def test_refresh_widgets_declared_and_in_blueprint(self) -> None:
        py = (ROOT / "cartridges" / "window.py").read_text(encoding="utf-8")
        blp = (ROOT / "data" / "gtk" / "window.blp").read_text(encoding="utf-8")
        for widget in ("xcloud_refresh_button", "xcloud_refresh_spinner"):
            self.assertIn(widget, py)
            self.assertIn(widget, blp)
        self.assertIn("_on_xcloud_refresh_clicked", py)
        self.assertIn("_xcloud_refresh_done", py)
        self.assertIn("_xcloud_refresh_failed", py)

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


if __name__ == "__main__":
    unittest.main()

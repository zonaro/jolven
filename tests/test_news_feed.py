import importlib
import sys
import types
import unittest
from unittest.mock import patch

import requests
from gi.repository import GLib

from cartridges.utils import news_feed
from cartridges.utils.news_feed import (
    FREETOKEEP_FEED_URL,
    GAMERPOWER_FEED_URL,
    NEWS_FEEDS,
    TRINITYWEB_FEED_URL,
    NewsPost,
    all_sources,
    feeds_for_language,
    fetch_all_news,
    fetch_news,
    is_brazilian_portuguese,
    parse_news,
)


def _item(
    title="Some Game (Steam) Giveaway",
    guid="https://example.com/some-game",
    link="https://example.com/some-game",
    pubdate="Thu, 08 Oct 2026 17:49:15 +0000",
    description="Free game, grab it!",
    category=None,
):
    category_el = f"<category>{category}</category>" if category else ""
    return (
        "<item>"
        f"<title>{title}</title>"
        f"<guid>{guid}</guid>"
        f"<link>{link}</link>"
        f"<pubDate>{pubdate}</pubDate>"
        f"<description>{description}</description>"
        f"{category_el}"
        "</item>"
    )


def _doc(*items):
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<rss version=\"2.0\"><channel>" + "".join(items) + "</channel></rss>"
    )


def _post(identifier: str, timestamp: int, source: str) -> NewsPost:
    """One post as the feeds would hand it over."""
    return NewsPost(
        identifier=identifier,
        timestamp=timestamp,
        title=f"Post {identifier}",
        url=f"https://example.com/{identifier}",
        summary="",
        category="",
        source=source,
    )


class NewsFeedTests(unittest.TestCase):
    def test_feeds_use_https_aggregates(self):
        urls = [url for _source, url in NEWS_FEEDS]
        self.assertIn(GAMERPOWER_FEED_URL, urls)
        self.assertIn(FREETOKEEP_FEED_URL, urls)
        for url in urls:
            self.assertTrue(url.startswith("https://"))
        self.assertEqual(urls.count(GAMERPOWER_FEED_URL), 1)
        self.assertEqual(urls.count(FREETOKEEP_FEED_URL), 1)
        self.assertTrue(TRINITYWEB_FEED_URL.startswith("https://"))

    def test_is_brazilian_portuguese_accepts_locale_spellings(self):
        for value in ("pt_BR", "pt-BR", "pt_BR.UTF-8", "pt_BR:pt:en"):
            self.assertTrue(is_brazilian_portuguese(value), value)
        for value in ("", "en_US", "pt_PT", "auto", "es_ES.UTF-8"):
            self.assertFalse(is_brazilian_portuguese(value), value)

    def test_feeds_for_language_gates_pt_br_source(self):
        english = [url for _source, url in feeds_for_language("en_US")]
        self.assertEqual(english, [url for _source, url in NEWS_FEEDS])
        self.assertNotIn(TRINITYWEB_FEED_URL, english)

        portuguese = [url for _source, url in feeds_for_language("pt_BR")]
        self.assertIn(TRINITYWEB_FEED_URL, portuguese)
        self.assertEqual(len(portuguese), len(NEWS_FEEDS) + 1)

    def test_all_sources_lists_the_base_sources(self):
        sources = all_sources("en_US")
        self.assertEqual(sources, tuple(source for source, _url in NEWS_FEEDS))
        self.assertNotIn("TrinityWeb", sources)

    def test_all_sources_adds_the_pt_br_source_only_for_pt_br(self):
        portuguese = all_sources("pt_BR")
        self.assertIn("TrinityWeb", portuguese)
        self.assertEqual(portuguese, all_sources("en_US") + ("TrinityWeb",))

    def test_all_sources_follows_the_poll_order(self):
        for language in ("", "en_US", "pt_BR", "pt_BR.UTF-8"):
            self.assertEqual(
                all_sources(language),
                tuple(source for source, _url in feeds_for_language(language)),
                language,
            )

    def test_feeds_for_language_drops_a_disabled_source(self):
        feeds = feeds_for_language("pt_BR", disabled=("GamerPower",))
        sources = [source for source, _url in feeds]
        self.assertNotIn("GamerPower", sources)
        self.assertIn("TrinityWeb", sources)
        # The rest of the list keeps its order and its place.
        self.assertEqual(sources, ["FitGirl", "FreeToKeep", "TrinityWeb"])

    def test_feeds_for_language_without_disabled_keeps_everything(self):
        self.assertEqual(feeds_for_language("en_US"), NEWS_FEEDS)
        self.assertEqual(feeds_for_language("en_US", disabled=()), NEWS_FEEDS)
        # A source that does not exist changes nothing.
        self.assertEqual(
            feeds_for_language("en_US", disabled=("Nope",)), NEWS_FEEDS
        )

    def test_fetch_all_news_never_requests_a_disabled_feed(self):
        with patch.object(news_feed, "fetch_news", return_value=[]) as fetch:
            fetch_all_news(language="pt_BR", disabled=("GamerPower", "TrinityWeb"))
            urls = [call.args[0] for call in fetch.call_args_list]
        self.assertNotIn(GAMERPOWER_FEED_URL, urls)
        self.assertNotIn(TRINITYWEB_FEED_URL, urls)
        self.assertIn(FREETOKEEP_FEED_URL, urls)
        self.assertEqual(len(urls), 2)

    def test_fetch_all_news_polls_every_feed_when_nothing_is_disabled(self):
        with patch.object(news_feed, "fetch_news", return_value=[]) as fetch:
            fetch_all_news(language="pt_BR")
            urls = [call.args[0] for call in fetch.call_args_list]
        self.assertIn(GAMERPOWER_FEED_URL, urls)
        self.assertIn(TRINITYWEB_FEED_URL, urls)
        self.assertEqual(len(urls), len(NEWS_FEEDS) + 1)

    def test_fetch_all_news_polls_pt_br_source_only_in_pt_br(self):
        with patch.object(news_feed, "fetch_news", return_value=[]) as fetch:
            fetch_all_news(language="en_US")
            english_urls = [call.args[0] for call in fetch.call_args_list]
            fetch.reset_mock()
            fetch_all_news(language="pt_BR")
            portuguese_urls = [call.args[0] for call in fetch.call_args_list]
        self.assertNotIn(TRINITYWEB_FEED_URL, english_urls)
        self.assertIn(TRINITYWEB_FEED_URL, portuguese_urls)

    def test_parse_tags_source(self):
        posts = parse_news(_doc(_item()), source="GamerPower")
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0].source, "GamerPower")
        self.assertEqual(posts[0].title, "Some Game (Steam) Giveaway")

    def test_parse_supports_two_digit_year_pubdate(self):
        posts = parse_news(
            _doc(_item(pubdate="Thu, 08 Oct 26 17:49:15 +0000")),
            source="GamerPower",
        )
        self.assertEqual(len(posts), 1)
        self.assertGreater(posts[0].timestamp, 0)

    def test_parse_keeps_first_category(self):
        posts = parse_news(
            _doc(_item(category="Steam")), source="FreeToKeep"
        )
        self.assertEqual(posts[0].category, "Steam")

    def test_parse_skips_digest_and_titleless(self):
        doc = _doc(
            _item(title="Updates Digest #99"),
            _item(title=""),
            _item(title="Real Post"),
        )
        posts = parse_news(doc, source="FitGirl")
        self.assertEqual([post.title for post in posts], ["Real Post"])

    def test_parse_dedupes_repeated_guid(self):
        doc = _doc(_item(guid="dup"), _item(guid="dup"))
        posts = parse_news(doc, source="GamerPower")
        self.assertEqual(len(posts), 1)

    def test_parse_reads_enclosure_image(self):
        doc = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<rss version=\"2.0\"><channel><item>"
            "<title>Free Game</title>"
            "<guid>ftk-1</guid>"
            "<link>https://freetokeep.gg/game/free-game</link>"
            "<pubDate>Thu, 08 Oct 2026 18:00:43 GMT</pubDate>"
            "<description>Free to keep.</description>"
            "<enclosure url=\"https://example.com/cover.jpg\" "
            "length=\"0\" type=\"image/jpeg\" />"
            "</item></channel></rss>"
        )
        posts = parse_news(doc, source="FreeToKeep")
        self.assertEqual(posts[0].image, "https://example.com/cover.jpg")

    def test_parse_reads_media_content_image(self):
        doc = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<rss version=\"2.0\" "
            "xmlns:media=\"http://search.yahoo.com/mrss/\"><channel><item>"
            "<title>Giveaway</title>"
            "<guid>gp-1</guid>"
            "<link>https://www.gamerpower.com/giveaway</link>"
            "<pubDate>Thu, 08 Oct 26 17:49:15 +0000</pubDate>"
            "<description>Grab it.</description>"
            "<media:content url=\"https://example.com/offer.jpg\" "
            "type=\"image/jpeg\" />"
            "</item></channel></rss>"
        )
        posts = parse_news(doc, source="GamerPower")
        self.assertEqual(posts[0].image, "https://example.com/offer.jpg")

    def test_parse_rejects_non_image_or_unsafe_thumbnail(self):
        doc = _doc(_item()).replace(
            "</channel>",
            "<item><title>Audio</title><guid>a</guid>"
            "<link>https://example.com/a</link>"
            "<enclosure url=\"https://example.com/a.mp3\" type=\"audio/mpeg\" />"
            "</item><item><title>Evil</title><guid>e</guid>"
            "<link>https://example.com/e</link>"
            "<enclosure url=\"javascript:alert(1)\" type=\"image/png\" />"
            "</item></channel>",
        )
        posts = parse_news(doc, source="FreeToKeep")
        by_title = {post.title: post for post in posts}
        self.assertEqual(by_title["Audio"].image, "")
        self.assertEqual(by_title["Evil"].image, "")

    def test_fetch_news_resolves_source_from_url(self):
        with patch.object(
            news_feed, "fetch_feed_text", return_value=_doc(_item())
        ) as transport:
            posts = fetch_news(GAMERPOWER_FEED_URL)
        transport.assert_called_once()
        self.assertEqual(posts[0].source, "GamerPower")

    def test_fetch_all_news_merges_newest_first(self):
        old = NewsPost(
            identifier="old",
            timestamp=100,
            title="Old",
            url="https://example.com/old",
            summary="",
            category="",
            source="FitGirl",
        )
        new = NewsPost(
            identifier="new",
            timestamp=200,
            title="New",
            url="https://example.com/new",
            summary="",
            category="",
            source="GamerPower",
        )
        with patch.object(
            news_feed, "fetch_news", side_effect=[[old], [new], []]
        ):
            self.assertEqual(len(NEWS_FEEDS), 3)
            merged = fetch_all_news()
        self.assertEqual([post.identifier for post in merged], ["new", "old"])

    def test_fetch_all_news_dedupes_across_feeds_keeping_newest(self):
        stale = NewsPost(
            identifier="same",
            timestamp=100,
            title="Stale",
            url="https://example.com/x",
            summary="",
            category="",
            source="FitGirl",
        )
        fresh = NewsPost(
            identifier="same",
            timestamp=300,
            title="Fresh",
            url="https://example.com/x",
            summary="",
            category="",
            source="FreeToKeep",
        )
        with patch.object(
            news_feed, "fetch_news", side_effect=[[stale], [], [fresh]]
        ):
            merged = fetch_all_news()
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].title, "Fresh")

    def test_fetch_all_news_isolates_per_feed_failure(self):
        good = NewsPost(
            identifier="good",
            timestamp=50,
            title="Good",
            url="https://example.com/good",
            summary="",
            category="",
            source="GamerPower",
        )
        with patch.object(
            news_feed,
            "fetch_news",
            side_effect=[[good], requests.ConnectionError("down"), []],
        ):
            merged = fetch_all_news()
        self.assertEqual([post.identifier for post in merged], ["good"])


class _FakeSettings:
    """Stand-in for a Gio.Settings object: a dict and the few calls used here."""

    def __init__(self, values=None):
        self.values = dict(values or {})

    def get_string(self, key):
        return str(self.values.get(key, ""))

    def set_string(self, key, value):
        self.values[key] = value

    def get_strv(self, key):
        return list(self.values.get(key, []))

    def set_strv(self, key, value):
        self.values[key] = list(value)

    def get_int64(self, key):
        return int(self.values.get(key, 0))

    def set_int64(self, key, value):
        self.values[key] = int(value)


class _InlineThread:
    """A `threading.Thread` stand-in that runs its target right away.

    The poll must not reach the network from a test, and the test must not
    race a real worker: the target runs inline, on the calling thread.
    """

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        if self._target is not None:
            self._target(*self._args, **self._kwargs)


def _drain_main_context() -> None:
    """Run the callbacks the poll queued, so nothing leaks into the next test."""
    context = GLib.MainContext.default()
    for _ in range(100):
        if not context.pending():
            break
        context.iteration(False)


def _load_news_checker():
    """Import the news checker with a stubbed `cartridges.shared`.

    `cartridges/shared.py` is generated by Meson and is absent from a source
    checkout, so the checker cannot be imported as it is. The stub it ends up
    holding is the one every test here talks to.
    """
    stub = types.ModuleType("cartridges.shared")
    stub.schema = _FakeSettings()
    stub.state_schema = _FakeSettings()
    # An app id no installed schema answers to: the checker asks the schema
    # whether it knows the key before reading it, and this keeps the answer
    # "yes, the stub knows it" whatever happens to be installed.
    stub.APP_ID = "io.github.zonaro.JolvenTest"

    original = sys.modules.get("cartridges.shared")
    parent = sys.modules.get("cartridges")
    had_parent_attr = parent is not None and "shared" in parent.__dict__
    original_parent_attr = parent.__dict__.get("shared") if parent else None
    sys.modules["cartridges.shared"] = stub
    if parent is not None:
        parent.shared = stub
    try:
        module = importlib.import_module("cartridges.utils.news_checker")
    finally:
        if original is not None:
            sys.modules["cartridges.shared"] = original
        else:
            sys.modules.pop("cartridges.shared", None)
        if parent is not None:
            if had_parent_attr:
                parent.shared = original_parent_attr
            else:
                parent.__dict__.pop("shared", None)
    # The checker may have been imported earlier against the real shared
    # module; point it at the stub either way.
    module.shared = stub
    return module, stub


class NewsCheckerTests(unittest.TestCase):
    """The checker's half of the source filter: GSettings in, filtered cache out."""

    @classmethod
    def setUpClass(cls):
        cls.module, cls.shared = _load_news_checker()

    def setUp(self):
        self.schema = _FakeSettings()
        self.state = _FakeSettings()
        self.shared.schema = self.schema
        self.shared.state_schema = self.state

    def _checker(self):
        return self.module.NewsChecker()

    def _seed(self, checker, posts):
        """Fill the cache through the path a real poll takes."""
        checker._apply(list(posts))  # pylint: disable=protected-access

    def test_disabled_sources_starts_empty(self):
        self.assertEqual(self.module.disabled_sources(), ())

    def test_set_source_enabled_round_trip(self):
        self.module.set_source_enabled("GamerPower", False)
        self.assertEqual(self.module.disabled_sources(), ("GamerPower",))
        self.module.set_source_enabled("GamerPower", True)
        self.assertEqual(self.module.disabled_sources(), ())

    def test_set_source_enabled_leaves_the_other_sources_alone(self):
        self.module.set_source_enabled("GamerPower", False)
        self.module.set_source_enabled("FreeToKeep", False)
        self.assertEqual(
            self.module.disabled_sources(), ("GamerPower", "FreeToKeep")
        )
        self.module.set_source_enabled("GamerPower", True)
        self.assertEqual(self.module.disabled_sources(), ("FreeToKeep",))

    def test_set_source_enabled_is_idempotent(self):
        self.module.set_source_enabled("GamerPower", False)
        self.module.set_source_enabled("GamerPower", False)
        self.assertEqual(self.module.disabled_sources(), ("GamerPower",))
        self.module.set_source_enabled("GamerPower", True)
        self.module.set_source_enabled("GamerPower", True)
        self.assertEqual(self.module.disabled_sources(), ())

    def test_ui_language_prefers_the_preference(self):
        self.schema.values["language"] = "pt_BR"
        self.assertEqual(self.module.ui_language(), "pt_BR")

    def test_a_schema_without_the_key_disables_nothing(self):
        # An installed schema older than this build does not know the key,
        # and reading it anyway would abort the process inside GLib.
        with patch.object(self.module, "_schema_has_key", return_value=False):
            self.assertEqual(self.module.disabled_sources(), ())
            self.module.set_source_enabled("GamerPower", False)
        self.assertEqual(self.schema.values.get("disabled-news-sources"), None)

    def test_check_async_polls_only_the_enabled_sources(self):
        self.schema.values["language"] = "en_US"
        self.module.set_source_enabled("GamerPower", False)
        checker = self._checker()
        recorded = {}

        def fake_fetch_all_news(**kwargs):
            recorded.update(kwargs)
            return []

        with patch.object(
            self.module, "fetch_all_news", side_effect=fake_fetch_all_news
        ), patch.object(self.module.threading, "Thread", _InlineThread):
            checker.check_async()
        _drain_main_context()

        self.assertEqual(recorded.get("language"), "en_US")
        self.assertEqual(recorded.get("disabled"), ("GamerPower",))

    def test_apply_drops_posts_of_a_source_disabled_mid_poll(self):
        checker = self._checker()
        posts = [
            _post("a", 100, "FitGirl"),
            _post("b", 200, "GamerPower"),
        ]
        # The poll went out with the source still enabled, but the user
        # switched it off while the request was on the wire.
        self.module.set_source_enabled("GamerPower", False)
        checker._apply(posts)  # pylint: disable=protected-access

        self.assertEqual([post.identifier for post in checker.posts], ["a"])

    def test_refilter_drops_the_posts_of_a_disabled_source(self):
        checker = self._checker()
        self._seed(
            checker,
            [_post("a", 100, "FitGirl"), _post("b", 200, "GamerPower")],
        )
        changes = []
        checker.connect("posts-changed", lambda *_args: changes.append(True))

        self.module.set_source_enabled("GamerPower", False)
        checker.refilter()

        self.assertEqual([post.identifier for post in checker.posts], ["a"])
        self.assertEqual(len(changes), 1)

    def test_refilter_keeps_the_posts_of_an_enabled_source(self):
        checker = self._checker()
        self._seed(
            checker,
            [_post("a", 100, "FitGirl"), _post("b", 200, "GamerPower")],
        )
        changes = []
        checker.connect("posts-changed", lambda *_args: changes.append(True))

        self.module.set_source_enabled("FreeToKeep", False)
        checker.refilter()

        self.assertEqual(
            [post.identifier for post in checker.posts], ["a", "b"]
        )
        self.assertEqual(changes, [])

    def test_refilter_emits_only_when_the_list_changed(self):
        checker = self._checker()
        self._seed(checker, [_post("a", 100, "FitGirl")])
        changes = []
        checker.connect("posts-changed", lambda *_args: changes.append(True))

        checker.refilter()
        self.assertEqual(changes, [])

        self.module.set_source_enabled("FitGirl", False)
        checker.refilter()
        self.assertEqual(len(changes), 1)
        self.assertEqual(list(checker.posts), [])

        # A second pass finds nothing left to drop and stays quiet.
        checker.refilter()
        self.assertEqual(len(changes), 1)

    def test_refilter_on_an_empty_cache_is_safe(self):
        checker = self._checker()
        changes = []
        checker.connect("posts-changed", lambda *_args: changes.append(True))

        checker.refilter()

        self.assertEqual(list(checker.posts), [])
        self.assertEqual(changes, [])

    def test_refilter_recomputes_the_unseen_flag(self):
        checker = self._checker()
        self._seed(
            checker,
            [_post("a", 100, "FitGirl"), _post("b", 200, "GamerPower")],
        )
        self.state.values["news-last-seen-ts"] = 150
        checker._refresh_unseen()  # pylint: disable=protected-access
        self.assertTrue(checker.has_unseen)

        # The newest post belongs to the source that is about to be switched
        # off, so the badge must go down with it.
        self.module.set_source_enabled("GamerPower", False)
        checker.refilter()

        self.assertFalse(checker.has_unseen)


if __name__ == "__main__":
    unittest.main()

import unittest
from pathlib import Path

from bunnyforge import _dokuwiki
from bunnyforge import _common

NS = "testwiki"   # tests own their namespace; never the campaign's


class TestConversion(unittest.TestCase):
    def test_headings_and_marks(self):
        out = _dokuwiki.to_dokuwiki("## Sub\n**bold** and *em*", "Title")
        self.assertIn("====== Title ======", out)
        self.assertIn("===== Sub =====", out)
        self.assertIn("**bold**", out)
        self.assertIn("//em//", out)

    def test_code_and_links(self):
        out = _dokuwiki.to_dokuwiki("`code` and [label](target)", "T")
        self.assertIn("''code''", out)
        self.assertIn("[[target|label]]", out)

    def test_lists(self):
        out = _dokuwiki.to_dokuwiki("- one\n  - two", "T")
        self.assertIn("  * one", out)
        self.assertIn("    * two", out)

    def test_strip_leading_heading(self):
        self.assertEqual(_dokuwiki.strip_leading_heading("# Title\nbody\n"), "body\n")
        self.assertEqual(_dokuwiki.strip_leading_heading("body\n"), "body\n")


class TestOptionalTitle(unittest.TestCase):
    def test_no_title_prepended_when_none(self):
        out = _dokuwiki.to_dokuwiki("# Species House Rule\n\nbody\n")
        # The H1 converts in place; no extra heading is added.
        self.assertEqual(out.count("====== Species House Rule ======"), 1)
        self.assertTrue(out.startswith("====== Species House Rule ======"))

    def test_title_still_prepended_when_given(self):
        out = _dokuwiki.to_dokuwiki("body\n", "Title")
        self.assertTrue(out.startswith("====== Title ======"))


class TestPageIds(unittest.TestCase):
    def test_page_id_lowercases_and_joins(self):
        self.assertEqual(
            _dokuwiki.page_id("Mechanics/species-house-rule.md"),
            "mechanics:species-house-rule")

    def test_page_id_with_prefix(self):
        self.assertEqual(
            _dokuwiki.page_id("Mechanics/species-house-rule.md", f"{NS}:export"),
            f"{NS}:export:mechanics:species-house-rule")

    def test_page_id_nested(self):
        self.assertEqual(
            _dokuwiki.page_id("Briefs/session-001/mira-venn.md", NS),
            f"{NS}:briefs:session-001:mira-venn")

    def test_page_path(self):
        root = Path("/tmp/pages")
        self.assertEqual(
            _dokuwiki.page_path(f"{NS}:export:mechanics:x", root),
            root / NS / "export" / "mechanics" / "x.txt")

    def test_reserved_dir_collisions(self):
        self.assertEqual(
            _dokuwiki.reserved_dir_collisions(
                ["Mechanics/a.md", "export/b.md", "Players/c.md"]),
            ["export", "players"])
        self.assertEqual(
            _dokuwiki.reserved_dir_collisions(["Mechanics/a.md"]), [])

    def test_reserved_dir_collisions_top_level_file(self):
        # A bare top-level file named after a reserved sub-namespace collides
        # just as surely as a directory of the same name would.
        self.assertEqual(
            _dokuwiki.reserved_dir_collisions(["players.md"]), ["players"])
        self.assertEqual(
            _dokuwiki.reserved_dir_collisions(
                ["Mechanics/a.md", "export/b.md", "Players/c.md", "players.md",
                 "Export.md"]),
            ["export", "players"])


class TestWrapper(unittest.TestCase):
    def test_wrapper_is_two_includes_only(self):
        out = _dokuwiki.wrapper_text(
            f"{NS}:export:mechanics:x", f"{NS}:players:mechanics:x")
        self.assertIn(f"{{{{page>{NS}:export:mechanics:x}}}}", out)
        self.assertIn(f"{{{{page>{NS}:players:mechanics:x}}}}", out)
        # No title heading — the title belongs with the content.
        self.assertNotIn("======", out)
        self.assertTrue(out.endswith("\n"))


class TestLinkParsing(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(_dokuwiki.parse_wikilink("table-rules"),
                         ("table-rules", "", ""))

    def test_label(self):
        self.assertEqual(_dokuwiki.parse_wikilink("table-rules|The Rules"),
                         ("table-rules", "", "The Rules"))

    def test_anchor(self):
        self.assertEqual(_dokuwiki.parse_wikilink("table-rules#surprise"),
                         ("table-rules", "surprise", ""))

    def test_anchor_and_label(self):
        self.assertEqual(_dokuwiki.parse_wikilink("table-rules#surprise|See"),
                         ("table-rules", "surprise", "See"))

    def test_whitespace_stripped(self):
        self.assertEqual(_dokuwiki.parse_wikilink("  table-rules  |  See  "),
                         ("table-rules", "", "See"))

    def test_separators_inside_label_are_kept(self):
        # Only the first `|` separates, and `#` is only an anchor separator
        # before it — a label may contain either character verbatim.
        self.assertEqual(_dokuwiki.parse_wikilink("target|a|b"),
                         ("target", "", "a|b"))
        self.assertEqual(_dokuwiki.parse_wikilink("target|has#hash"),
                         ("target", "", "has#hash"))

    def test_format_roundtrip(self):
        self.assertEqual(
            _dokuwiki.format_wikilink(f"{NS}:mechanics:table-rules", "", "table-rules"),
            f"[[{NS}:mechanics:table-rules|table-rules]]")
        self.assertEqual(
            _dokuwiki.format_wikilink(f"{NS}:mechanics:table-rules", "surprise", "See"),
            f"[[{NS}:mechanics:table-rules#surprise|See]]")
        self.assertEqual(
            _dokuwiki.format_wikilink(f"{NS}:mechanics:table-rules", "", ""),
            f"[[{NS}:mechanics:table-rules]]")


class TestClassifyTarget(unittest.TestCase):
    def test_resolved_ambiguous_unresolved(self):
        a = Path("/ws/Mechanics/table-rules.md")
        b = Path("/ws/Ideas/table-rules.md")
        index = {"table-rules": {a}, "dupe": {a, b}}

        v = _dokuwiki.classify_target("table-rules", index, frozenset())
        self.assertEqual(v.case, "resolved")
        self.assertEqual(v.path, a)

        self.assertEqual(
            _dokuwiki.classify_target("dupe", index, frozenset()).case, "ambiguous")
        self.assertIsNone(_dokuwiki.classify_target("dupe", index, frozenset()).path)

        self.assertEqual(
            _dokuwiki.classify_target("nope", index, frozenset()).case, "unresolved")

    def test_non_file_link_forms_pass_through(self):
        # Valid DokuWiki link forms that name no workspace file at all. They
        # must not be fatal, and review.py's wikilink check must agree — both
        # go through _common.is_pass_through_target.
        index = {"table-rules": {Path("/ws/Mechanics/table-rules.md")}}
        content_dirs = frozenset({"mechanics", "perceptions"})
        for target in ("Mechanics", "Perceptions", "campaign/Mechanics",
                       "https://example.com", "wp>Seoul", "#anchor", "", "   "):
            with self.subTest(target=target):
                v = _dokuwiki.classify_target(target, index, content_dirs)
                self.assertEqual(v.case, "pass-through")
                self.assertIsNone(v.path)

    def test_case_insensitive_and_path_form(self):
        a = Path("/ws/Mechanics/table-rules.md")
        index = {"table-rules": {a}}
        self.assertEqual(
            _dokuwiki.classify_target("Table-Rules", index, frozenset()).case, "resolved")
        self.assertEqual(
            _dokuwiki.classify_target("Mechanics/table-rules", index, frozenset()).case,
            "resolved")


class TestRewriteWikilinks(unittest.TestCase):
    @staticmethod
    def _resolver(mapping):
        def resolve(target):
            return mapping.get(target, (None, "unresolved"))
        return resolve

    def test_rewrites_and_reports(self):
        body = "See [[table-rules]] and `[[campaign-feats]]`.\n"
        resolve = self._resolver({
            "table-rules": (f"{NS}:mechanics:table-rules", "exported"),
            "campaign-feats": (f"{NS}:mechanics:campaign-feats", "exported"),
        })
        out, seen = _dokuwiki.rewrite_wikilinks(body, resolve)
        self.assertIn(f"[[{NS}:mechanics:table-rules|table-rules]]", out)
        self.assertIn(f"[[{NS}:mechanics:campaign-feats|campaign-feats]]", out)
        self.assertEqual(seen, [("table-rules", "exported", 1),
                                ("campaign-feats", "exported", 1)])
        # the backticks around the inline-code link survive untouched
        self.assertIn(f"`[[{NS}:mechanics:campaign-feats|campaign-feats]]`", out)

    def test_reports_source_line(self):
        body = "intro\n\nSee [[table-rules]].\n\nand [[table-rules]] again\n"
        resolve = self._resolver(
            {"table-rules": (f"{NS}:mechanics:table-rules", "exported")})
        _out, seen = _dokuwiki.rewrite_wikilinks(body, resolve)
        self.assertEqual([s.line for s in seen], [3, 5])

    def test_preserves_label_and_anchor(self):
        body = "[[table-rules#surprise|the rule]]\n"
        resolve = self._resolver({"table-rules": (f"{NS}:mechanics:table-rules", "exported")})
        out, _ = _dokuwiki.rewrite_wikilinks(body, resolve)
        self.assertIn(f"[[{NS}:mechanics:table-rules#surprise|the rule]]", out)

    def test_rewrites_inside_fenced_code(self):
        # There is no code exemption. to_dokuwiki passes ``` through verbatim
        # and DokuWiki has no fence syntax, so a link inside a fence renders
        # as a live link on the player wiki — exempting it would let a
        # gm-only target publish silently, unreported, with a zero exit.
        body = "before [[table-rules]]\n\n```\nsee [[table-rules]]\n```\n"
        resolve = self._resolver({"table-rules": (f"{NS}:mechanics:table-rules", "exported")})
        out, seen = _dokuwiki.rewrite_wikilinks(body, resolve)
        self.assertIn(f"before [[{NS}:mechanics:table-rules|table-rules]]", out)
        self.assertIn(f"see [[{NS}:mechanics:table-rules|table-rules]]", out)
        self.assertNotIn("[[table-rules]]", out)
        self.assertEqual(seen, [("table-rules", "exported", 1),
                                ("table-rules", "exported", 4)])

    def test_fenced_gm_only_link_is_reported(self):
        body = "```\nsee [[secret]]\n```\n"
        resolve = self._resolver({"secret": (None, "unexported")})
        out, seen = _dokuwiki.rewrite_wikilinks(body, resolve)
        self.assertIn("[[secret]]", out)
        self.assertEqual(seen, [("secret", "unexported", 2)])

    def test_unrewritable_link_is_left_but_reported(self):
        body = "See [[open-questions]].\n"
        resolve = self._resolver({"open-questions": (None, "unexported")})
        out, seen = _dokuwiki.rewrite_wikilinks(body, resolve)
        self.assertIn("[[open-questions]]", out)
        self.assertEqual(seen, [("open-questions", "unexported", 1)])


class TestMarkdownLinkNormalisation(unittest.TestCase):
    def test_converts_inline_link(self):
        self.assertEqual(
            _common.markdown_links_to_wikilinks("See [the mole](the-mole) now."),
            "See [[the-mole|the mole]] now.")

    def test_converts_external_url(self):
        self.assertEqual(
            _common.markdown_links_to_wikilinks("[Anthropic](https://anthropic.com)"),
            "[[https://anthropic.com|Anthropic]]")

    def test_multiple_on_one_line(self):
        self.assertEqual(
            _common.markdown_links_to_wikilinks("[a](x) and [b](y)"),
            "[[x|a]] and [[y|b]]")

    def test_leaves_existing_wikilinks_alone(self):
        # These two inputs contain a `(...)` immediately or nearly adjacent
        # to a `[[...]]`, unlike the old "[[already|a wikilink]]" fixture
        # (no parens at all, so no regex could ever touch it). Both must
        # round-trip unchanged.
        self.assertEqual(
            _common.markdown_links_to_wikilinks("[[open]] (a note)"),
            "[[open]] (a note)")
        self.assertEqual(
            _common.markdown_links_to_wikilinks("[[open]](x)"),
            "[[open]](x)")

    def test_leaves_plain_text_alone(self):
        self.assertEqual(
            _common.markdown_links_to_wikilinks("no links here [not] (a link)"),
            "no links here [not] (a link)")

    def test_does_not_match_across_a_newline(self):
        # Finding 1: an unbalanced `[` earlier in the body must not swallow
        # a following line's real link -- verified against the exact input
        # that demonstrated the regression.
        text = ("Roll 2d6 [+2 if trained\n"
                "and see [the rules](open) for details.\n")
        out = _common.markdown_links_to_wikilinks(text)
        self.assertEqual(
            out,
            "Roll 2d6 [+2 if trained\n"
            "and see [[open|the rules]] for details.\n")

    def test_leaves_markdown_images_alone(self):
        # Finding 2: an image names an asset, not a workspace document, and
        # must not be treated as a link the wikilink policy judges.
        self.assertEqual(
            _common.markdown_links_to_wikilinks("![a map](map.png)"),
            "![a map](map.png)")
        self.assertEqual(
            _common.markdown_links_to_wikilinks(
                "![a map](map.png) and [the rules](open)."),
            "![a map](map.png) and [[open|the rules]].")

    def test_to_dokuwiki_still_converts_markdown_links(self):
        out = _dokuwiki.to_dokuwiki("See [the rules](table-rules).")
        self.assertIn("[[table-rules|the rules]]", out)


if __name__ == "__main__":
    unittest.main()

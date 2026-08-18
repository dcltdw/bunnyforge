#!/usr/bin/env python3
"""
Tests for the campaign workspace scripts. Stdlib unittest only — run with:

    python3 -m bunnyforge.run_tests

No third-party dependencies, so this runs anywhere Python 3 does (including CI
with nothing installed).
"""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from bunnyforge import _common
from bunnyforge import _config
from bunnyforge import _dokuwiki
from bunnyforge import build_sheets


class TestCommon(unittest.TestCase):
    def _ws_with(self, text: str) -> Path:
        """A temp workspace containing the given campaign.toml text."""
        d = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        (d / "campaign.toml").write_text(text, encoding="utf-8")
        return d

    def test_split_front_matter_basic(self):
        fm, body = _common.split_front_matter(
            "---\ntype: npc\ncanon: draft\n---\n# Body\ntext\n")
        self.assertEqual(fm["type"], "npc")
        self.assertEqual(fm["canon"], "draft")
        self.assertIn("# Body", body)

    def test_split_front_matter_none(self):
        fm, body = _common.split_front_matter("# No front matter\n")
        self.assertEqual(fm, {})
        self.assertEqual(body, "# No front matter\n")

    def test_split_front_matter_folds_continuation(self):
        fm, _ = _common.split_front_matter(
            "---\nsummary: >-\n  one two\n  three\n---\nbody")
        self.assertEqual(fm["summary"], "one two three")

    def test_split_front_matter_duplicate_key_takes_last(self):
        # Matches YAML: the idea/session templates rely on this.
        fm, _ = _common.split_front_matter(
            "---\ncanon: draft\ncanon: speculative\n---\nbody")
        self.assertEqual(fm["canon"], "speculative")

    def test_strip_yaml_comment(self):
        self.assertEqual(_common.strip_yaml_comment("now  # a hint"), "now")
        self.assertEqual(_common.strip_yaml_comment("player-visible"), "player-visible")
        self.assertEqual(_common.strip_yaml_comment(""), "")

    def test_normalize_visibility_default_when_unset(self):
        self.assertEqual(_common.normalize_visibility({}), "gm-only")
        self.assertEqual(_common.normalize_visibility({}, default="mixed"), "mixed")

    def test_normalize_visibility_each_value(self):
        for v in ("gm-only", "player-visible", "mixed"):
            self.assertEqual(_common.normalize_visibility({"visibility": v}), v)

    def test_normalize_visibility_strips_inline_comment(self):
        self.assertEqual(
            _common.normalize_visibility({"visibility": "player-visible  # note"}),
            "player-visible")

    def test_normalize_visibility_unknown_is_gm_only(self):
        # A typo must never widen the audience.
        self.assertEqual(
            _common.normalize_visibility({"visibility": "everyone"}, default="mixed"),
            "gm-only")

    def test_content_dir_names_unions_entity_and_inherit_lowercased(self):
        # #62: the archive is canon too, so its (default) name joins the
        # union alongside every configured entity/inherit dir.
        cfg = _config.load(self._ws_with(
            '[campaign]\nnamespace = "t"\n\n[workspace]\n'
            'entity_dirs = ["NPCs", "Setting"]\ninherit_dirs = ["Briefs"]\n'))
        self.assertEqual(_common.content_dir_names(cfg),
                         frozenset({"npcs", "setting", "briefs", "archive"}))

    def test_content_dir_names_follows_config_not_defaults(self):
        # A campaign that renames its directories must get ITS names, which a
        # hardcoded default would silently override.
        cfg = _config.load(self._ws_with(
            '[campaign]\nnamespace = "t"\n\n[workspace]\n'
            'entity_dirs = ["Dramatis"]\ninherit_dirs = ["Preps"]\n'))
        self.assertEqual(_common.content_dir_names(cfg),
                         frozenset({"dramatis", "preps", "archive"}))
        self.assertNotIn("npcs", _common.content_dir_names(cfg))


class TestSharedHandoutHelpers(unittest.TestCase):
    """These helpers outlived publish_handouts.py — the export pipeline uses
    them. `player_facing` lives in _common, `to_dokuwiki` in _dokuwiki."""

    def test_player_facing_gm_marker(self):
        body = "player text\n\n---\n## GM notes\nsecret\n"
        self.assertEqual(_common.player_facing(body).strip(), "player text")

    def test_player_facing_dm_marker_backcompat(self):
        body = "player text\n\n---\n## DM notes\nsecret\n"
        self.assertEqual(_common.player_facing(body).strip(), "player text")

    def test_player_facing_absent(self):
        self.assertIsNone(_common.player_facing("just player text\n"))

    def test_to_dokuwiki_headings_and_marks(self):
        out = _dokuwiki.to_dokuwiki("## Sub\n**bold** and *em*", "Title")
        self.assertIn("====== Title ======", out)
        self.assertIn("===== Sub =====", out)
        self.assertIn("**bold**", out)
        self.assertIn("//em//", out)


class TestBuildSheets(unittest.TestCase):
    def test_parse_sections(self):
        secs = build_sheets.parse_sections("## Want\nto win\n## Method\nby guile\n")
        self.assertEqual(secs["want"], "to win")
        self.assertEqual(secs["method"], "by guile")

    def test_clean_strips_comments_and_placeholders(self):
        self.assertEqual(build_sheets.clean("<!-- c -->real\n<placeholder>"), "real")

    def test_resolve_section_modes(self):
        w = {"want": "writeup want"}
        b = {"want": "brief want"}
        self.assertEqual(build_sheets.resolve_section("writeup", "Want", w, b), "writeup want")
        self.assertEqual(build_sheets.resolve_section("brief", "Want", w, b), "brief want")
        self.assertEqual(build_sheets.resolve_section("pick", "Want", w, {}), "writeup want")
        self.assertEqual(build_sheets.resolve_section("pick", "Want", w, b), "brief want")

    def test_resolve_section_explicit_key(self):
        w = {"synthesis": "the portrait"}
        self.assertEqual(
            build_sheets.resolve_section("writeup:synthesis", "Disposition", w, {}),
            "the portrait")

    def test_visibility_label(self):
        self.assertEqual(build_sheets.visibility_label("player-visible"), "Player-visible")
        self.assertEqual(build_sheets.visibility_label("mixed"), "Mixed")
        self.assertEqual(build_sheets.visibility_label("gm-only"), "GM-only")
        self.assertEqual(
            build_sheets.visibility_label("gm-only", "the coronation"),
            "GM-only (reveals: the coronation)")

    def test_render_shows_visibility(self):
        out = build_sheets.render(
            "mira-venn", "npc", "1", {"synthesis": "x"}, {}, {"title": "Mira Venn"},
            "", visibility="gm-only", reveal_when="the coronation")
        self.assertIn("GM-only (reveals: the coronation)", out)

        out2 = build_sheets.render(
            "yun", "npc", "1", {"synthesis": "x"}, {}, {"title": "Yun"},
            "", visibility="player-visible")
        self.assertIn("Player-visible", out2)


def _write_campaign_toml(root: Path, **overrides: str) -> Path:
    """Mark `root` as a campaign workspace. `overrides` become [workspace]
    keys verbatim (e.g. sheets_dir="Output"), so a test can prove main()
    reads campaign.toml rather than a hardcoded convention."""
    lines = ['[campaign]', 'namespace = "test"']
    if overrides:
        lines += ['', '[workspace]']
        lines += [f'{k} = "{v}"' for k, v in overrides.items()]
    (root / "campaign.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root


class TestBuildSheetsMain(unittest.TestCase):
    """End-to-end coverage of main(), steered via --workspace rather than a
    reassigned module global — that mechanism has been retired. This is the
    first coverage build_sheets.main() has had at all; previously every test
    here exercised only the pure helper functions."""

    def _run_main(self, workspace: Path, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = build_sheets.main(["--workspace", str(workspace), *argv])
        return rc, out.getvalue(), err.getvalue()

    def test_list_briefs_reports_sessions_and_counts(self):
        with tempfile.TemporaryDirectory() as d:
            root = _write_campaign_toml(Path(d))
            session_dir = root / "Briefs" / "session-001"
            session_dir.mkdir(parents=True)
            (session_dir / "mira-venn.md").write_text("## Want\nx\n", encoding="utf-8")
            (session_dir / "yun.md").write_text("## Want\ny\n", encoding="utf-8")

            rc, out, _ = self._run_main(root, "--list-briefs")

            self.assertEqual(rc, 0)
            self.assertIn("session-001", out)
            self.assertIn("2 briefs", out)

    def test_builds_sheet_using_default_dirs(self):
        with tempfile.TemporaryDirectory() as d:
            root = _write_campaign_toml(Path(d))
            (root / "NPCs").mkdir()
            (root / "NPCs" / "mira-venn.md").write_text(
                "---\ncanon: draft\n---\n## Synthesis\nA cunning merchant.\n",
                encoding="utf-8")
            brief_dir = root / "Briefs" / "session-001"
            brief_dir.mkdir(parents=True)
            (brief_dir / "mira-venn.md").write_text(
                "---\ntype: npc\n---\n## This session\nWants to trade.\n",
                encoding="utf-8")

            rc, out, _ = self._run_main(root, "1")

            self.assertEqual(rc, 0)
            dest = root / "_Sheets" / "session-001" / "npc-mira-venn.html"
            self.assertTrue(dest.is_file())
            self.assertIn("cunning merchant", dest.read_text(encoding="utf-8"))

    def test_builds_sheet_honours_type_dirs_and_sheets_dir_overrides(self):
        # Same scenario, but the workspace renames both the writeup directory
        # (via type_dirs) and the output directory (via sheets_dir). If
        # main() ever hardcoded "NPCs" or "_Sheets" instead of reading the
        # config, this would look in the wrong places and fail to find/write
        # the file.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "campaign.toml").write_text(
                '[campaign]\nnamespace = "test"\n\n'
                '[workspace]\nsheets_dir = "Output"\n\n'
                '[workspace.type_dirs]\n'
                'npc = "Persons"\nfaction = "Factions"\nplace = "Setting"\n',
                encoding="utf-8")
            (root / "Persons").mkdir()
            (root / "Persons" / "mira-venn.md").write_text(
                "---\ncanon: draft\n---\n## Synthesis\nA cunning merchant.\n",
                encoding="utf-8")
            brief_dir = root / "Briefs" / "session-001"
            brief_dir.mkdir(parents=True)
            (brief_dir / "mira-venn.md").write_text(
                "---\ntype: npc\n---\n## This session\nWants to trade.\n",
                encoding="utf-8")

            rc, out, _ = self._run_main(root, "1")

            self.assertEqual(rc, 0)
            dest = root / "Output" / "session-001" / "npc-mira-venn.html"
            self.assertTrue(dest.is_file())
            self.assertIn("cunning merchant", dest.read_text(encoding="utf-8"))
            self.assertFalse((root / "_Sheets").exists())

    def test_builds_sheet_honours_briefs_dir_override(self):
        # briefs_dir had no live guard: the repo's own Briefs/ contains only
        # README.md (no session-NNN/ subdirectory), so a --list-briefs
        # before/after stdout comparison never exercises the loop body and
        # can't prove this wiring either way. This test puts a real brief
        # under a renamed directory, so a hardcoded "Briefs" would fail to
        # find brief_dir at all and return 1 instead of building the sheet.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "campaign.toml").write_text(
                '[campaign]\nnamespace = "test"\n\n'
                '[workspace]\nbriefs_dir = "SessionNotes"\n',
                encoding="utf-8")
            (root / "NPCs").mkdir()
            (root / "NPCs" / "mira-venn.md").write_text(
                "---\ncanon: draft\n---\n## Synthesis\nA cunning merchant.\n",
                encoding="utf-8")
            brief_dir = root / "SessionNotes" / "session-001"
            brief_dir.mkdir(parents=True)
            (brief_dir / "mira-venn.md").write_text(
                "---\ntype: npc\n---\n## This session\nWants to trade.\n",
                encoding="utf-8")

            rc, out, _ = self._run_main(root, "1")

            self.assertEqual(rc, 0)
            dest = root / "_Sheets" / "session-001" / "npc-mira-venn.html"
            self.assertTrue(dest.is_file())
            self.assertIn("cunning merchant", dest.read_text(encoding="utf-8"))
            self.assertFalse((root / "Briefs").exists())

    def test_missing_workspace_returns_nonzero_with_a_clear_message(self):
        # --workspace pointing at a directory with no campaign.toml is an
        # error, not a search hint — resolve_workspace must not walk up.
        with tempfile.TemporaryDirectory() as d:
            rc, _, err = self._run_main(Path(d), "1")
            self.assertEqual(rc, 1)
            self.assertIn("campaign.toml", err)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""
Tests for bunnyforge.export_player. Stdlib unittest only — run with:

    python3 -m bunnyforge.run_tests

This is a safety tool: it must never write a `gm-only` file, or GM-only
content from a `player-visible`/`mixed` file, into Export/. The tests below
check the individual rules, then close with a single paranoid leak test that
scans every byte written to the output tree for sentinels planted in every
GM-only construct.
"""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from bunnyforge import _common
from bunnyforge import _config
from bunnyforge import export_player

# The fixtures below rely on the conventional directory shape (NPCs,
# Mechanics, Handouts, ... — see _config._DEFAULTS) that a campaign.toml with
# no [workspace] table falls back to, so a bare namespace declaration is all
# any of them needs.
_MINIMAL_CAMPAIGN_TOML = '[campaign]\nnamespace = "test"\n'


def make_workspace(root: Path, files: dict) -> Path:
    """files: {relative_path: text}. Creates parents and writes each file.

    Always leaves a campaign.toml in place (the conventional defaults, unless
    the caller supplies its own under that key), so callers can load a
    Workspace from `root`.
    """
    root.mkdir(parents=True, exist_ok=True)
    if "campaign.toml" not in files:
        (root / "campaign.toml").write_text(_MINIMAL_CAMPAIGN_TOML, encoding="utf-8")
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return root


def run(root: Path) -> tuple[export_player.ExportResult, Path]:
    out_dir = root / "Export"
    ws = _config.open_workspace(root)
    result, _log = export_player.run_export(ws, out_dir)
    return result, out_dir


class TestStripGmSections(unittest.TestCase):
    def test_drops_named_sections_and_keeps_rest(self):
        body = (
            "# Title\n\n## Rules text\nkeep this\n\n"
            "## Design intent\nsecret rationale\n\n"
            "## Balance notes\nsecret math\n\n"
            "## Playtest log\nnone yet\n"
        )
        out, n = export_player.strip_gm_sections(body)
        self.assertEqual(n, 3)
        self.assertIn("keep this", out)
        self.assertNotIn("Design intent", out)
        self.assertNotIn("secret rationale", out)
        self.assertNotIn("Balance notes", out)
        self.assertNotIn("secret math", out)
        self.assertNotIn("Playtest log", out)

    def test_heading_level_aware_subheading_dropped_sibling_kept(self):
        body = (
            "## Design intent\n"
            "top-level rationale\n"
            "### Sub-heading\n"
            "nested rationale, still secret\n"
            "## Interactions and edge cases\n"
            "this survives\n"
        )
        out, n = export_player.strip_gm_sections(body)
        self.assertEqual(n, 1)
        self.assertNotIn("Design intent", out)
        self.assertNotIn("Sub-heading", out)
        self.assertNotIn("nested rationale", out)
        self.assertIn("Interactions and edge cases", out)
        self.assertIn("this survives", out)

    def test_case_insensitive_and_trailing_punctuation(self):
        body = "## BALANCE NOTES:  \nsecret\n## Next\nkept\n"
        out, n = export_player.strip_gm_sections(body)
        self.assertEqual(n, 1)
        self.assertNotIn("secret", out)
        self.assertIn("kept", out)

    def test_no_matching_sections_is_a_no_op(self):
        body = "## Rules text\nplain content\n"
        out, n = export_player.strip_gm_sections(body)
        self.assertEqual(n, 0)
        self.assertEqual(out, body)


class TestStripHtmlComments(unittest.TestCase):
    def test_removes_comment(self):
        out = export_player.strip_html_comments("before <!-- gm scratch --> after")
        self.assertNotIn("gm scratch", out)
        self.assertIn("before", out)
        self.assertIn("after", out)

    def test_removes_multiline_comment(self):
        out = export_player.strip_html_comments("a\n<!--\nsecret\nblock\n-->\nb")
        self.assertNotIn("secret", out)
        self.assertIn("a", out)
        self.assertIn("b", out)


class TestRunExport(unittest.TestCase):
    def test_gm_only_produces_no_output_file(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_workspace(Path(d), {
                "Mechanics/secret.md":
                    "---\ntype: mechanic\nvisibility: gm-only\n---\n# Secret\nbody\n",
            })
            result, out_dir = run(root)
            self.assertEqual(result.exported, 0)
            self.assertEqual(result.skipped_gm_only, 1)
            self.assertFalse((out_dir / "Mechanics/secret.md").exists())

    def test_player_visible_strips_meta_sections_keeps_rules(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_workspace(Path(d), {
                "Mechanics/rule.md": (
                    "---\ntype: mechanic\nvisibility: player-visible\n---\n"
                    "# Rule\n\n## Rules text\nplayers read this\n\n"
                    "## Design intent\nGM rationale\n\n"
                    "## Balance notes\nGM math\n\n"
                    "## Playtest log\nGM history\n"
                ),
            })
            result, out_dir = run(root)
            self.assertEqual(result.exported, 1)
            out_file = out_dir / "Mechanics/rule.md"
            self.assertTrue(out_file.exists())
            text = out_file.read_text(encoding="utf-8")
            self.assertIn("players read this", text)
            self.assertNotIn("Design intent", text)
            self.assertNotIn("GM rationale", text)
            self.assertNotIn("Balance notes", text)
            self.assertNotIn("GM math", text)
            self.assertNotIn("Playtest log", text)
            self.assertNotIn("GM history", text)

    def test_mixed_exports_only_above_gm_notes(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_workspace(Path(d), {
                "Handouts/letter.md": (
                    "---\ntype: handout\nvisibility: mixed\n---\n"
                    "# The Letter\nplayer-facing text\n\n"
                    "---\n## GM notes\nGM-only secret\n"
                ),
            })
            result, out_dir = run(root)
            self.assertEqual(result.exported, 1)
            text = (out_dir / "Handouts/letter.md").read_text(encoding="utf-8")
            self.assertIn("player-facing text", text)
            self.assertNotIn("GM notes", text)
            self.assertNotIn("GM-only secret", text)

    def test_mixed_without_separator_is_skipped_entirely(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_workspace(Path(d), {
                "Handouts/broken.md": (
                    "---\ntype: handout\nvisibility: mixed\n---\n"
                    "# Broken\nno separator here, cannot tell what is safe\n"
                ),
            })
            result, out_dir = run(root)
            self.assertEqual(result.exported, 0)
            self.assertEqual(result.skipped_unsplittable, 1)
            self.assertFalse((out_dir / "Handouts/broken.md").exists())

    def test_unknown_visibility_fails_safe_to_gm_only(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_workspace(Path(d), {
                "Mechanics/typo.md":
                    "---\ntype: mechanic\nvisibility: everyone\n---\n# Typo\nbody\n",
            })
            result, out_dir = run(root)
            self.assertEqual(result.exported, 0)
            self.assertEqual(result.skipped_gm_only, 1)
            self.assertFalse((out_dir / "Mechanics/typo.md").exists())

    def test_html_comments_do_not_survive(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_workspace(Path(d), {
                "Mechanics/commented.md": (
                    "---\ntype: mechanic\nvisibility: player-visible\n---\n"
                    "# Commented\nvisible text\n<!-- GM scratch: do not ship -->\nmore text\n"
                ),
            })
            result, out_dir = run(root)
            text = (out_dir / "Mechanics/commented.md").read_text(encoding="utf-8")
            self.assertNotIn("GM scratch", text)
            self.assertIn("visible text", text)
            self.assertIn("more text", text)

    def test_heading_level_awareness_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_workspace(Path(d), {
                "Mechanics/nested.md": (
                    "---\ntype: mechanic\nvisibility: player-visible\n---\n"
                    "# Nested\n\n## Design intent\ntop\n### Sub-heading\nnested secret\n"
                    "## Interactions and edge cases\nsurvives\n"
                ),
            })
            result, out_dir = run(root)
            text = (out_dir / "Mechanics/nested.md").read_text(encoding="utf-8")
            self.assertNotIn("Design intent", text)
            self.assertNotIn("Sub-heading", text)
            self.assertNotIn("nested secret", text)
            self.assertIn("Interactions and edge cases", text)
            self.assertIn("survives", text)

    def test_preserves_relative_path(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_workspace(Path(d), {
                "Mechanics/Sub/deep.md":
                    "---\ntype: mechanic\nvisibility: player-visible\n---\n# Deep\nx\n",
            })
            result, out_dir = run(root)
            self.assertTrue((out_dir / "Mechanics/Sub/deep.md").exists())


class TestLeakage(unittest.TestCase):
    """The one test that matters most: no GM-only sentinel survives, anywhere
    in the output tree, under any of the constructs that can carry one."""

    def test_no_sentinel_leaks_into_export_under_any_construct(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_workspace(Path(d), {
                # A whole gm-only file: must not appear at all.
                "NPCs/villain.md": (
                    "---\ntype: npc\nvisibility: gm-only\n---\n"
                    "# Villain\nSENTINEL-GM-ONLY-FILE\n"
                ),
                # Unknown visibility, fails safe to gm-only.
                "NPCs/typo.md": (
                    "---\ntype: npc\nvisibility: everyone\n---\n"
                    "# Typo\nSENTINEL-UNKNOWN-VISIBILITY\n"
                ),
                # A mixed file: content below the GM-notes marker.
                "Handouts/letter.md": (
                    "---\ntype: handout\nvisibility: mixed\n---\n"
                    "# The Letter\nplayer text\n\n"
                    "---\n## GM notes\nSENTINEL-MIXED-BELOW-MARKER\n"
                ),
                # A mixed file with no separator: skipped entirely.
                "Handouts/broken.md": (
                    "---\ntype: handout\nvisibility: mixed\n---\n"
                    "# Broken\nSENTINEL-MIXED-NO-SEPARATOR\n"
                ),
                # player-visible file with all three meta-sections.
                "Mechanics/rule.md": (
                    "---\ntype: mechanic\nvisibility: player-visible\n---\n"
                    "# Rule\n\n## Rules text\nkeep this\n\n"
                    "## Design intent\nSENTINEL-DESIGN-INTENT\n\n"
                    "## Balance notes\nSENTINEL-BALANCE-NOTES\n\n"
                    "## Playtest log\nSENTINEL-PLAYTEST-LOG\n"
                ),
                # Nested sub-heading under a meta-section.
                "Mechanics/nested.md": (
                    "---\ntype: mechanic\nvisibility: player-visible\n---\n"
                    "# Nested\n\n## Design intent\ntop\n"
                    "### Sub-heading\nSENTINEL-NESTED-SUBHEADING\n"
                    "## Interactions and edge cases\nsurvives\n"
                ),
                # HTML comment (GM scratch) inside an otherwise safe file.
                "Mechanics/commented.md": (
                    "---\ntype: mechanic\nvisibility: player-visible\n---\n"
                    "# Commented\nvisible\n<!-- SENTINEL-HTML-COMMENT -->\nmore\n"
                ),
                # Case/punctuation variants of the meta-section headings.
                "Mechanics/variants.md": (
                    "---\ntype: mechanic\nvisibility: player-visible\n---\n"
                    "# Variants\n\n## design intent:\nSENTINEL-LOWERCASE-COLON\n"
                    "## BALANCE NOTES\nSENTINEL-UPPERCASE\n"
                    "## Playtest Log.\nSENTINEL-TRAILING-PERIOD\n"
                ),
            })

            sentinels = [
                "SENTINEL-GM-ONLY-FILE",
                "SENTINEL-UNKNOWN-VISIBILITY",
                "SENTINEL-MIXED-BELOW-MARKER",
                "SENTINEL-MIXED-NO-SEPARATOR",
                "SENTINEL-DESIGN-INTENT",
                "SENTINEL-BALANCE-NOTES",
                "SENTINEL-PLAYTEST-LOG",
                "SENTINEL-NESTED-SUBHEADING",
                "SENTINEL-HTML-COMMENT",
                "SENTINEL-LOWERCASE-COLON",
                "SENTINEL-UPPERCASE",
                "SENTINEL-TRAILING-PERIOD",
            ]

            result, out_dir = run(root)

            # Sanity: something was actually exported (an empty tree would
            # trivially "pass" the leak scan below without proving anything).
            self.assertGreater(result.exported, 0)

            all_output_text = ""
            for p in out_dir.rglob("*"):
                if p.is_file():
                    all_output_text += p.read_text(encoding="utf-8")
                    all_output_text += "\n"
                    all_output_text += p.relative_to(out_dir).as_posix()

            for sentinel in sentinels:
                self.assertNotIn(sentinel, all_output_text,
                                  f"leaked sentinel: {sentinel}")

            # And the gm-only / unsplittable files must be entirely absent.
            self.assertFalse((out_dir / "NPCs/villain.md").exists())
            self.assertFalse((out_dir / "NPCs/typo.md").exists())
            self.assertFalse((out_dir / "Handouts/broken.md").exists())


class TestMain(unittest.TestCase):
    """main(), steered via --workspace rather than a reassigned module
    global — that mechanism has been retired."""

    def _run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = export_player.main(list(argv))
        return rc, out.getvalue(), err.getvalue()

    def test_main_writes_export_dir_and_returns_zero_when_clean(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_workspace(Path(d), {
                "Mechanics/rule.md":
                    "---\ntype: mechanic\nvisibility: player-visible\n---\n# Rule\nx\n",
            })
            rc, _out, err = self._run_main("--workspace", str(root))
            self.assertEqual(rc, 0, err)
            self.assertTrue((root / "Export/Mechanics/rule.md").exists())

    def test_main_returns_nonzero_when_mixed_file_unsplittable(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_workspace(Path(d), {
                "Handouts/broken.md":
                    "---\ntype: handout\nvisibility: mixed\n---\n# Broken\nno separator\n",
            })
            rc, _out, _err = self._run_main("--workspace", str(root))
            self.assertEqual(rc, 1)

    def test_export_dir_follows_the_chosen_workspace(self):
        # The output directory is derived from the resolved workspace, not
        # from a module constant fixed at import: two workspaces must receive
        # their own Export/, and neither the install repo's nor each other's.
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            a = make_workspace(d / "a", {
                "Mechanics/from-a.md":
                    "---\ntype: mechanic\nvisibility: player-visible\n---\n# A\nx\n",
            })
            b = make_workspace(d / "b", {
                "Mechanics/from-b.md":
                    "---\ntype: mechanic\nvisibility: player-visible\n---\n# B\nx\n",
            })

            self.assertEqual(self._run_main("--workspace", str(a))[0], 0)
            self.assertEqual(self._run_main("--workspace", str(b))[0], 0)

            self.assertTrue((a / "Export/Mechanics/from-a.md").is_file())
            self.assertTrue((b / "Export/Mechanics/from-b.md").is_file())
            self.assertFalse((a / "Export/Mechanics/from-b.md").exists())
            self.assertFalse((b / "Export/Mechanics/from-a.md").exists())

    def test_missing_workspace_returns_nonzero_with_a_clear_message(self):
        # --workspace pointing at a directory with no campaign.toml is an
        # error, not a search hint — resolve_workspace must not walk up.
        with tempfile.TemporaryDirectory() as d:
            rc, _out, err = self._run_main("--workspace", d)
            self.assertEqual(rc, 1)
            self.assertIn("campaign.toml", err)


if __name__ == "__main__":
    unittest.main()

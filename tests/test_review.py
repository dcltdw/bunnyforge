import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bunnyforge import _common
from bunnyforge import _config
from bunnyforge import review
from tests.test_dokuwiki_install import make_install


# The fixtures below rely on the conventional directory shape (NPCs,
# Mechanics, Briefs, ... — see _config._DEFAULTS) that a campaign.toml with no
# [workspace] table falls back to, so a bare namespace declaration is all any
# of them needs.
_MINIMAL_CAMPAIGN_TOML = '[campaign]\nnamespace = "test"\n'


def make_workspace(root: Path, files: dict) -> Path:
    """files: {relative_path: text}. Creates parents and writes each file.

    Always leaves a campaign.toml in place (the conventional defaults, unless
    the caller supplies its own under that key), so callers can load a
    Workspace from `root`.
    """
    if "campaign.toml" not in files:
        (root / "campaign.toml").write_text(_MINIMAL_CAMPAIGN_TOML, encoding="utf-8")
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return root


class TestEnumerator(unittest.TestCase):
    def test_categories_and_exclusions(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_workspace(Path(d), {
                "NPCs/mira-venn.md": "---\ntype: npc\nvisibility: gm-only\n---\nbody",
                "NPCs/README.md": "# readme",
                "Briefs/session-001/mira-venn.md": "---\ntype: brief\n---\nb",
                "compendium.md": "# Compendium",
                "_Archive/old.md": "---\ntype: npc\n---\nx",
                "_Templates/npc.md": "---\ntype: npc\n---\nx",
                "Sheets/session-001/npc-mira-venn.html": "<html>",
            })
            ws = _config.open_workspace(root)
            recs = _common.iter_content_files(ws)
            by_path = {r.path.relative_to(ws.root).as_posix(): r for r in recs}

            self.assertIn("NPCs/mira-venn.md", by_path)
            self.assertEqual(by_path["NPCs/mira-venn.md"].category, "entity")
            self.assertEqual(by_path["Briefs/session-001/mira-venn.md"].category, "inherit")
            self.assertEqual(by_path["compendium.md"].category, "root")

            # Excluded: READMEs, _Archive, _Templates, generated Sheets.
            self.assertNotIn("NPCs/README.md", by_path)
            self.assertNotIn("_Archive/old.md", by_path)
            self.assertNotIn("_Templates/npc.md", by_path)
            self.assertNotIn("Sheets/session-001/npc-mira-venn.html", by_path)

    def test_exclude_dirs_filters_nested_directories_too(self):
        # test_categories_and_exclusions above only ever puts an excluded
        # directory at the workspace *root*, where entity/inherit dirs are
        # never walked from anyway — so the exclude_dirs filter inside the
        # rglob loop never actually fires there. This puts one *inside* an
        # entity dir, the only place the filter is ever consulted.
        with tempfile.TemporaryDirectory() as d:
            root = make_workspace(Path(d), {
                "NPCs/mira-venn.md": "---\ntype: npc\nvisibility: gm-only\n---\nbody",
                "NPCs/_Archive/old.md": "---\ntype: npc\nvisibility: gm-only\n---\nx",
            })
            ws = _config.open_workspace(root)
            recs = _common.iter_content_files(ws)
            by_path = {r.path.relative_to(ws.root).as_posix(): r for r in recs}

            self.assertIn("NPCs/mira-venn.md", by_path)
            self.assertNotIn("NPCs/_Archive/old.md", by_path)

    def test_records_sorted_by_path_regardless_of_creation_order(self):
        # Creation order deliberately scrambled — root doc first, "z" before
        # "a" within the same entity dir — and root/entity/inherit all
        # contribute a record, so a natural (unsorted) walk order would not
        # coincidentally already be ascending.
        with tempfile.TemporaryDirectory() as d:
            root = make_workspace(Path(d), {
                "NPCs/z.md": "---\ntype: npc\nvisibility: gm-only\n---\nz",
                "compendium.md": "# Compendium",
                "Briefs/b.md": "---\ntype: brief\n---\nb",
                "NPCs/a.md": "---\ntype: npc\nvisibility: gm-only\n---\na",
            })
            ws = _config.open_workspace(root)
            recs = _common.iter_content_files(ws)
            rels = [r.path.relative_to(ws.root).as_posix() for r in recs]

            # Sanity: all three category loops actually contributed a
            # record, so an already-sorted result isn't a trivial artifact
            # of only one loop running.
            self.assertEqual(
                set(rels), {"NPCs/z.md", "compendium.md", "Briefs/b.md", "NPCs/a.md"})
            self.assertEqual(rels, sorted(rels))

    def test_front_matter_parsed(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_workspace(Path(d), {
                "Mechanics/x.md": "---\ntype: mechanic\nvisibility: player-visible\n---\ntext",
            })
            ws = _config.open_workspace(root)
            rec = _common.iter_content_files(ws)[0]
            self.assertEqual(rec.fm["visibility"], "player-visible")
            self.assertIn("text", rec.body)


class TestVisibilityAudit(unittest.TestCase):
    def test_lists_entity_files_only(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_workspace(Path(d), {
                "Mechanics/pc-rules.md": "---\ntype: mechanic\nvisibility: player-visible\n---\nx",
                "Mechanics/secret.md": "---\ntype: mechanic\nvisibility: gm-only\nreveal_when: the coronation\n---\nx",
                "Briefs/session-001/x.md": "---\ntype: brief\n---\nx",
                "compendium.md": "# c",
            })
            ws = _config.open_workspace(root)
            files = review._common.iter_content_files(ws)
            found = review.check_visibility_audit(files, ws.root)
            msgs = {f.file: f.message for f in found}

            self.assertEqual(msgs["Mechanics/pc-rules.md"], "player-visible")
            self.assertIn("gm-only", msgs["Mechanics/secret.md"])
            self.assertIn("the coronation", msgs["Mechanics/secret.md"])
            # inherit + root files are not audited
            self.assertNotIn("Briefs/session-001/x.md", msgs)
            self.assertNotIn("compendium.md", msgs)
            self.assertTrue(all(f.severity == "info" for f in found))

    def test_mixed_visibility_message_is_not_doubled(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_workspace(Path(d), {
                "Mechanics/shared.md": "---\ntype: mechanic\nvisibility: mixed\n---\nx",
            })
            ws = _config.open_workspace(root)
            files = review._common.iter_content_files(ws)
            found = review.check_visibility_audit(files, ws.root)
            msgs = {f.file: f.message for f in found}

            self.assertEqual(msgs["Mechanics/shared.md"], "mixed")


class TestFrontMatter(unittest.TestCase):
    def test_flags_missing_and_invalid(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_workspace(Path(d), {
                "NPCs/good.md": "---\ntype: npc\ncanon: draft\nvisibility: gm-only\nsummary: A person.\n---\nx",
                "NPCs/no-vis.md": "---\ntype: npc\ncanon: draft\nsummary: X.\n---\nx",
                "NPCs/bad-canon.md": "---\ntype: npc\ncanon: nonsense\nvisibility: gm-only\nsummary: X.\n---\nx",
                "NPCs/no-summary.md": "---\ntype: npc\ncanon: draft\nvisibility: gm-only\n---\nx",
                "compendium.md": "# c",  # root: exempt
            })
            ws = _config.open_workspace(root)
            files = review._common.iter_content_files(ws)
            found = review.check_front_matter(files, ws.root)
            errors = {f.file for f in found if f.severity == "error"}
            warns = {f.file for f in found if f.severity == "warn"}

            self.assertIn("NPCs/no-vis.md", errors)
            self.assertIn("NPCs/bad-canon.md", errors)
            self.assertIn("NPCs/no-summary.md", warns)
            self.assertNotIn("NPCs/good.md", errors | warns)
            self.assertNotIn("compendium.md", errors | warns)

    def test_comment_only_summary_is_treated_as_missing(self):
        # Regression test for #7: `summary: # fill me in` used to slip past
        # the presence check. strip_yaml_comment's `\s+#` pattern requires
        # whitespace *before* the `#`, and split_front_matter already strips
        # leading whitespace from every field value, so a comment-only value
        # always has `#` as its first character and strip_yaml_comment on it
        # is a provable no-op (verified by probe). check_front_matter now
        # treats a value starting with `#` as empty, locally.
        with tempfile.TemporaryDirectory() as d:
            root = make_workspace(Path(d), {
                "NPCs/x.md": "---\ntype: npc\ncanon: draft\nvisibility: gm-only\n"
                             "summary: # fill me in\n---\nbody",
            })
            ws = _config.open_workspace(root)
            files = review._common.iter_content_files(ws)
            found = review.check_front_matter(files, ws.root)
            warns = {f.file for f in found if f.severity == "warn"}

            self.assertIn("NPCs/x.md", warns)


class TestWikilinks(unittest.TestCase):
    def test_extract_ignores_fenced_blocks_and_comments(self):
        body = "See [[mira-venn]] and [[riverbend|Riverbend]].\n<!-- [[nope]] -->"
        self.assertEqual(review.extract_wikilinks(body), ["mira-venn", "riverbend"])

    def test_extract_fenced_wikilink_not_extracted(self):
        body = "```\n[[mira-venn]]\n```"
        self.assertEqual(review.extract_wikilinks(body), [])

    def test_extract_backticked_single_wikilink_is_extracted(self):
        # This workspace's convention (AGENTS.md) is to write wikilinks
        # inside backticks: a code span containing nothing but one wikilink
        # must still be extracted.
        body = "See `[[mira-venn]]` for details."
        self.assertEqual(review.extract_wikilinks(body), ["mira-venn"])

    def test_extract_multi_token_code_span_not_extracted(self):
        body = "`see [[a]] and [[b]] below`"
        self.assertEqual(review.extract_wikilinks(body), [])

    def test_extract_multi_wikilink_code_span_not_extracted(self):
        # No leading prose, but more than one wikilink in the span: the
        # greedy unwrap regex must not treat this as a single-link span.
        body = "`[[a]] and [[b]]`"
        self.assertEqual(review.extract_wikilinks(body), [])

    def test_extract_prose_bearing_code_span_not_extracted(self):
        body = "`the target is [[mira-venn]]`"
        self.assertEqual(review.extract_wikilinks(body), [])

    def test_extract_html_comment_not_extracted(self):
        body = "<!-- [[nope]] -->"
        self.assertEqual(review.extract_wikilinks(body), [])

    def test_flags_unresolved(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_workspace(Path(d), {
                "NPCs/mira-venn.md": "---\ntype: npc\naliases: [the apprentice]\nvisibility: gm-only\n---\nSee [[compendium]].",
                "Setting/riverbend.md": "---\ntype: setting\nvisibility: gm-only\n---\nLinks: [[mira-venn]], [[the apprentice]], [[ghost-town]].",
                "compendium.md": "# c",
            })
            ws = _config.open_workspace(root)
            files = review._common.iter_content_files(ws)
            found = review.check_wikilinks(files, ws)
            bad = {(f.file, f.message) for f in found}

            # ghost-town resolves to nothing -> warn
            self.assertTrue(any("ghost-town" in m for _, m in bad))
            # mira-venn (stem), the apprentice (alias), compendium (root) all resolve
            self.assertFalse(any("mira-venn" in m for _, m in bad))
            self.assertFalse(any("apprentice" in m for _, m in bad))
            self.assertFalse(any("compendium" in m for _, m in bad))

    def test_resolves_path_form_target_by_last_segment(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_workspace(Path(d), {
                "Mechanics/species-house-rule.md": "---\ntype: mechanic\nvisibility: gm-only\n---\nx",
                "style-guide.md": "---\n---\nSee `[[Mechanics/species-house-rule]]`.",
            })
            ws = _config.open_workspace(root)
            files = review._common.iter_content_files(ws)
            found = review.check_wikilinks(files, ws)
            self.assertFalse(any("species-house-rule" in f.message for f in found))

    def test_bare_content_dir_names_are_valid_targets(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_workspace(Path(d), {
                "AGENTS.md": "---\n---\nSee `[[Mechanics]]`, `[[Factions]]`, `[[Ideas]]`, `[[Handouts]]`.",
            })
            ws = _config.open_workspace(root)
            files = review._common.iter_content_files(ws)
            found = review.check_wikilinks(files, ws)
            self.assertEqual(found, [])

    def test_block_style_aliases_each_resolve_individually(self):
        # Regression test for #9: block-style `aliases:` used to fold into
        # one junk alias via split_front_matter's continuation-line joining,
        # so neither declared alias resolved.
        with tempfile.TemporaryDirectory() as d:
            root = make_workspace(Path(d), {
                "NPCs/ghost.md": "---\ntype: npc\nvisibility: gm-only\n"
                                  "aliases:\n  - The Ghost\n  - Old Man\n---\nx",
                "Setting/riverbend.md": "---\ntype: setting\nvisibility: gm-only\n---\n"
                                       "See [[The Ghost]] and [[Old Man]].",
            })
            ws = _config.open_workspace(root)
            files = review._common.iter_content_files(ws)
            found = review.check_wikilinks(files, ws)
            self.assertEqual(found, [])


class TestCompendium(unittest.TestCase):
    def test_flags_unindexed_entities(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_workspace(Path(d), {
                "compendium.md": "# Compendium\n- [[mira-venn]] indexed\n",
                "NPCs/mira-venn.md": "---\ntype: npc\nvisibility: gm-only\n---\nx",
                "NPCs/vessarine-holt.md": "---\ntype: npc\nvisibility: gm-only\n---\nx",
                "Sessions/session-001.md": "---\ntype: session\nvisibility: gm-only\n---\nx",
            })
            ws = _config.open_workspace(root)
            files = review._common.iter_content_files(ws)
            found = review.check_compendium(files, ws)
            flagged = {f.file for f in found}

            self.assertIn("NPCs/vessarine-holt.md", flagged)       # not indexed
            self.assertNotIn("NPCs/mira-venn.md", flagged)  # indexed
            self.assertNotIn("Sessions/session-001.md", flagged)  # sessions exempt

    def test_flags_nested_unindexed_entities(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_workspace(Path(d), {
                "compendium.md": "# Compendium\n- [[boris]] indexed\n",
                "NPCs/Villains/boris.md": "---\ntype: npc\nvisibility: gm-only\n---\nx",
                "NPCs/Villains/vera.md": "---\ntype: npc\nvisibility: gm-only\n---\nx",
            })
            ws = _config.open_workspace(root)
            files = review._common.iter_content_files(ws)
            found = review.check_compendium(files, ws)
            flagged = {f.file for f in found}

            self.assertIn("NPCs/Villains/vera.md", flagged)   # nested, not indexed
            self.assertNotIn("NPCs/Villains/boris.md", flagged)  # nested, indexed

    def test_alias_indexed_entity_not_flagged_unindexed(self):
        # Regression test for #8: compendium.md indexing an entity by one
        # of its declared aliases must satisfy the compendium check, the
        # same way it already satisfies check_wikilinks.
        with tempfile.TemporaryDirectory() as d:
            root = make_workspace(Path(d), {
                "compendium.md": "# Compendium\n- [[the apprentice]] indexed\n",
                "NPCs/mira-venn.md": "---\ntype: npc\naliases: [the apprentice]\n"
                                    "visibility: gm-only\n---\nx",
            })
            ws = _config.open_workspace(root)
            files = review._common.iter_content_files(ws)
            found = review.check_compendium(files, ws)
            flagged = {f.file for f in found}

            self.assertNotIn("NPCs/mira-venn.md", flagged)

    def test_path_form_indexed_entity_not_flagged_unindexed(self):
        # Regression test for #8: compendium.md indexing an entity by a
        # path-form target (resolved by last segment) must also satisfy the
        # compendium check.
        with tempfile.TemporaryDirectory() as d:
            root = make_workspace(Path(d), {
                "compendium.md": "# Compendium\n- [[Mechanics/species-house-rule]] indexed\n",
                "Mechanics/species-house-rule.md": "---\ntype: mechanic\n"
                                                     "visibility: gm-only\n---\nx",
            })
            ws = _config.open_workspace(root)
            files = review._common.iter_content_files(ws)
            found = review.check_compendium(files, ws)
            flagged = {f.file for f in found}

            self.assertNotIn("Mechanics/species-house-rule.md", flagged)


class TestRevealWhen(unittest.TestCase):
    def test_flags_reveal_when_on_non_gm_only(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_workspace(Path(d), {
                "Mechanics/ok.md": "---\ntype: mechanic\nvisibility: gm-only\nreveal_when: the coronation\n---\nx",
                "Mechanics/bad.md": "---\ntype: mechanic\nvisibility: player-visible\nreveal_when: the coronation\n---\nx",
                "Mechanics/plain.md": "---\ntype: mechanic\nvisibility: player-visible\n---\nx",
            })
            ws = _config.open_workspace(root)
            files = review._common.iter_content_files(ws)
            found = review.check_reveal_when(files, ws.root)
            flagged = {f.file for f in found}

            self.assertIn("Mechanics/bad.md", flagged)
            self.assertNotIn("Mechanics/ok.md", flagged)
            self.assertNotIn("Mechanics/plain.md", flagged)


class TestRunnerCLI(unittest.TestCase):
    def test_run_suite_and_exit_code(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_workspace(Path(d), {
                "compendium.md": "# c\n- [[good]]\n",
                "NPCs/good.md": "---\ntype: npc\ncanon: draft\nvisibility: player-visible\nsummary: Good.\n---\nx",
                "NPCs/broken.md": "---\ntype: npc\ncanon: draft\nsummary: No vis.\n---\nx",
            })
            ws = _config.open_workspace(root)
            findings = review.run_suite("checkup", ws)
            checks = {f.check for f in findings}
            self.assertIn("visibility-audit", checks)
            self.assertIn("front-matter", checks)
            # broken.md missing visibility -> an error finding exists
            self.assertTrue(any(f.severity == "error" for f in findings))

    def test_format_terminal_contains_sections(self):
        findings = [
            review.Finding("info", "visibility-audit", "NPCs/a.md", "gm-only"),
            review.Finding("error", "front-matter", "NPCs/b.md", "missing `visibility`"),
        ]
        text = review.format_terminal(findings, "checkup")
        self.assertIn("visibility-audit", text)
        self.assertIn("NPCs/b.md", text)
        self.assertIn("missing `visibility`", text)

    def test_format_terminal_uses_given_suite_not_hardcoded_checkup(self):
        # A suite other than "checkup" must still print its own check blocks,
        # not silently fall back to the checkup suite's block list.
        review.SUITES["other-suite"] = ["front-matter"]
        try:
            findings = [
                review.Finding("error", "front-matter", "NPCs/b.md", "missing `visibility`"),
            ]
            text = review.format_terminal(findings, "other-suite")
            self.assertIn("front-matter  (1 finding(s))", text)
            self.assertNotIn("wikilinks  (", text)
        finally:
            del review.SUITES["other-suite"]

    def test_unknown_suite_errors(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                review.main(["nonesuch"])


class TestMainWorkspace(unittest.TestCase):
    """main(), steered via --workspace rather than a reassigned module
    global — that mechanism has been retired."""

    def _run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = review.main(list(argv))
        return rc, out.getvalue(), err.getvalue()

    def test_reviews_the_chosen_workspace_and_exits_nonzero_on_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_workspace(Path(d), {
                "NPCs/broken.md":
                    "---\ntype: npc\ncanon: draft\nsummary: No vis.\n---\nx",
            })
            rc, out, _err = self._run_main("--workspace", str(root))
            self.assertEqual(rc, 1)
            self.assertIn("NPCs/broken.md", out)
            self.assertIn("missing `visibility`", out)

    def test_clean_workspace_exits_zero(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_workspace(Path(d), {
                "compendium.md": "# c\n- [[good]]\n",
                "NPCs/good.md":
                    "---\ntype: npc\ncanon: draft\nvisibility: player-visible\n"
                    "summary: Good.\n---\nx",
            })
            rc, _out, err = self._run_main("--workspace", str(root))
            self.assertEqual(rc, 0, err)

    def test_html_report_lands_in_the_chosen_workspaces_reviews_dir(self):
        # The report path follows --workspace: write_html takes the root it
        # was handed rather than reading a module constant fixed at import.
        with tempfile.TemporaryDirectory() as d:
            root = make_workspace(Path(d), {
                "NPCs/good.md":
                    "---\ntype: npc\ncanon: draft\nvisibility: player-visible\n"
                    "summary: Good.\n---\nx",
            })
            rc, out, err = self._run_main("--workspace", str(root), "--html")
            # The fixture is one clean draft NPC, so checkup finds nothing:
            # exit 0 exactly. Accepting 1 as well would let a fixture that
            # started erroring pass unnoticed.
            self.assertEqual(rc, 0, err)
            self.assertTrue((root / "Reviews" / "checkup.html").is_file())
            # ...and the printed path is workspace-relative, not absolute.
            # Asserting the tail alone does not show that: an absolute
            # /tmp/.../Reviews/checkup.html contains it too. The literal must
            # include what comes immediately BEFORE the path, so anything
            # printed between "HTML report: " and "Reviews/" fails.
            self.assertIn("HTML report: Reviews/checkup.html", out)

    def test_missing_workspace_returns_nonzero_with_a_clear_message(self):
        # --workspace pointing at a directory with no campaign.toml is an
        # error, not a search hint — resolve_workspace must not walk up.
        with tempfile.TemporaryDirectory() as d:
            rc, _out, err = self._run_main("--workspace", d)
            self.assertEqual(rc, 1)
            self.assertIn("campaign.toml", err)


class TestHtml(unittest.TestCase):
    def test_writes_report(self):
        from bunnyforge import review as r
        findings = [
            r.Finding("info", "visibility-audit", "NPCs/a.md", "player-visible"),
            r.Finding("error", "front-matter", "NPCs/b.md", "missing `visibility`"),
            r.Finding("warn", "wikilinks", "NPCs/c.md", "broken wikilink: [[<script>]]"),
        ]
        with tempfile.TemporaryDirectory() as d:
            dest = r.write_html("checkup", findings, Path(d))
            self.assertEqual(dest, Path(d) / "Reviews" / "checkup.html")
            self.assertTrue(dest.is_file())
            html_text = dest.read_text(encoding="utf-8")
            self.assertIn("NPCs/b.md", html_text)
            self.assertIn("player-visible", html_text)
            # Test HTML escaping: <script> should be escaped to &lt;script&gt;
            self.assertIn("&lt;script&gt;", html_text)
            self.assertNotIn("<script>", html_text)


class TestMarkdownLinkChecked(unittest.TestCase):
    def test_broken_markdown_link_is_flagged(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_workspace(Path(d), {
                "Mechanics/a.md":
                    "---\ntype: mechanic\nvisibility: gm-only\n---\n"
                    "See [the rules](nonexistent-doc).\n",
            })
            ws = _config.open_workspace(root)
            files = _common.iter_content_files(ws)
            found = review.check_wikilinks(files, ws)
            self.assertTrue(any("nonexistent-doc" in f.message for f in found))

    def test_markdown_link_to_external_url_not_flagged(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_workspace(Path(d), {
                "Mechanics/a.md":
                    "---\ntype: mechanic\nvisibility: gm-only\n---\n"
                    "See [Anthropic](https://anthropic.com).\n",
            })
            ws = _config.open_workspace(root)
            files = _common.iter_content_files(ws)
            self.assertEqual(review.check_wikilinks(files, ws), [])

    def test_extract_includes_markdown_form(self):
        self.assertEqual(
            review.extract_wikilinks("a [x](target-one) and [[target-two]]"),
            ["target-one", "target-two"])


class TestResolverMovedToCommon(unittest.TestCase):
    def test_common_exposes_the_resolver(self):
        self.assertTrue(callable(_common.split_aliases))
        self.assertTrue(callable(_common.aliases_for))
        self.assertTrue(callable(_common.target_index))
        self.assertTrue(callable(_common.resolve_target))

    def test_resolves_stem_and_alias(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_workspace(Path(d), {
                "NPCs/mira-venn.md":
                    "---\ntype: npc\nvisibility: gm-only\naliases: [the apprentice]\n---\nx",
            })
            ws = _config.open_workspace(root)
            files = _common.iter_content_files(ws)
            index = _common.target_index(files)
            self.assertTrue(_common.resolve_target("mira-venn", index))
            self.assertTrue(_common.resolve_target("The Apprentice", index))
            self.assertFalse(_common.resolve_target("nobody", index))


class TestCompendiumDirsFromConfig(unittest.TestCase):
    """check_compendium must filter against the workspace's own
    config.compendium_dirs, not a hardcoded list or one re-derived from
    entity_dirs (e.g. entity_dirs minus {Sessions, Handouts})."""

    def test_uses_workspace_compendium_dirs_not_a_derived_list(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_workspace(Path(d), {
                "campaign.toml": (
                    '[campaign]\nnamespace = "t"\n\n[workspace]\n'
                    'entity_dirs = ["NPCs", "Sessions"]\n'
                    'compendium_dirs = ["Sessions"]\n'),
                "compendium.md": "# c\n",
                "NPCs/a.md": "---\ntype: npc\nvisibility: gm-only\n---\nx",
                "Sessions/s1.md": "---\ntype: session\nvisibility: gm-only\n---\nx",
            })
            ws = _config.open_workspace(root)
            files = review._common.iter_content_files(ws)
            found = review.check_compendium(files, ws)
            flagged = {f.file for f in found}

            # Sessions IS in compendium_dirs here (unlike this repo's own
            # config) -> unindexed Sessions/s1.md must be flagged.
            self.assertIn("Sessions/s1.md", flagged)
            # NPCs is an entity_dir but NOT in compendium_dirs -> never
            # flagged, even though a derivation from entity_dirs would
            # wrongly include it.
            self.assertNotIn("NPCs/a.md", flagged)


if __name__ == "__main__":
    unittest.main()


class TestWikiConfCheck(unittest.TestCase):
    def test_useacl_off_is_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_install(Path(d), local_php="$conf['useacl'] = 0;\n")
            findings = review.check_wiki_conf([], root)
            self.assertTrue(any(f.severity == "error" and "useacl" in f.message
                                for f in findings), findings)

    def test_useacl_on_but_set_in_dokuwiki_php_is_an_error(self):
        # The exact shape of the first historical failure: the value is
        # right, but it lives in the file upgrades overwrite, so it is one
        # upgrade away from silently reverting.
        with tempfile.TemporaryDirectory() as d:
            root = make_install(Path(d), dokuwiki_php="$conf['useacl'] = 1;\n")
            findings = review.check_wiki_conf([], root)
            self.assertTrue(any(f.severity == "error" and "dokuwiki.php" in f.message
                                for f in findings), findings)

    def test_useacl_on_in_local_php_passes(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_install(Path(d),
                                local_php="$conf['useacl'] = 1;\n"
                                          "$conf['useheading'] = 'navigation';\n")
            self.assertEqual(review.check_wiki_conf([], root), [])

    def test_useheading_unset_is_a_warning(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_install(Path(d), local_php="$conf['useacl'] = 1;\n")
            findings = review.check_wiki_conf([], root)
            self.assertTrue(any(f.severity == "warn" and "useheading" in f.message
                                for f in findings), findings)

    def test_useheading_zero_is_a_warning(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_install(Path(d),
                                local_php="$conf['useacl'] = 1;\n"
                                          "$conf['useheading'] = 0;\n")
            findings = review.check_wiki_conf([], root)
            self.assertTrue(any(f.severity == "warn" and "useheading" in f.message
                                for f in findings), findings)

    def test_useheading_navigation_is_accepted(self):
        # The value actually in use on a real install. A naive `== 1` check
        # would false-alarm here, which is why the invariant is truthiness.
        with tempfile.TemporaryDirectory() as d:
            root = make_install(Path(d),
                                local_php="$conf['useacl'] = 1;\n"
                                          "$conf['useheading'] = 'navigation';\n")
            self.assertEqual(
                [f for f in review.check_wiki_conf([], root)
                 if "useheading" in f.message], [])


class TestWikiAclCheck(unittest.TestCase):
    def test_a_group_grant_without_a_fallthrough_rule_is_an_error(self):
        # The second historical failure, stated generically: ns:* grants to a
        # group and says nothing about anyone else, so any logged-in account
        # outside that group falls through to the global rule.
        with tempfile.TemporaryDirectory() as d:
            root = make_install(Path(d), acl="*\t@user\t2\nns:*\t@team\t2\n")
            findings = review.check_wiki_acl([], root)
            self.assertTrue(any(f.severity == "error" and "ns:*" in f.message
                                for f in findings), findings)

    def test_a_group_grant_with_an_at_user_rule_passes(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_install(
                Path(d), acl="*\t@user\t2\nns:*\t@team\t2\nns:*\t@user\t1\n")
            self.assertEqual(review.check_wiki_acl([], root), [])

    def test_a_group_grant_with_an_at_all_denial_passes(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_install(Path(d), acl="gm:*\t@gm\t2\ngm:*\t@ALL\t0\n")
            self.assertEqual(review.check_wiki_acl([], root), [])

    def test_a_user_grant_needs_no_fallthrough_rule(self):
        # The rule is about group grants. A per-user grant does not create
        # the fall-through hazard, so it must not be reported.
        with tempfile.TemporaryDirectory() as d:
            root = make_install(Path(d), acl="ns:*\talice\t2\n")
            self.assertEqual(review.check_wiki_acl([], root), [])

    def test_a_group_rule_of_level_zero_is_not_a_grant(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_install(Path(d), acl="ns:*\t@team\t0\n")
            self.assertEqual(review.check_wiki_acl([], root), [])

    def test_every_offending_scope_is_reported_not_just_the_first(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_install(Path(d), acl="a:*\t@x\t2\nb:*\t@y\t2\n")
            findings = review.check_wiki_acl([], root)
            self.assertEqual(len(findings), 2, findings)


class TestWikiPluginsCheck(unittest.TestCase):
    def test_missing_include_plugin_is_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            findings = review.check_wiki_plugins([], make_install(Path(d)))
            self.assertTrue(any(f.severity == "error" for f in findings), findings)

    def test_disabled_include_plugin_is_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_install(Path(d), plugins=("include",),
                                plugins_local_php="$plugins['include'] = 0;\n")
            findings = review.check_wiki_plugins([], root)
            self.assertTrue(any("disabled" in f.message for f in findings), findings)

    def test_installed_and_enabled_passes(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_install(Path(d), plugins=("include",))
            self.assertEqual(review.check_wiki_plugins([], root), [])


class TestWikiRemote(unittest.TestCase):
    def _wiki(self, d: Path, local_php="", dokuwiki_php=""):
        (d / "conf").mkdir(parents=True, exist_ok=True)
        (d / "lib" / "plugins").mkdir(parents=True, exist_ok=True)
        (d / "conf" / "dokuwiki.php").write_text(
            "<?php\n" + dokuwiki_php, encoding="utf-8")
        if local_php:
            (d / "conf" / "local.php").write_text(
                "<?php\n" + local_php, encoding="utf-8")
        return d

    def _findings(self, d):
        return review.check_wiki_remote([], d)

    def test_disabled_is_no_finding(self):
        with tempfile.TemporaryDirectory() as d:
            wiki = self._wiki(Path(d), dokuwiki_php="$conf['remote'] = 0;\n")
            self.assertEqual(self._findings(wiki), [])

    def test_enabled_without_remoteuser_is_error(self):
        with tempfile.TemporaryDirectory() as d:
            wiki = self._wiki(Path(d), local_php="$conf['remote'] = 1;\n")
            findings = self._findings(wiki)
            self.assertTrue(any(f.severity == "error" and
                                "remoteuser" in f.message for f in findings))

    def test_stock_not_set_placeholder_counts_as_unset(self):
        with tempfile.TemporaryDirectory() as d:
            wiki = self._wiki(Path(d), local_php=(
                "$conf['remote'] = 1;\n"
                "$conf['remoteuser'] = '!!not set!!';\n"))
            findings = self._findings(wiki)
            self.assertTrue(any("remoteuser" in f.message for f in findings))

    def test_scoped_remoteuser_is_clean(self):
        with tempfile.TemporaryDirectory() as d:
            wiki = self._wiki(Path(d), local_php=(
                "$conf['remote'] = 1;\n"
                "$conf['remoteuser'] = 'deploybot';\n"))
            self.assertEqual(self._findings(wiki), [])

    def test_enabled_from_dokuwiki_php_is_provenance_error(self):
        with tempfile.TemporaryDirectory() as d:
            wiki = self._wiki(Path(d), dokuwiki_php=(
                "$conf['remote'] = 1;\n"
                "$conf['remoteuser'] = 'deploybot';\n"))
            findings = self._findings(wiki)
            self.assertTrue(any(f.severity == "error" and
                                "dokuwiki.php" in f.message for f in findings))

    def test_remoteuser_scoped_but_from_dokuwiki_php_is_provenance_error(self):
        # remote itself is correctly scoped to local.php; remoteuser is the
        # one that reverts on upgrade. This is the sharper failure the
        # provenance rule on `remote` alone misses entirely: the check
        # passes clean today and hands every account the API back the next
        # time DokuWiki upgrades.
        with tempfile.TemporaryDirectory() as d:
            wiki = self._wiki(
                Path(d),
                local_php="$conf['remote'] = 1;\n",
                dokuwiki_php="$conf['remoteuser'] = 'deploybot';\n")
            findings = self._findings(wiki)
            self.assertTrue(
                any(f.severity == "error" and "remoteuser" in f.message
                    and "dokuwiki.php" in f.message for f in findings),
                findings)
            # And nothing else fires: `remote` itself is clean, so only the
            # remoteuser-provenance finding should be present.
            self.assertEqual(len(findings), 1, findings)

    def test_placeholder_remoteuser_from_dokuwiki_php_is_still_unset(self):
        # The placeholder is DokuWiki's not-configured sentinel regardless
        # of which file it appears in. It must trip the unset finding, not
        # the provenance one — there is nothing to move to local.php, the
        # deploy user was simply never scoped.
        with tempfile.TemporaryDirectory() as d:
            wiki = self._wiki(
                Path(d),
                local_php="$conf['remote'] = 1;\n",
                dokuwiki_php="$conf['remoteuser'] = '!!not set!!';\n")
            findings = self._findings(wiki)
            self.assertTrue(
                any(f.severity == "error" and "unset" in f.message
                    for f in findings),
                findings)
            self.assertFalse(
                any(f.file and "dokuwiki.php" in f.file for f in findings),
                findings)
            self.assertEqual(len(findings), 1, findings)

    def test_both_scoped_to_local_php_is_still_clean(self):
        # Confirms the new provenance rule does not false-alarm on the
        # already-correct configuration.
        with tempfile.TemporaryDirectory() as d:
            wiki = self._wiki(Path(d), local_php=(
                "$conf['remote'] = 1;\n"
                "$conf['remoteuser'] = 'deploybot';\n"))
            self.assertEqual(self._findings(wiki), [])

    def test_wiki_suite_includes_wiki_remote(self):
        self.assertIn("wiki-remote", review.SUITES["wiki"])


class TestWikiSuiteWiring(unittest.TestCase):
    def test_checkup_does_not_include_any_wiki_check(self):
        # CI has no wiki. The separation is the whole skippability mechanism,
        # so it gets an explicit test rather than resting on the suite lists
        # happening to be right.
        self.assertEqual(
            [c for c in review.SUITES["checkup"] if c.startswith("wiki-")], [])

    def test_the_wiki_suite_is_exactly_the_wiki_checks(self):
        self.assertTrue(all(c.startswith("wiki-") for c in review.SUITES["wiki"]))
        self.assertEqual(set(review.SUITES["wiki"]), review._NEEDS_WIKI)

    def test_every_registered_check_belongs_to_a_suite(self):
        registered = set(review.CHECKS)
        in_suites = {c for names in review.SUITES.values() for c in names}
        self.assertEqual(registered, in_suites)

    def test_the_wiki_suite_requires_wiki_root(self):
        # No --wiki-root and no [wiki] install_root in campaign.toml: the
        # instructional error must name both routes. A real workspace is
        # needed here (--wiki-root's absence can only be resolved against
        # config once the workspace holding that config is known), so this
        # uses an explicit one rather than relying on ambient cwd/env.
        with tempfile.TemporaryDirectory() as d:
            ws = make_workspace(Path(d), {})
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = review.main(["wiki", "--workspace", str(ws)])
            self.assertEqual(rc, 1)
            self.assertIn("--wiki-root", err.getvalue())
            self.assertIn("install_root", err.getvalue())
            self.assertIn("campaign.toml", err.getvalue())

    def test_a_bad_wiki_root_is_one_error_line_not_a_traceback(self):
        with tempfile.TemporaryDirectory() as d:
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = review.main(["wiki", "--wiki-root", d,
                                  "--workspace", str(Path(d))])
            self.assertEqual(rc, 1)
            self.assertIn("error:", err.getvalue())
            self.assertNotIn("Traceback", err.getvalue())

    def test_configured_install_root_used_when_flag_absent(self):
        # --wiki-root absent, [wiki] install_root set: the configured path
        # is used. Proven without a real DokuWiki install by pointing at a
        # nonexistent directory and checking that _dokuwiki_install's own
        # (already-instructional) refusal names that exact path — evidence
        # the configured value, not some other default, reached check_root.
        with tempfile.TemporaryDirectory() as d:
            configured = str(Path(d) / "configured-wiki-copy")
            ws = make_workspace(Path(d) / "ws", {
                "campaign.toml": '[campaign]\nnamespace = "test"\n'
                                 f'[wiki]\ninstall_root = "{configured}"\n'})
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = review.main(["wiki", "--workspace", str(ws)])
            self.assertEqual(rc, 1)
            self.assertIn(configured, err.getvalue())

    def test_flag_overrides_configured_install_root(self):
        # Explicit beats configured: when both are present, --wiki-root
        # wins. Distinguished the same way as above — two different
        # nonexistent paths, and only the flag's should appear in the error.
        with tempfile.TemporaryDirectory() as d:
            configured = str(Path(d) / "configured-wiki-copy")
            flagged = str(Path(d) / "flagged-wiki-copy")
            ws = make_workspace(Path(d) / "ws", {
                "campaign.toml": '[campaign]\nnamespace = "test"\n'
                                 f'[wiki]\ninstall_root = "{configured}"\n'})
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = review.main(["wiki", "--workspace", str(ws),
                                  "--wiki-root", flagged])
            self.assertEqual(rc, 1)
            self.assertIn(flagged, err.getvalue())
            self.assertNotIn(configured, err.getvalue())

    def test_configured_install_root_expands_tilde(self):
        # The CLI already expands ~ and resolves --wiki-root; the configured
        # value must get the same treatment rather than being handed to
        # check_root as a literal "~/...".
        with tempfile.TemporaryDirectory() as home:
            ws = make_workspace(Path(home) / "ws", {
                "campaign.toml": '[campaign]\nnamespace = "test"\n'
                                 '[wiki]\ninstall_root = '
                                 '"~/configured-wiki-copy"\n'})
            expected = str(Path(home) / "configured-wiki-copy")
            out, err = io.StringIO(), io.StringIO()
            with mock.patch.dict(os.environ, {"HOME": home}, clear=False), \
                 contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = review.main(["wiki", "--workspace", str(ws)])
            self.assertEqual(rc, 1)
            self.assertNotIn("~", err.getvalue())
            self.assertIn(expected, err.getvalue())

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from bunnyforge import _config
from bunnyforge import deploy_export
from bunnyforge import export_player

NS = "testwiki"   # tests own their namespace; never the campaign's

# The fixtures below rely on the conventional directory shape (NPCs,
# Mechanics, Perceptions, ... — see _config._DEFAULTS) that a campaign.toml
# with no [workspace] table falls back to, so a bare namespace declaration is
# all any of them needs. A campaign.toml written into an Export/ or staging
# directory is simply ignored (render_tree only globs *.md).
_MINIMAL_CAMPAIGN_TOML = '[campaign]\nnamespace = "test"\n'


def make_export(root: Path, files: dict) -> Path:
    if "campaign.toml" not in files:
        root.mkdir(parents=True, exist_ok=True)
        (root / "campaign.toml").write_text(_MINIMAL_CAMPAIGN_TOML, encoding="utf-8")
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return root


def run_main(argv):
    """Call deploy_export.main(argv); return (rc, out, err)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = deploy_export.main(argv)
    return rc, out.getvalue(), err.getvalue()


def namespace_of(root: Path) -> str:
    """The namespace main() renders a run against `root` under.

    Read back from the workspace's own campaign.toml rather than written as a
    literal, so a main() that stopped consulting config would fail here.
    """
    return _config.open_workspace(root).config.namespace


class TestRenderTree(unittest.TestCase):
    def test_writes_content_and_wrapper(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            export = make_export(d / "Export", {
                "Mechanics/species-house-rule.md": "# Species House Rule\n\n- one\n",
            })
            staging = d / "stage"
            result, _log = deploy_export.render_tree(export, staging, base=NS)

            content = staging / NS / "export" / "mechanics" / "species-house-rule.txt"
            wrapper = staging / NS / "mechanics" / "species-house-rule.txt"
            self.assertTrue(content.is_file())
            self.assertTrue(wrapper.is_file())

            body = content.read_text(encoding="utf-8")
            self.assertIn("====== Species House Rule ======", body)
            self.assertIn("  * one", body)
            # exactly one title heading — no injected duplicate
            self.assertEqual(body.count("====== Species House Rule ======"), 1)

            wrap = wrapper.read_text(encoding="utf-8")
            self.assertIn(f"{{{{page>{NS}:export:mechanics:species-house-rule}}}}", wrap)
            self.assertIn(f"{{{{page>{NS}:players:mechanics:species-house-rule}}}}", wrap)

            self.assertEqual(result.pages, 1)
            self.assertEqual(result.wrappers, 1)

            # NS:players:... belongs to the players and must never be
            # written by this script — only referenced from the wrapper.
            players = staging / NS / "players" / "mechanics" / "species-house-rule.txt"
            self.assertFalse(players.exists())

    def test_protected_page_gets_no_wrapper(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            export = make_export(d / "Export", {"main.md": "# Main\n\nhand-written\n"})
            staging = d / "stage"
            result, _log = deploy_export.render_tree(export, staging, base=NS)

            self.assertFalse((staging / NS / "main.txt").exists())
            # Neither a wrapper nor a content page is produced for a
            # protected page — check both halves, not just the wrapper.
            self.assertFalse((staging / NS / "export" / "main.txt").exists())
            self.assertEqual(result.wrappers, 0)
            self.assertEqual(result.pages, 0)
            self.assertEqual(result.skipped, 1)

    def test_reserved_dir_refused(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            export = make_export(d / "Export", {"export/a.md": "# A\n"})
            staging = d / "stage"
            result, _log = deploy_export.render_tree(export, staging, base=NS)

            self.assertEqual(result.collisions, ["export"])
            self.assertEqual(result.pages, 0)

    def test_protected_page_is_base_aware(self):
        # The protected set is namespace-relative, derived from whatever
        # `base` render_tree was handed; a non-default `base` must still
        # protect its own main.md rather than falling through and writing a
        # wrapper for it.
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            export = make_export(d / "Export", {"main.md": "# Main\n\nhand-written\n"})
            staging = d / "stage"
            result, _log = deploy_export.render_tree(export, staging, base="wiki")

            self.assertFalse((staging / "wiki" / "main.txt").exists())
            self.assertFalse((staging / "wiki" / "export" / "main.txt").exists())
            self.assertEqual(result.skipped, 1)
            self.assertEqual(result.pages, 0)

    def test_body_leading_blank_line_stripped(self):
        # export_player.py's exported body (via _common.split_front_matter)
        # starts with the blank line left behind by the front-matter split.
        # render_tree must strip it so the H1 lands on the staged page's
        # first line rather than after a stray blank line.
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            export = make_export(d / "Export", {
                "Mechanics/x.md": "\n# X\n\nbody text\n",
            })
            staging = d / "stage"
            deploy_export.render_tree(export, staging, base=NS)

            content = staging / NS / "export" / "mechanics" / "x.txt"
            text = content.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("====== X ======"),
                             f"leading blank line survived: {text!r}")


class TestNoLeakThroughRender(unittest.TestCase):
    """Every GM construct carries a sentinel; none may survive to staging."""

    def test_sentinels_absent_from_staged_tree(self):
        sentinels = [
            "SENTINEL_GMONLY_FILE",
            "SENTINEL_UNKNOWN_VIS",
            "SENTINEL_BELOW_GM_NOTES",
            "SENTINEL_DESIGN_INTENT",
            "SENTINEL_BALANCE_NOTES",
            "SENTINEL_PLAYTEST_LOG",
            "SENTINEL_HTML_COMMENT",
        ]
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            ws = make_export(d / "ws", {
                "Mechanics/secret.md":
                    "---\ntype: mechanic\nvisibility: gm-only\n---\n"
                    "# Secret\n\nSENTINEL_GMONLY_FILE\n",
                "Mechanics/garbage.md":
                    "---\ntype: mechanic\nvisibility: nonsense\n---\n"
                    "# Garbage\n\nSENTINEL_UNKNOWN_VIS\n",
                "Mechanics/mixed.md":
                    "---\ntype: mechanic\nvisibility: mixed\n---\n"
                    "# Mixed\n\nplayer text\n\n---\n## GM notes\n\n"
                    "SENTINEL_BELOW_GM_NOTES\n",
                "Mechanics/open.md":
                    "---\ntype: mechanic\nvisibility: player-visible\n---\n"
                    "# Open\n\nrules text\n\n"
                    "## Design intent\n\nSENTINEL_DESIGN_INTENT\n\n"
                    "## Balance notes\n\nSENTINEL_BALANCE_NOTES\n\n"
                    "## Playtest log\n\nSENTINEL_PLAYTEST_LOG\n\n"
                    "## Interactions and edge cases\n\nkeep me\n"
                    "<!-- SENTINEL_HTML_COMMENT -->\n",
            })

            export = d / "Export"
            export_player.run_export(_config.open_workspace(ws), export)

            staging = d / "stage"
            deploy_export.render_tree(export, staging, base=NS)

            staged = list(staging.rglob("*.txt"))
            self.assertTrue(staged, "render produced no pages")
            blob = "\n".join(p.read_text(encoding="utf-8") for p in staged)

            for s in sentinels:
                self.assertNotIn(s, blob, f"{s} leaked into the staged tree")

            # ...and the player-facing text that should survive, did.
            self.assertIn("rules text", blob)
            self.assertIn("keep me", blob)
            self.assertIn("player text", blob)


class TestMainIntegration(unittest.TestCase):
    """main()'s exit code and stream routing: swap argv, capture streams,
    assert on main()'s return code — not just render_tree()'s return value,
    which main() could still misreport."""

    def _run(self, argv):
        return run_main(argv)

    def test_missing_render_only_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            rc, _out, err = self._run(["--staging", str(Path(d) / "stage")])
            self.assertNotEqual(rc, 0)
            self.assertIn("--render-only", err)

    def test_missing_export_dir_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            # --workspace explicitly: without it main() resolves from cwd,
            # so the test only reached its assertion because the repo it
            # runs in happens to be a campaign workspace. That stops being
            # true the moment these files ship on their own.
            ws = make_export(d / "ws", {})
            rc, _out, err = self._run([
                "--render-only",
                "--workspace", str(ws),
                "--staging", str(d / "stage"),
                "--export-dir", str(d / "no-such-export"),
            ])
            self.assertNotEqual(rc, 0)
            self.assertIn("not found", err)

    def test_reserved_namespace_collision_is_refused_and_lands_on_stderr(self):
        # Pins the stdout/stderr split to the exit code, not to the literal
        # "REFUSED" substring main() currently keys off of: if render_tree's
        # wording ever changes, this must fail rather than silently move the
        # collision message to stdout while still exiting non-zero.
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            ws = make_export(d / "ws", {})     # see the note above on --workspace
            make_export(d / "Export", {"export/a.md": "# A\n"})
            rc, out, err = self._run([
                "--render-only",
                "--workspace", str(ws),
                "--staging", str(d / "stage"),
                "--export-dir", str(d / "Export"),
            ])
            self.assertNotEqual(rc, 0)
            self.assertIn("export", err)
            self.assertNotIn("collides", out)

    def test_success_exits_zero(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            ws = make_export(d / "ws", {})
            make_export(d / "Export", {"Mechanics/a.md": "# A\n\nbody\n"})
            rc, out, _err = self._run([
                "--render-only",
                "--workspace", str(ws),
                "--staging", str(d / "stage"),
                "--export-dir", str(d / "Export"),
            ])
            self.assertEqual(rc, 0)
            self.assertIn("1 page(s)", out)
            # main() has no CLI hook to override the namespace, so it renders
            # under whatever the resolved workspace's campaign.toml declares —
            # read it back rather than hardcoding it.
            self.assertTrue(
                (d / "stage" / namespace_of(ws) / "export"
                 / "mechanics" / "a.txt").exists())

    def test_existing_nonempty_staging_dir_is_refused(self):
        # Finding 1: a leftover staging directory from a prior run must not
        # be silently rendered into — a retired page's file could survive
        # untouched while this run still reports success.
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            ws = make_export(d / "ws", {})
            make_export(d / "Export", {"Mechanics/b.md": "# B\n\nbody\n"})
            staging = d / "stage"
            ns = namespace_of(ws)
            (staging / ns / "export" / "mechanics").mkdir(parents=True)
            (staging / ns / "export" / "mechanics" / "a.txt").write_text(
                "leftover from a retired page\n", encoding="utf-8")

            rc, _out, err = self._run([
                "--render-only",
                "--workspace", str(ws),
                "--staging", str(staging),
                "--export-dir", str(d / "Export"),
            ])
            self.assertNotEqual(rc, 0)
            self.assertIn(str(staging), err)
            self.assertIn("not empty", err)
            # Refusal must not touch the leftover file.
            self.assertEqual(
                (staging / ns / "export" / "mechanics" / "a.txt").read_text(
                    encoding="utf-8"),
                "leftover from a retired page\n")

    def test_existing_empty_staging_dir_is_allowed(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            ws = make_export(d / "ws", {})     # see the note above on --workspace
            make_export(d / "Export", {"Mechanics/a.md": "# A\n\nbody\n"})
            staging = d / "stage"
            staging.mkdir()

            rc, _out, _err = self._run([
                "--render-only",
                "--workspace", str(ws),
                "--staging", str(staging),
                "--export-dir", str(d / "Export"),
            ])
            self.assertEqual(rc, 0)


class TestLinkPolicy(unittest.TestCase):
    def _workspace(self, d):
        root = make_export(d / "ws", {
            "Mechanics/open.md":
                "---\ntype: mechanic\nvisibility: player-visible\n---\n"
                "# Open\n\nSee [[secret]] and [[open]].\n",
            "Mechanics/secret.md":
                "---\ntype: mechanic\nvisibility: gm-only\n---\n# Secret\n\nx\n",
        })
        return _config.open_workspace(root)

    def test_exported_target_rewritten_to_wrapper(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            ws = self._workspace(d)
            export = make_export(d / "Export", {"Mechanics/open.md": "# Open\n\nSee [[open]].\n"})
            resolver = deploy_export.build_link_resolver(
                ws, ["Mechanics/open.md"], NS, False)
            result, _log = deploy_export.render_tree(
                export, d / "stage", base=NS, link_resolver=resolver)
            body = (d / "stage" / NS / "export" / "mechanics" / "open.txt").read_text()
            self.assertIn(f"[[{NS}:mechanics:open|open]]", body)
            self.assertEqual(result.link_issues, [])

    def test_unexported_target_refused_by_default(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            ws = self._workspace(d)
            export = make_export(d / "Export", {"Mechanics/open.md": "# Open\n\nSee [[secret]].\n"})
            resolver = deploy_export.build_link_resolver(
                ws, ["Mechanics/open.md"], NS, False)
            result, _log = deploy_export.render_tree(
                export, d / "stage", base=NS, link_resolver=resolver)
            self.assertEqual([i.case for i in result.link_issues], ["unexported"])
            self.assertEqual([i.line for i in result.link_issues], [3])
            self.assertEqual(result.placeholder_ids, set())

    def test_placeholder_flag_writes_zero_byte_page(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            ws = self._workspace(d)
            export = make_export(d / "Export", {"Mechanics/open.md": "# Open\n\nSee [[secret]].\n"})
            staging = d / "stage"
            resolver = deploy_export.build_link_resolver(
                ws, ["Mechanics/open.md"], NS, True)
            result, log = deploy_export.render_tree(
                export, staging, base=NS, link_resolver=resolver)
            body = (staging / NS / "export" / "mechanics" / "open.txt").read_text()
            self.assertIn(f"[[{NS}:mechanics:secret|secret]]", body)
            ph = staging / NS / "mechanics" / "secret.txt"
            self.assertTrue(ph.is_file())
            self.assertEqual(ph.stat().st_size, 0)
            self.assertEqual(result.placeholder_ids, {f"{NS}:mechanics:secret"})
            # An accepted link must not be logged as REFUSED — this run exits 0.
            joined = "\n".join(log)
            self.assertIn("placeholder", joined)
            self.assertNotIn("REFUSED", joined)

    def test_unresolved_refused_even_with_flag(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            ws = self._workspace(d)
            export = make_export(d / "Export", {"Mechanics/open.md": "# Open\n\nSee [[tabel-rules]].\n"})
            resolver = deploy_export.build_link_resolver(
                ws, ["Mechanics/open.md"], NS, True)
            result, _log = deploy_export.render_tree(
                export, d / "stage", base=NS, link_resolver=resolver)
            self.assertEqual([i.case for i in result.link_issues], ["unresolved"])
            self.assertEqual(result.placeholder_ids, set())

    def test_alias_target_resolves(self):
        # A target spelled as a front-matter alias rather than the file stem
        # still rewrites to the wrapper page ID of the file it names.
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            ws = _config.open_workspace(make_export(d / "ws", {
                "Mechanics/table-rules.md":
                    "---\ntype: mechanic\nvisibility: player-visible\n"
                    "aliases: [The Rules]\n---\n# Table Rules\n\nx\n",
            }))
            resolver = deploy_export.build_link_resolver(
                ws, ["Mechanics/table-rules.md"], NS, False)
            self.assertEqual(resolver("The Rules"),
                             (f"{NS}:mechanics:table-rules", "exported"))

    def test_label_and_anchor_survive_the_policy_path(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            ws = self._workspace(d)
            export = make_export(d / "Export", {
                "Mechanics/open.md":
                    "# Open\n\nSee [[open|the open rule]] and [[open#surprise]].\n",
            })
            resolver = deploy_export.build_link_resolver(
                ws, ["Mechanics/open.md"], NS, False)
            result, _log = deploy_export.render_tree(
                export, d / "stage", base=NS, link_resolver=resolver)
            body = (d / "stage" / NS / "export" / "mechanics" / "open.txt").read_text()
            self.assertIn(f"[[{NS}:mechanics:open|the open rule]]", body)
            self.assertIn(f"[[{NS}:mechanics:open#surprise|open]]", body)
            self.assertEqual(result.link_issues, [])

    def test_pass_through_links_are_not_issues(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            ws = self._workspace(d)
            export = make_export(d / "Export", {
                "Mechanics/open.md":
                    "# Open\n\nSee [[Mechanics]], [[https://example.com]], "
                    "[[wp>Seoul]] and [[#anchor]].\n",
            })
            resolver = deploy_export.build_link_resolver(
                ws, ["Mechanics/open.md"], NS, False)
            result, _log = deploy_export.render_tree(
                export, d / "stage", base=NS, link_resolver=resolver)
            self.assertEqual(result.link_issues, [])
            body = (d / "stage" / NS / "export" / "mechanics" / "open.txt").read_text()
            for raw in ("[[Mechanics]]", "[[https://example.com]]",
                        "[[wp>Seoul]]", "[[#anchor]]"):
                self.assertIn(raw, body)


class TestLinkPolicyThroughMain(unittest.TestCase):
    """The `fatal` filter lives in main(), so exercise it through the CLI.

    render_tree reports every non-accepted link; only main() decides which of
    them actually refuses the run, and neither exit code is pinned by the
    render_tree-level tests above. main() resolves links against the workspace
    it was pointed at, so pass --workspace to stay hermetic.
    """

    def _run_against(self, workspace, argv):
        return run_main(["--workspace", str(workspace)] + argv)

    def _setup(self, d, body):
        ws = make_export(d / "ws", {
            "Mechanics/open.md":
                "---\ntype: mechanic\nvisibility: player-visible\n---\n"
                "# Open\n\nx\n",
            "Mechanics/secret.md":
                "---\ntype: mechanic\nvisibility: gm-only\n---\n# Secret\n\nx\n",
        })
        make_export(d / "Export", {"Mechanics/open.md": body})
        return ws

    def test_unexported_link_without_flag_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            ws = self._setup(d, "# Open\n\nSee [[secret]].\n")
            rc, _out, err = self._run_against(ws, [
                "--render-only",
                "--staging", str(d / "stage"),
                "--export-dir", str(d / "Export"),
            ])
            self.assertEqual(rc, 1)
            self.assertIn("REFUSED", err)
            self.assertIn("Mechanics/open.md:3", err)
            # main() has no CLI hook to override the namespace, so it renders
            # under the resolved workspace's declared one.
            self.assertFalse(
                (d / "stage" / namespace_of(ws)
                 / "mechanics" / "secret.txt").exists())

    def test_unexported_link_with_flag_exits_zero_and_writes_placeholder(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            ws = self._setup(d, "# Open\n\nSee [[secret]].\n")
            rc, out, err = self._run_against(ws, [
                "--render-only",
                "--staging", str(d / "stage"),
                "--export-dir", str(d / "Export"),
                "--create-empty-placeholders",
            ])
            self.assertEqual(rc, 0)
            ph = d / "stage" / namespace_of(ws) / "mechanics" / "secret.txt"
            self.assertTrue(ph.is_file())
            self.assertEqual(ph.stat().st_size, 0)
            # An accepted link is never called REFUSED, on either stream.
            self.assertNotIn("REFUSED", out + err)
            # ...and the exposed page ID is named in the summary, since it
            # publishes a gm-only filename to the player wiki's index.
            self.assertIn(f"{namespace_of(ws)}:mechanics:secret", out)

    def test_flag_does_not_rescue_a_typo(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            ws = self._setup(d, "# Open\n\nSee [[scret]].\n")
            rc, _out, err = self._run_against(ws, [
                "--render-only",
                "--staging", str(d / "stage"),
                "--export-dir", str(d / "Export"),
                "--create-empty-placeholders",
            ])
            self.assertEqual(rc, 1)
            self.assertIn("unresolved", err)

    def test_pass_through_link_does_not_refuse_the_run(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            ws = self._setup(d, "# Open\n\nSee [[Mechanics]] and [[wp>Seoul]].\n")
            rc, _out, err = self._run_against(ws, [
                "--render-only",
                "--staging", str(d / "stage"),
                "--export-dir", str(d / "Export"),
            ])
            self.assertEqual(rc, 0)
            self.assertNotIn("REFUSED", err)

    def test_markdown_link_to_gm_only_exits_nonzero(self):
        # Finding 4: nothing pinned this property through main() -- only
        # render_tree()'s return value was exercised for markdown links.
        # This is the exact case the whole branch exists to make refuse.
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            ws = self._setup(d, "# Open\n\nSee [the secret](secret).\n")
            rc, _out, err = self._run_against(ws, [
                "--render-only",
                "--staging", str(d / "stage"),
                "--export-dir", str(d / "Export"),
            ])
            self.assertNotEqual(rc, 0)
            self.assertIn("REFUSED", err)


class TestMarkdownLinkPolicy(unittest.TestCase):
    def _ws(self, d):
        root = make_export(d / "ws", {
            "Mechanics/open.md":
                "---\ntype: mechanic\nvisibility: player-visible\n---\n# Open\n\nx\n",
            "NPCs/the-mole.md":
                "---\ntype: npc\nvisibility: gm-only\n---\n# The Mole\n\nsecret\n",
        })
        return _config.open_workspace(root)

    def test_markdown_link_to_gm_only_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            ws = self._ws(d)
            export = make_export(d / "Export", {
                "Mechanics/open.md": "# Open\n\nSee [the mole](the-mole).\n"})
            resolver = deploy_export.build_link_resolver(
                ws, ["Mechanics/open.md"], NS, False)
            result, _log = deploy_export.render_tree(
                export, d / "stage", base=NS, link_resolver=resolver)
            self.assertEqual([(i.target, i.case) for i in result.link_issues],
                             [("the-mole", "unexported")])

    def test_markdown_link_to_exported_file_is_rewritten(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            ws = self._ws(d)
            export = make_export(d / "Export", {
                "Mechanics/open.md": "# Open\n\nSee [the rules](open).\n"})
            resolver = deploy_export.build_link_resolver(
                ws, ["Mechanics/open.md"], NS, False)
            deploy_export.render_tree(export, d / "stage", base=NS, link_resolver=resolver)
            body = (d / "stage" / NS / "export" / "mechanics" / "open.txt").read_text()
            self.assertIn(f"[[{NS}:mechanics:open|the rules]]", body)

    def test_markdown_link_to_external_url_passes_through(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            ws = self._ws(d)
            export = make_export(d / "Export", {
                "Mechanics/open.md": "# Open\n\nSee [Anthropic](https://anthropic.com).\n"})
            resolver = deploy_export.build_link_resolver(
                ws, ["Mechanics/open.md"], NS, False)
            result, _log = deploy_export.render_tree(
                export, d / "stage", base=NS, link_resolver=resolver)
            body = (d / "stage" / NS / "export" / "mechanics" / "open.txt").read_text()
            self.assertIn("[[https://anthropic.com|Anthropic]]", body)
            self.assertEqual(result.link_issues, [])

    def test_markdown_image_is_not_treated_as_a_link(self):
        # Finding 2: an image is not a link to a workspace document; it must
        # not be normalised to a wikilink and must not become a link-policy
        # refusal, even though its bare "src" would otherwise be unresolved.
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            ws = self._ws(d)
            export = make_export(d / "Export", {
                "Mechanics/open.md": "# Open\n\n![a map](map.png)\n"})
            resolver = deploy_export.build_link_resolver(
                ws, ["Mechanics/open.md"], NS, False)
            result, _log = deploy_export.render_tree(
                export, d / "stage", base=NS, link_resolver=resolver)
            body = (d / "stage" / NS / "export" / "mechanics" / "open.txt").read_text()
            self.assertIn("![a map](map.png)", body)
            self.assertEqual(result.link_issues, [])

    def test_md_suffixed_target_message_suggests_bare_stem(self):
        # Finding 2: `open.md` never resolves (the index holds bare stems),
        # so this is a documented hard refusal -- but the message must say
        # why in terms the author can act on, not just "unresolved".
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            ws = self._ws(d)
            export = make_export(d / "Export", {
                "Mechanics/open.md": "# Open\n\nSee [the rules](open.md).\n"})
            resolver = deploy_export.build_link_resolver(
                ws, ["Mechanics/open.md"], NS, False)
            result, log = deploy_export.render_tree(
                export, d / "stage", base=NS, link_resolver=resolver)
            self.assertEqual([(i.target, i.case) for i in result.link_issues],
                             [("open.md", "unresolved")])
            joined = "\n".join(log)
            self.assertIn("bare stem", joined)
            self.assertIn("'open'", joined)


class TestAmbiguousThroughDeploy(unittest.TestCase):
    def _ws(self, d):
        root = make_export(d / "ws", {
            "Mechanics/open.md":
                "---\ntype: mechanic\nvisibility: player-visible\n---\n# Open\n\nx\n",
            "NPCs/dupe.md":
                "---\ntype: npc\nvisibility: player-visible\n---\n# Dupe A\n\nx\n",
            "Ideas/dupe.md":
                "---\ntype: idea\nvisibility: player-visible\n---\n# Dupe B\n\nx\n",
        })
        return _config.open_workspace(root)

    def test_ambiguous_target_refuses_and_never_placeholders(self):
        for placeholders in (False, True):
            with self.subTest(placeholders=placeholders):
                with tempfile.TemporaryDirectory() as d:
                    d = Path(d)
                    ws = self._ws(d)
                    export = make_export(d / "Export", {
                        "Mechanics/open.md": "# Open\n\nSee [[dupe]].\n"})
                    resolver = deploy_export.build_link_resolver(
                        ws, ["Mechanics/open.md"], NS, placeholders)
                    result, _log = deploy_export.render_tree(
                        export, d / "stage", base=NS, link_resolver=resolver)
                    self.assertEqual([i.case for i in result.link_issues],
                                     ["ambiguous"])
                    self.assertEqual(result.placeholder_ids, set())


class TestImporterOutputSurvivesTheExporter(unittest.TestCase):
    """The importer emits `[t](t)`; the exporter's link policy must see it."""

    def test_imported_markdown_link_to_gm_only_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            ws = _config.open_workspace(make_export(d / "ws", {
                "Perceptions/what-we-think.md":
                    "---\ntype: perception\nvisibility: player-visible\n---\n"
                    "# What We Think\n\nx\n",
                "NPCs/the-mole.md":
                    "---\ntype: npc\nvisibility: gm-only\n---\n# The Mole\n\ns\n",
            }))
            # Exactly what convert_markup produces for a bare [[the-mole]].
            export = make_export(d / "Export", {
                "Perceptions/what-we-think.md":
                    "# What We Think\n\nWe suspect [the-mole](the-mole).\n"})
            resolver = deploy_export.build_link_resolver(
                ws, ["Perceptions/what-we-think.md"], NS, False)
            result, _log = deploy_export.render_tree(
                export, d / "stage", base=NS, link_resolver=resolver)
            self.assertEqual([(i.target, i.case) for i in result.link_issues],
                             [("the-mole", "unexported")])


class TestNamespaceFromConfig(unittest.TestCase):
    """The namespace main() renders under comes from the resolved workspace's
    config, not from a literal or a module constant.

    The predecessor of this class rebound the import-time config global and
    reloaded the module to prove the value was read rather than remembered.
    That global no longer exists — no name in this file refers to it, so the
    sweep that proves it is gone stays honest. main() now resolves per run,
    so the same property is provable without touching module state: run
    twice against two workspaces declaring two namespaces that appear
    nowhere in src/, and the staged paths must differ accordingly.
    A reintroduced literal cannot satisfy both runs.
    """

    def _render_under(self, ns: str) -> tuple[Path, str, int]:
        d = Path(self.enterContext(tempfile.TemporaryDirectory()))
        ws = d / "ws"
        ws.mkdir()
        (ws / "campaign.toml").write_text(
            f'[campaign]\nnamespace = "{ns}"\n', encoding="utf-8")
        make_export(d / "Export", {"Mechanics/a.md": "# A\n\nbody\n"})
        rc, _out, err = run_main([
            "--render-only",
            "--workspace", str(ws),
            "--staging", str(d / "stage"),
            "--export-dir", str(d / "Export"),
        ])
        return d / "stage", err, rc

    def test_namespace_comes_from_the_resolved_workspaces_config(self):
        for ns in ("regressioncheck", "otherwiki"):
            with self.subTest(namespace=ns):
                stage, err, rc = self._render_under(ns)
                self.assertEqual(rc, 0, err)
                self.assertTrue(
                    (stage / ns / "export" / "mechanics" / "a.txt").is_file(),
                    f"nothing staged under {ns}: {sorted(p.as_posix() for p in stage.rglob('*'))}")
                # ...and nothing was staged under the other run's namespace,
                # which would mean the value had been remembered.
                self.assertEqual(sorted(p.name for p in stage.iterdir()), [ns])


class TestExportDirComposesWithWorkspace(unittest.TestCase):
    """--export-dir's default is computed after --workspace is resolved.

    A parser-build-time default (the old `default=str(EXPORT_DIR)`) is fixed
    to the install repo, so omitting --export-dir would silently export the
    wrong workspace's Export/ however --workspace was pointed.
    """

    def test_omitted_export_dir_defaults_to_the_chosen_workspaces_export(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            ws = d / "ws"
            ws.mkdir()
            (ws / "campaign.toml").write_text(
                '[campaign]\nnamespace = "wschosen"\n', encoding="utf-8")
            make_export(ws / "Export", {"Mechanics/a.md": "# A\n\nbody\n"})

            rc, out, err = run_main([
                "--render-only",
                "--workspace", str(ws),
                "--staging", str(d / "stage"),
            ])

            self.assertEqual(rc, 0, err)
            self.assertIn("1 page(s)", out)
            self.assertTrue(
                (d / "stage" / "wschosen" / "export" / "mechanics"
                 / "a.txt").is_file())

    def test_explicit_export_dir_still_wins(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            ws = d / "ws"
            ws.mkdir()
            (ws / "campaign.toml").write_text(
                '[campaign]\nnamespace = "wschosen"\n', encoding="utf-8")
            # The workspace's own Export/ holds a decoy that must not be read.
            make_export(ws / "Export", {"Mechanics/decoy.md": "# Decoy\n\nx\n"})
            make_export(d / "elsewhere", {"Mechanics/a.md": "# A\n\nbody\n"})

            rc, _out, err = run_main([
                "--render-only",
                "--workspace", str(ws),
                "--staging", str(d / "stage"),
                "--export-dir", str(d / "elsewhere"),
            ])

            self.assertEqual(rc, 0, err)
            base = d / "stage" / "wschosen" / "export" / "mechanics"
            self.assertTrue((base / "a.txt").is_file())
            self.assertFalse((base / "decoy.txt").exists())

    def test_missing_workspace_returns_nonzero_with_a_clear_message(self):
        # --workspace pointing at a directory with no campaign.toml is an
        # error, not a search hint — resolve_workspace must not walk up.
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            empty = d / "nothing-here"
            empty.mkdir()
            rc, _out, err = run_main([
                "--render-only",
                "--workspace", str(empty),
                "--staging", str(d / "stage"),
            ])
            self.assertEqual(rc, 1)
            self.assertIn("campaign.toml", err)


class TestClassifyPage(unittest.TestCase):
    """The spec's eight-row state matrix, walked as a table."""

    def test_all_eight_rows(self):
        h = deploy_export.page_hash
        rows = [
            # (target, wiki_text, manifest_hash) -> action
            ("t\n", None, None, "new"),
            ("t\n", None, h("old\n"), "deleted-on-wiki"),
            ("t\n", "t\n", h("t\n"), "unchanged"),
            ("t2\n", "t\n", h("t\n"), "update"),
            ("t\n", "t\n", h("other\n"), "adopt"),      # resume-after-crash
            ("t2\n", "t\n", h("other\n"), "drift"),
            ("t\n", "t\n", None, "adopt"),               # manual-era match
            ("t2\n", "t\n", None, "drift-manual-era"),
        ]
        for target, wiki, mh, expected in rows:
            with self.subTest(expected=expected):
                self.assertEqual(
                    deploy_export.classify_page(target, wiki, mh), expected)


class TestManifest(unittest.TestCase):
    def test_missing_file_is_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(
                deploy_export.load_manifest(Path(d) / "none.json"), {})

    def test_round_trip_sorted(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / ".bunnyforge" / "wiki-manifest.json"
            deploy_export.save_manifest(path, {"b:x": "2", "a:x": "1"})
            raw = path.read_text(encoding="utf-8")
            self.assertLess(raw.index('"a:x"'), raw.index('"b:x"'))
            self.assertEqual(deploy_export.load_manifest(path),
                             {"a:x": "1", "b:x": "2"})

    def test_unknown_version_refused(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "m.json"
            path.write_text('{"version": 99, "pages": {}}', encoding="utf-8")
            with self.assertRaises(deploy_export.DeployError):
                deploy_export.load_manifest(path)

    def test_bad_json_refused_instructionally(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "m.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(deploy_export.DeployError) as ctx:
                deploy_export.load_manifest(path)
            self.assertIn(str(path), str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

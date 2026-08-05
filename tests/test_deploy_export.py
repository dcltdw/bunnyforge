import contextlib
import io
import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from bunnyforge import _config
from bunnyforge import deploy_export
from bunnyforge import export_player
from bunnyforge._dokuwiki_rpc import RpcError

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


class FakeClient:
    """In-memory wiki: a dict of pages. Mimics get_page/save_page, applies a
    save normalization (strips trailing newlines, like DokuWiki) so
    read-back hashing is exercised for real."""

    def __init__(self, pages=None, fail_on=None):
        self.pages = dict(pages or {})
        self.saves = []
        self.fail_on = fail_on

    def get_page(self, pid):
        return self.pages.get(pid)

    def save_page(self, pid, text, summary=None):
        if pid == self.fail_on:
            raise RpcError(111, "denied", "core.savePage")
        self.saves.append(pid)
        self.pages[pid] = text.rstrip("\n") + "\n"


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

    def test_default_run_without_wiki_config_is_instructional(self):
        # Bare deploy-export is now a network dry run; with no [wiki] url it
        # must say exactly what to add and where, and mention --render-only.
        with tempfile.TemporaryDirectory() as d:
            # The brief's literal fixture pointed --workspace at `d` while
            # only ever writing campaign.toml under d/Export -- resolving the
            # workspace itself would fail before the wiki-url check this test
            # exists to exercise. Give `d` its own campaign.toml (no [wiki]
            # table) so resolve_workspace succeeds and the run reaches that
            # check.
            (Path(d) / "campaign.toml").write_text(
                _MINIMAL_CAMPAIGN_TOML, encoding="utf-8")
            export = make_export(Path(d) / "Export", {"Mechanics/a.md": "# A\n"})
            rc, _out, err = self._run(
                ["--workspace", str(d), "--export-dir", str(export)])
            self.assertEqual(rc, 1)
            self.assertIn("[wiki]", err)
            self.assertIn('url = "https://<wiki>"', err)
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


class TestNewCliSurface(unittest.TestCase):
    def _run(self, argv):
        return run_main(argv)

    def test_render_only_and_go_mutually_exclusive(self):
        with self.assertRaises(SystemExit) as ctx:
            deploy_export.main(["--render-only", "--go", "--staging", "/tmp/x"])
        self.assertEqual(ctx.exception.code, 2)

    def test_render_only_still_requires_staging(self):
        with tempfile.TemporaryDirectory() as d:
            make_export(Path(d) / "Export", {"Mechanics/a.md": "# A\n"})
            rc, _out, err = self._run(["--workspace", str(d), "--render-only"])
            self.assertEqual(rc, 1)
            self.assertIn("--staging", err)

    def test_missing_token_is_instructional(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "campaign.toml").write_text(
                '[campaign]\nnamespace = "test"\n'
                '[wiki]\nurl = "https://wiki.invalid"\n', encoding="utf-8")
            make_export(Path(d) / "Export", {"Mechanics/a.md": "# A\n"})
            os.environ.pop("BUNNYFORGE_WIKI_TOKEN", None)
            rc, _out, err = self._run(["--workspace", str(d)])
            self.assertEqual(rc, 1)
            self.assertIn("BUNNYFORGE_WIKI_TOKEN", err)

    def test_http_url_refused_before_any_network(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "campaign.toml").write_text(
                '[campaign]\nnamespace = "test"\n'
                '[wiki]\nurl = "http://wiki.invalid"\n', encoding="utf-8")
            make_export(Path(d) / "Export", {"Mechanics/a.md": "# A\n"})
            with unittest.mock.patch.dict(
                    os.environ, {"BUNNYFORGE_WIKI_TOKEN": "t"}):
                rc, _out, err = self._run(["--workspace", str(d)])
            self.assertEqual(rc, 1)
            self.assertIn("http://", err)

    def test_omitted_staging_renders_for_real_into_a_temp_dir_that_is_cleaned_up(self):
        # No test may touch the network, so this drives a run that must
        # render for real (proving the temp dir actually works as a staging
        # target, not just that one gets created) while still never reaching
        # run_deploy: an unresolved link fatally refuses the run from inside
        # main() *after* render_tree has already written pages into the temp
        # staging dir, but before any RPC call would be made.
        real_temp_dir_cls = deploy_export.tempfile.TemporaryDirectory
        captured = {}

        class RecordingTempDir(real_temp_dir_cls):
            def __enter__(self):
                path = super().__enter__()
                captured["path"] = path
                return path

            def __exit__(self, *exc_info):
                # Snapshot what landed on disk immediately before cleanup —
                # captured["path"] no longer exists once super().__exit__
                # returns.
                root = Path(captured["path"])
                captured["files"] = sorted(
                    p.relative_to(root).as_posix() for p in root.rglob("*.txt"))
                return super().__exit__(*exc_info)

        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "campaign.toml").write_text(
                '[campaign]\nnamespace = "test"\n'
                '[wiki]\nurl = "https://wiki.invalid"\n', encoding="utf-8")
            make_export(Path(d) / "Export", {
                "Mechanics/open.md": "# Open\n\nSee [[totally-nonexistent]].\n",
            })
            with unittest.mock.patch.dict(
                    os.environ, {"BUNNYFORGE_WIKI_TOKEN": "t"}), \
                unittest.mock.patch.object(
                    deploy_export.tempfile, "TemporaryDirectory",
                    RecordingTempDir):
                rc, _out, err = self._run(["--workspace", str(d)])
            self.assertEqual(rc, 1)
            self.assertIn("unresolved", err)
            # The content page was actually rendered into the temp dir before
            # the fatal-link check refused the run.
            self.assertTrue(
                any(f.endswith("mechanics/open.txt")
                    for f in captured["files"]),
                captured["files"])
            self.assertFalse(Path(captured["path"]).exists())


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

    def test_non_object_json_refused_instructionally(self):
        # Valid JSON but not an object at all (e.g. a bare array) must not
        # reach `raw.get(...)` — that would raise AttributeError instead of
        # the instructional DeployError every malformed manifest owes.
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "m.json"
            path.write_text("[1, 2, 3]", encoding="utf-8")
            with self.assertRaises(deploy_export.DeployError) as ctx:
                deploy_export.load_manifest(path)
            self.assertIn(str(path), str(ctx.exception))

    def test_non_object_pages_refused_instructionally(self):
        # A `pages` field that isn't a JSON object must be refused rather
        # than silently misread — dict() of some non-dict shapes (e.g. a
        # list of two-character strings) succeeds without error and would
        # otherwise corrupt the read instead of refusing it.
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "m.json"
            path.write_text('{"version": 1, "pages": ["ab", "cd"]}',
                            encoding="utf-8")
            with self.assertRaises(deploy_export.DeployError) as ctx:
                deploy_export.load_manifest(path)
            self.assertIn(str(path), str(ctx.exception))


class TestStagedPages(unittest.TestCase):
    def test_ids_and_placeholder_translation(self):
        with tempfile.TemporaryDirectory() as d:
            staging = Path(d)
            page = staging / NS / "export" / "mechanics" / "rule.txt"
            page.parent.mkdir(parents=True)
            page.write_text("body\n", encoding="utf-8")
            ph = staging / NS / "npcs" / "ghost.txt"
            ph.parent.mkdir(parents=True)
            ph.write_bytes(b"")  # zero-byte placeholder: savePage refuses
            staged = deploy_export.staged_pages(staging)
            self.assertEqual(staged[f"{NS}:export:mechanics:rule"], "body\n")
            self.assertEqual(staged[f"{NS}:npcs:ghost"],
                             deploy_export.PLACEHOLDER_BODY)


class TestPlanDeploy(unittest.TestCase):
    def test_classifies_and_finds_orphans(self):
        wiki = {"w:a": "old\n", "w:gone-from-workspace": "still here\n"}
        staged = {"w:a": "new\n", "w:b": "fresh\n"}
        manifest = {"w:a": deploy_export.page_hash("old\n"),
                    "w:gone-from-workspace": "x",
                    "w:resolved": "y"}  # deleted on wiki by a human
        plan = deploy_export.plan_deploy(staged, manifest, wiki.get, "w")
        self.assertEqual(plan.pages["w:a"].action, "update")
        self.assertEqual(plan.pages["w:b"].action, "new")
        self.assertEqual(plan.orphans, ["w:gone-from-workspace"])
        self.assertEqual(plan.resolved_orphans, ["w:resolved"])

    def test_protected_pages_never_fetched_never_planned(self):
        fetched = []

        def fetch(pid):
            fetched.append(pid)
            return None

        staged = {"w:main": "x\n", "w:players:notes": "x\n", "w:ok": "x\n"}
        plan = deploy_export.plan_deploy(staged, {}, fetch, "w")
        self.assertEqual(sorted(plan.refused), ["w:main", "w:players:notes"])
        self.assertNotIn("w:main", plan.pages)
        self.assertNotIn("w:main", fetched)
        self.assertNotIn("w:players:notes", fetched)
        self.assertIn("w:ok", plan.pages)


class TestWriteOrder(unittest.TestCase):
    def test_content_lands_immediately_before_its_wrapper(self):
        ids = [f"{NS}:export:npcs:ana", f"{NS}:npcs:ana",
               f"{NS}:export:npcs:bob", f"{NS}:npcs:bob",
               f"{NS}:aaa-placeholder"]
        order = deploy_export.write_order(ids, NS)
        self.assertEqual(order, [
            f"{NS}:aaa-placeholder",
            f"{NS}:export:npcs:ana", f"{NS}:npcs:ana",
            f"{NS}:export:npcs:bob", f"{NS}:npcs:bob",
        ])

    def test_unpaired_content_page_stays_sorted(self):
        ids = [f"{NS}:export:npcs:solo"]
        self.assertEqual(deploy_export.write_order(ids, NS), ids)

    def test_duplicate_input_ids_yield_each_page_once(self):
        # present = set(ids) dedupes for membership, but a loop driven off
        # the raw (un-deduped) list would re-trigger "mate present -> emit
        # mate + self" once per repeat. write_order's whole purpose is an
        # exactly-once, content-before-wrapper order, so a duplicated input
        # must not duplicate the output.
        ids = [f"{NS}:npcs:ana", f"{NS}:npcs:ana", f"{NS}:export:npcs:ana"]
        order = deploy_export.write_order(ids, NS)
        self.assertEqual(order, [f"{NS}:export:npcs:ana", f"{NS}:npcs:ana"])


class TestApplyDeploy(unittest.TestCase):
    def _apply(self, plan, staged, client, manifest, path, overwrite=()):
        return deploy_export.apply_deploy(
            plan, staged, client, manifest, path, set(overwrite), "w",
            "https://<wiki>")

    def test_clean_deploy_writes_and_baselines_readback(self):
        client = FakeClient()
        staged = {"w:export:npcs:ana": "body\n\n", "w:npcs:ana": "wrap\n"}
        manifest = {}
        with tempfile.TemporaryDirectory() as d:
            mpath = Path(d) / "m.json"
            plan = deploy_export.plan_deploy(staged, manifest, client.get_page, "w")
            result = self._apply(plan, staged, client, manifest, mpath)
            self.assertIsNone(result.failure)
            # content before wrapper
            self.assertEqual(client.saves,
                             ["w:export:npcs:ana", "w:npcs:ana"])
            # baseline is the hash of the READ-BACK text (normalized by the
            # fake), not of the bytes sent
            self.assertEqual(manifest["w:export:npcs:ana"],
                             deploy_export.page_hash("body\n"))
            # manifest written through to disk
            self.assertEqual(deploy_export.load_manifest(mpath), manifest)

    def test_adopt_rebaselines_without_writing(self):
        client = FakeClient({"w:a": "same\n"})
        staged = {"w:a": "same\n"}
        manifest = {"w:a": "stale-hash"}
        with tempfile.TemporaryDirectory() as d:
            mpath = Path(d) / "m.json"
            plan = deploy_export.plan_deploy(staged, manifest, client.get_page, "w")
            result = self._apply(plan, staged, client, manifest, mpath)
            self.assertEqual(client.saves, [])
            self.assertEqual(result.adopted, ["w:a"])
            self.assertEqual(manifest["w:a"], deploy_export.page_hash("same\n"))
            self.assertEqual(deploy_export.load_manifest(mpath), manifest)

    def test_drift_held_unless_overwritten(self):
        client = FakeClient({"w:a": "wiki edit\n"})
        staged = {"w:a": "ours\n"}
        manifest = {"w:a": deploy_export.page_hash("older\n")}
        with tempfile.TemporaryDirectory() as d:
            mpath = Path(d) / "m.json"
            plan = deploy_export.plan_deploy(staged, manifest, client.get_page, "w")
            result = self._apply(plan, staged, client, manifest, mpath)
            self.assertEqual(client.saves, [])
            result = self._apply(plan, staged, client, manifest, mpath,
                                 overwrite=["w:a"])
            self.assertEqual(client.saves, ["w:a"])
            self.assertEqual(manifest["w:a"], deploy_export.page_hash("ours\n"))

    def test_overwrite_of_unheld_page_refused(self):
        client = FakeClient()
        staged = {"w:a": "x\n"}
        with tempfile.TemporaryDirectory() as d:
            plan = deploy_export.plan_deploy(staged, {}, client.get_page, "w")
            with self.assertRaises(deploy_export.DeployError) as ctx:
                self._apply(plan, staged, client, {}, Path(d) / "m.json",
                            overwrite=["w:nope"])
            self.assertIn("w:nope", str(ctx.exception))

    def test_failed_save_aborts_reports_written_and_remaining(self):
        client = FakeClient(fail_on="w:b")
        staged = {"w:a": "1\n", "w:b": "2\n", "w:c": "3\n"}
        manifest = {}
        with tempfile.TemporaryDirectory() as d:
            mpath = Path(d) / "m.json"
            plan = deploy_export.plan_deploy(staged, manifest, client.get_page, "w")
            result = self._apply(plan, staged, client, manifest, mpath)
            self.assertIsNotNone(result.failure)
            self.assertIn("ACL", result.failure)  # translated, not raw
            self.assertEqual(result.written, ["w:a"])
            self.assertEqual(result.remaining, ["w:b", "w:c"])
            # the page that DID land is baselined — re-run converges
            self.assertIn("w:a", deploy_export.load_manifest(mpath))
            self.assertNotIn("w:b", deploy_export.load_manifest(mpath))

    def test_resolved_orphans_dropped_from_manifest(self):
        client = FakeClient({"w:a": "x\n"})
        staged = {"w:a": "x\n"}
        manifest = {"w:a": deploy_export.page_hash("x\n"), "w:gone": "h"}
        with tempfile.TemporaryDirectory() as d:
            mpath = Path(d) / "m.json"
            plan = deploy_export.plan_deploy(staged, manifest, client.get_page, "w")
            self._apply(plan, staged, client, manifest, mpath)
            self.assertNotIn("w:gone", manifest)
            self.assertNotIn("w:gone", deploy_export.load_manifest(mpath))


def make_workspace(d: Path) -> Path:
    (d / "campaign.toml").write_text(_MINIMAL_CAMPAIGN_TOML, encoding="utf-8")
    return d


class TestDriftCopies(unittest.TestCase):
    def test_copies_mirror_pages_layout_and_dir_recreated(self):
        with tempfile.TemporaryDirectory() as d:
            drift = Path(d) / "wiki-drift"
            stale = drift / "old.txt"
            stale.parent.mkdir(parents=True)
            stale.write_text("stale", encoding="utf-8")
            deploy_export.write_drift_copies(
                {"w:npcs:ana": "wiki text\n"}, drift)
            self.assertFalse(stale.exists())  # recreated from empty
            copy = drift / "w" / "npcs" / "ana.txt"
            self.assertEqual(copy.read_text(encoding="utf-8"), "wiki text\n")


class TestRunDeploy(unittest.TestCase):
    def _stage(self, d: Path, pages: dict) -> Path:
        staging = d / "stage"
        for pid, text in pages.items():
            p = deploy_export.page_path(pid, staging)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        return staging

    def _run(self, ws_root, staging, client, go=False, overwrite=()):
        ws = _config.open_workspace(ws_root)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            rc = deploy_export.run_deploy(
                ws, staging, client, go, set(overwrite), "https://<wiki>")
        return rc, out.getvalue()

    def test_dry_run_is_default_shape_no_writes_no_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            d = make_workspace(Path(d))
            staging = self._stage(d, {"test:npcs:ana": "hello\n"})
            client = FakeClient()
            rc, out = self._run(d, staging, client, go=False)
            self.assertEqual(rc, 0)
            self.assertEqual(client.saves, [])  # zero wiki writes
            self.assertFalse(
                (d / ".bunnyforge" / "wiki-manifest.json").exists())
            self.assertIn("new", out)  # the full plan is printed

    def test_go_writes_and_persists_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            d = make_workspace(Path(d))
            staging = self._stage(d, {"test:npcs:ana": "hello\n"})
            client = FakeClient()
            rc, _ = self._run(d, staging, client, go=True)
            self.assertEqual(rc, 0)
            self.assertEqual(client.saves, ["test:npcs:ana"])
            manifest = deploy_export.load_manifest(
                d / ".bunnyforge" / "wiki-manifest.json")
            self.assertIn("test:npcs:ana", manifest)

    def test_drift_held_diffed_copied_and_nonzero_in_both_modes(self):
        with tempfile.TemporaryDirectory() as d:
            d = make_workspace(Path(d))
            staging = self._stage(d, {"test:npcs:ana": "ours\n"})
            client = FakeClient({"test:npcs:ana": "theirs\n"})
            for go in (False, True):
                with self.subTest(go=go):
                    rc, out = self._run(d, staging, client, go=go)
                    self.assertEqual(rc, 1)
                    self.assertEqual(client.saves, [])
                    self.assertIn("wiki (current)", out)   # unified diff sides
                    self.assertIn("deploy (target)", out)
                    self.assertIn("--overwrite", out)      # resolution path
                    copy = (d / ".bunnyforge" / "wiki-drift" / "test" /
                            "npcs" / "ana.txt")
                    self.assertEqual(copy.read_text(encoding="utf-8"),
                                     "theirs\n")

    def test_deleted_on_wiki_held_and_reported(self):
        with tempfile.TemporaryDirectory() as d:
            d = make_workspace(Path(d))
            staging = self._stage(d, {"test:npcs:ana": "ours\n"})
            deploy_export.save_manifest(
                d / ".bunnyforge" / "wiki-manifest.json",
                {"test:npcs:ana": "somehash"})
            client = FakeClient()  # page absent on wiki
            rc, out = self._run(d, staging, client, go=True)
            self.assertEqual(rc, 1)
            self.assertEqual(client.saves, [])
            self.assertIn("deleted", out)

    def test_orphan_reported_never_deleted_nonzero(self):
        with tempfile.TemporaryDirectory() as d:
            d = make_workspace(Path(d))
            staging = self._stage(d, {"test:npcs:ana": "x\n"})
            client = FakeClient({"test:npcs:ana": "x\n",
                                 "test:npcs:retired": "old\n"})
            deploy_export.save_manifest(
                d / ".bunnyforge" / "wiki-manifest.json",
                {"test:npcs:ana": deploy_export.page_hash("x\n"),
                 "test:npcs:retired": deploy_export.page_hash("old\n")})
            rc, out = self._run(d, staging, client, go=True)
            self.assertEqual(rc, 1)
            self.assertIn("test:npcs:retired", out)
            self.assertIn("manual", out)  # removal is a manual act
            self.assertIn("test:npcs:retired", client.pages)  # never deleted

    def test_resume_after_crash_adopts_and_exits_zero(self):
        with tempfile.TemporaryDirectory() as d:
            d = make_workspace(Path(d))
            staging = self._stage(d, {"test:npcs:ana": "same\n"})
            client = FakeClient({"test:npcs:ana": "same\n"})
            deploy_export.save_manifest(
                d / ".bunnyforge" / "wiki-manifest.json",
                {"test:npcs:ana": "stale-pre-crash-hash"})
            rc, out = self._run(d, staging, client, go=True)
            self.assertEqual(rc, 0)
            self.assertEqual(client.saves, [])
            self.assertIn("adopt", out)

    def test_drift_dir_recreated_each_planning_run(self):
        with tempfile.TemporaryDirectory() as d:
            d = make_workspace(Path(d))
            stale = d / ".bunnyforge" / "wiki-drift" / "stale.txt"
            stale.parent.mkdir(parents=True)
            stale.write_text("old", encoding="utf-8")
            staging = self._stage(d, {"test:npcs:ana": "x\n"})
            client = FakeClient({"test:npcs:ana": "x\n"})
            deploy_export.save_manifest(
                d / ".bunnyforge" / "wiki-manifest.json",
                {"test:npcs:ana": deploy_export.page_hash("x\n")})
            rc, _ = self._run(d, staging, client)
            self.assertEqual(rc, 0)
            self.assertFalse(stale.exists())


if __name__ == "__main__":
    unittest.main()

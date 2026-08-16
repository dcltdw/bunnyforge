"""Tests for bunnyforge.vscode — the editor-integration command.

Everything external is injected or mocked: `_fetch` (network), `_run`
(subprocess), `_interactive`/`_ask` (TTY). No test touches GitHub or a
real editor.
"""

import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bunnyforge import init, vscode


class TestPackagedContract(unittest.TestCase):
    """vscode.py's constants and data/vscode/settings.json are two halves
    of one contract (#34 froze it); drift between them is a red test."""

    def _lines(self) -> list[str]:
        return (init.packaged_bytes("vscode/settings.json")
                .decode("utf-8").split("\n"))

    def test_the_packaged_markers_match_the_constants(self):
        stripped = [l.strip() for l in self._lines()]
        self.assertEqual(stripped.count(vscode.MARKER_BEGIN), 1)
        self.assertEqual(stripped.count(vscode.MARKER_END), 1)

    def test_the_packaged_region_round_trips_through_the_toggle(self):
        # disable(enable(x)) == x proves the packaged off-form is exactly
        # what disable_region produces — the byte-level half of the contract.
        lines = self._lines()
        begin, end = vscode.maybe_region(lines)
        self.assertEqual(vscode.region_state(lines, begin, end), "off")
        on = vscode.enable_region(lines, begin, end)
        self.assertEqual(vscode.region_state(on, begin, end), "on")
        self.assertEqual(vscode.disable_region(on, begin, end), lines)


def _hand_switched_to_saturated() -> list[str]:
    """The packaged file with the palette switched BY HAND, exactly as the
    header comment describes: the active (high) palette commented out with
    plain "//" — never "//- ", which the toggle owns — and the saturated
    alternate uncommented, carrying the separator its new neighbours need.
    """
    lines = (init.packaged_bytes("vscode/settings.json")
             .decode("utf-8").split("\n"))
    begin, _ = vscode.maybe_region(lines)
    sat = next(i for i, l in enumerate(lines)
               if l.strip().startswith("// ── ALTERNATE: saturated"))
    sub = next(i for i, l in enumerate(lines)
               if l.strip().startswith("// ── ALTERNATE: subtle"))
    out = list(lines)
    for i in range(begin + 1, sat):
        indent, body = vscode._split_indent(out[i])
        if body.startswith(vscode.OFF_PREFIX):
            out[i] = indent + "// " + body[len(vscode.OFF_PREFIX):]
    live = []
    for i in range(sat + 1, sub):
        indent, body = vscode._split_indent(out[i])
        if body.startswith("// "):
            out[i] = indent + body[3:]
            live.append(i)
    out[live[-1]] += ","          # a live member now: "table" follows it
    return out


class TestPackagedPaletteSwitch(unittest.TestCase):
    """Finding 1: the header's switch instructions have to be a procedure
    the engine survives — "//- " is the toggle's prefix, not the user's."""

    def _lines(self) -> list[str]:
        return (init.packaged_bytes("vscode/settings.json")
                .decode("utf-8").split("\n"))

    def test_the_header_documents_the_plain_comment_switch(self):
        lines = self._lines()
        begin, _ = vscode.maybe_region(lines)
        header = "\n".join(lines[:begin])
        self.assertIn("--replace", header)       # the supported restore
        self.assertIn('"//"', header)            # how to deactivate a palette

    def test_a_hand_switched_palette_reports_on_and_is_valid_json(self):
        lines = _hand_switched_to_saturated()
        begin, end = vscode.maybe_region(lines)
        self.assertEqual(vscode.region_state(lines, begin, end), "on")
        data = json.loads("\n".join(
            l for l in lines if not l.strip().startswith("//")))
        self.assertIn("highlight.regexes", data)
        self.assertIn("#ef4444",                 # the saturated palette, live
                      json.dumps(data["highlight.regexes"]))

    def test_vscode_on_is_a_no_op_on_a_hand_switched_palette(self):
        ws = _ws(self)
        (ws / ".vscode").mkdir()
        before = "\n".join(_hand_switched_to_saturated())
        (ws / ".vscode" / "settings.json").write_text(before, encoding="utf-8")
        with mock.patch.object(vscode, "_offer_highlight"), \
             contextlib.redirect_stdout(io.StringIO()) as out:
            rc = vscode.main(["on", "--workspace", str(ws)])
        self.assertEqual(rc, 0)
        self.assertIn("already on", out.getvalue())
        self.assertEqual((ws / ".vscode" / "settings.json")
                         .read_text("utf-8"), before)


SAMPLE_OFF = """\
{
  // prose above the marker — never load-bearing
  // bunnyforge:begin visibility-colouring
  //- "highlight.regexes": {
    //- "^x$": { "a": 1 }
  //- },
  // ── ALTERNATE ──
  // "highlight.regexes": { "alt": true }
  // bunnyforge:end visibility-colouring
  "markdown.preview.frontMatter": "table"
}
""".split("\n")


class TestRegionEngine(unittest.TestCase):

    def test_finds_the_marker_pair(self):
        self.assertEqual(vscode.maybe_region(SAMPLE_OFF), (2, 8))

    def test_no_markers_at_all_is_none_not_an_error(self):
        self.assertIsNone(vscode.maybe_region(["{", "}"]))

    def test_a_lone_or_duplicated_marker_is_a_refusal(self):
        lone = [l for l in SAMPLE_OFF if l.strip() != vscode.MARKER_END]
        with self.assertRaises(vscode.VscodeError):
            vscode.maybe_region(lone)
        doubled = SAMPLE_OFF + ["  " + vscode.MARKER_BEGIN]
        with self.assertRaises(vscode.VscodeError):
            vscode.maybe_region(doubled)

    def test_end_before_begin_is_a_refusal(self):
        swapped = ["  " + vscode.MARKER_END, "x", "  " + vscode.MARKER_BEGIN]
        with self.assertRaises(vscode.VscodeError):
            vscode.maybe_region(swapped)

    def test_state_off_then_on(self):
        begin, end = vscode.maybe_region(SAMPLE_OFF)
        self.assertEqual(vscode.region_state(SAMPLE_OFF, begin, end), "off")
        on = vscode.enable_region(SAMPLE_OFF, begin, end)
        self.assertEqual(vscode.region_state(on, begin, end), "on")

    def test_enable_preserves_indentation_and_plain_comments(self):
        begin, end = vscode.maybe_region(SAMPLE_OFF)
        on = vscode.enable_region(SAMPLE_OFF, begin, end)
        self.assertEqual(on[3], '  "highlight.regexes": {')
        self.assertEqual(on[4], '    "^x$": { "a": 1 }')
        self.assertEqual(on[6], "  // ── ALTERNATE ──")   # untouched
        self.assertEqual(on[7], '  // "highlight.regexes": { "alt": true }')
        self.assertEqual(on[9], '  "markdown.preview.frontMatter": "table"')

    def test_disable_prefixes_only_live_lines(self):
        begin, end = vscode.maybe_region(SAMPLE_OFF)
        on = vscode.enable_region(SAMPLE_OFF, begin, end)
        self.assertEqual(vscode.disable_region(on, begin, end), SAMPLE_OFF)

    def test_both_transforms_are_idempotent(self):
        begin, end = vscode.maybe_region(SAMPLE_OFF)
        off2 = vscode.disable_region(SAMPLE_OFF, begin, end)
        self.assertEqual(off2, SAMPLE_OFF)
        on = vscode.enable_region(SAMPLE_OFF, begin, end)
        self.assertEqual(vscode.enable_region(on, begin, end), on)

    def test_transforms_do_not_mutate_their_input(self):
        begin, end = vscode.maybe_region(SAMPLE_OFF)
        copy = list(SAMPLE_OFF)
        vscode.enable_region(SAMPLE_OFF, begin, end)
        self.assertEqual(SAMPLE_OFF, copy)


UNMANAGED = """\
{
  "editor.rulers": [80],
  "highlight.regexes": {
    "^(## GM notes{2}\\\\s*)$": {
      "decorations": [{ "quote": "}" }]
    }
  },
  "markdown.preview.frontMatter": "table"
}
""".split("\n")


class TestStructuralEdits(unittest.TestCase):

    def test_key_span_ignores_braces_in_strings_and_comments(self):
        # The value spans lines 2..6; "{2}" and the "}" string literal and
        # any // comment must not confuse the scan.
        self.assertEqual(vscode.key_span(UNMANAGED, 2), 6)

    def test_key_span_on_a_single_line_value(self):
        doc = ['{', '  "highlight.regexes": {},', '}']
        self.assertEqual(vscode.key_span(doc, 1), 1)

    def test_key_span_refuses_unbalanced_braces(self):
        with self.assertRaises(vscode.VscodeError):
            vscode.key_span(['{', '  "highlight.regexes": {', ''], 1)

    def test_finds_the_unmanaged_key_and_skips_comments(self):
        self.assertEqual(vscode.find_unmanaged_key(UNMANAGED, None), 2)
        commented = ['{', '  // "highlight.regexes": {}', '}']
        self.assertIsNone(vscode.find_unmanaged_key(commented, None))

    def test_the_managed_region_is_not_reported_as_unmanaged(self):
        begin, end = vscode.maybe_region(SAMPLE_OFF)
        on = vscode.enable_region(SAMPLE_OFF, begin, end)
        self.assertIsNone(vscode.find_unmanaged_key(on, (begin, end)))

    def test_packaged_region_lines_are_marker_delimited(self):
        region = vscode.packaged_region_lines()
        self.assertEqual(region[0].strip(), vscode.MARKER_BEGIN)
        self.assertEqual(region[-1].strip(), vscode.MARKER_END)

    def _spliced_json(self, doc, *, enabled=True):
        """Splice, optionally enable, then parse as strict JSON — the
        property that actually matters in both toggle states."""
        out = vscode.splice_region(doc)
        begin, end = vscode.maybe_region(out)
        lines = vscode.enable_region(out, begin, end) if enabled else out
        return out, json.loads("\n".join(
            l for l in lines if not l.strip().startswith("//")))

    def test_splice_puts_the_region_first_and_keeps_the_file_valid(self):
        doc = ['{', '  // a comment', '  "editor.rulers": [80]', '}', '']
        out, data = self._spliced_json(doc)
        begin, _ = vscode.maybe_region(out)
        self.assertEqual(begin, 1)                  # first member, not last
        self.assertIn("highlight.regexes", data)
        self.assertEqual(data["editor.rulers"], [80])
        # and the off state parses too — the region is all comments there
        self.assertEqual(self._spliced_json(doc, enabled=False)[1],
                         {"editor.rulers": [80]})

    def test_splice_into_an_empty_object_needs_no_comma(self):
        # Sole member: the region's own trailing comma has to go, or the
        # enabled file ends `},}`.
        _, data = self._spliced_json(['{', '}'])
        self.assertEqual(list(data), ["highlight.regexes"])

    def test_splice_drops_a_dangling_comma_from_the_last_member(self):
        # cmd_on's replace path deletes the unmanaged key before splicing;
        # if that key was last, the member before it keeps its comma.
        _, data = self._spliced_json(['{', '  "editor.rulers": [80],', '}'])
        self.assertEqual(data["editor.rulers"], [80])
        self.assertIn("highlight.regexes", data)

    def test_splice_ignores_a_comment_shaped_like_an_opening_brace(self):
        # A header comment ending in `{` must not become the splice point:
        # the region would land outside the settings object.
        doc = ['// tuned for project {',
               '{',
               '  "editor.rulers": [80]',
               '}',
               '']
        out, data = self._spliced_json(doc)
        begin, _ = vscode.maybe_region(out)
        self.assertEqual(out.index('{'), begin - 1)   # inside the object
        self.assertIn("highlight.regexes", data)
        self.assertEqual(data["editor.rulers"], [80])

    def test_splice_refuses_a_file_with_no_closing_brace(self):
        with self.assertRaises(vscode.VscodeError):
            vscode.splice_region(['not a settings object'])

    def test_adopt_brackets_the_minimum_span(self):
        out = vscode.adopt_key(UNMANAGED, 2)
        begin, end = vscode.maybe_region(out)
        self.assertEqual(out[begin].strip(), vscode.MARKER_BEGIN)
        self.assertEqual(out[begin + 1], UNMANAGED[2])   # content untouched
        self.assertEqual(out[end - 1], UNMANAGED[6])
        self.assertEqual(vscode.region_state(out, begin, end), "on")
        # everything outside the span is byte-identical
        self.assertEqual(out[:begin], UNMANAGED[:2])
        self.assertEqual(out[end + 1:], UNMANAGED[7:])

    def _both_states(self, lines):
        """The file parsed as strict JSON in BOTH toggle states — the
        property comma normalisation exists to hold."""
        begin, end = vscode.maybe_region(lines)
        return tuple(
            json.loads("\n".join(l for l in state
                                 if not l.strip().startswith("//")))
            for state in (vscode.enable_region(lines, begin, end),
                          vscode.disable_region(lines, begin, end)))

    def test_adopt_of_a_last_member_key_is_valid_in_both_states(self):
        # The member before a last-placed region keeps a comma that
        # dangles the moment `off` comments the region out.
        doc = ['{',
               '  "editor.tabSize": 2,',
               '  "highlight.regexes": {',
               '    "^x$": { "a": 1 }',
               '  }',
               '}',
               '']
        out = vscode.adopt_key(doc, 2)
        on, off = self._both_states(out)
        self.assertEqual(on["editor.tabSize"], 2)
        self.assertIn("highlight.regexes", on)
        self.assertEqual(off, {"editor.tabSize": 2})
        self.assertIn('    "^x$": { "a": 1 }', out)   # content untouched

    def test_adopt_of_a_sole_key_is_valid_in_both_states(self):
        doc = ['{', '  "highlight.regexes": {},', '}', '']
        on, off = self._both_states(vscode.adopt_key(doc, 1))
        self.assertEqual(list(on), ["highlight.regexes"])
        self.assertEqual(off, {})

    def test_replace_of_a_last_placed_region_is_valid_in_both_states(self):
        # `on` into `{}` strips the region's trailing comma; `--replace`
        # restores the packaged region, which still carries it.
        doc = vscode.splice_region(['{', '}'])
        begin, end = vscode.maybe_region(doc)
        on, off = self._both_states(vscode.replace_region(doc, begin, end))
        self.assertEqual(list(on), ["highlight.regexes"])
        self.assertEqual(off, {})

    def test_replace_swaps_region_content_for_packaged(self):
        begin, end = vscode.maybe_region(SAMPLE_OFF)
        out = vscode.replace_region(SAMPLE_OFF, begin, end)
        nbegin, nend = vscode.maybe_region(out)
        self.assertEqual(out[nbegin:nend + 1], vscode.packaged_region_lines())
        self.assertEqual(out[:nbegin], SAMPLE_OFF[:begin])   # outside kept


def _proc(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


class TestEditorDiscovery(unittest.TestCase):

    def test_finds_editors_on_path_in_stable_first_order(self):
        which = {"code": "/usr/bin/code", "cursor": "/usr/bin/cursor"}.get
        found = vscode.discover_editors(which=which, platform="linux")
        self.assertEqual([(e.cli_id, e.supported) for e in found],
                         [("code", True), ("cursor", False)])

    def test_falls_back_to_the_mac_app_bundle(self):
        mac = ("/Applications/Visual Studio Code.app/Contents/Resources"
               "/app/bin/code")
        found = vscode.discover_editors(
            which=lambda _: None, platform="darwin",
            exists=lambda p: p == mac)
        self.assertEqual([e.path for e in found], [mac])

    def test_pick_honours_the_flag_and_rejects_unknown(self):
        editors = [vscode.Editor("code", "Visual Studio Code",
                                 "/usr/bin/code", True)]
        self.assertEqual(vscode.pick_editor(editors, "code"), editors[0])
        with self.assertRaises(vscode.VscodeError):
            vscode.pick_editor(editors, "codium")

    def test_pick_with_none_found_names_the_command_palette(self):
        with self.assertRaises(vscode.VscodeError) as ctx:
            vscode.pick_editor([], None)
        self.assertIn("Shell Command", str(ctx.exception))

    def test_pick_defaults_to_stable_without_a_tty(self):
        editors = [
            vscode.Editor("code", "Visual Studio Code", "/u/code", True),
            vscode.Editor("cursor", "Cursor", "/u/cursor", False),
        ]
        with mock.patch.object(vscode, "_interactive", return_value=False):
            self.assertEqual(vscode.pick_editor(editors, None).cli_id, "code")

    def test_pick_without_stable_and_no_tty_names_the_flag(self):
        editors = [vscode.Editor("cursor", "Cursor", "/u/cursor", False),
                   vscode.Editor("codium", "VSCodium", "/u/codium", False)]
        with mock.patch.object(vscode, "_interactive", return_value=False):
            with self.assertRaises(vscode.VscodeError) as ctx:
                vscode.pick_editor(editors, None)
        self.assertIn("--editor", str(ctx.exception))


class TestVersions(unittest.TestCase):

    def test_parse_version_accepts_v_prefix(self):
        self.assertEqual(vscode.parse_version("v0.1.0"), (0, 1, 0))
        self.assertEqual(vscode.parse_version("0.10.2"), (0, 10, 2))

    def test_parse_version_refuses_garbage(self):
        with self.assertRaises(vscode.VscodeError):
            vscode.parse_version("latest")

    def test_installed_version_parses_the_listing(self):
        editor = vscode.Editor("code", "VS Code", "/u/code", True)
        listing = ("other.extension@9.9.9\n"
                   "dcltdw.bunnyforge-visibility-preview@0.1.0\n")
        with mock.patch.object(vscode, "_run",
                               return_value=_proc(listing)) as run:
            self.assertEqual(vscode.installed_version(editor), (0, 1, 0))
        run.assert_called_once_with(
            ["/u/code", "--list-extensions", "--show-versions"])

    def test_installed_version_none_when_absent(self):
        editor = vscode.Editor("code", "VS Code", "/u/code", True)
        with mock.patch.object(vscode, "_run", return_value=_proc("a@1\n")):
            self.assertIsNone(vscode.installed_version(editor))

    def test_installed_version_surfaces_a_failing_cli(self):
        editor = vscode.Editor("code", "VS Code", "/u/code", True)
        with mock.patch.object(vscode, "_run",
                               return_value=_proc("", 1, "boom")):
            with self.assertRaises(vscode.VscodeError):
                vscode.installed_version(editor)


RELEASE_JSON = json.dumps({
    "tag_name": "v0.2.0",
    "assets": [
        {"name": "notes.txt", "browser_download_url": "u1", "size": 1},
        {"name": "bunnyforge-visibility-preview-0.2.0.vsix",
         "browser_download_url": "https://example.invalid/x.vsix",
         "size": 4,
         "digest": "sha256:" + __import__("hashlib")
             .sha256(b"vsix").hexdigest()},
    ],
}).encode("utf-8")


class TestReleaseClient(unittest.TestCase):

    def test_parses_tag_asset_size_and_digest(self):
        release = vscode.latest_release(fetch=lambda url: RELEASE_JSON)
        self.assertEqual(release.version, (0, 2, 0))
        self.assertEqual(release.tag, "v0.2.0")
        self.assertEqual(release.vsix_name,
                         "bunnyforge-visibility-preview-0.2.0.vsix")
        self.assertEqual(release.size, 4)
        self.assertEqual(len(release.sha256), 64)

    def test_a_missing_digest_is_tolerated(self):
        data = json.loads(RELEASE_JSON)
        del data["assets"][1]["digest"]
        release = vscode.latest_release(
            fetch=lambda url: json.dumps(data).encode())
        self.assertIsNone(release.sha256)

    def test_no_vsix_asset_is_an_error(self):
        data = json.loads(RELEASE_JSON)
        data["assets"] = data["assets"][:1]
        with self.assertRaises(vscode.VscodeError):
            vscode.latest_release(fetch=lambda url: json.dumps(data).encode())

    def test_network_failure_degrades_to_a_named_error(self):
        def down(url):
            raise OSError("no route to host")
        with self.assertRaises(vscode.VscodeError) as ctx:
            vscode.latest_release(fetch=down)
        self.assertIn("GitHub", str(ctx.exception))


class TestCache(unittest.TestCase):

    def test_cache_dir_per_platform(self):
        home = Path.home()
        self.assertEqual(
            vscode.cache_dir(platform="darwin", environ={}),
            home / "Library" / "Caches" / "bunnyforge" / "vsix")
        self.assertEqual(
            vscode.cache_dir(platform="linux",
                             environ={"XDG_CACHE_HOME": "/xdg"}),
            Path("/xdg") / "bunnyforge" / "vsix")
        self.assertEqual(
            vscode.cache_dir(platform="linux", environ={}),
            home / ".cache" / "bunnyforge" / "vsix")
        self.assertEqual(
            vscode.cache_dir(platform="win32",
                             environ={"LOCALAPPDATA": r"C:\U\l"}),
            Path(r"C:\U\l") / "bunnyforge" / "vsix")

    def _release(self):
        return vscode.latest_release(fetch=lambda url: RELEASE_JSON)

    def test_downloads_verifies_and_caches(self):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        calls = []

        def fetch(url):
            calls.append(url)
            return b"vsix"

        with mock.patch.object(vscode, "cache_dir", return_value=tmp):
            path = vscode.obtain_vsix(self._release(), fetch=fetch)
            self.assertEqual(path.read_bytes(), b"vsix")
            # second run: cache hit, no re-download
            vscode.obtain_vsix(self._release(), fetch=fetch)
        self.assertEqual(calls, ["https://example.invalid/x.vsix"])

    def test_a_truncated_download_never_lands_in_the_cache(self):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        with mock.patch.object(vscode, "cache_dir", return_value=tmp):
            with self.assertRaises(vscode.VscodeError):
                vscode.obtain_vsix(self._release(), fetch=lambda url: b"vs")
        self.assertEqual(list(tmp.iterdir()), [])

    def test_a_digest_mismatch_never_lands_in_the_cache(self):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        with mock.patch.object(vscode, "cache_dir", return_value=tmp):
            with self.assertRaises(vscode.VscodeError):
                vscode.obtain_vsix(self._release(), fetch=lambda url: b"eviL")
        self.assertEqual(list(tmp.iterdir()), [])

    def test_a_corrupt_cached_file_is_re_downloaded(self):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        release = self._release()
        stale = tmp / f"{release.tag}-{release.vsix_name}"
        stale.write_bytes(b"junk-of-wrong-size")
        with mock.patch.object(vscode, "cache_dir", return_value=tmp):
            path = vscode.obtain_vsix(release, fetch=lambda url: b"vsix")
        self.assertEqual(path.read_bytes(), b"vsix")


def _machine_env(case, installed=None, listing=""):
    """Patch discovery + subprocess + network for machine-half tests.
    Returns the mock recording _run calls."""
    editor = vscode.Editor("code", "Visual Studio Code", "/u/code", True)
    case.enterContext(mock.patch.object(
        vscode, "discover_editors", return_value=[editor]))
    shown = (f"{vscode.EXTENSION_ID}@{installed}\n" if installed else "")
    run = case.enterContext(mock.patch.object(
        vscode, "_run",
        return_value=_proc(shown + listing)))
    case.enterContext(mock.patch.object(
        vscode, "latest_release",
        return_value=vscode.latest_release(fetch=lambda url: RELEASE_JSON)))
    tmp = Path(case.enterContext(tempfile.TemporaryDirectory()))
    case.enterContext(mock.patch.object(
        vscode, "obtain_vsix",
        return_value=tmp / "v0.2.0-x.vsix"))
    return run


class TestInstallUpdate(unittest.TestCase):

    def test_install_refuses_without_yes_when_not_a_tty(self):
        _machine_env(self)
        with mock.patch.object(vscode, "_interactive", return_value=False):
            with contextlib.redirect_stdout(io.StringIO()), \
                 contextlib.redirect_stderr(io.StringIO()) as err:
                rc = vscode.main(["install"])
        self.assertEqual(rc, 1)
        self.assertIn("--yes", err.getvalue())

    def test_install_prints_provenance_and_installs(self):
        run = _machine_env(self)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = vscode.main(["install", "--yes"])
        self.assertEqual(rc, 0)
        text = out.getvalue()
        self.assertIn(vscode.EXTENSION_REPO, text)   # pinned source, shown
        self.assertIn("v0.2.0", text)
        install_call = run.call_args_list[-1].args[0]
        self.assertEqual(install_call[:2], ["/u/code", "--install-extension"])
        self.assertIn("--force", install_call)

    def test_install_is_idempotent_at_the_current_version(self):
        run = _machine_env(self, installed="0.2.0")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = vscode.main(["install", "--yes"])
        self.assertEqual(rc, 0)
        self.assertIn("nothing to do", out.getvalue())
        for call in run.call_args_list:
            self.assertNotIn("--install-extension", call.args[0])

    def test_update_requires_an_existing_install(self):
        _machine_env(self)   # nothing installed
        with contextlib.redirect_stdout(io.StringIO()), \
             contextlib.redirect_stderr(io.StringIO()) as err:
            rc = vscode.main(["update", "--yes"])
        self.assertEqual(rc, 1)
        self.assertIn("vscode install", err.getvalue())

    def test_update_upgrades_an_older_install(self):
        run = _machine_env(self, installed="0.1.0")
        with contextlib.redirect_stdout(io.StringIO()):
            rc = vscode.main(["update", "--yes"])
        self.assertEqual(rc, 0)
        self.assertIn("--install-extension",
                      run.call_args_list[-1].args[0])


class TestUninstall(unittest.TestCase):

    def test_uninstall_runs_the_editor_cli(self):
        run = _machine_env(self, installed="0.2.0")
        with contextlib.redirect_stdout(io.StringIO()):
            rc = vscode.main(["uninstall", "--yes"])
        self.assertEqual(rc, 0)
        self.assertEqual(run.call_args_list[-1].args[0],
                         ["/u/code", "--uninstall-extension",
                          vscode.EXTENSION_ID])

    def test_uninstall_when_absent_is_a_no_op(self):
        run = _machine_env(self)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = vscode.main(["uninstall", "--yes"])
        self.assertEqual(rc, 0)
        self.assertIn("nothing to do", out.getvalue())
        for call in run.call_args_list:
            self.assertNotIn("--uninstall-extension", call.args[0])


class TestStatus(unittest.TestCase):

    def test_status_without_a_workspace_says_so_and_exits_zero(self):
        _machine_env(self, installed="0.1.0")
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        env = {k: v for k, v in os.environ.items()
               if k != "BUNNYFORGE_WORKSPACE"}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(Path, "cwd", return_value=tmp), \
             contextlib.redirect_stdout(io.StringIO()) as out:
            rc = vscode.main(["status"])
        self.assertEqual(rc, 0)
        text = out.getvalue()
        self.assertIn("0.1.0", text)          # installed
        self.assertIn("0.2.0", text)          # available
        self.assertIn("none found", text)     # the workspace half, plainly

    def test_status_reports_colouring_state_in_a_workspace(self):
        _machine_env(self, installed="0.2.0")
        ws = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        (ws / "campaign.toml").write_text(
            '[campaign]\nnamespace = "probe"\n', encoding="utf-8")
        (ws / ".vscode").mkdir()
        (ws / ".vscode" / "settings.json").write_bytes(
            init.packaged_bytes("vscode/settings.json"))
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = vscode.main(["status", "--workspace", str(ws)])
        self.assertEqual(rc, 0)
        self.assertIn("off", out.getvalue())

    def _status_env(self, editors):
        self.enterContext(mock.patch.object(
            vscode, "discover_editors", return_value=editors))
        self.enterContext(mock.patch.object(vscode, "_run",
                                            return_value=_proc("")))
        self.enterContext(mock.patch.object(
            vscode, "latest_release",
            return_value=vscode.latest_release(
                fetch=lambda url: RELEASE_JSON)))
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        env = {k: v for k, v in os.environ.items()
               if k != "BUNNYFORGE_WORKSPACE"}
        self.enterContext(mock.patch.dict(os.environ, env, clear=True))
        self.enterContext(mock.patch.object(Path, "cwd", return_value=tmp))

    def test_status_never_prompts_when_several_editors_are_found(self):
        # A read-only report must not block on "install into [1]:".
        self._status_env([
            vscode.Editor("code", "Visual Studio Code", "/u/code", True),
            vscode.Editor("cursor", "Cursor", "/u/cursor", False),
        ])
        self.enterContext(mock.patch.object(
            vscode, "_interactive", return_value=True))
        ask = self.enterContext(mock.patch.object(
            vscode, "_ask", side_effect=AssertionError("status prompted")))
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = vscode.main(["status"])
        self.assertEqual(rc, 0)
        ask.assert_not_called()
        self.assertIn("Visual Studio Code", out.getvalue())   # stable wins
        self.assertNotIn("install into", out.getvalue())

    def test_status_says_when_the_editor_filter_matched_nothing(self):
        self._status_env([
            vscode.Editor("code", "Visual Studio Code", "/u/code", True)])
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = vscode.main(["status", "--editor", "bogus"])
        self.assertEqual(rc, 0)
        text = out.getvalue()
        self.assertIn("bogus", text)                  # the filter, named
        self.assertIn("Visual Studio Code", text)     # what it reports on

    def test_status_degrades_when_github_is_unreachable(self):
        editor = vscode.Editor("code", "Visual Studio Code", "/u/code", True)
        self.enterContext(mock.patch.object(
            vscode, "discover_editors", return_value=[editor]))
        self.enterContext(mock.patch.object(vscode, "_run",
                                            return_value=_proc("")))
        self.enterContext(mock.patch.object(
            vscode, "latest_release",
            side_effect=vscode.VscodeError("couldn't reach GitHub")))
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        env = {k: v for k, v in os.environ.items()
               if k != "BUNNYFORGE_WORKSPACE"}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(Path, "cwd", return_value=tmp), \
             contextlib.redirect_stdout(io.StringIO()) as out:
            rc = vscode.main(["status"])
        self.assertEqual(rc, 0)               # status reports; never fails
        self.assertIn("unknown", out.getvalue())

    def test_status_degrades_when_the_editor_cli_fails(self):
        editor = vscode.Editor("code", "Visual Studio Code", "/u/code", True)
        self.enterContext(mock.patch.object(
            vscode, "discover_editors", return_value=[editor]))
        self.enterContext(mock.patch.object(
            vscode, "installed_version",
            side_effect=vscode.VscodeError("code --list-extensions failed: "
                                           "permission denied")))
        self.enterContext(mock.patch.object(vscode, "_run",
                                            return_value=_proc("")))
        self.enterContext(mock.patch.object(
            vscode, "latest_release",
            return_value=vscode.latest_release(fetch=lambda url: RELEASE_JSON)))
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        env = {k: v for k, v in os.environ.items()
               if k != "BUNNYFORGE_WORKSPACE"}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(Path, "cwd", return_value=tmp), \
             contextlib.redirect_stdout(io.StringIO()) as out:
            rc = vscode.main(["status"])
        self.assertEqual(rc, 0)               # status reports; never fails
        text = out.getvalue()
        self.assertEqual(text.count("preview ext"), 1)  # exactly one line
        self.assertIn("unknown", text)
        self.assertIn("permission denied", text)
        self.assertIn("none found", text)     # workspace half still runs


def _ws(case) -> Path:
    ws = Path(case.enterContext(tempfile.TemporaryDirectory())).resolve()
    (ws / "campaign.toml").write_text(
        '[campaign]\nnamespace = "probe"\n', encoding="utf-8")
    return ws


def _settings_of(ws: Path) -> list[str]:
    return (ws / ".vscode" / "settings.json").read_text("utf-8").split("\n")


class TestOnOff(unittest.TestCase):

    def _on(self, ws, *flags):
        with mock.patch.object(vscode, "_offer_highlight"), \
             contextlib.redirect_stdout(io.StringIO()) as out, \
             contextlib.redirect_stderr(io.StringIO()) as err:
            rc = vscode.main(["on", "--workspace", str(ws), *flags])
        return rc, out.getvalue(), err.getvalue()

    def test_on_creates_the_file_enabled_when_absent(self):
        ws = _ws(self)
        rc, _, _ = self._on(ws)
        self.assertEqual(rc, 0)
        lines = _settings_of(ws)
        begin, end = vscode.maybe_region(lines)
        self.assertEqual(vscode.region_state(lines, begin, end), "on")
        # strict JSON once comments drop — the whole point of the layout
        json.loads("\n".join(
            l for l in lines if not l.strip().startswith("//")))

    def test_on_enables_a_scaffolded_off_file(self):
        ws = _ws(self)
        (ws / ".vscode").mkdir()
        (ws / ".vscode" / "settings.json").write_bytes(
            init.packaged_bytes("vscode/settings.json"))
        rc, _, _ = self._on(ws)
        self.assertEqual(rc, 0)
        lines = _settings_of(ws)
        begin, end = vscode.maybe_region(lines)
        self.assertEqual(vscode.region_state(lines, begin, end), "on")

    def test_on_is_idempotent(self):
        ws = _ws(self)
        self._on(ws)
        before = _settings_of(ws)
        rc, out, _ = self._on(ws)
        self.assertEqual(rc, 0)
        self.assertIn("already on", out)
        self.assertEqual(_settings_of(ws), before)

    def test_on_replace_resets_hand_tuning(self):
        ws = _ws(self)
        self._on(ws)
        lines = _settings_of(ws)
        begin, _ = vscode.maybe_region(lines)
        # hand-tune a colour inside the region
        idx = next(i for i, l in enumerate(lines) if "#ff3333" in l)
        lines[idx] = lines[idx].replace("#ff3333", "#123456")
        (ws / ".vscode" / "settings.json").write_text(
            "\n".join(lines), encoding="utf-8")
        rc, _, _ = self._on(ws, "--replace")
        self.assertEqual(rc, 0)
        text = "\n".join(_settings_of(ws))
        self.assertNotIn("#123456", text)
        self.assertIn("#ff3333", text)

    def test_on_without_replace_preserves_hand_tuning(self):
        ws = _ws(self)
        self._on(ws)
        lines = _settings_of(ws)
        idx = next(i for i, l in enumerate(lines) if "#ff3333" in l)
        lines[idx] = lines[idx].replace("#ff3333", "#123456")
        (ws / ".vscode" / "settings.json").write_text(
            "\n".join(lines), encoding="utf-8")
        rc, _, _ = self._on(ws)   # already on; must not touch content
        self.assertEqual(rc, 0)
        self.assertIn("#123456", "\n".join(_settings_of(ws)))

    def test_off_disables_and_hints_at_uninstall(self):
        ws = _ws(self)
        self._on(ws)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = vscode.main(["off", "--workspace", str(ws)])
        self.assertEqual(rc, 0)
        lines = _settings_of(ws)
        begin, end = vscode.maybe_region(lines)
        self.assertEqual(vscode.region_state(lines, begin, end), "off")
        self.assertIn("bunnyforge vscode uninstall", out.getvalue())
        # the pin survives off — it belongs to the preview half
        self.assertIn('"markdown.preview.frontMatter": "table"',
                      "\n".join(lines))

    def test_on_replace_after_on_into_an_empty_object(self):
        # Two commands from a bare `{}`: the region is the sole member,
        # so the packaged region's trailing comma must not come back.
        ws = _ws(self)
        (ws / ".vscode").mkdir()
        (ws / ".vscode" / "settings.json").write_text("{\n}\n",
                                                      encoding="utf-8")
        self.assertEqual(self._on(ws)[0], 0)
        self.assertEqual(self._on(ws, "--replace")[0], 0)
        json.loads("\n".join(l for l in _settings_of(ws)
                             if not l.strip().startswith("//")))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(vscode.main(["off", "--workspace", str(ws)]), 0)
        self.assertEqual(json.loads("\n".join(
            l for l in _settings_of(ws)
            if not l.strip().startswith("//"))), {})

    def test_adopt_then_off_leaves_valid_json(self):
        ws = _ws(self)
        (ws / ".vscode").mkdir()
        (ws / ".vscode" / "settings.json").write_text(
            '{\n'
            '  "editor.tabSize": 2,\n'
            '  "highlight.regexes": {\n'
            '    "^tuned$": { "regexFlags": "gm" }\n'
            '  }\n'
            '}\n', encoding="utf-8")
        self.assertEqual(self._on(ws, "--adopt")[0], 0)
        data = json.loads("\n".join(l for l in _settings_of(ws)
                                    if not l.strip().startswith("//")))
        self.assertIn("^tuned$", json.dumps(data["highlight.regexes"]))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(vscode.main(["off", "--workspace", str(ws)]), 0)
        self.assertEqual(json.loads("\n".join(
            l for l in _settings_of(ws)
            if not l.strip().startswith("//"))), {"editor.tabSize": 2})

    def test_off_with_no_file_is_a_named_error(self):
        ws = _ws(self)
        with contextlib.redirect_stderr(io.StringIO()) as err:
            rc = vscode.main(["off", "--workspace", str(ws)])
        self.assertEqual(rc, 1)
        self.assertIn("error: ", err.getvalue())

    def test_on_refuses_unbalanced_markers(self):
        ws = _ws(self)
        (ws / ".vscode").mkdir()
        broken = [l for l in init.packaged_bytes("vscode/settings.json")
                  .decode("utf-8").split("\n")
                  if l.strip() != vscode.MARKER_END]
        (ws / ".vscode" / "settings.json").write_text(
            "\n".join(broken), encoding="utf-8")
        rc, _, err = self._on(ws)
        self.assertEqual(rc, 1)
        self.assertIn("unbalanced", err)


class TestOnConflict(unittest.TestCase):
    """The duplicate-key hazard: a hand-rolled highlight.regexes outside
    any markers. Never append; ask, recommending adopt (decision 6)."""

    def _handrolled(self) -> Path:
        ws = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        (ws / "campaign.toml").write_text(
            '[campaign]\nnamespace = "probe"\n', encoding="utf-8")
        (ws / ".vscode").mkdir()
        (ws / ".vscode" / "settings.json").write_text(
            '{\n'
            '  // tuned by hand, years of care\n'
            '  "highlight.regexes": {\n'
            '    "^tuned$": { "regexFlags": "gm" }\n'
            '  },\n'
            '  "editor.rulers": [80]\n'
            '}\n', encoding="utf-8")
        return ws

    def _on(self, ws, *flags):
        with mock.patch.object(vscode, "_offer_highlight"), \
             contextlib.redirect_stdout(io.StringIO()) as out, \
             contextlib.redirect_stderr(io.StringIO()) as err:
            rc = vscode.main(["on", "--workspace", str(ws), *flags])
        return rc, out.getvalue(), err.getvalue()

    def test_no_tty_and_no_flag_fails_naming_both_flags(self):
        ws = self._handrolled()
        with mock.patch.object(vscode, "_interactive", return_value=False):
            rc, _, err = self._on(ws)
        self.assertEqual(rc, 1)
        self.assertIn("--adopt", err)
        self.assertIn("--replace", err)
        self.assertIn("tuned", (ws / ".vscode" / "settings.json")
                      .read_text("utf-8"))   # untouched

    def test_adopt_brackets_the_users_rules_untouched(self):
        ws = self._handrolled()
        rc, _, _ = self._on(ws, "--adopt")
        self.assertEqual(rc, 0)
        lines = _settings_of(ws)
        begin, end = vscode.maybe_region(lines)
        self.assertEqual(vscode.region_state(lines, begin, end), "on")
        self.assertIn("^tuned$", "\n".join(lines[begin:end]))
        self.assertIn("years of care", "\n".join(lines))   # comment kept

    def test_replace_discards_the_users_rules_for_packaged(self):
        ws = self._handrolled()
        rc, _, _ = self._on(ws, "--replace")
        self.assertEqual(rc, 0)
        text = "\n".join(_settings_of(ws))
        self.assertNotIn("^tuned$", text)
        self.assertIn("visibility:", text)
        self.assertIn('"editor.rulers": [80]', text)   # rest of file kept

    def test_interactive_cancel_changes_nothing_and_exits_nonzero(self):
        ws = self._handrolled()
        before = (ws / ".vscode" / "settings.json").read_text("utf-8")
        with mock.patch.object(vscode, "_interactive", return_value=True), \
             mock.patch.object(vscode, "_ask", return_value="c"):
            rc, _, _ = self._on(ws)
        self.assertEqual(rc, 1)
        self.assertEqual((ws / ".vscode" / "settings.json")
                         .read_text("utf-8"), before)


class TestOfferHighlight(unittest.TestCase):

    def test_on_offers_the_highlight_extension_when_missing(self):
        ws = _ws(self)
        editor = vscode.Editor("code", "Visual Studio Code", "/u/code", True)
        self.enterContext(mock.patch.object(
            vscode, "discover_editors", return_value=[editor]))
        run = self.enterContext(mock.patch.object(
            vscode, "_run", return_value=_proc("")))
        self.enterContext(mock.patch.object(
            vscode, "_interactive", return_value=True))
        self.enterContext(mock.patch.object(
            vscode, "_ask", return_value="y"))
        with contextlib.redirect_stdout(io.StringIO()):
            rc = vscode.main(["on", "--workspace", str(ws)])
        self.assertEqual(rc, 0)
        self.assertIn(
            ["/u/code", "--install-extension", vscode.HIGHLIGHT_ID],
            [c.args[0] for c in run.call_args_list])

    def test_a_failed_highlight_install_does_not_fail_the_toggle(self):
        # The file was already written; the offer is a courtesy, so a
        # non-zero editor CLI is a note, never the command's exit code.
        ws = _ws(self)
        editor = vscode.Editor("code", "Visual Studio Code", "/u/code", True)
        self.enterContext(mock.patch.object(
            vscode, "discover_editors", return_value=[editor]))
        self.enterContext(mock.patch.object(
            vscode, "_run", return_value=_proc("", 1, "marketplace down")))
        self.enterContext(mock.patch.object(
            vscode, "_interactive", return_value=True))
        self.enterContext(mock.patch.object(vscode, "_ask", return_value="y"))
        with contextlib.redirect_stdout(io.StringIO()) as out, \
             contextlib.redirect_stderr(io.StringIO()) as err:
            rc = vscode.main(["on", "--workspace", str(ws)])
        self.assertEqual(rc, 0)
        self.assertEqual(err.getvalue(), "")
        self.assertIn("note:", out.getvalue())
        self.assertIn("marketplace down", out.getvalue())
        lines = _settings_of(ws)
        self.assertEqual(vscode.region_state(
            lines, *vscode.maybe_region(lines)), "on")

    def test_non_interactive_on_prints_a_hint_instead(self):
        ws = _ws(self)
        editor = vscode.Editor("code", "Visual Studio Code", "/u/code", True)
        self.enterContext(mock.patch.object(
            vscode, "discover_editors", return_value=[editor]))
        run = self.enterContext(mock.patch.object(
            vscode, "_run", return_value=_proc("")))
        self.enterContext(mock.patch.object(
            vscode, "_interactive", return_value=False))
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = vscode.main(["on", "--workspace", str(ws)])
        self.assertEqual(rc, 0)               # the toggle itself succeeded
        self.assertIn(vscode.HIGHLIGHT_ID, out.getvalue())
        self.assertNotIn(
            ["/u/code", "--install-extension", vscode.HIGHLIGHT_ID],
            [c.args[0] for c in run.call_args_list])


class TestSetup(unittest.TestCase):

    def test_setup_installs_then_offers_on_in_a_workspace(self):
        ws = _ws(self)
        _machine_env(self)
        self.enterContext(mock.patch.object(
            vscode, "_offer_highlight"))
        with contextlib.redirect_stdout(io.StringIO()):
            rc = vscode.main(["setup", "--workspace", str(ws), "--yes"])
        self.assertEqual(rc, 0)
        self.assertTrue((ws / ".vscode" / "settings.json").is_file())

    def test_setup_without_a_workspace_still_installs(self):
        _machine_env(self)
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        env = {k: v for k, v in os.environ.items()
               if k != "BUNNYFORGE_WORKSPACE"}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(Path, "cwd", return_value=tmp), \
             contextlib.redirect_stdout(io.StringIO()) as out:
            rc = vscode.main(["setup", "--yes"])
        self.assertEqual(rc, 0)
        self.assertIn("no campaign workspace", out.getvalue())

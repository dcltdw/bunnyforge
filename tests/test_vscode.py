"""Tests for bunnyforge.vscode — the editor-integration command.

Everything external is injected or mocked: `_fetch` (network), `_run`
(subprocess), `_interactive`/`_ask` (TTY). No test touches GitHub or a
real editor.
"""

import contextlib
import io
import json
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

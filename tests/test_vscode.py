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

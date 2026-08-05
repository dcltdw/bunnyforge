import contextlib
import gzip
import io
import os
import re
import tempfile
import unittest
from pathlib import Path

from bunnyforge import import_perceptions as ip


class TestInlineMarkup(unittest.TestCase):
    """One case per DokuWiki inline construct the importer claims to handle."""

    def test_bold_passes_through(self):
        # NOTE: the bold rule is an identity transform (**x** -> **x**), so
        # deleting the substitution entirely is also a no-op for this input.
        # A mutation test can't distinguish "rule present" from "rule
        # deleted" here; this case is vacuous by construction and cannot be
        # strengthened without changing what bold markup converts to.
        self.assertEqual(ip.convert_markup("**bold**"), "**bold**")

    def test_italic_becomes_asterisks(self):
        self.assertEqual(ip.convert_markup("//italic//"), "*italic*")

    def test_url_is_not_mistaken_for_italic(self):
        # Both a URL and italic emphasis on the same line. With the (?<!:)
        # guard, only the italic text converts and the URL is untouched.
        # Without the guard, the URL's // would be consumed as an opening
        # italic delimiter, corrupting output to "see http:*example.com and
        # *not italic// too".
        self.assertEqual(
            ip.convert_markup("see http://example.com and //not italic// too"),
            "see http://example.com and *not italic* too")

    def test_underline_markers_are_dropped(self):
        self.assertEqual(ip.convert_markup("__under__"), "under")

    def test_monospace_becomes_backticks(self):
        self.assertEqual(ip.convert_markup("''mono''"), "`mono`")

    def test_del_becomes_strikethrough(self):
        self.assertEqual(ip.convert_markup("<del>gone</del>"), "~~gone~~")

    def test_trailing_backslashes_become_hard_break(self):
        self.assertEqual(ip.convert_markup("end of line\\\\"), "end of line  ")

    def test_labelled_link(self):
        self.assertEqual(ip.convert_markup("[[target|Label]]"), "[Label](target)")

    def test_bare_link_uses_target_as_label(self):
        self.assertEqual(ip.convert_markup("[[target]]"), "[target](target)")


class TestHeadings(unittest.TestCase):
    """DokuWiki inverts the heading scale: ====== is h1, == is h5."""

    def test_six_equals_is_h1(self):
        self.assertEqual(ip.convert_markup("====== Title ======"), "# Title")

    def test_five_equals_is_h2(self):
        self.assertEqual(ip.convert_markup("===== Sub ====="), "## Sub")

    def test_two_equals_is_h5(self):
        self.assertEqual(ip.convert_markup("== Deep =="), "##### Deep")

    def test_unbalanced_heading_half_converts_known_quirk(self):
        # KNOWN QUIRK, pinned deliberately. The heading pattern is
        # `^\s*(={2,6})\s*(.*?)\s*\1\s*$`, and `(={2,6})` backtracks: for
        # `====== Lopsided ===` it matches only the first three `=`, so the
        # backreference finds the trailing `===` and the rest of the leading
        # run is swept into the title. Result: `#### === Lopsided`.
        #
        # This contradicts the module's stated policy of passing unrecognised
        # markup through unmangled, but it is existing behaviour on malformed
        # input and changing it is out of scope here. The test exists so a
        # future fix is a deliberate, visible change rather than a surprise.
        self.assertEqual(ip.convert_markup("====== Lopsided ==="),
                         "#### === Lopsided")


class TestLists(unittest.TestCase):
    """DokuWiki indents two spaces per level; `*` is unordered, `-` ordered."""

    def test_first_level_unordered(self):
        self.assertEqual(ip.convert_markup("  * one"), "- one")

    def test_second_level_unordered_indents_once(self):
        self.assertEqual(ip.convert_markup("    * two"), "  - two")

    def test_ordered_marker(self):
        self.assertEqual(ip.convert_markup("  - first"), "1. first")


class TestCodeBlocks(unittest.TestCase):
    def test_content_inside_code_is_not_converted(self):
        src = "<code>\nraw //not italic// here\n</code>\n"
        self.assertIn("//not italic//", ip.convert_markup(src))

    def test_conversion_resumes_after_a_code_block(self):
        # Regression: the closing tag failed to clear the in-code flag, so
        # everything after the first code block was passed through raw.
        src = ("<code>\nraw //not italic// here\n</code>\n\n"
               "====== A Heading ======\n\nand //real italic//.\n")
        out = ip.convert_markup(src)
        self.assertIn("# A Heading", out)
        self.assertIn("*real italic*", out)
        self.assertIn("//not italic//", out)   # still raw inside the block

    def test_file_blocks_behave_the_same(self):
        src = "<file>\nkeep //this//\n</file>\n\n//converted//\n"
        out = ip.convert_markup(src)
        self.assertIn("keep //this//", out)
        self.assertIn("*converted*", out)


def _write_attic(attic_root: Path, page_id: str, ts: int, text: str) -> None:
    rel = Path(*page_id.split(":"))
    d = attic_root / rel.parent
    d.mkdir(parents=True, exist_ok=True)
    with gzip.open(d / f"{rel.name}.{ts}.txt.gz", "wt", encoding="utf-8") as fh:
        fh.write(text)


def _write_page(pages_root: Path, page_id: str, text: str) -> Path:
    rel = Path(*page_id.split(":")).with_suffix(".txt")
    p = pages_root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


class TestRevisionSelection(unittest.TestCase):
    def test_attic_revisions_sorted_oldest_first(self):
        with tempfile.TemporaryDirectory() as d:
            attic = Path(d)
            for ts in (300, 100, 200):
                _write_attic(attic, "party:mira", ts, f"v{ts}")
            revs = ip.attic_revisions(attic, "party:mira")
            self.assertEqual([ts for ts, _ in revs], [100, 200, 300])

    def test_attic_revisions_empty_when_namespace_absent(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(ip.attic_revisions(Path(d), "party:nobody"), [])

    def test_read_page_current_when_no_as_of(self):
        with tempfile.TemporaryDirectory() as d:
            pages, attic = Path(d) / "pages", Path(d) / "attic"
            _write_page(pages, "party:mira", "current text")
            got = ip.read_page(pages, attic, "party:mira", None)
            self.assertIsNotNone(got)
            self.assertEqual(got[0], "current text")

    def test_read_page_missing_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            pages, attic = Path(d) / "pages", Path(d) / "attic"
            pages.mkdir()
            self.assertIsNone(ip.read_page(pages, attic, "party:nobody", None))

    def test_read_page_picks_newest_revision_at_or_before_as_of(self):
        with tempfile.TemporaryDirectory() as d:
            pages, attic = Path(d) / "pages", Path(d) / "attic"
            pages.mkdir()
            _write_attic(attic, "party:mira", 100, "oldest")
            _write_attic(attic, "party:mira", 200, "middle")
            _write_attic(attic, "party:mira", 300, "newest")
            got = ip.read_page(pages, attic, "party:mira", 250)
            self.assertEqual(got[0], "middle")
            self.assertEqual(got[1], 200)

    def test_read_page_returns_none_when_nothing_is_old_enough(self):
        # No archived revision at or before as_of, and the current page is
        # newer than as_of, so there is nothing honest to return.
        with tempfile.TemporaryDirectory() as d:
            pages, attic = Path(d) / "pages", Path(d) / "attic"
            _write_page(pages, "party:mira", "current")
            _write_attic(attic, "party:mira", 500, "later")
            self.assertIsNone(ip.read_page(pages, attic, "party:mira", 100))

    def test_read_page_revision_exactly_at_as_of_is_included(self):
        # "At or before as_of" is inclusive of the boundary itself. A test
        # that only probes strictly-before values (e.g. as_of=250 against
        # revisions at 100/200/300) can't tell `ts <= as_of` apart from
        # `ts < as_of`, since no candidate ever lands exactly on as_of. This
        # places a revision's timestamp exactly equal to as_of to pin down
        # the inclusive boundary.
        with tempfile.TemporaryDirectory() as d:
            pages, attic = Path(d) / "pages", Path(d) / "attic"
            pages.mkdir()
            _write_attic(attic, "party:mira", 100, "oldest")
            _write_attic(attic, "party:mira", 200, "boundary")
            got = ip.read_page(pages, attic, "party:mira", 200)
            self.assertEqual(got[0], "boundary")
            self.assertEqual(got[1], 200)

    def test_read_page_current_page_exactly_at_as_of_is_included(self):
        # Same inclusive-boundary concern, but for the current-page fallback
        # path: the current file's mtime set exactly equal to as_of.
        with tempfile.TemporaryDirectory() as d:
            pages, attic = Path(d) / "pages", Path(d) / "attic"
            p = _write_page(pages, "party:mira", "current")
            os.utime(p, (200, 200))
            got = ip.read_page(pages, attic, "party:mira", 200)
            self.assertIsNotNone(got)
            self.assertEqual(got[0], "current")


class TestFileBuilding(unittest.TestCase):
    def test_slugify_flattens_namespace_and_underscores(self):
        # Uppercase input pins .lower(): without it, uppercase letters fall
        # outside [^a-z0-9] and are treated as separators, silently deleting
        # them (e.g. "Mira_Venn" -> "ira-enn") rather than raising an error.
        self.assertEqual(ip.slugify("testwiki:party:Mira_Venn"), "testwiki-party-mira-venn")

    def test_first_heading_found(self):
        self.assertEqual(ip.first_heading("====== A ======\nx"), "A")

    def test_first_heading_absent(self):
        self.assertIsNone(ip.first_heading("no heading"))

    def test_build_file_marks_content_as_perception(self):
        out = ip.build_file("party:mira", "====== Mira ======\n\nbody\n", 0, None)
        self.assertIn("canon: perception", out)
        self.assertIn("party:mira", out)

    def test_build_file_as_of_label_appears_in_front_matter(self):
        out = ip.build_file("party:mira", "====== Mira ======\n\nbody\n", 0, "2026-03-14")
        self.assertIn("as_of: 2026-03-14", out)


def _write_campaign_toml(root: Path, perceptions_dir: str | None = None) -> Path:
    """Mark `root` as a campaign workspace, optionally overriding
    perceptions_dir so a test can prove main() reads the config key rather
    than a hardcoded 'Perceptions'."""
    lines = ['[campaign]', 'namespace = "test"']
    if perceptions_dir is not None:
        lines += ['', '[workspace]', f'perceptions_dir = "{perceptions_dir}"']
    (root / "campaign.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root


class TestMain(unittest.TestCase):
    """End-to-end coverage of main(), the script's only file-writing path.

    Each test builds a temp campaign workspace (a directory holding
    campaign.toml) and steers main() with `--workspace <root> --wiki-data
    <path> ...` rather than reassigning a module global — that mechanism has
    been retired; main() now resolves everything it needs from the
    Workspace it is handed.
    """

    def _run_main_capturing(self, workspace: Path, *argv) -> tuple[int, str]:
        """Run main() and hand back both the exit code and stdout.

        The plain _run_main below discards both captured buffers, which is
        why nothing could assert on the run summary before issue #25.
        """
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = ip.main(["--workspace", str(workspace), *argv])
        return rc, out.getvalue()

    def _run_main(self, workspace: Path, *argv) -> int:
        rc, _out = self._run_main_capturing(workspace, *argv)
        return rc

    def test_blank_page_is_counted_and_named_in_the_summary(self):
        # Issue #25's reproducer: two pages present, one blank. The run used
        # to report "1 written, 0 skipped, 0 unavailable" — the blank page
        # vanished from the output and from the tally, indistinguishable
        # from a page that was never there.
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            _write_campaign_toml(d)
            data = d / "data"
            _write_page(data / "pages", "party:mira", "====== Mira ======\n\nbody\n")
            _write_page(data / "pages", "party:blank", "   \n\n")

            rc, out = self._run_main_capturing(d, "--wiki-data", str(data))

            self.assertEqual(rc, 0)
            self.assertIn("1 written, 0 skipped, 1 blank, 0 unavailable.", out)
            # Every other outcome prints a per-page line; blank pages used to
            # print nothing at all, so the operator could not tell which page
            # it was.
            self.assertIn("party:blank", out)

    def test_every_page_considered_lands_in_exactly_one_category(self):
        # The accounting invariant the issue asks for:
        # written + skipped + blank + unavailable == pages considered.
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            _write_campaign_toml(d)
            data, perceptions = d / "data", d / "Perceptions"
            _write_page(data / "pages", "party:written", "====== W ======\n\nbody\n")
            _write_page(data / "pages", "party:blank", "\n")
            _write_page(data / "pages", "party:existing", "====== E ======\n\nbody\n")
            perceptions.mkdir()
            (perceptions / "party-existing.md").write_text("already here\n",
                                                           encoding="utf-8")

            rc, out = self._run_main_capturing(d, "--wiki-data", str(data))

            self.assertEqual(rc, 0)
            m = re.search(
                r"(\d+) written, (\d+) skipped, (\d+) blank, (\d+) unavailable\.", out)
            self.assertIsNotNone(m, f"summary line not found in:\n{out}")
            self.assertEqual(sum(int(g) for g in m.groups()), 3)

    def test_a_wholly_blank_namespace_reports_every_page(self):
        # The degenerate case: nothing is written, but the operator must
        # still be told three pages were considered rather than seeing a
        # bare "0 written" that reads like an empty namespace.
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            _write_campaign_toml(d)
            data = d / "data"
            for n in ("a", "b", "c"):
                _write_page(data / "pages", f"party:{n}", "  \n")

            rc, out = self._run_main_capturing(d, "--wiki-data", str(data))

            self.assertEqual(rc, 0)
            self.assertIn("0 written, 0 skipped, 3 blank, 0 unavailable.", out)

    def test_successful_run_writes_expected_file_and_returns_zero(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            _write_campaign_toml(d)
            data, perceptions = d / "data", d / "Perceptions"
            _write_page(data / "pages", "party:mira", "====== Mira ======\n\nbody\n")

            rc = self._run_main(d, "--wiki-data", str(data), "--go")

            self.assertEqual(rc, 0)
            out_file = perceptions / "party-mira.md"
            self.assertTrue(out_file.exists())
            self.assertIn("canon: perception", out_file.read_text(encoding="utf-8"))

    def test_perceptions_dir_honours_config_override(self):
        # Same scenario as above, but the workspace renames its perceptions
        # directory. If main() ever hardcoded "Perceptions" instead of
        # reading ws.config.perceptions_dir, this would write to the wrong
        # place and the assertion below would fail to find the file.
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            _write_campaign_toml(d, perceptions_dir="PlayerBeliefs")
            data = d / "data"
            _write_page(data / "pages", "party:mira", "====== Mira ======\n\nbody\n")

            rc = self._run_main(d, "--wiki-data", str(data), "--go")

            self.assertEqual(rc, 0)
            self.assertTrue((d / "PlayerBeliefs" / "party-mira.md").exists())
            self.assertFalse((d / "Perceptions").exists())

    def test_as_of_produces_dated_filename_and_selects_archived_revision(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            _write_campaign_toml(d)
            data, perceptions = d / "data", d / "Perceptions"

            # Current page is stamped far in the future so it's outside the
            # --as-of window; only the archived revision (well before it)
            # should qualify. If --as-of ever fell through to current text
            # instead of the archive, this would catch it.
            cur = _write_page(data / "pages", "party:mira",
                               "====== Mira ======\n\ncurrent body\n")
            os.utime(cur, (4102444800, 4102444800))  # 2100-01-01
            _write_attic(data / "attic", "party:mira", 100,
                         "====== Mira ======\n\narchived body\n")

            rc = self._run_main(d, "--wiki-data", str(data), "--as-of", "2020-01-01", "--go")

            self.assertEqual(rc, 0)
            out_file = perceptions / "party-mira--2020-01-01.md"
            self.assertTrue(out_file.exists())
            content = out_file.read_text(encoding="utf-8")
            self.assertIn("archived body", content)
            self.assertNotIn("current body", content)
            self.assertIn("as_of: 2020-01-01", content)

    def test_existing_destination_skipped_without_overwrite_then_replaced_with_it(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            _write_campaign_toml(d)
            data, perceptions = d / "data", d / "Perceptions"
            perceptions.mkdir(parents=True)
            dest = perceptions / "party-mira.md"
            dest.write_text("SENTINEL - pre-existing", encoding="utf-8")
            _write_page(data / "pages", "party:mira", "====== Mira ======\n\nnew body\n")

            # No --go here: the file already exists and --overwrite is not
            # given, so this hits the "skip (exists)" path before the
            # dry-run/--go branch is ever consulted — a dry run proves the
            # same thing a --go run would.
            rc = self._run_main(d, "--wiki-data", str(data))
            self.assertEqual(rc, 0)
            self.assertEqual(dest.read_text(encoding="utf-8"), "SENTINEL - pre-existing")

            rc = self._run_main(d, "--wiki-data", str(data), "--overwrite", "--go")
            self.assertEqual(rc, 0)
            content = dest.read_text(encoding="utf-8")
            self.assertIn("new body", content)
            self.assertNotIn("SENTINEL", content)

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            _write_campaign_toml(d)
            data, perceptions = d / "data", d / "Perceptions"
            _write_page(data / "pages", "party:mira", "====== Mira ======\n\nbody\n")

            # No --go: the bare run IS the dry run now (package-wide
            # convention), so this is the default invocation, not a flag.
            rc = self._run_main(d, "--wiki-data", str(data))

            self.assertEqual(rc, 0)
            # A dry run must never create the destination directory, let
            # alone write into it.
            self.assertFalse(perceptions.exists())

    def test_go_writes(self):
        # Mirror of test_dry_run_writes_nothing with --go: the file actually
        # appears, with the expected front matter.
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            _write_campaign_toml(d)
            data, perceptions = d / "data", d / "Perceptions"
            _write_page(data / "pages", "party:mira", "====== Mira ======\n\nbody\n")

            rc = self._run_main(d, "--wiki-data", str(data), "--go")

            self.assertEqual(rc, 0)
            out_file = perceptions / "party-mira.md"
            self.assertTrue(out_file.exists())
            self.assertIn("canon: perception", out_file.read_text(encoding="utf-8"))

    def test_dry_run_flag_removed(self):
        # --dry-run is gone, not deprecated: argparse rejects it loudly
        # (exit code 2) rather than silently accepting a stale script's flag
        # with a now-different meaning.
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as ctx:
                ip.main(["--wiki-data", "/nonexistent", "--dry-run"])
        self.assertEqual(ctx.exception.code, 2)

    def test_malformed_as_of_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            _write_campaign_toml(d)
            data = d / "data"
            _write_page(data / "pages", "party:mira", "text")

            rc = self._run_main(d, "--wiki-data", str(data), "--as-of", "not-a-date")

            self.assertEqual(rc, 1)

    def test_missing_namespace_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            _write_campaign_toml(d)
            data = d / "data"
            _write_page(data / "pages", "other:page", "text")  # no "party" namespace

            rc = self._run_main(d, "--wiki-data", str(data))

            self.assertEqual(rc, 1)

    def test_missing_workspace_returns_nonzero_with_a_clear_message(self):
        # --workspace pointing at a directory with no campaign.toml is an
        # error, not a search hint — resolve_workspace must not walk up.
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            data = d / "data"
            _write_page(data / "pages", "party:mira", "text")

            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = ip.main(["--workspace", str(d), "--wiki-data", str(data)])

            self.assertEqual(rc, 1)
            self.assertIn("campaign.toml", err.getvalue())


if __name__ == "__main__":
    unittest.main()

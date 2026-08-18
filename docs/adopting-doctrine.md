# Adopting packaged doctrine

`AGENTS.md` in your workspace is a copy of the one bunnyforge ships. The
package owns it: it is generic, identical in every workspace, and changes
when bunnyforge changes. `campaign-doctrine.md` beside it is yours, and no
release will ever touch it.

That split is what makes adoption cheap. Because nothing campaign-specific
lives in `AGENTS.md`, a new version is a file copy rather than a merge.

## Adopting a new version

From your workspace root, with the new bunnyforge installed:

    python3 -c "import pathlib; from bunnyforge import init; \
      pathlib.Path('AGENTS.md').write_bytes( \
        init.packaged_bytes('doctrine/AGENTS.md'))"
    git diff AGENTS.md

Read the diff — that is the whole review, and it is the reason this stays a
manual step. If your workspace pins `bunnyforge==` in `requirements.txt`,
bump it in the same commit. If you also have a `tests/test_campaign_drift.py`
that compares your copy to the installed package byte for byte, run it — it
goes green when the copy and the pin agree.

If the diff contains something you do not want, the answer is not to keep the
old bytes. Put the exception in `campaign-doctrine.md`, naming the generic
rule it displaces, and take the upstream copy whole.

## Migrating a workspace scaffolded before the split

Workspaces created before `campaign-doctrine.md` existed have their
campaign-specific rules written into `AGENTS.md` itself. Five steps, once:

1. **Find what is yours.** Diff your `AGENTS.md` against the version you
   currently pin, not against the newest one — otherwise upstream changes you
   have not adopted yet look like local edits:

       git -C /path/to/bunnyforge show vX.Y.Z:src/bunnyforge/data/doctrine/AGENTS.md > /tmp/pinned.md
       diff -u /tmp/pinned.md AGENTS.md

   What remains is your campaign's own material.

2. **Move it.** Create `campaign-doctrine.md` (copy the packaged stub with
   `python3 -c "import pathlib; from bunnyforge import init; pathlib.Path('campaign-doctrine.md').write_bytes(init.packaged_bytes('root/campaign-doctrine.md'))"`)
   and cut those sections into it. Where a section overrides a rule in
   `AGENTS.md`, say which rule, in the section itself.

3. **Register the new file.** If your `campaign.toml` lists `root_docs`
   explicitly, add `"campaign-doctrine.md"` to it — an explicit list
   overrides the packaged default, so the new entry will not reach you
   otherwise. If the key is commented out, there is nothing to do.

4. **Take the packaged `AGENTS.md` whole**, using the adopt command above.
   This performs any pending upstream adoption (and the pin bump, if you
   have one) at the same time.

5. **Turn the guard on.** If your `tests/test_campaign_drift.py` allowlists
   `AGENTS.md`, delete that entry. It exists because the file was a fork;
   after the split it is a copy again, and it can be compared exactly. Run
   the suite.

Step 5 is the point of the whole exercise. An allowlisted file is an
unguarded file, and `AGENTS.md` is the one you least want unguarded.

## Migrating to the not-canon underscore

Workspaces scaffolded before the underscore convention was defined carry
the old names: an excluded `_Archive/`, and generated output written to
bare `Sheets/`, `Reviews/`, `Export/`. Five steps, once, from the
workspace root:

1. **Make the archive canon.** `git mv _Archive Archive`, then restructure
   its contents to mirror sections (`Archive/NPCs/...`) where they do not
   already — an archived file outside any mirrored section is still walked
   and validated, just not held to the compendium-index obligation its
   section would apply. If you would rather keep a different top-level
   name, set `workspace.archive_dir` in `campaign.toml` instead of
   renaming to `Archive`; it can be anything except a `_`- or
   `.`-prefixed name, which the loader refuses outright, because that
   would exclude the archive from every walk.

2. **Mark the generated output.** For each of `Sheets`, `Reviews`, `Export`
   that exists: `git mv Sheets _Sheets` (and likewise) — or simply delete
   them; all three are rebuilt by the tools.

3. **Update `campaign.toml`** if it sets these keys explicitly:
   `sheets_dir` becomes `"_Sheets"`, and `exclude_dirs` drops `_Ignore`,
   `_Archive`, `_Templates`, `Sheets`, and `Reviews` — `_Ignore` and
   `_Templates` are the prefix rule's job now, `_Archive`'s old entry is
   subsumed by the new `archive_dir` walk (step 1), and `Sheets`/`Reviews`
   were redundant even before this: content directories are walked by an
   explicit allowlist, and neither was ever on it. Keep `docs`, `scripts`,
   `tests`, and any campaign-specific entries — that trio is now the
   packaged default for `exclude_dirs`, so an unmodified list can be
   deleted from `campaign.toml` entirely.

4. **Take the packaged `AGENTS.md` whole** (see "Adopting a new version"
   above), and merge the new ignore lines from the packaged `.gitignore`
   (`_Sheets/`, `_Reviews/`, `_Export/`) into yours — add them alongside
   whatever your workspace already ignores, rather than overwriting the
   file, since unlike `AGENTS.md` your `.gitignore` is not package-owned
   and may carry entries of your own.

5. **Run `bunnyforge review checkup`.** Newly walked archive files may
   produce front-matter findings, or `name-collisions` errors against
   their live replacements (an archived file and its replacement sharing
   a stem is now an error, not a silent ambiguity); fix or accept each —
   that review is the archive joining canon.

A workspace that skips this migration still works: old `_Archive/` is
skipped by the prefix rule exactly as `exclude_dirs` skipped it before,
and `Sheets/`, `Reviews/`, and `Export/` were never walked as content in
the first place — content directories are walked by an explicit
allowlist, not by scanning the workspace root, so an unlisted directory
was always invisible to every read tool and check. The archive simply
stays invisible until step 1 runs.

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

1. **Make the archive canon — the rename is mandatory.** If `_Archive/`
   exists: `git mv _Archive Archive`, then restructure its contents to
   mirror sections (`Archive/NPCs/...`) where they do not already — an
   archived file outside any mirrored section is still walked and
   validated, just not held to the compendium-index obligation its
   section would apply. The directory must lose its `_` prefix one way or
   another: `is_machinery` treats *any* `_`-prefixed name as never-walked,
   whatever `campaign.toml` says, so adding a config key without renaming
   the directory migrates nothing — the walk reads `config.archive_dir`
   off disk, finds no such directory (it's still sitting at `_Archive/`),
   and returns silently, so step 5's `review checkup` would show nothing
   new and the archive would still be invisible, with no error to say so.
   If you would rather use a name other than `Archive`, set
   `workspace.archive_dir` in `campaign.toml` to that name **and** rename
   the directory to match, e.g. `git mv _Archive Chronicle` alongside
   `archive_dir = "Chronicle"` — any name works except one starting with
   `_` or `.`, which the loader refuses outright for exactly the reason
   above.

2. **Clear the generated output.** `Sheets/`, `Reviews/`, and `Export/`
   have been gitignored since the first packaged `.gitignore` (and
   `Export/` is disposable even if yours predates that), so on a typical
   workspace none of them are tracked, and `git mv Sheets _Sheets` fails
   on an untracked directory with "source directory is empty". The
   simple, always-working move: for each that exists, `rm -rf Sheets`
   (and likewise for `Reviews`, `Export`) — all three are rebuilt by the
   tools on demand, so nothing is lost. Only if yours is one of the rare
   workspaces where the directory is actually tracked does `git mv Sheets
   _Sheets` work as written, preserving its history in one step.

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
   and may carry entries of your own. While you are in there, remove any
   old unprefixed `Sheets/`/`Reviews/` lines — dead patterns once step 2
   has run.

5. **Run `bunnyforge review checkup`.** Newly walked archive files may
   produce front-matter findings — up to three per file (`type`, `canon`,
   `visibility`), so a large archive can mean hundreds of findings.
   `[[review.accepted]]` entries have no wildcards (all four keys
   required, exact `file` match), so accepting each one individually does
   not scale — backfilling front matter on the archived files is the
   realistic path for most archives. `name-collisions` errors may also
   appear: a stem shared between an archived file and a live one is now
   an error, not a silent ambiguity, but not every collision involves the
   archive — some are live-vs-live pairs that predate this migration
   entirely. An acceptance entry names the alphabetically-first of the
   two colliding paths, which for a live-vs-archive pair is the one under
   `Archive/`. Fix or accept each — that review is the archive joining
   canon.

   The archive is now exported, too: `export-player` and `deploy-export`
   walk it under the same visibility rules as everything else, so a
   retired file with no `visibility` set defaults to `gm-only` and is
   skipped — but a retired **player-visible** NPC republishes under a new
   `ns:archive:...` wiki namespace, and its old `ns:npcs:...` page becomes
   an orphan. Review the first `export-player` output and the
   `deploy-export` dry run before `--go`, and check the `visibility` of
   any `status: retired` file while you're in there.

A workspace that skips this migration still works: old `_Archive/` is
skipped by the prefix rule exactly as `exclude_dirs` skipped it before,
and `Sheets/`, `Reviews/`, and `Export/` were never walked as content in
the first place — content directories are walked by an explicit
allowlist, not by scanning the workspace root, so an unlisted directory
was always invisible to every read tool and check. The archive simply
stays invisible until step 1 runs.

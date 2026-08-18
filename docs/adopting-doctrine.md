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
manual step. Then bump the `bunnyforge==` pin in `requirements.txt` in the
same commit, and run your campaign tests. `tests/test_campaign_drift.py`
compares your copy to the installed package byte for byte; it goes green when
the copy and the pin agree.

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

2. **Move it.** Create `campaign-doctrine.md` (copy the packaged stub from
   `python3 -c "from bunnyforge import init; print(init.packaged_bytes('root/campaign-doctrine.md').decode())"`)
   and cut those sections into it. Where a section overrides a rule in
   `AGENTS.md`, say which rule, in the section itself.

3. **Take the packaged `AGENTS.md` whole**, using the adopt command above.
   This performs any pending upstream adoption at the same time.

4. **Register the new file.** If your `campaign.toml` lists `root_docs`
   explicitly, add `"campaign-doctrine.md"` to it — an explicit list
   overrides the packaged default, so the new entry will not reach you
   otherwise. If the key is commented out, there is nothing to do.

5. **Turn the guard on.** If your `tests/test_campaign_drift.py` allowlists
   `AGENTS.md`, delete that entry. It exists because the file was a fork;
   after the split it is a copy again, and it can be compared exactly. Bump
   the pin and run the suite.

Step 5 is the point of the whole exercise. An allowlisted file is an
unguarded file, and `AGENTS.md` is the one you least want unguarded.

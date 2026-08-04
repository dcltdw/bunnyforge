# bunnyforge

The tool package for this workspace. Not campaign content; agents may ignore
this directory when answering questions about the setting.

Install once per machine (the repo lives in Dropbox; installs do not sync):

    pip install -e .

Each tool is its own module: `python3 -m bunnyforge.<tool>`. The workspace is
the directory holding `campaign.toml`, found in this order: the `--workspace
PATH` flag, then the `BUNNYFORGE_WORKSPACE` environment variable, then the
nearest `campaign.toml` walking up from the current directory. If none of the
three finds one, the tool prints a single `error:` line and exits 1 — there is
no fallback to the repository the package was installed from, so a tool run
outside a workspace never operates on some other campaign by accident.

The flag and the variable are both used as given: they name a workspace, they
do not seed a search, so pointing either at a directory without a
`campaign.toml` is an error rather than a hint to start walking. Two tools are
exceptions to the list above. `run_tests` takes no `--workspace` flag and
resolves by variable or walk only, since a test runner invoked from outside
its own workspace has no use case worth a flag. `init` resolves no workspace
at all — it creates the `campaign.toml` the others walk to, and takes the
destination as a positional argument instead.

## The `bunnyforge` command

Installing the package also installs a `bunnyforge` console script — a thin
front door mapping subcommands onto the module entry points:

    bunnyforge init | review | export-player | deploy-export |
              import-perceptions | build-sheets | names | test

Everything after the subcommand is passed to the tool unchanged, so
`bunnyforge review --help` is review's own help and every flag works exactly
as it does through `python3 -m`. `python3 -m bunnyforge <command>` does the
same without the install-time wrapper. The module doors above keep working
unchanged; the command is an addition, not a move. If the command is missing
after pulling this change, re-run `pip install -e .` — script wrappers are
generated at install time.

## init.py

Scaffolds a new campaign workspace: everything `review checkup` and the other
tools expect, from files the package carries.

```sh
python3 -m bunnyforge.init ~/campaigns/my-campaign --name "My Campaign"
python3 -m bunnyforge.init ./here --name "My Campaign" --namespace elsewhere
```

`--name` is required. `--namespace` defaults to a slug of the name (lowercased,
non-alphanumerics stripped) and is slugged whichever way it arrives. `PATH` must
not exist, or must be an empty directory — a file, a non-empty directory, or an
existing `campaign.toml` is one `error:` line and exit 1. There is no `--force`
and no overwrite semantics.

What it writes: `campaign.toml` (live keys for name, namespace and the culture
directory; every defaultable key present as a comment showing its default), the
8 root docs, the 10 content directories each with its README, all 16
`_Templates/` files, a starter culture at `names/cultures/vashkand.toml`, and a
minimal `.gitignore`. It does not run `git init`; version control is your move.
The result passes `review checkup` with 0 errors and 0 warnings and runs
`generate_names` with no manual fixes — asserted by
`tests/test_init.py::TestFreshWorkspacePassesTheGate`.

The files live in `src/bunnyforge/data/`, and a single `MANIFEST` in `init.py`
maps each to its destination and to the in-repo file it must stay
byte-identical to. `init` iterates it to write; the tests iterate the same one
to verify, so a generic file that drifts from its canonical source is a red
test rather than a surprise in somebody's new campaign.

## run_tests.py

The single entry point for the test suite. CI and humans invoke the same
command, so the two cannot drift.

```sh
python3 -m bunnyforge.run_tests
python3 -m bunnyforge.run_tests -v
```

Exits non-zero if any test fails. `.github/workflows/tests.yml` runs it on every
pull request and on pushes to `main`.

## The sync model

There is no bidirectional sync, deliberately. Two writers plus two directions
produces merge conflicts and drift. Instead there are two independent
one-way pipelines, and no file ever has more than one writer:

```
wiki (player namespace)  ──import──▶  Perceptions/    read-only to the GM
workspace                ──export──▶  wiki (<ns>)      read-only to players
everything else          ── never leaves the workspace ─
```

Enforce the read-only halves with DokuWiki ACLs on each pipeline's namespace.

## Why the markup converters are hand-rolled

Both pipelines translate between Markdown and DokuWiki markup using converters
written here rather than a general-purpose tool such as pandoc. That is a
deliberate decision, not an oversight, and it has explicit conditions under
which it should be reversed. Recorded here so it is not re-litigated from
scratch — and so the revisit triggers are somewhere a future maintainer will
actually look.

The three converters are small: `to_dokuwiki` (`_dokuwiki.py`),
`convert_markup` (`import_perceptions.py`), and
`markdown_links_to_wikilinks` (`_common.py`) — under 100 lines between them.

**The decision: keep them.** Three reasons, heaviest first.

1. **A converter would not replace the part that matters.** The
   safety-critical code is not markup conversion — it is the link policy:
   classify every `[[target]]`, refuse what would leak or break, never mint a
   placeholder for a typo. Pandoc has no notion of any of that. Routing
   through HTML as a pivot makes it actively worse: wikilinks would arrive as
   `<a href>` and the policy would have to be rewritten against HTML, making
   the *dangerous* code harder in order to simplify the *cosmetic* code.

2. **Stdlib-only is load-bearing here, not dogma.** This package declares zero
   runtime dependencies and its CI installs nothing. Pandoc is a system binary
   that would have to exist on every developer machine, in CI, and — for the
   importer — on the wiki host.

3. **The domain is narrow and static.** The constructs a real exported corpus
   uses are headings, bold, italic, lists, code spans and wikilinks. A
   general-purpose converter is built for a problem this pipeline does not
   have.

**The argument against, which is real.** Four defects have been found in those
converters. Three are still open, all pinned by tests so they are known
behaviour rather than surprises:

- *(fixed)* `</code>` never cleared the in-code flag, so everything after the
  first code block imported raw.
- `to_dokuwiki`'s emphasis handling is line-scoped: a `*span*` crossing a
  newline is left as literal asterisks.
- `convert_markup("====== Lopsided ===")` yields `#### === Lopsided`, because
  the `(={2,6})` group backtracks — contradicting the module's own
  pass-through-unmangled policy.
- Markdown links with nested brackets (`[a [nested] label](x)`) are invisible
  to both the converter and the link policy.

Four defects is a pattern, but a survivable one at this size.

**Revisit if any of these happen** — each is checkable, not a matter of taste:

- **The corpus starts using tables or fenced code.** Both are zero today, and
  both are where hand-rolled converters get genuinely painful. Measure with
  `grep -cE '^\s*\|' ` and `grep -cE '^\s*```' ` over the exported tree.
- **A fifth defect of the same class appears.** Four is survivable; five says
  the approach does not fit.
- **The importer becomes the priority.** It is the better candidate than the
  exporter if a switch ever happens — lower stakes, no safety policy entangled
  with it, and where the worst bug lived.

**A middle path worth knowing about, for the wiki → Markdown direction only.**
DokuWiki ships its own renderer (`bin/render.php`) on the server, and it is
authoritative — it is the real parser, not an approximation of it. If importer
fidelity ever became the priority, shelling to PHP on the wiki host would add
no new dependency to this package. It helps only the direction that reads
*from* the wiki, which is also the direction with the worse bugs.

**Not the question.** "Should we pivot through HTML?" is the weaker form of the
idea; if a tool converts Markdown to DokuWiki directly, an HTML hop is lossy
for nothing. The real question is only ever "adopt an external converter?".
One fact was never confirmed when this was decided and should be checked before
relying on it: whether pandoc has a DokuWiki *reader* at all. It is believed to
have a DokuWiki *writer*.

## import_perceptions.py

Exports player-authored wiki pages into `Perceptions/`, marked
`canon: perception`. Never writes to the wiki.

Reads DokuWiki's flat files rather than its API, because `data/attic/` keeps
every historical revision — which makes exact session-boundary snapshots free.

```sh
python3 -m bunnyforge.import_perceptions --wiki-data /path/to/dokuwiki/data
python3 -m bunnyforge.import_perceptions --wiki-data ... --namespace party
python3 -m bunnyforge.import_perceptions --wiki-data ... --as-of 2026-03-14
```

`--as-of YYYY-MM-DD` captures each page as it stood on that date, suffixing the
filename so snapshots accumulate rather than replace each other. Existing files
are skipped unless `--overwrite` is passed.

## export_player.py

Writes player-safe copies of content files to `Export/` (gitignored,
generated, safe to delete and regenerate).

`gm-only` files are skipped entirely — not written, not even by name. For
`player-visible` files, the standard GM meta-sections (`## Design intent`,
`## Balance notes`, `## Playtest log`) are stripped, heading-level aware, so
a nested sub-heading under one of them is dropped too. `mixed` files are
split on the `## GM notes` separator and only the portion above it is
exported; a `mixed` file *without* that separator cannot be split safely and
is skipped entirely, the same as `gm-only`, rather than guessed at. HTML
comments are stripped everywhere.

```sh
python3 -m bunnyforge.export_player
```

Prints a summary: files exported, files skipped as `gm-only`, GM sections
stripped. Exits non-zero if any `mixed` file was skipped for lacking the
separator, since that indicates a handout that needs fixing.

`Handouts/` is an ordinary content directory: handouts export like any other
player-visible file, to `<ns>:handouts:<stem>`, and are subject to the same
wikilink policy. There is no separate handout publisher.

## deploy_export.py

Renders `Export/` into a DokuWiki page tree — content pages in DokuWiki markup
plus include-wrappers — ready to be copied onto the wiki.

    python3 -m bunnyforge.export_player
    python3 -m bunnyforge.deploy_export --render-only --staging /tmp/stage

Each exported file becomes two pages: `<ns>:export:<dir>:<stem>` holding the
converted content, and `<ns>:<dir>:<stem>` holding two Include directives —
one for that content, one for `<ns>:players:<dir>:<stem>`, which players own
and this pipeline never writes. `<ns>:main` is hand-written on the wiki and
is never wrapped or overwritten. `<ns>` is `campaign.namespace` from
`campaign.toml`.

Transport to the server is not implemented yet; `--render-only` is currently
required.

`--staging` must be a fresh or empty directory. A pre-existing, non-empty
staging tree is refused rather than rendered into, since a page dropped from
this run (e.g. flipped to `gm-only` since the last run) would otherwise
survive untouched from the previous run while this run still reports success.

**Known limitations.** `to_dokuwiki`'s emphasis handling (`*text*`, `**text**`)
is line-scoped: an emphasis span crossing a line break is left as literal
asterisks rather than converted. There is no fenced-code or table handling —
both pass through unconverted.

Wikilinks in exported content are rewritten to point at the wrapper page —
`[[table-rules]]` becomes `[[<ns>:mechanics:table-rules|table-rules]]` — so
following a cross-reference lands on the composed page rather than the raw
content half. Targets are resolved by stem or front-matter alias, using the same
resolver `review.py` uses, and `|label` / `#anchor` are preserved.

**Every** `[[...]]` in an exported body is subject to this policy, including
ones inside backticks or a ``` fence. Markup does not protect a link: DokuWiki
has no fence syntax and `to_dokuwiki` passes the markers through verbatim, so a
"fenced" link renders as a live link on the player wiki. Exempting it would let
a link to a `gm-only` doc publish silently, unreported, with a zero exit.

Markdown inline links are normalised to wikilinks (`[the rules](table-rules)`
becomes `[[table-rules|the rules]]`) *before* the policy runs, so they are
subject to it too. Converting them afterwards — which is what `to_dokuwiki`
does — would publish a live link the policy never inspected, including one
naming a `gm-only` document.

A link is refused, with a non-zero exit, when it points at a workspace file that
was not exported (`unexported` — a `gm-only` doc), at nothing at all
(`unresolved` — a typo or a deleted file), or at several files at once
(`ambiguous` — two files share a stem or alias, so rewriting it would mean
guessing which one was meant; disambiguate by renaming or by dropping the
duplicate alias). The first is usually a content problem rather than a link
problem — prose that tells a player to "see `[[open-questions]]`" should not be
player-visible in the first place.

Links that name no workspace file at all pass through untouched and are never
refused: external URLs, interwiki shortcuts (`[[wp>Seoul]]`), anchor-only links,
empty targets, and bare content-directory names such as `[[Mechanics]]`.
`review.py`'s wikilink check treats exactly the same set as valid — both call
`_common.is_pass_through_target`, so the checkup and the exporter cannot
disagree about what counts as a broken link *target*.

That agreement is about targets only, not about which links get inspected in
the first place. `review.py`'s `extract_wikilinks` strips fenced and inline
code *before* scanning for links, so a markdown or wikilink written inside
backticks or a ``` fence passes the checkup clean. The exporter applies the
same policy to every link regardless of surrounding markup (see above), so a
link the checkup ignored can still be refused, or silently published, by
`deploy_export.py`. The exporter is the stricter of the two — a clean checkup
does not guarantee a clean export.

    python3 -m bunnyforge.deploy_export --render-only --staging /tmp/stage \
        --create-empty-placeholders

`--create-empty-placeholders` keeps `unexported` links and writes a zero-byte
page at the target, which DokuWiki counts as existing, so the link resolves
instead of offering a create-link. It is an escape hatch for publishing before
the prose is fixed, not the steady state. It does **not** apply to `unresolved`
or `ambiguous` targets — a typo stays fatal in both modes.

Note what a placeholder exposes. The page is empty, but its ID is derived from
the unexported file's path, so `NPCs/the-mole.md` mints `<ns>:npcs:the-mole`
— a `gm-only` **filename**, visible in the player wiki's index and search, even
though `export_player.py` otherwise guarantees such a file is "not exported in
any form, not even their filename appears". The run summary therefore lists
every placeholder page ID it wrote; read that list before copying the staging
tree onto the wiki.

## review.py

Runs a named suite of workspace checks on demand.

    python3 -m bunnyforge.review checkup          # terminal report (plain text)
    python3 -m bunnyforge.review checkup --html   # also writes Reviews/checkup.html

The `checkup` suite runs five mechanical checks: visibility-audit, front-matter,
wikilinks, compendium-completeness, and reveal-when consistency. Exit code is
non-zero if any check produces an error. Adding a check: write a
`check_*(files, workspace)` function, register it in `CHECKS`, and add its name
to a suite in `SUITES`. A check needing the whole `Workspace` (for its config)
goes in `_NEEDS_WORKSPACE`; one needing a DokuWiki install root goes in
`_NEEDS_WIKI`. The agent-judgment half of the checkup lives in
`checks/checkup.md`.

### The `wiki` suite

    python3 -m bunnyforge.review wiki --wiki-root /path/to/dokuwiki

Asserts configuration invariants of a **live DokuWiki install** — the only
checks here that look outside the workspace. `--wiki-root` is the installation
root, the directory holding `conf/` and `lib/`. (Note that is *not* the same
path as `import_perceptions`'s `--wiki-data`, which points at `data/`.)

**Run it after every DokuWiki upgrade.** An upgrade is precisely when this
drifts, and the two worst failures on record were both config drift that no
unit test could have caught:

- `useacl` must be enabled **and set in `conf/local.php`**, not
  `conf/dokuwiki.php`. Checking the value alone is not enough: upgrades
  overwrite `dokuwiki.php`, so a correct setting in the wrong file is one
  upgrade away from silently disabling access control entirely.
- **Every namespace granting to a group must also carry an `@ALL` or `@user`
  rule of its own.** Without one, an account outside that group falls through
  to a broader rule and can end up with more access than intended — while
  anonymous spot-checks look perfectly clean, because guests are denied
  correctly. Stated as one rule over whatever scopes exist, so a newly added
  namespace is covered by default.
- The `include` plugin must be installed **and** enabled; the entire wrapper
  page design is composed of its directives.
- `useheading` must be set to something truthy, or wrapper pages display raw
  page IDs instead of their included heading.

`checkup` never includes these checks, so CI — which has no wiki — is
unaffected. Everything is read from the install's files directly; there is no
network access and no dependency beyond the standard library.

**What this suite deliberately does not assert:** that GM namespaces resolve to
`NONE` for specific player groups. That is an *effective-permission* question
needing DokuWiki's own resolution order (most-specific-first, user rules
beating group rules, maximum across matching group rules), and it is the one
invariant that cannot be stated without naming particular namespaces and
groups. Reimplementing that resolution risks the checker and the wiki
disagreeing, which is worse than not checking; the alternative is shelling out
to DokuWiki's `auth_aclcheck`, which needs PHP and a real install rather than a
readable copy. The universal denial rule above catches the same class of defect
without either cost.

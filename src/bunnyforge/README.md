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

What it writes — 38 files, every one of them a `MANIFEST` entry: `campaign.toml`
(live keys for name, namespace and the culture directory; every defaultable key
present as a comment showing its default), the 8 root docs, the 10 content
directories each with its README, the 12 `_Templates/` files, a starter culture
at `names/cultures/vashkand.toml`, a minimal `.gitignore`, the 3-file `tests/`
scaffold, and 2 files under `.vscode/`. It does not run `git init`; version
control is your move. The result passes `review checkup` with 0 errors and 0
warnings and runs `generate_names` with no manual fixes — asserted by
`tests/test_init.py::TestFreshWorkspacePassesTheGate`.

The `.vscode/` pair ships **inert**: `settings.json` carries a colouring block
that tints `.md` files by their front-matter `visibility`, disabled line by line
behind a reserved `//- ` prefix between two `bunnyforge:` marker comments, and
`extensions.json` recommends the extension that renders it. A scaffolded
workspace therefore looks exactly like one without the files until someone
deletes the prefixes. The markers and the off-prefix are a frozen format —
`tests/test_init.py::TestVscodeScaffold` pins them, and parses the file as
strict JSON in both toggle states.

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

Follows the package-wide dry-run convention: the default run only reports what
it would write; pass `--go` to actually write. **Breaking, pre-1.0:** earlier
versions took a `--dry-run` flag with the opposite default (writing unless
`--dry-run` was passed). `--dry-run` no longer exists — a bare invocation is
now the rehearsal, and `--go` is what writes.

```sh
python3 -m bunnyforge.import_perceptions --wiki-data /path/to/dokuwiki/data          # dry run
python3 -m bunnyforge.import_perceptions --wiki-data ... --go
python3 -m bunnyforge.import_perceptions --wiki-data ... --namespace party --go
python3 -m bunnyforge.import_perceptions --wiki-data ... --as-of 2026-03-14 --go
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
plus include-wrappers — and deploys it to the wiki over DokuWiki's JSON-RPC
API. Three invocations:

| invocation | what it does |
|---|---|
| `deploy_export.py` | **Dry run (the default).** Render, fetch the wiki's current state, print the full deploy plan — including pages held back for drift. Writes nothing to the wiki, makes no manifest change. |
| `deploy_export.py --go` | Same plan, then perform the writes it calls for and update the manifest. |
| `deploy_export.py --render-only --staging PATH` | Render only, offline. No `[wiki]` config and no token needed; unchanged from before this pipeline could deploy at all. |

    python3 -m bunnyforge.export_player
    python3 -m bunnyforge.deploy_export                          # dry run
    python3 -m bunnyforge.deploy_export --go                     # deploy
    python3 -m bunnyforge.deploy_export --render-only --staging /tmp/stage
    python3 -m bunnyforge.deploy_export --go --overwrite <ns>:npcs:<stem>

`--staging` is optional in the default and `--go` modes — a temporary
directory is used and removed at exit, so a stale tree can never be pushed —
and required with `--render-only`, where the staged tree is the deliverable.
Whenever `--staging` is given, it must be a fresh or empty directory: a
pre-existing, non-empty staging tree is refused rather than rendered into,
since a page dropped from this run (e.g. flipped to `gm-only` since the last
run) would otherwise survive untouched from the previous run while this run
still reports success.

`--overwrite <page-id>` (repeatable) writes a held-back page anyway and
re-baselines it; see "Drift" below. It only takes effect with `--go`.

Each exported file becomes two pages: `<ns>:export:<dir>:<stem>` holding the
converted content, and `<ns>:<dir>:<stem>` holding two Include directives —
one for that content, one for `<ns>:players:<dir>:<stem>`, which players own
and this pipeline never writes. `<ns>:main` is hand-written on the wiki and
is never wrapped or overwritten. `<ns>` is `campaign.namespace` from
`campaign.toml`.

### Connecting to the wiki

Any mode but `--render-only` needs a `[wiki]` table in `campaign.toml` naming
the wiki's **base URL** — the client appends `lib/exe/jsonrpc.php` itself, so
do not include it:

```toml
[wiki]
url = "https://<wiki>"
```

(The same table can also carry `install_root`, an unrelated key read only by
the `wiki` review suite below — a local filesystem path, never sent over the
wire.)

`https://` is required. A plain `http://` URL is refused — the token would
cross the wire in clear — except for `localhost`, `127.0.0.1`, or `::1`,
where a local test install has nothing to leak.

That check can only vet the URL you configured, so **redirects are refused
too**, rather than followed. A wiki whose canonical URL redirects (apex to
`www`, or an `https` vhost that `301`s to `http`) would otherwise carry the
`Authorization` header onto the redirect target: `urllib` forwards it even
across a host change. Point `[wiki] url` at the wiki's canonical base URL —
the JSON-RPC endpoint has no legitimate reason to redirect.

Both credential headers are sent on every call: `Authorization: Bearer
<token>` and `X-DokuWiki-Token: <token>`. Some hosts run PHP as CGI/FastCGI,
which makes Apache strip `Authorization` before PHP ever sees it;
`X-DokuWiki-Token` is not special-cased that way and is what actually works
on such hosts, while keeping `Authorization` preserves compatibility with any
build that only honours that one. See the troubleshooting note below if
every call fails with `-32603`.

It also needs a DokuWiki API token, resolved in order:

1. the `BUNNYFORGE_WIKI_TOKEN` environment variable, or
2. a single line in `<workspace>/.bunnyforge/wiki-token`.

The token file is refused, with a `chmod 600 <path>` instruction, if it is
readable by group or world — a wiki credential must be private. Its
directory is checked too: a `.bunnyforge/` writable by group or world is
refused with `chmod 700 <path>`, because anyone who can write the directory
can replace the credential inside it. Create the token on the wiki itself:
log in as the deploy user, open its profile, and generate an API token there.

**Troubleshooting: every call fails with `-32603`.** The wiki received no
usable credential at all. The likely cause is the host running PHP as
CGI/FastCGI, which makes Apache strip the `Authorization` header before PHP
ever sees it — a hosting-config problem, not a bunnyforge bug. bunnyforge
already sends `X-DokuWiki-Token` alongside `Authorization`, which usually
survives on such hosts; if `-32603` persists, check the token itself and that
the API user is within `$conf['remoteuser']`.

### The manifest

`<workspace>/.bunnyforge/wiki-manifest.json` records the hash of what this
tool last wrote for every page it deployed. It is **committed** to the
campaign repo, not gitignored: deploying from a second machine then sees the
true baseline, and the post-deploy diff is reviewable in the repo's own git
history like any other change.

### Drift

A staged page is **held back**, never silently overwritten, for any of three
reasons:

- **drift** — the page changed on the wiki since the last deploy: the wiki's
  current text no longer matches the hash this tool recorded, and it also
  differs from what would now be deployed.
- **drift-manual-era** — this page has no baseline in the manifest at all,
  yet the wiki's current text differs from what would be deployed. This is
  what fires on the **first** deploy against a wiki that already has content
  from the old manual-copy workflow, or against any page edited by hand
  outside this tool: with no recorded baseline the tool cannot tell what
  changed, so it refuses to guess and holds the page back rather than
  overwriting a page it never wrote itself.
- **deleted-on-wiki** — the page is still staged (its source file is still
  exported), but a human deleted the wiki page since the last deploy.
  Recreating it would clobber that deletion decision, so it is held back
  instead. This is distinct from an **orphan** (below): an orphan is a
  manifest entry that has dropped *out of* the staged set — the source file
  was removed, or its visibility changed — whereas `deleted-on-wiki` is a
  page still being staged whose *wiki* copy is the one that's gone.

For `drift` and `drift-manual-era` the plan reports a unified diff against
the staged target, and the wiki's current text is written to
`<workspace>/.bunnyforge/wiki-drift/` for manual merge (recreated from empty
on every planning run, so a page that stops drifting leaves no stale copy
behind); `deleted-on-wiki` has no wiki text to diff or copy. The resolution
is the same for all three: either pull the wiki edit into the workspace
source — the next render then matches and the drift disappears — or re-run
with `--overwrite <page-id> --go` to clobber it and re-baseline.

The same guarantee holds **within** a single `--go` run. The plan fetches
every page up front, so on a large campaign tens of seconds pass between a
page being read and being written. Each page is therefore re-read immediately
before its save, and a page whose wiki text changed in that window is
reported `SKIPPED` and left alone — the run exits non-zero and the next plan
reports it as ordinary drift, with a diff. This applies to `--overwrite`
pages too: `--overwrite` consents to clobbering the diff the plan printed,
and an edit that landed after that diff was never reviewed.

### Orphans

A manifest entry no longer staged (the source file was deleted, or flipped
to `gm-only`) is **reported as an orphan, never deleted** — removing the wiki
page is a manual act this tool does not automate. If the page was already
deleted on the wiki by hand, it is reported as resolved instead and drops
from the manifest on `--go`.

The exit code is non-zero if anything was held back or any orphan was
reported, in both dry-run and `--go` modes — a clean plan is the only way to
see exit 0.

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

### Live wiki check

`tests/live_wiki_check.py` is an opt-in, human-invoked script that exercises
this transport against a **real** DokuWiki install — the same kind of
confidence `tests/check_portability.py` gives a culture author, but for the
deploy transport. It is not a `unittest` test: `unittest discover`'s default
pattern is `test*.py`, so this file is never collected, and it **never runs
in CI or the normal test suite** — every other test in this suite is
offline by design, and that posture never changes.

```sh
PYTHONPATH=src python3 tests/live_wiki_check.py --workspace PATH            # read-only checks
PYTHONPATH=src python3 tests/live_wiki_check.py --workspace PATH --go       # full battery, writes to the wiki
```

Without `--go` it runs three read-only checks (the auth handshake, the
missing-page contract, and the protected-page guard) and writes nothing.
With `--go` it also deploys, edits, drift-tests, `--overwrite`s, and
resume-after-crash-tests a small probe page under `<ns>:live-wiki-check:` —
using its own temporary workspace and manifest, never the real
`<workspace>/.bunnyforge/wiki-manifest.json` — probes two RPC edge cases
(`core.savePage` refusing an empty page; the `~~NOTOC~~` placeholder body
saving as non-empty), and publishes a hand-built pair of cross-linked pages
to confirm that a rewritten absolute link — `[[<ns>:<dir>:<stem>|label]]`,
the form `deploy-export`'s link rewriter emits — resolves from the wiki
root when followed from *inside* an included page, the shape every
reader-facing page actually takes (via `core.getPageHTML`; the check
reports itself SKIPPED rather than failing if that RPC method is absent on
an older DokuWiki release). Every write check reuses the same handful of
stable page IDs, so running it repeatedly updates those same pages in place
rather than piling up new ones. **This tool cannot delete wiki pages**, so
neither can this script — it prints the page IDs it touched at the end, and
removing them, if ever wanted, is a manual act on the wiki itself.

`--workspace` is optional: `--wiki-url URL --namespace NS`, given together,
run the same checks with no campaign workspace and no `campaign.toml` at
all — this is how CI runs it (see below). The two must be given together;
either alone is refused with an instructional error. The credential still
resolves the same way as everywhere else in this package —
`BUNNYFORGE_WIKI_TOKEN` first, else `<workspace>/.bunnyforge/wiki-token` —
except that with no `--workspace` there is no token file to fall back to,
so the environment variable is the only option; if it is unset, the script
fails naming it.

```sh
BUNNYFORGE_WIKI_TOKEN=... PYTHONPATH=src python3 tests/live_wiki_check.py \
    --wiki-url https://<wiki> --namespace <ns>            # read-only checks
BUNNYFORGE_WIKI_TOKEN=... PYTHONPATH=src python3 tests/live_wiki_check.py \
    --wiki-url https://<wiki> --namespace <ns> --go       # full battery
```

#### CI canary

`.github/workflows/live-wiki-canary.yml` runs this script's full battery
(`--go`) weekly against a real wiki, using three repository secrets:
`WIKI_URL`, `WIKI_TOKEN` (passed to the script as `BUNNYFORGE_WIKI_TOKEN`),
and `WIKI_NAMESPACE`. It is triggered by `schedule` and `workflow_dispatch`
only — never `push` or `pull_request`, since GitHub withholds secrets from
forked pull requests, which would make a secrets-requiring check
permanently red on outside contributions. If any of the three secrets is
unset, the job prints a notice naming them and exits successfully — a red
check caused by missing configuration would be noise, not signal. The repo
has no branch protection, so this job is deliberately not a required check
either way: it is a canary, meant to fail loudly when it fails, not a merge
gate, and it is not a substitute for the unit suite above, which is.

Security notes for whoever configures the secrets: issue a **separate**
DokuWiki API token for CI rather than reusing a human's local one, so it
can be revoked independently without disturbing anyone's own setup, and
keep the deploy user's ACL as narrow as this job actually needs (write
access to its own `live-wiki-check` sub-path is enough — it never touches
anything else).

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

### Accepting a finding

A check that reports a finding the operator has already judged and accepted
reports it forever, exits non-zero on every future run, and eventually trains
the operator to stop reading the summary — at which point the next *real*
finding gets lost in the noise. Record that judgement in `campaign.toml`:

```toml
[[review.accepted]]
check  = "wiki-acl"
file   = "conf/acl.auth.php"
match  = "<ns>:* grants to a group"
reason = "Intentional: account creation is restricted, so any logged-in account is a small trusted set."
```

All four keys are required, and `reason` must be non-empty — `load()` refuses
an entry missing either, naming the offending entry, because an acceptance
with no rationale is indistinguishable from a mistake six months later. A
finding is accepted when `check` and `file` match exactly and `match` is a
**substring** of the finding's message (substring rather than the whole
message, so a reworded but otherwise-unchanged message doesn't silently
un-accept a judgement).

**This accepts one specific finding, never a check.** Only a finding whose
check, file, and message substring all match is excluded; a *different*
finding from the same check — a new file, a new scope, a new namespace — still
reports and still fails the run. Wholesale-silencing `wiki-acl` would hide the
next namespace that gets it wrong; the unit of acceptance is deliberately the
finding, not the check.

Accepted findings never vanish: they're excluded from the exit code and from
each check's issue count, but listed in their own `Accepted` section of both
the terminal and HTML report, each with its recorded reason — so the decision
stays visible instead of quietly disappearing. If one acceptance's `match`
turns out to cover more than one finding this run, that finding count is
reported alongside it, so an operator can see a loose `match` covering more
than intended. And if an acceptance matches nothing this run — the config it
described has since changed — it's reported as a `warn`-severity finding
under a synthetic `review-accepted` check, so a stale judgement surfaces
rather than sitting invisibly forever; being `warn` rather than `error`, it
never reddens the run on its own.

The mechanism applies to every suite (`checkup`, `wiki`, and any future one),
not just `wiki` — one mechanism is easier to explain than a per-suite variant.
An acceptance whose `check` belongs to a suite that isn't currently running is
simply not evaluated (neither matched nor reported stale) — a `wiki-acl`
acceptance sitting unused during a `checkup` run doesn't spuriously warn.

### The `wiki` suite

    python3 -m bunnyforge.review wiki --wiki-root /path/to/dokuwiki

Asserts configuration invariants of a **live DokuWiki install** — the only
checks here that look outside the workspace. `--wiki-root` is the installation
root, the directory holding `conf/` and `lib/`. (Note that is *not* the same
path as `import_perceptions`'s `--wiki-data`, which points at `data/`.)

That path does not change between runs, so rather than retyping it every time,
name it once in `campaign.toml`:

```toml
[wiki]
install_root = "/path/to/a/wiki/copy"
```

`--wiki-root` still wins when both are given. Either way the value is
expanded (`~`) and resolved the same way before use. Neither supplied is an
error naming both routes; this key does not acquire the copy for you — it
must already exist on disk, however obtained (a mount, an unpacked backup, a
synced folder).

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
- If the remote (JSON-RPC) API is enabled, it must be **scoped**: `remote`
  itself must be set in `conf/local.php`, not the upgrade-overwritten
  `conf/dokuwiki.php`, and `remoteuser` must name the deploy user rather than
  being left unset — an unset `remoteuser` lets every wiki account call the
  API. A disabled remote API is a legitimate secure state and raises nothing;
  this only fires once `deploy-export` is meant to be usable.

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

### Is the snapshot fresh? (`wiki-snapshot`)

The suite above checks a **copy**, and nothing connects that copy to the wiki
it came from. A stale copy checks last month's configuration and reports
nothing wrong — the most dangerous kind of pass, because it looks identical to
a genuinely clean run.

**And the copy cannot date itself.** `rsync -a` preserves the remote's
mtimes, so every timestamp inside it — files and directories alike —
describes the *wiki's* history, not the copy's. A snapshot pulled ten minutes
ago and one pulled in March read identically by their own file times.

The `wiki-snapshot` check instead reads a marker the fetch script writes at
the snapshot root: `<install_root>/.bunnyforge-snapshot-fetched-at`, an
ISO-8601 UTC timestamp (`date -u +"%Y-%m-%dT%H:%M:%SZ"`, e.g.
`2026-08-06T00:21:01Z`). Every finding it produces is `warn`, never `error` —
the point is to stop a stale pass from looking clean, not to redden a run:

- **Marker absent** — a copy obtained by hand, a mount, an unpacked backup —
  warns that the snapshot's age is unknown, honestly rather than
  accusingly: absence is a legitimate way to get a copy.
- **Marker present but older than the threshold** warns, naming the age in
  days and the threshold.
- **Marker malformed or unparseable** warns saying so.
- **Marker present and fresh** produces no finding.

A stale or unknown-age snapshot never changes the exit code by itself — only
an `error`-severity finding does that, and this check never produces one. The
threshold defaults to 30 days and is configurable:

```toml
[wiki]
snapshot_max_age_days = 14
```

Must be a positive integer; refused instructionally otherwise (a wrong type,
or a value ≤ 0, at `campaign.toml` parse time).

### Refreshing the snapshot (`--fetch-latest`)

    python3 -m bunnyforge.review wiki --fetch-latest

Two commands where one would do is exactly how a stale snapshot happens:
forgetting to refresh the copy before reviewing. `--fetch-latest` runs a
**configured command** and refuses to review if it fails:

```toml
[wiki]
fetch_command = "./scripts/fetch-wiki-snapshot.sh"
```

**bunnyforge never learns what ssh is.** It runs whatever the operator
configured, waits, and checks the exit status — rsync, scp, sftp, a mount
refresh, anything. That keeps the tool transport-agnostic, and keeps it
useful to someone on a hosted wiki with no shell access, who simply does not
set `fetch_command` and does not pass the flag.

Mechanically: the command is split with `shlex.split` and run with
`shell=False` — never a shell — from the **workspace root**, so a relative
path like `./scripts/...` resolves the way the operator wrote it. Its
stdout and stderr are always printed: the whole point of this flag is that
the fetch owns its own self-labelled error messages, so swallowing them would
defeat it. A non-zero exit means the review is refused (a non-zero exit,
`--html` not written, the suite never runs) with a message making clear the
*fetch* failed, not a check — exactly what `fetch && review` does in a shell,
and equally clear about which half failed.

`--fetch-latest` with no `fetch_command` configured is refused
instructionally, naming the key and the TOML shape, before anything runs.
It is also refused on a suite that does not use a wiki root (`checkup`) —
there being nothing there for it to refresh.

**This is a code-execution surface.** `fetch_command` is a shell command
`campaign.toml` names and `review.py` executes. It is the operator's own
file, at the same trust level as a `Makefile` or an `npm` script — not
sandboxed, not vetted — and should be treated that way rather than
discovered.

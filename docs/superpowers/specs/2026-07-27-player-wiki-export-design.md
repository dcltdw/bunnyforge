# Player-facing wiki export (design)

> **Partially superseded (2026-08-05):** the transport half of this design
> (sequencing steps 6–8: rsync, `receive_export.sh`, `indexer.php`, the
> server-side `manifest.json`) is superseded by
> [2026-08-05-deploy-export-rpc-transport-design.md](2026-08-05-deploy-export-rpc-transport-design.md),
> which replaces it with DokuWiki's JSON-RPC API. The render half — namespace
> layout, wrapper format, ACL design, wikilink rewriting, leak-test posture —
> is shipped and untouched. The drift guarantee carries over verbatim; the
> open absolute-link verification item carries into the new spec's
> first-deploy checklist.

> **Provenance:** a scrubbed copy of a development record from the
> private campaign repository where this tool was first built. Campaign
> identifiers are neutralised throughout; the verbatim original stays in
> that private repo. Staged for publication 2026-08-02.

**Date:** 2026-07-27
**Status:** **render half implemented and shipped** (Plan A `ecdabe4`; wikilink
rewriting `a10f3a8`, issue #17; markdown-link policy #23, issue #21). Transport
(sequencing steps 6–8) is **not built** — `deploy_export` still refuses anything
but `--render-only`. See "Sequencing" for what is done and what is not.

## Purpose

Publish player-safe workspace content to the campaign DokuWiki, so players can
read it in the place they already read campaign material, annotate it, and have
those annotations flow back into the workspace.

`scripts/export_player.py` (PR #15) already produces the content half: it walks
the workspace and writes player-safe Markdown to `Export/`. This design covers
everything downstream of that — converting to DokuWiki markup, composing pages,
getting them onto the server, and keeping the two sides from clobbering each
other.

`export_player.py` itself is unchanged by this work. It stays a pure content
generator that knows nothing about DokuWiki.

## Relationship to the existing sync model

`src/bunnyforge/README.md` states the sync model as two one-way pipelines under one
rule: **no file ever has more than one writer.** This design adds a third
pipeline and preserves the rule.

```
wiki (player namespace)  ──import──▶  Perceptions/        read-only to the GM
Handouts/                ──publish──▶ wiki (published)    read-only to players
workspace                ──export───▶ wiki (campaign ns)  read-only to players   NEW
everything else          ── never leaves the workspace ─
```

The sync-model diagram in `src/bunnyforge/README.md` must be updated as part of this
work; it currently says two pipelines.

## Target environment

Verified by direct inspection on 2026-07-27:

| | |
|---|---|
| Host | `<gm-user>@<host>` (FreeBSD, shared hosting), key-based ssh |
| DokuWiki root | `~/<wiki-dir>/dokuwiki` (symlink → `public_html/<wiki-domain>/`) |
| Version | 2026-07-14a "Mort" |
| PHP CLI | 8.2.32 |
| Indexer | `bin/indexer.php` present |
| Backup dir | `~/backup/` exists |
| Include plugin | **not installed** — a prerequisite, see Ops prerequisites |

Configuration note: all site customisations live in `conf/local.php`, and
`conf/dokuwiki.php` is stock. Nothing in this design should ever write to
`conf/dokuwiki.php` — upgrades overwrite it.

## Namespace layout

Three namespaces, each with exactly one writer. `<ns>` throughout this
document is the campaign's base namespace (today, the value of
`[campaign].namespace` in `campaign.toml`):

```
<ns>:<dir>:<stem>               wrapper — pure includes.      Written by deploy.
<ns>:export:<dir>:<stem>        exported content.             Written by deploy.
<ns>:players:<dir>:<stem>       player annotations.           Written by players.
```

The wrapper exists so that `export_player.py`'s output stays pure content. Wiki
composition — what a reader-facing page is assembled *from* — is a separate
concern living in a separate layer. It also means a future third source can be
included without touching the exported content.

### Page ID mapping

`<Dir>/<stem>.md` → `<ns>:export:<dir>:<stem>`, directory lower-cased.

```
Mechanics/species-house-rule.md
  wrapper   <ns>:mechanics:species-house-rule
  content   <ns>:export:mechanics:species-house-rule
  players   <ns>:players:mechanics:species-house-rule
```

DokuWiki lower-cases page IDs and accepts hyphens, so the workspace's kebab-case
stems map across unchanged. On disk: `data/pages/<ns>/export/mechanics/species-house-rule.txt`.

Two guards:

- **Refuse to deploy** if any content directory is named `export` or `players` —
  it would collide with the reserved sub-namespaces.
- **Never generate a wrapper for `<ns>:main`.** It is hand-written prose that
  exists nowhere in the workspace and must not be clobbered.

### Wrapper format

The wrapper is *only* includes:

```
{{page><ns>:export:mechanics:species-house-rule}}
{{page><ns>:players:mechanics:species-house-rule}}
```

The page title lives in the exported content, where it comes from the source
file's H1 — one fact, one writer. A title change is then an ordinary content
change, not a special wrapper change. `publish_handouts.py`'s
`strip_leading_heading()` is therefore **not** used on this path; the H1
converts to `====== ... ======` and stays with its content.

When `<ns>:players:...` does not exist, the Include plugin renders a
create-link, which is how a player starts annotating a page — no commented-out
placeholder needed.

### ACLs

DokuWiki resolves most-specific-first, so the split needs two rules on top of
existing global ones:

| Scope | Group | Permission |
|---|---|---|
| `<ns>:*` | `@ALL` | None (0) |
| `<ns>:*` | `@user` | Read (1) |
| `<ns>:*` | `@<ns>players` | Read (1) |
| `<ns>:*` | `@<ns>gm` | Delete (16) |
| `<ns>:players:*` | `@<ns>players` | Delete (16) |
| `<ns>:players:*` | `@<ns>gm` | Read (1) |

DokuWiki levels are cumulative: `0` none, `1` read, `2` edit, `4` create,
`8` upload, `16` delete. Where several group rules match at the same
specificity, the **maximum** wins. Players get full CRUD in their own namespace
and read everywhere else — so `@<ns>players` is the only group with any edit
right, and that right is scoped to the one namespace they own.

The `<ns>:* @user 1` line matters: a global `* @user 2` rule grants edit to
any logged-in user, and accounts outside `@<ns>players` would otherwise fall
through to it. This was verified empirically with `auth_aclcheck` against a real
account outside the group, not reasoned about.

**The GM is read-only on `<ns>:players:*`** — players own their annotations
outright. `import_perceptions.py` reads the flat files directly, so this costs
the pull-back pipeline nothing.

**The GM is not a member of `@<ns>players`.** The group name means what it
says. Consequently **every `<ns>:*` rule granting `@<ns>players` must have
a matching `@<ns>gm` rule**, or the GM silently loses that access; a comment
in `conf/acl.auth.php` records this.

Naming: `@<ns>players` pairs with `@<ns>gm`. The older bare `@<ns>` was
ambiguous — it read as "everyone in the campaign" while being used as "the
players" — which matters in a file that governs who can read GM material.
This campaign is the only one on the wiki whose ACLs encode a role split, so
`@<other1>` and `@<other2>` keep their bare campaign names.

`<other1>:*`, `<other2>:*`, `main`, and the global `*` rules are left untouched. The
global `* @user 2` rule governs unrelated campaigns and is out of scope.

`<ns>gm:*` gained `@ALL 0` and `@user 0`. It previously had only an
`@<ns>gm` grant, so every logged-in account outside that group fell through
the global `* @user 2` and had **edit** on the entire GM namespace. Guests were
unaffected, which is why anonymous checks looked clean. Out of scope for the
export itself, fixed alongside it.

## Wikilink rewriting

Amendment for GitHub issue #17. The original design did not consider wikilinks
at all.

`[[target]]` is live DokuWiki syntax, so a workspace wikilink survives
conversion and becomes a real link on the wiki. Two consequences, both verified
by rendering against the live install rather than assumed:

- **Code spans do not protect links.** The workspace writes cross-references as
  `` `[[table-rules]]` ``, which converts to `''[[table-rules]]''`. DokuWiki
  still linkifies inside `''…''` — it emits `<code><a href=…>` — so backticking
  changes the styling and nothing else.
- **Bare targets resolve relative to the containing namespace.** From
  `<ns>:export:mechanics:*`, `[[table-rules]]` resolves to
  `<ns>:export:mechanics:table-rules` — the raw content page. A reader
  following a cross-reference therefore steps outside the wrapper and loses the
  `<ns>:players:*` half, defeating the composition the wrapper exists for.

### Resolution

Every `[[target]]` in an exported body is resolved with the **shared resolver in
`review.py`** (`_split_aliases`, `_aliases_for`, `_resolve_target`, added in
PR #12), which matches file stems *and* front-matter aliases. Reusing it is
deliberate: two definitions of "what does this link point at" would drift, and
the checkup would then disagree with the exporter about which links are broken.
`|label` and `#anchor` are preserved.

Each target falls into exactly one of three cases:

| Case | Resolves to | Behaviour |
|---|---|---|
| **A** | a file that **was** exported | rewrite to the absolute wrapper ID |
| **B** | a real workspace file **not** exported (`gm-only`, or `mixed` without a separator) | refuse — see below |
| **C** | **nothing** | refuse, always |

**Case A — rewrite to the wrapper.**

```
[[table-rules]]  ->  [[<ns>:mechanics:table-rules|table-rules]]
```

Absolute, so it lands on the wrapper rather than resolving inside
`<ns>:export:`. The label preserves the original display text, so prose reads
unchanged. An existing `|label` is kept as-is.

**Case B — refuse by default; `--create-empty-placeholders` to publish anyway.**

By default the deploy refuses, reporting each offending link with its source
file and line, and exits non-zero. This is deliberate: the six such links in the
corpus at time of writing are all *"see `[[open-questions]]`"*-style GM pointers
embedded in player-visible rules text. The link being broken is the lesser
problem — the sentence should not be telling a player to consult the GM's
open-questions document at all. Refusing surfaces the content bug rather than
rendering it tidily.

With `--create-empty-placeholders`, the link is kept and rewritten as in case A,
and a **zero-byte page** is written at the target ID. Verified on the live
install: a zero-byte page renders as `wikilink1` (exists), so the link resolves
and no create-link appears. Placeholders are plain pages in the wrapper
namespace, not wrapper/content pairs — there is no content page to include.

The flag is an escape hatch for publishing before the prose is fixed, not the
intended steady state.

**Case C — always refuse.** A target resolving to nothing is a typo or a
reference to a deleted file. `--create-empty-placeholders` does **not** apply:
minting a page for a misspelling would convert a detectable error into a
permanent empty page nobody notices. Case C is a hard failure in both modes.

### Interaction with later phases

Placeholders are export-written pages, so they enter the manifest and are
subject to drift detection like any other. If the link that justified a
placeholder disappears, the placeholder becomes an orphan and is reported by the
same mechanism as any other retired page.

## Pipeline

| Where | Step |
|---|---|
| local | `export_player.py` → `Export/` (Markdown) — unchanged |
| local | render `Export/` → DokuWiki markup, build wrappers → staging dir |
| local | compare against manifest; hold back drifted pages |
| local | rsync staging **and** `receive_export.sh` to the server |
| remote | snapshot → unroll → reindex |
| local | write updated manifest; report orphans and drift |

`--dry-run` renders and reports without transferring anything. As with
`publish_handouts.py`, the documented practice is to dry-run first.

### Shipping the receiver each run

`receive_export.sh` is versioned in this repo and rsynced to the server on every
run, then invoked over ssh. The remote logic is reviewable in PRs and can never
be stale relative to the payload it processes, because the two arrive together.

### Snapshot

Taken by the receiver, before anything is written. It archives **directories,
not enumerated file lists**, so anything added by hand is captured without
anyone having chosen to include it:

```
data/pages/<ns>    data/media/<ns>    data/meta/<ns>    data/attic/<ns>
```

Media because a hand-uploaded image is exactly the "added out of band" case;
meta and attic because they hold the changelog and revision history that make a
restore faithful. Output: a timestamped tarball in `~/backup/`.

### Index rebuild

`php bin/indexer.php` after unrolling. DokuWiki indexes lazily via a per-pageview
request, so bulk-written files would otherwise stay unsearchable. Writing files
directly also bypasses `data/attic/` and `data/changes.log`, so exported pages
carry no per-page revision history — an accepted trade-off that
`publish_handouts.py` already makes.

## Deletion semantics

**The export never deletes anything.** Destructive operations are not a side
effect of publishing.

When a source file stops being player-visible — flipped to `gm-only`, renamed,
or deleted — the exported wiki page is now orphaned, and leaving it published is
a leak. The deploy therefore:

1. Reports each orphan on **stderr**.
2. **Exits non-zero**, matching `export_player.py`'s posture for unsplittable
   `mixed` files, so a rare event fails loudly rather than scrolling past.
3. Prints a ready-to-run command naming each page explicitly:

```
python3 scripts/unpublish_export.py --page <ns>:export:mechanics:species-house-rule
```

`unpublish_export.py` **re-verifies** before deleting: given a page ID, it
confirms that page still has no corresponding source file, so a command
copy-pasted from an older run cannot delete something that has since come back.
It snapshots first and reindexes after, same as the deploy. Deletion is removing
the `.txt` and reindexing; stale index entries mean this path likely needs
`indexer.php -c`, which the deploy path does not.

No blast-radius thresholds or percentage guards — the event is rare, explicit
page IDs plus re-verification are sufficient.

## Drift detection

Each deploy writes `manifest.json` to the server: page ID → sha256 of the exact
bytes written.

On the next deploy, each page's current on-wiki content is hashed and compared:

- **Match** — the deploy owns the page; overwrite freely.
- **Mismatch** — a human edited it out of band. **Do not touch it.** Report it.

This gives the guarantee that a quick wiki edit made mid-run survives, rather
than being silently clobbered by the following deploy. Timestamps are not used;
rsync and tar both rewrite mtimes.

The drift set is also the seam for a future `sync.py` (see Out of scope): the
pages whose hashes diverged are exactly the pages with wiki edits not yet in the
workspace, and the deploy has to compute that set anyway to protect them.

## Modules

New `src/bunnyforge/_dokuwiki.py` holds every DokuWiki-specific concern:

- `to_dokuwiki()` and `strip_leading_heading()`, **moved out of**
  `publish_handouts.py`, which then imports them (no behaviour change)
- page-ID mapping
- wrapper rendering
- wikilink rewriting (see the amendment above), consuming `review.py`'s shared
  target resolver rather than reimplementing resolution

This mirrors the move PR #15 already made with `player_facing()`, and keeps
`_common.py` from becoming a junk drawer of unrelated helpers.

| File | Role |
|---|---|
| `src/bunnyforge/_dokuwiki.py` (new) | conversion, page IDs, wrapper rendering, link rewriting |
| `src/bunnyforge/deploy_export.py` (new) | orchestration: render, links, manifest, rsync, invoke, report |
| `scripts/receive_export.sh` (new) | remote: snapshot → unroll → reindex |
| `scripts/unpublish_export.py` (new) | retire named pages; re-verify, snapshot, reindex |
| `scripts/publish_handouts.py` (modified) | imports from `_dokuwiki` |
| `src/bunnyforge/export_player.py` | unchanged |

## Testing

Rendering, page-ID mapping, wrapper generation, and manifest comparison are pure
functions — stdlib `unittest`, no network. `receive_export.sh` is tested via
subprocess against a throwaway DokuWiki tree in a temp directory.
`deploy_export.py` is exercised through `--dry-run`; live ssh is not tested in
CI.

**The leak test extends.** PR #15 has a sentinel test proving no GM content
survives into the Markdown export. That guarantee must hold through *conversion*
too, so the same sentinel workspace is rendered to DokuWiki markup and scanned
again. A conversion bug that resurrects stripped content is the one failure this
project cannot afford.

## Sequencing

Each step is one reviewable PR.

1. ~~**Merge PR #15**~~ — done.
2. `main.txt` remainder → `Setting/campaign-overview.md`; move
   `_ExtractInbound/player-blurb.html` to `_Done/`. (Independent of this design.)
3. ~~Extract `scripts/_dokuwiki.py`~~ — done (Plan A).
4. ~~Rendering: page IDs, wrappers, conversion, extended leak test~~ — done
   (Plan A, merged in `ecdabe4`).
5. ~~**Wikilink rewriting** (issue #17): the three-case resolution above,
   `--create-empty-placeholders`, and tests covering a link to an exported
   entity, to a non-exported GM doc, to nothing, with `|label`, with `#anchor`,
   and via a front-matter alias.~~ — done, merged in `a10f3a8`. Markdown inline
   links were brought under the same policy afterwards by #23 (issue #21), since
   `to_dokuwiki` would otherwise have converted them *after* the policy ran and
   published a live link nothing had inspected.
6. `receive_export.sh` + its tests.
7. `deploy_export.py` transport half, including manifest and drift detection.
8. `unpublish_export.py`.
9. Docs: `src/bunnyforge/README.md`, `AGENTS.md`.

Steps 5 onward are Plan B. Step 5 is deliberately first in that sequence: it is
pure local rendering with no server dependency, so it can land and be tested
while the transport work is still being written.

## Ops prerequisites

All complete as of 2026-07-27.

- ~~**Install the Include plugin**~~ — done; verified rendering a real page.
- ~~**Apply the ACL block**~~ — done, and verified with `auth_aclcheck` against
  real accounts including one outside `@<ns>players`, which is the
  case the `@user` rule exists to close.
- ~~**Set `useheading`**~~ — `'navigation'` in `conf/local.php`.
- **Tune Include display options** (`&noheader`, edit-button visibility) once
  real exported pages can be seen on the wiki. Still open; needs content
  published first, so it belongs after Plan B's transport lands.

## Out of scope

- **`sync.py`** — a future orchestrator over the three pipelines: import player
  material, pull back drifted export pages into the workspace, then export. It
  composes the existing scripts rather than writing files itself. Drift
  detection here is the seam it needs; the pull-back is a later phase.
- **Reconciling `main.txt`'s already-migrated half** with `Mechanics/`. Settled:
  the workspace versions are current, the wiki sections are done, no action.
- **Migrating `<ns>gm:`** out of the wiki into the workspace. That is the
  separate, ongoing `_ExtractInbound/` effort; this design neither reads from
  nor writes to that namespace.
- **Publishing media.** Only `.md` content is exported; images and attachments
  stay manual.

## Resolved by verification against the live install (2026-07-27)

- **An included heading does become the wrapper page's title.** Rendering a
  heading-less pure-include page gave metadata `title` = the *included* page's
  H1, so includes do contribute to the metadata pass. But `useheading` was `0`,
  so DokuWiki displayed the raw page ID instead. **Resolved by setting
  `$conf['useheading'] = 'navigation'` in `conf/local.php`** — first heading used
  for breadcrumbs, links and search results, without altering content rendering.
  It lives in `local.php`, not `dokuwiki.php`, so upgrades cannot silently
  revert it.
- **The Include plugin is installed and working** (release 2025-07-22, `phpmin
  8.0` against PHP 8.2.32). An include of a *non-existent* page renders an empty
  container carrying a `plugin_include_editbtn` marker — so the "one click to
  start annotating" affordance for `<ns>:players:*` is real.
- **Zero-byte pages count as existing** (`wikilink1`), which is what makes the
  `--create-empty-placeholders` behaviour above work.

## Open items to verify during implementation

- **Whether a rewritten absolute link resolves from root when followed from
  *inside* an included page.** This is issue #17's third item, and it is the one
  assumption underneath the whole rewriting design that has **not** been
  confirmed empirically. Case A emits `[[<ns>:<dir>:<stem>|label]]` — no leading
  colon — on the understanding that under stock DokuWiki configuration a page ID
  containing `:` is resolved from the root rather than relative to the containing
  namespace. If that is wrong, a link followed from within
  `<ns>:export:<dir>:*` would resolve to `<ns>:export:<dir>:<ns>:<dir>:<stem>`
  and dangle — the exact failure the rewriting exists to prevent, reintroduced
  one level down.

  Two adjacent facts *were* verified live on 2026-07-27 (code spans still
  linkify; zero-byte pages count as existing), but not this one, and it cannot
  be checked from here: **nothing has ever been published**, because transport
  (sequencing steps 6–8) is not built and `deploy_export` refuses anything but
  `--render-only`. So this is not a deferral by choice — there is no wiki state
  to test against until transport ships.

  **This must be checked on the first real deploy, before it is trusted.** It is
  recorded here rather than left in a closed issue precisely so that closing #17
  does not lose it. Note the risk is bounded: it is a navigation defect, not a
  leak. The link policy's refusals — which are what stop `gm-only` material
  reaching the player wiki — do not depend on this assumption at all.
- **Duplicate search hits.** The Include plugin respects ACLs, so included pages
  must stay player-readable, which means DokuWiki indexes all three namespaces.
  Searching an entity will surface the wrapper and both halves. Inherent to any
  include-based composition; accepted, revisit if it grates.
- **Whether `indexer.php` needs `-c`** on the unpublish path to purge stale
  entries for removed pages.
- **Whether placeholder pages need `-c` too.** A placeholder that later becomes
  a real exported page changes from zero-byte to content; the incremental
  indexer keys on mtime and should notice, but this is untested.

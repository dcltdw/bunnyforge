# deploy-export RPC transport (design)

**Date:** 2026-08-05
**Status:** designed, not built. Supersedes the transport half of
[2026-07-27-player-wiki-export-design.md](2026-07-27-player-wiki-export-design.md)
(sequencing steps 6–8); the render half of that spec is shipped and untouched.
**Ticket:** #7.

## Purpose

`deploy-export` implements the render half of the publish pipeline and stops
there: `--render-only` writes a staging tree shaped like DokuWiki's
`data/pages/`, and a human copies it onto the wiki by hand. This design closes
that gap over DokuWiki's JSON-RPC API, making the tool's first network
capability a deliberate, bounded one.

## Supersession, on the record

The 2026-07-27 spec designed transport as rsync + a versioned
`receive_export.sh` on the server + `indexer.php`, with a `manifest.json`
pushed to the host for drift detection. That approach is **superseded**, not
quietly contradicted; an annotation at the top of that spec points here. Why:

- **The wiki does its own bookkeeping.** Indexing, cache invalidation, and
  revision history happen because the wiki performed the write. The rsync
  route had to trigger reindexing explicitly and wrote revisions DokuWiki did
  not author.
- **No shell access, no remote script.** `receive_export.sh` — shipped,
  versioned, and invoked over ssh — disappears as a component.
- **`core.getPage` kills the server-side manifest.** The manifest lived on the
  server because rsync cannot read back what is there. RPC reads current
  on-wiki bytes directly, so drift is computable with no server-side state.

The old spec's drift guarantee is preserved verbatim: *"a quick wiki edit made
mid-run survives, rather than being silently clobbered by the following
deploy."*

What the old spec still owns: the namespace layout, wrapper format, ACL
design, wikilink rewriting, and the leak-test posture — all shipped. Its
still-open verification item (whether a rewritten absolute link resolves from
root when followed from *inside* an included page) carries forward into this
spec's first-deploy checklist rather than being lost.

## Verified against the live target (2026-08-04/05)

Facts this design builds on, verified on a real `2026-07-14a "Mort"` install
(ticket #7 comments):

- JSON-RPC is live at `lib/exe/jsonrpc.php`; XML-RPC also exists. **This
  design targets JSON-RPC only** — XML-RPC handling has reportedly been
  unreliable since the 2022 releases, and supporting both doubles the surface
  to serve installs older than the one being built for.
- The endpoint is **POST-only**: GET returns `-32606`.
- In the simplified `PATH_INFO` form, **success responses still carry an
  `error` object** — `{"result": …, "error": {"code": 0, "message":
  "success"}}`. A client testing for the presence of `error` calls every
  success a failure. The success test is: `error` absent, `null`, or
  `code == 0`.
- `$conf['remote']` defaults to `0`; a disabled API returns `-32605`. The
  target wiki's owner has enabled it and scoped `remoteuser`.
- `core.savePage`, `core.getPage`, and `core.listPages` exist and cover write,
  drift-read, and namespace enumeration.
- Auth supports JWT tokens, HTTP Basic, and session cookies. Tokens are the
  right shape for a deploy tool: scopable, revocable without a password
  change, never the owner's login.

## Scope

**In:** transport in `deploy_export.py`; a new `_dokuwiki_rpc.py` client; a
`[wiki]` config table and token resolution in `_config.py`; a `wiki-remote`
check in `review.py`'s wiki suite; the package-wide dry-run/`--go` CLI
convention (including `import_perceptions.py`); drift diff report and inbound
copies; tests; docs.

**Out:** deleting wiki pages (orphans are reported, never deleted — decided,
not omitted); publishing media; XML-RPC; and the wiki→workspace merge wizard /
auto-apply (`sync.py`'s seam — see Out of scope).

**Hard constraints inherited from the project:** zero runtime dependencies
(`urllib.request`, `json`, `ssl`, `hashlib`, `difflib` are all stdlib);
nothing campaign-specific in this repo — `<wiki>` / `<ns>` placeholders
throughout code, tests, docs, and issues.

## Configuration and credentials

`campaign.toml` gains an optional `[wiki]` table:

```toml
[wiki]
url = "https://<wiki>"        # base URL; the client appends lib/exe/jsonrpc.php
```

The URL is campaign data and `campaign.toml` lives in the private campaign
repo, so a hostname there is fine; this repo only ever shows placeholders.
A missing `[wiki] url` is an error only when a run needs the network —
`--render-only` never does — and the error says what to add and where.

**The credential is a DokuWiki API token**, resolved in order:

1. `BUNNYFORGE_WIKI_TOKEN` environment variable, if set;
2. else `<workspace>/.bunnyforge/wiki-token` — a single line, trailing
   whitespace stripped. Refused with a `chmod 600` instruction if the file is
   group- or world-readable.

Missing both → instructional error naming both sources and where a token
comes from (the wiki user's profile → API token). A rejected credential is a
server-side answer and is translated per the error table (`-32604`).

Sent as `Authorization: Bearer <token>`. HTTP Basic is deliberately not
supported: one auth path is one to test, and a token is strictly better for
this job. Plain `http://` URLs are refused — the token would cross the wire
in clear — except for localhost, which keeps a local test install usable.

The OS keychain was considered and rejected: platform-specific branching in a
deliberately portable stdlib-only tool, untestable in CI.

`init`'s scaffolded `.gitignore` gains `.bunnyforge/wiki-token` and
`.bunnyforge/wiki-drift/`. The manifest (below) stays committed, so the
ignores are those two entries, not the directory.

## CLI surface

Package-wide convention, adopted here and applied to every mutating command:
**the default run is a dry run; `--go` performs the writes.** Documented in
the top-level README so future commands inherit it.

| invocation | network | writes |
|---|---|---|
| `bunnyforge deploy-export` | read only | renders, fetches, prints the full plan — including pages held back for drift — writes nothing to the wiki, no manifest change |
| `bunnyforge deploy-export --go` | read + write | same plan, then saves pages and updates the manifest |
| `bunnyforge deploy-export --render-only --staging PATH` | none | renders only; unchanged from today, needs no `[wiki]` and no token |

- `--staging` is **optional** in dry-run and `--go` modes: omitted, the
  render goes to a fresh temp directory removed at exit; given, the tree
  persists for inspection (the existing non-empty-directory refusal
  unchanged). It stays **required** with `--render-only`, where the tree *is*
  the deliverable.
- `--render-only` and `--go` are mutually exclusive. `--render-only` is not
  folded into the dry-run convention: it is not a rehearsal of anything, it
  is a different (offline) deliverable.
- A deploy always uploads what it just rendered, so a stale staging tree can
  never be pushed.
- `--overwrite <page-id>` (repeatable, only meaningful with `--go`): the
  explicit escape hatch for a drifted page the user has decided to clobber —
  that named page is written and re-baselined this run. Destructive intent is
  always spelled out per page, never blanket.
- `--create-empty-placeholders` and `--workspace` are unchanged.

**`import-perceptions` adopts the same convention:** the default becomes a
dry run, `--go` writes, and `--dry-run` is removed. This is a breaking CLI
change to a shipped command; the tool is pre-1.0, the release notes and
README call it out.

## The RPC client — `_dokuwiki_rpc.py`

Third sibling in the DokuWiki family: `_dokuwiki.py` knows markup,
`_dokuwiki_install.py` knows an install on disk, `_dokuwiki_rpc.py` knows an
install over the wire. Stdlib only; imports nothing from `_config` — it takes
`(base_url, token)` and knows nothing about workspaces.

- Speaks the **simplified `PATH_INFO` form**: `POST
  <url>/lib/exe/jsonrpc.php/core.savePage` with a JSON object of named
  params. This is the form verified live; no JSON-RPC 2.0 envelope, no id
  bookkeeping.
- **Success test:** `error` absent, `null`, or `code == 0` — never
  key-presence.
- Headers: `Authorization: Bearer <token>`, `Content-Type: application/json`,
  `User-Agent: bunnyforge/<version>`. One timeout (default 30s). Standard TLS
  verification, no knob to disable it.
- Surface: `call(method, params)` plus three typed wrappers:
  - `get_page(id) -> str | None` — `None` for "does not exist" (error 121
    translated internally; it is a state, not a failure);
  - `save_page(id, text, summary)` — every save carries the change summary
    `bunnyforge deploy-export`, so wiki history shows provenance.

  `core.listPages` exists but nothing in this design needs it — orphan
  detection is manifest-based — so no wrapper is built for it (YAGNI; the
  generic `call` reaches it if a future check wants namespace enumeration).
- Failures raise `RpcError(code, message, method)`. Translation to prose
  happens in one table (below), not at call sites.
- The transport function is injectable, so tests never construct a socket.

## The deploy manifest

`<workspace>/.bunnyforge/wiki-manifest.json`, **committed to the campaign
repo**: deploying from a second machine sees the truth, and the post-deploy
diff is reviewable in git history. Format:

```json
{"version": 1, "pages": {"<page-id>": "<sha256-hex>"}}
```

The hash is of **what the wiki returns from `get_page` immediately after a
successful save**, not of the bytes sent: DokuWiki normalizes content on save
(trailing newlines, line endings), and hashing our own bytes would make every
page look self-drifted on the next run. Cost: one read-back fetch per written
page; at campaign scale (tens of pages) that is nothing.

The gitignored alternative was considered and rejected: a fresh clone or
second machine would see every page as drifted exactly when the guarantee is
least expected to fail.

## The deploy algorithm

Plan, then apply; `--go` is the only difference between them.

**Plan.** Render to staging (existing code, byte-identical output), enumerate
staged pages, and classify each against two facts — current wiki text
(fetched and hashed) and the manifest entry:

| wiki page | manifest entry | condition | action |
|---|---|---|---|
| absent | absent | | **new** — write |
| absent | present | | **deleted on wiki** — hold back, report: a human deleted it, recreating would clobber that decision |
| present | present, hashes match | target == wiki bytes | **unchanged** — skip |
| present | present, hashes match | target ≠ wiki bytes | **update** — write |
| present | present, hashes differ | target == wiki bytes | **adopt** — no write, re-baseline the manifest (resume-after-crash: the page was saved but the run died before the manifest write) |
| present | present, hashes differ | target ≠ wiki bytes | **drift** — hold back, report |
| present | absent | target == wiki bytes | **adopt** — the first-RPC-deploy case: pages hand-copied during the manual era match exactly |
| present | absent | target ≠ wiki bytes | **drift** — hold back, report: could be hand-edits from the manual era |

**Protected pages are refused in the uploader too**, independent of the
render-side skip: any staged page ID equal to `<ns>:main` (from
`PROTECTED_PAGE_NAMES`) or under `<ns>:players:` is never fetched and never
written. Belt and braces — a render bug cannot become a wiki write. The
render half never generates `<ns>:players:*`; this guard is for the case
where that ever stops being true.

**Drift report and inbound copies.** Every held-back page is reported with
its page ID, why it was held (drift / deleted on wiki / manual-era mismatch),
and a **unified diff** (`difflib.unified_diff`) between the current wiki text
and what this run would have written, sides labelled `wiki (current)` and
`deploy (target)`. The run also writes each drifted page's current wiki text
to `<workspace>/.bunnyforge/wiki-drift/<page path>.txt` (namespace colons as
directories, mirroring `data/pages/` layout) for manual merge — mirroring how
Perceptions handles inbound player text without touching sources. The tool
owns `wiki-drift/` outright and recreates it from empty on every planning
run (dry-run or `--go`; `--render-only` never touches it), so a page that
stops drifting does not leave a stale copy behind. Copies are
written in both dry-run and `--go` modes: they are part of reporting, not
deployment, and the directory is gitignored and outside the content walk.

Resolution paths, stated in the report: pull the edit into the workspace
source (next render then matches, drift disappears), or pass
`--overwrite <page-id>` to clobber that page and re-baseline it.

**Orphans.** Manifest entries with no staged counterpart — the source file
left the workspace or went `gm-only`. **Reported, never deleted.** The report
prints each orphan's page ID and says outright that removing the wiki page is
a manual act. Once a human has deleted it on the wiki, the next run sees
`get_page → None` for that entry and drops it from the manifest
automatically, so resolved orphans clean themselves up instead of being
reported forever.

**Placeholders — a collision found during design.** `core.savePage` refuses
to create an empty page (error 132), so the render half's zero-byte
placeholder trick cannot cross RPC as-is. The uploader translates a zero-byte
staged page into the body `~~NOTOC~~` — a control macro that renders nothing,
so the page displays blank while being non-empty and existing, which is all a
placeholder is for. Verifying it renders blank on the live install is a
first-deploy checklist item.

**Ordering and partial failure.** Writes happen in sorted page order, except
each content page lands immediately before its wrapper, so a wrapper never
points at a not-yet-written include for longer than one call. The manifest is
written through to disk after **each** successful save. A run that dies
mid-way needs no resume machinery: re-running converges, because
already-written pages classify as *unchanged* or *adopt*. A failed save
aborts the run, reports what was written and what remains, exits non-zero,
and says to re-run.

**Exit codes.** Non-zero if anything was held back (drift, deleted-on-wiki)
or any orphan was reported — in both dry-run and `--go` modes, matching the
render half's fail-loudly posture. Zero on a clean plan or deploy.

## Error translation

One table in `_dokuwiki_rpc.py`, applied by `deploy_export`; every code a
user can plausibly hit becomes a sentence naming the fix, per the project's
instructional-errors ruling. Codes collected from the DokuWiki source during
design; `-32605` and `-32606` verified live.

| condition | user-facing message names |
|---|---|
| DNS failure / connection refused / timeout (`URLError`) | the URL from `[wiki]`, and that it is a connectivity or config problem, not a wiki fault |
| HTTP 404 at the endpoint | no JSON-RPC endpoint — DokuWiki too old (the minimum release, pinned during implementation) or wrong base URL |
| `-32605` | "your wiki's remote API is disabled; set `$conf['remote'] = 1` in `conf/local.php`, not `conf/dokuwiki.php`" — on the critical path: `remote` defaults to 0, so every new user hits this on their first deploy |
| `-32604` | not authorized: check the token (`BUNNYFORGE_WIKI_TOKEN` / `.bunnyforge/wiki-token`) and that the API user is within `$conf['remoteuser']` |
| `111` | the wiki's ACL denies this user on `<page-id>` — grant the deploy user edit on the campaign namespace |
| `133` | page locked by an editing session — retry after the lock expires (default 15 minutes) |
| `134` | content blocked by the wiki's wordblock blacklist, naming the page |
| `-32606`, `-32700`, `-32602`, `131`, `132` | "bug in bunnyforge, please report" — client-side defects a user should never see |
| anything else | method, code, raw message, "unrecognised code — please report" |

`121` never reaches the user — it is the internal "does not exist" signal.
`-32603`'s meaning differs between DokuWiki's layers (method-not-found at the
API layer, internal error in the standard), which is exactly why unknown
codes print raw rather than guessing.

## `review wiki` gains `wiki-remote`

New check in the existing wiki suite, built on `_dokuwiki_install.read_conf`
— no new parsing, no network; the suite stays runnable against a filesystem
copy and CI never needs a live wiki. Universal rules, naming no campaign:

| finding | severity |
|---|---|
| `remote` enabled but `remoteuser` unset or empty — every wiki account can call the API | error |
| `remote` enabled from `conf/dokuwiki.php` — one upgrade from silently reverting | error (mirrors the `useacl` provenance rule) |
| `remote` disabled | no finding — a disabled API is a legitimate secure state; the deploy's `-32605` translation owns that path |

`remoteuser`'s stock value is the placeholder `!!not set!!`, which DokuWiki
treats as not-configured; the check treats it as unset, not as a scoping.

## Testing

No test touches the network; CI is unchanged in kind. The suite floor is 436
— a floor; the real count is re-derived from an actual run, never trusted
from prose — green on 3.11, 3.12, and 3.13.

- **Client** — injected transport; all three success shapes (`error` absent /
  `null` / `code 0` — the key-presence trap pinned by a test), each
  translated error code, Bearer and Content-Type headers on the request,
  `121 → None` in `get_page`, timeout and `URLError` translation,
  non-localhost `http://` refusal.
- **Planner** — the classification is a pure function
  `(target_bytes, wiki_text, manifest_hash) → action`; one table-driven test
  walks all eight rows of the state matrix.
- **Orchestration** — a fake client over an in-memory dict of pages: clean
  deploy; drift hold-back + diff + inbound copy + `--overwrite`; resume after
  simulated mid-run death (*adopt*); deleted-on-wiki hold-back; orphan report
  and self-cleanup; protected-page refusal at the transport layer; zero-byte
  → `~~NOTOC~~`; dry-run default making zero wiki writes and zero manifest
  changes; write-through manifest after each save; content-before-wrapper
  ordering; `wiki-drift/` recreated from empty each run.
- **Config/credentials** — `[wiki]` parsing, token resolution order,
  group-readable token file refusal, instructional messages for missing url
  and token.
- **Review** — `wiki-remote` findings against fixture `conf/` trees,
  including `!!not set!!`.
- **import-perceptions** — default is dry run; `--go` writes; `--dry-run`
  rejected.
- **Leak sentinel** — unaffected: the transport sends staged bytes verbatim;
  the one exception, the placeholder translation, carries no content.

## Modules, docs, release

| file | change |
|---|---|
| `src/bunnyforge/_dokuwiki_rpc.py` | **new** — client, `RpcError`, error translation table |
| `src/bunnyforge/deploy_export.py` | plan/apply orchestration, new CLI surface; render code untouched |
| `src/bunnyforge/_config.py` | `[wiki]` table, token resolution |
| `src/bunnyforge/review.py` | `wiki-remote` check in the wiki suite |
| `src/bunnyforge/import_perceptions.py` | dry-run default + `--go`, `--dry-run` removed |
| `src/bunnyforge/data/root/gitignore` | `+ .bunnyforge/wiki-token`, `+ .bunnyforge/wiki-drift/` |
| `docs/superpowers/specs/2026-07-27-player-wiki-export-design.md` | supersession annotation on the transport half |
| `README.md`, `src/bunnyforge/README.md` | pipeline loses "(manual copy)"; dry-run/`--go` convention documented |

Release: the package's first network capability plus a CLI break in
`import-perceptions` — a minor bump to 0.2.0, tag-driven per the README's
Releasing section (bump `pyproject.toml`, tag `v0.2.0`, CI refuses a
mismatch), expecting PyPI index lag before the campaign repo can re-pin.

## First-live-deploy checklist

Named here because no test can cover them; each is checked on the first real
deploy before being trusted:

1. `~~NOTOC~~` placeholder pages render blank and count as existing.
2. The exact named-parameter spelling `core.savePage` expects in the
   simplified `PATH_INFO` form (verified against the live wiki, then pinned
   in the client's tests).
3. The old spec's carried-forward item: a rewritten absolute link
   (`[[<ns>:<dir>:<stem>|label]]`, no leading colon) resolves from the root
   when followed from *inside* an included page. First publication finally
   creates the wiki state needed to check it. Bounded risk: a navigation
   defect, not a leak — the link policy's refusals do not depend on it.
4. The read-back hash equals a re-fetch a minute later (i.e. `get_page` is
   stable after save; no lazy normalization on later reads).

## Out of scope, on the record

- **Merge wizard / auto-apply of wiki edits into workspace sources.** The
  export is a lossy one-way projection (GM-only stripping, Markdown→DokuWiki
  conversion, link rewriting); inverting it is not well-defined, and
  workspace sources have exactly one writer. The drift diff plus
  `wiki-drift/` inbound copies are this design's answer; the interactive
  merge is `sync.py`'s seam and gets its own ticket and design.
- **Deleting wiki pages**, including an `unpublish` command. Orphans are
  reported with their page IDs; removal is a manual wiki act. If the manual
  step grates in practice, an explicit per-page retire command can be
  designed later — the old spec's `unpublish_export.py` re-verification
  posture is the starting point.
- **Media.** Only `.md` content is exported; images stay manual.
- **XML-RPC.**

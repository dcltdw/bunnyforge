# Changelog

Notable changes to bunnyforge, in the format of
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). This project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html); while
the major version is `0`, breaking changes arrive in minor bumps.

This file starts at 0.5.0. For anything earlier, see the
[releases page](https://github.com/dcltdw/bunnyforge/releases) and the git
history.

Entries land under `[Unreleased]` in the same PR as the change they
record; the release PR renames that section to the version it ships and
starts a fresh one.

## [Unreleased]

### Added

- `bunnyforge serve-mcp --log-file [PATH]` routes uvicorn's logs to a
  self-pruning file (rotated at midnight, 14 rotated days kept
  alongside the live one) instead of cluttering the terminal with
  access lines; errors still reach stderr too. Bare `--log-file` picks
  a platform default:
  `~/Library/Logs/bunnyforge/mcp.log` on macOS,
  `$XDG_STATE_HOME/bunnyforge/mcp.log` elsewhere. (#87)

### Changed

- `docs/serve-mcp.md` now walks through creating the named tunnel it
  recommends — login, create, route dns, config, launch agent — plus the
  traps: the ingress catch-all is mandatory, the credentials path must be
  absolute, a launch agent starts at login rather than boot, and the
  hostname answers 502 until `serve-mcp` is started. One
  anti-recommendation: no Cloudflare Access in front of the hostname; the
  connector must complete the server's own OAuth flow against it. (#84)

## [0.5.0] — 2026-08-18

The release where retrieval became scoped and ordered, and where the
workspace's own vocabulary got a rule: a leading underscore means not-canon.
Read **Migration** before upgrading a live campaign — this one is not a clean
drop-in for an existing workspace.

### Added

- **Scoped retrieval.** `search` and `list_entities` take
  `scope: live | archive | both` (default `both`), every result carries an
  `archived` flag, and `campaign_overview` reports `archive_sections`
  alongside the flat archive count. Sections resolve across both trees, so
  `section="NPCs"` covers `NPCs/` and `Archive/NPCs/` together. Doctrine
  states that the scope is the GM's call for creative work. (#72)
- **Task-start context doctrine.** Packaged `AGENTS.md` gains a
  `## Task-start context` section: four questions an agent answers before
  work begins — what is being built, whether NPCs are new or reused, the
  retrieval scope, and whether the output is player-visible — asked as one
  bundled message, with answers that persist for the task. The
  `campaign-doctrine.md` scaffold gains a stub for campaign-specific
  questions, and `campaign_overview`'s description points at the list. (#76)
- **`campaign-doctrine.md`.** A GM-owned doctrine file beside the
  package-owned `AGENTS.md`, scaffolded by `init`, never overwritten by an
  adoption. (#64)
- **Staging is readable over MCP.** `list_staged` and `read_staged` let an
  agent read back drafts it wrote in an earlier session. The canon read tools
  are untouched, and promotion stays manual and GM-only. (#60)

### Changed

- **A leading underscore means not-canon, biconditionally.** `_Archive/`
  becomes `Archive/` — it is the record of what happened, so it is canon and
  is now ordinary walked content, reaching review, player export and wiki
  deploy under normal visibility rules. Generated output takes the marker
  instead: `Sheets/`, `Reviews/` and `Export/` become `_Sheets/`,
  `_Reviews/`, `_Export/`. The repo-infrastructure directories (`docs/`,
  `scripts/`, `tests/`) keep their ecosystem names and are named as exempt in
  doctrine. One predicate, `_common.is_machinery`, now backs every surface
  that used to decide this separately. (#67)
- **`AGENTS.md` is package-owned and byte-identical in every workspace,**
  so adopting new doctrine is a file copy rather than a merge; anything
  campaign-specific belongs in `campaign-doctrine.md`. (#64)
- **`serve-mcp`'s staging directory split in two,** with separate
  vocabularies and guards: `_AgentDrafts/` for agent output with a full draft
  lifecycle, and `_ExtractInbound/` for the GM's inbound queue, read-only and
  only when asked. (#61)
- **`search` result order is now a contract:** live hits before archived
  ones, workspace-path order within each tree. Deliberately not a relevance
  promise. (#75)
- **README** corrects three claims that were wider than the code — which
  commands reach the network, which ones honour the `--go` dry-run
  convention, and which files carry a `visibility` field — and documents the
  wiki round-trip and `_ExtractInbound/`. (#77)

### Fixed

- **`search` no longer starves live results under its cap.** `Archive/`
  sorts before every live section, so on a campaign whose archive had
  outgrown `SEARCH_CAP` a default search could return 50 archived hits and
  zero live ones, hiding the current answer. Live-first ordering means every
  live hit is in the reply whenever live matches fit under the cap. The
  truncation notice now names which tree was cut and no longer fires on a
  reply that exactly fills the cap. `SEARCH_CAP` stays 50. (#75)
- **Name collisions across the canon trees now fail review.** A
  `name-collisions` check runs as a `checkup` **error**, closing a gap where
  a collision could pass review and surface only at deploy. (#67)

### Internal

- Enumerator exclusion tests assert exact equality on the whole enumerated
  result, one fixture per filter, so they can actually fail: three mutations
  that previously left the entire suite green now break it. Test-only, no
  production change. (#73)

### Migration

**Existing workspaces need a hand-reconcile.** `AGENTS.md` ships
byte-identical, and both #64 and #67 rewrote it substantially, as did the
task-start section in #76. The one-time recipe is in
[`docs/adopting-doctrine.md`](docs/adopting-doctrine.md) →
"Migrating to the not-canon underscore".

**The archive now flows into player export and wiki deploy** under normal
visibility rules. A campaign with retired `player-visible` files will
republish them under a new `ns:archive:…` namespace and orphan the old pages.
See step 5 of the migration recipe.

**Packaged prose in this release was cleared by deliberate human reads at PR
time, not by an automated check** — nothing yet screens `src/bunnyforge/data/`
for campaign-specific terms. That is the basis for the portability claim.

[Unreleased]: https://github.com/dcltdw/bunnyforge/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/dcltdw/bunnyforge/compare/v0.4.0...v0.5.0

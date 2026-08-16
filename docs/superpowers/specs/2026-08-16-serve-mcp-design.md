# serve-mcp: remote MCP access to a campaign workspace — design

**Date:** 2026-08-16
**Status:** draft, awaiting review

## Problem

A GM wants to do campaign content creation with a web-based Claude agent
(claude.ai), whose conversational "ask questions, offer options" style suits
brainstorming better than the local coding agent. But the GM materials — the
source of truth — live in a local bunnyforge workspace the web agent cannot
see. claude.ai reaches external data through custom connectors, which are
remote MCP servers.

`bunnyforge serve-mcp` runs an MCP server over a campaign workspace so a
web-based agent can read GM materials, use bunnyforge's generators, and write
drafts back — without ever becoming a second source of truth.

## Goals

- Give a claude.ai custom connector read access to the whole workspace,
  plus the name generator, with enough orientation tooling that a fresh
  conversation gets its bearings in one call.
- Serve workspace doctrine (style guide, situation-design guide, AGENTS.md)
  so the web agent collaborates under the same contract as a local agent.
- Accept written output back — new drafts and proposed revisions — into the
  workspace's staging area, feeding the existing extraction workflow.
- Keep the server deployable from the GM's own machine behind a tunnel,
  with a storage seam that permits a hosted deployment later.

## Non-goals

- **No publishing.** `export-player`, `deploy-export`, and anything touching
  `Export/` or the wiki are absent from the tool surface. Publishing to
  players remains a local, human-initiated act.
- **No visibility filtering.** The connector authenticates as the GM and
  serves everything, including `gm-only` material. A player-facing,
  visibility-filtered server is a conceivable future feature, not this one.
- **No hosted backend yet.** Phase 3 sketches it; this spec builds the
  local-machine shape.

## Decisions already made (with the user)

1. **Optional extra, not stdlib.** The MCP protocol layer comes from the
   official `mcp` Python SDK, installed via `pip install bunnyforge[mcp]`.
   Core bunnyforge keeps its zero-runtime-dependency doctrine; `serve-mcp`
   is inherently online, so an install-time dependency is acceptable there.
   Importing the subcommand without the extra fails with a friendly
   "install bunnyforge[mcp]" error; every other subcommand is unaffected.
2. **Write-back is required for the feature to be worth using.** Phase 1
   (read-only) is scaffolding; phase 2 (writes) is the usability milestone.
3. **Staging by default, direct edits behind a flag.** Without the flag the
   server never writes canonical directories. `--allow-direct-edits` enables
   in-place edits, each auto-committed to git.
4. **Start Mac-local, design for hosting.** All file access goes through one
   storage interface so a later hosted (git-clone-backed) deployment swaps
   the backend, not the tools.

## Architecture

```
claude.ai custom connector
        │  streamable HTTP (JSON-RPC / MCP)
        ▼
tunnel (Tailscale Funnel / cloudflared — user-run, documented not implemented)
        ▼
bunnyforge serve-mcp  ──►  MCP layer: tools + resources (mcp SDK)
        │
        ▼
WorkspaceStore (interface): read / list / search / stage_write / write
        │
        ▼
LocalStore → the workspace on disk (resolved via campaign.toml, like every
             other subcommand)
```

The server resolves its workspace exactly as other commands do
(`resolve_workspace`, `_config.load`). Tools are thin handlers over
`WorkspaceStore`; the store owns path resolution, traversal guards, and the
staging/canonical boundary. Phase 3's `GitStore` (clone, pull, commit, push)
implements the same interface.

## Deployment and auth

- The server binds localhost; reaching it from claude.ai is the tunnel's
  job. Bunnyforge documents the Tailscale Funnel / cloudflared recipe but
  does not manage tunnels.
- Auth is required by default: a static bearer token (`--token` /
  `BUNNYFORGE_MCP_TOKEN`), checked on every request. `--no-auth` exists for
  local testing only.
- claude.ai's connector auth requirements (OAuth support, token handling)
  must be validated end-to-end as part of phase 1; if a static bearer token
  is not accepted, the SDK's OAuth support is the fallback. This is the one
  external unknown in the design.

## Tool surface

| tool | phase | behaviour |
|---|---|---|
| `campaign_overview()` | 1 | Campaign name; each configured entity dir with entity counts; full text of `front-burner.md` and `open-questions.md` when present. One call to orient a fresh conversation. |
| `list_entities(section)` | 1 | Files in one entity dir: workspace-relative path, title, and a one-line summary drawn from front matter. |
| `read_entity(path)` | 1 | Full file content, front matter included. Any workspace-relative path, not just entity dirs (excluded dirs stay excluded). |
| `search(query, section?)` | 1 | Case-insensitive substring search across workspace content files; returns path + surrounding snippet per hit, capped per response. |
| `generate_names(culture, count)` | 1 | Wraps the existing name generator against the workspace's culture inventories. |
| `save_draft(section, name, content)` | 2 | Writes new content to `<staging>/<section>/<name>.md`. Refuses to overwrite an existing draft — the error tells the agent to pick another name. |
| `propose_revision(path, content)` | 2 | Full-file shadow copy of an existing canonical file, written to `<staging>/<path>` mirroring its workspace-relative path. Requires the target to exist. Local review is a diff away. |
| `write_entity(path, content)` | 2 | Registered only when the server runs with `--allow-direct-edits`. Edits the canonical file in place and auto-commits (`serve-mcp: edit <path>`), so review and undo are git operations. |

Write tools confine themselves mechanically: `save_draft` and
`propose_revision` may only create files under the staging directory;
`write_entity` may only touch existing content files inside the workspace.
Path traversal outside the workspace is rejected in `WorkspaceStore`, not in
each handler.

### Staging directory

New `[workspace]` config key `staging_dir`, default `_ExtractInbound`
(matching the existing convention where inbound material awaits extraction
and spent sources move to `_Done/`). The server creates it on first write if
absent. Drafts landing there feed the extraction workflow the workspace's
AGENTS.md already defines — the server's responsibility ends at staging.

### Resources

Workspace doctrine exposed as MCP resources, so the connector can load them
at conversation start: `style-guide.md`, `situation-design.md`, `AGENTS.md`.
Missing files are simply not listed.

## Phasing

1. **Phase 1 — read + orient.** The five read/generate tools, resources,
   token auth, tunnel recipe docs. Exit criterion: a claude.ai conversation
   can orient itself and answer questions about the campaign unaided.
2. **Phase 2 — write-back.** `save_draft`, `propose_revision`,
   `write_entity` + flag, `staging_dir` config. Exit criterion: a draft
   written from claude.ai lands in staging and flows through the local
   extraction workflow. *The feature is not usable in practice until this
   lands.*
3. **Phase 3 — hosted (not yet committed).** `GitStore` over the campaign's
   git remote; drafts arrive as commits. Only if Mac-only availability
   proves annoying in practice.

## Testing

- `WorkspaceStore` and each tool handler unit-tested against temporary
  workspaces built the way existing tests do (`load()` / `open_workspace()`
  against a scaffolded tree) — including traversal rejection, staging
  confinement, overwrite refusal, and flag-gating of `write_entity`.
- MCP layer exercised with the SDK's in-memory client against the running
  server object: list tools, call each, list/read resources.
- Auth: request without token → rejected; with token → served.
- The claude.ai connector handshake itself is validated manually in phase 1
  (external service; not automatable from the test suite).

## Security considerations

- Everything served is GM-eyes-only; the bearer token (and the tunnel's own
  auth, where used) is the only gate. Default-deny: no token configured and
  no `--no-auth` → the server refuses to start.
- Write surface is confined as described above; the deploy/publish path is
  structurally absent rather than merely forbidden.
- `--allow-direct-edits` trades a mechanical boundary for git history; the
  flag exists so that trade is always explicit and per-run.

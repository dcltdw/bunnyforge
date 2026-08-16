# serve-mcp: OAuth for the claude.ai connector — design

**Date:** 2026-08-16
**Status:** draft, awaiting review
**Supersedes:** the "Deployment and auth" section of
`2026-08-16-serve-mcp-design.md`, whose static-bearer-token assumption was
disproved empirically (issue #42).

## Problem

The original design assumed the claude.ai custom connector would carry a
static bearer token, with OAuth as fallback. Testing against the real
connector form over a live cloudflared tunnel (issue #42) disproved it:

- The form offers **OAuth Client ID** and **OAuth Client Secret**, both
  optional, and no custom-header field. A static token has nowhere to go.
- With both blank, claude.ai walks the standard OAuth discovery sequence —
  `/.well-known/oauth-protected-resource/mcp`, `/.well-known/oauth-authorization-server`,
  then `POST /register` (RFC 7591 Dynamic Client Registration) — and gives
  up when every probe returns 401: *"Couldn't register with bunnyforge-mcp's
  sign-in service."*

Two conclusions follow:

1. **claude.ai registers itself.** DCR means no pre-provisioned client at an
   external identity provider is needed. That is the tractable case.
2. **`_BearerAuth` is structurally incompatible with OAuth**, not merely
   missing a feature. It wraps the whole ASGI app and 401s everything
   without a token, but OAuth bootstrap is by definition unauthenticated —
   a client cannot present a token before discovering how to obtain one.
   Carving exemptions into the wrapper would mean re-deriving, and then
   tracking, the spec's list of public routes by hand.

## Goals

- A claude.ai custom connector connects with the Client ID / Secret fields
  **left blank**: DCR, authorization-code grant with PKCE, token refresh.
- Only the GM can authorize a client. Everything served remains
  GM-eyes-only; the tunnel makes the endpoints public, the auth design must
  keep the content private.
- Preserve the existing posture: default-deny (refuse to start without an
  auth mechanism) and `--no-auth` for local testing only.
- Stay inside the `bunnyforge[mcp]` extra with **no new dependencies**, and
  keep `serve_mcp.py` importable on a bare Python (SDK imports only inside
  function bodies).
- Nothing credential-shaped ever reaches git — neither this public repo nor
  the campaign workspace, which is itself a git repo.

## Non-goals

- **#46** (DNS-rebinding 421 through a tunnel). Independent fix, already
  confirmed. This design *coordinates on one shared flag* (`--public-host`,
  below) but does not implement transport security.
- **#41 / phase 2 write-back.** Planned elsewhere; unaffected — auth wraps
  the transport, not the tool surface.
- Multi-user auth, scopes, player-facing visibility filtering. One user,
  full access; `required_scopes` stays unset.

## Measured SDK surface (mcp 2.0.0)

Decisions below rest on these measured facts, not on documentation:

- `MCPServer(...)` accepts `auth_server_provider`, `token_verifier`, and
  `auth: AuthSettings`. Supplying **both** provider and verifier is a
  `ValueError`; supplying a provider alone auto-wraps it in the SDK's
  `ProviderTokenVerifier`, which verifies bearer tokens by calling the
  provider's own `load_access_token`. With provider + `AuthSettings`,
  `streamable_http_app()` assembles exactly the topology we need — **the
  SDK already knows which routes must be public**:
  - Mounted **unauthenticated**: `/.well-known/oauth-authorization-server`,
    `/.well-known/oauth-protected-resource/mcp`, `/authorize`, `/token`,
    `/register` (when `client_registration_options.enabled`), `/revoke`
    (when enabled).
  - Mounted **behind `RequireAuthMiddleware`**: `/mcp` only. Its 401 carries
    `WWW-Authenticate: Bearer ... resource_metadata="…"` pointing at the
    protected-resource metadata — the breadcrumb claude.ai's discovery
    follows.
- `OAuthAuthorizationServerProvider` has ten methods; the identity-assertion
  one is gated off by default (`identity_assertion_enabled=False`), leaving
  nine to implement: `get_client`, `register_client`, `authorize`,
  `load_authorization_code`, `exchange_authorization_code`,
  `load_refresh_token`, `exchange_refresh_token`, `load_access_token`,
  `revoke_token`.
- The SDK's handlers do the protocol work: the token handler **enforces
  PKCE** (S256 check of `code_verifier` against the stored
  `code_challenge`), the registration handler generates client
  credentials, and the authorization handler validates `redirect_uri`,
  scope, and response type before calling `provider.authorize()` — whose
  string return value it 302-redirects to. That return value is the hook
  where a consent page slots in.
- `validate_issuer_url` requires HTTPS **except** for
  localhost/127.0.0.1/::1, and forbids query/fragment. A cloudflared
  hostname (`https://…`) and a local dev issuer (`http://127.0.0.1:8765`)
  both pass.
- `MCPServer.custom_route(path, methods)` mounts extra Starlette routes on
  the same app — sufficient for a consent page.

## Approaches considered

### A. Self-hosted minimal authorization server, GM authenticated by a pre-shared key — **recommended**

bunnyforge implements the nine-method provider over in-process state plus a
small state file. DCR is enabled, so claude.ai registers itself. The one
place identity actually matters — the `/authorize` step — renders a minimal
consent page where the GM types a pre-shared key; correct key ⇒
authorization code ⇒ SDK-managed token exchange.

- **For:** proportionate to one user on one laptop. No accounts, no hosted
  services, no subscription, no new dependencies (the SDK ships all the
  protocol machinery; tokens are opaque random strings, so no JWT library).
  The security-critical surface bunnyforge owns is one constant-time string
  comparison; everything protocol-shaped (PKCE, redirect validation,
  client auth, metadata) is the SDK's tested code.
- **Against:** bunnyforge is now running an internet-facing OAuth
  authorization server, however small. The mitigation is that a stolen
  *protocol* interaction yields nothing without the GM key, and a stolen
  *token* is time-limited and revocable by restarting with a new key state.

### B. Resource-server mode only; delegate issuing to an external IdP

Implement only `TokenVerifier` (~10 lines) and point
`AuthSettings.issuer_url` at an external authorization server (Auth0,
Keycloak, Cloudflare Access…) that supports DCR.

- **For:** bunnyforge's auth code shrinks to token validation; a security
  team maintains the hard parts.
- **Against:** disproportionate for one user — a hosted IdP account (or a
  self-hosted Keycloak, a heavier operational burden than all of
  bunnyforge), tenant configuration, and DCR enablement, to protect one
  laptop. It also needs a stable public identity for callback URLs, so the
  ephemeral-tunnel question gets *harder*, not easier. Stated plainly per
  the design brief: this is the right call for a team or a hosted phase-3
  deployment, and the `TokenVerifier` seam keeps it reachable later, but it
  is not the least-bad option today.

### C. Self-hosted AS as in A, but GM login federated through GitHub

Same provider skeleton, but the consent step redirects to a GitHub OAuth
app and accepts only the repo owner's GitHub identity.

- **For:** no pre-shared key to manage; phishing-resistant login.
- **Against:** a GitHub OAuth app requires a **fixed callback URL**, which
  an ephemeral quick-tunnel hostname breaks every run; it adds a network
  dependency and a second protocol leg to debug; and it protects a
  single-user consent form whose threat model a high-entropy key already
  covers. More moving parts, same effective assurance.

### Rejected without a lettered entry

Keeping `_BearerAuth` and exempting the bootstrap routes. The evidence in
#42 already names the flaw: the wrapper would have to re-derive the SDK's
public-route list and track it as the spec evolves — and behind the
exemptions we would *still* need the authorization server of approach A.
All cost, no savings.

## Design (approach A)

### Architecture

`_BearerAuth` is deleted. Auth assembly moves into the SDK call:

```
MCPServer(
    "bunnyforge",
    auth_server_provider=SingleUserOAuthProvider(...),
    auth=AuthSettings(
        issuer_url=<derived, see below>,
        resource_server_url=<issuer>/mcp,
        client_registration_options=ClientRegistrationOptions(enabled=True),
    ),
)
```

No `token_verifier` is passed — the SDK forbids supplying both and wraps
the provider in `ProviderTokenVerifier` itself, so `/mcp` bearer checks
route through the provider's `load_access_token` (measured, above).

Resulting route surface:

| route | auth | source |
|---|---|---|
| `/.well-known/oauth-authorization-server` | public | SDK |
| `/.well-known/oauth-protected-resource/mcp` | public | SDK |
| `POST /register` | public (open DCR, per RFC 7591) | SDK |
| `GET/POST /authorize` | public entry; **GM key gates approval** | SDK → provider |
| `POST /token` | client credentials + PKCE | SDK |
| `GET/POST /consent` | public entry; GM key checked on POST | bunnyforge (`custom_route`) |
| `/mcp` | Bearer token required | SDK `RequireAuthMiddleware` |

### The provider: `SingleUserOAuthProvider`

One class in a new module `src/bunnyforge/_mcp_auth.py`. The module may
import `mcp` at top level — it is itself imported only inside
`serve_mcp.py` function bodies, so bare-Python imports of `serve_mcp`
remain safe (`cli.py` imports every subcommand unconditionally).

State: four dicts — registered clients, pending consent transactions,
authorization codes, access/refresh tokens — with clients and tokens
persisted (below) and transactions/codes deliberately memory-only.

| method | behaviour |
|---|---|
| `register_client` | Store the SDK-built client record. Cap stored clients (e.g. 32, evict oldest) so an internet-reachable open endpoint cannot grow memory unboundedly. |
| `get_client` | Lookup. |
| `authorize` | Park the `AuthorizationParams` under a random transaction id (10-minute expiry) and return `<issuer>/consent?txn=<id>` — the SDK 302s the GM's browser there. |
| `load_authorization_code` / `exchange_authorization_code` | Standard single-use code flow: codes expire after 5 minutes, are bound to the client id, and are deleted on exchange. PKCE verification is the SDK's job. Exchange issues an access token (1 h) and refresh token. |
| `load_refresh_token` / `exchange_refresh_token` | Rotate: old refresh token invalidated, new access + refresh pair issued. This is what makes server restarts and access-token expiry invisible to the GM. |
| `load_access_token` | Lookup; `None` if unknown or expired (prune on read). Serves as token verification for `/mcp`. |
| `revoke_token` | Delete access or refresh token. `RevocationOptions` stays disabled initially — claude.ai did not probe `/revoke` — but the method is trivial, so implement it and leave the route off. |

All tokens, codes, and transaction ids are `secrets.token_urlsafe(32)` —
opaque and looked up server-side. No JWTs, even though `pyjwt` happens to
ship with the SDK: opaque tokens need no signing keys to generate, rotate,
or leak, and revocation is a dict delete instead of a denylist.

### GM authentication: the consent page

The only place bunnyforge makes a security decision of its own.

- `GET /consent?txn=…` — minimal inline-HTML form: campaign name, the
  requesting client's `client_name` ("Claude"), one password input, submit.
  Unknown or expired txn ⇒ 400 with a "restart the connection from
  claude.ai" message.
- `POST /consent` — compare the submitted key against the configured GM key
  with `hmac.compare_digest`. On success: consume the transaction, mint the
  authorization code, 302 to the client's `redirect_uri` with `code` and
  `state`. On failure: re-render the form with an error after a ~1 s delay.
- The form is styled with nothing (it is used once per token lifetime by
  one person) and served with `Cache-Control: no-store`.

Brute-force posture: the key is expected to be high-entropy (docs show
`python3 -c "import secrets; print(secrets.token_urlsafe(24))"`), the
comparison is constant-time, failures are delayed, and transactions expire.
A lockout counter is deliberately omitted — it adds a self-DoS lever to
protect a 128-bit secret.

### Key naming: `--auth-key` replaces `--token`

The GM key is not a bearer token — it is never sent by the MCP client, it
is typed by the GM into the consent form once per grant. Keeping the name
`--token` / `BUNNYFORGE_MCP_TOKEN` would misdescribe the mechanism the
moment it ships. New spelling: **`--auth-key` / `BUNNYFORGE_MCP_KEY`**, and
the old spellings are removed rather than aliased — the server is pre-1.0
with exactly one operator, and a silent alias would preserve the wrong
mental model. `--help` text and `docs/serve-mcp.md` explain the change.

### Issuer URL and the tunnel

`AuthSettings.issuer_url` is required, and tunnel hostnames are ephemeral;
this is a real constraint with a two-part answer:

1. **The issuer is derived at startup, not configured separately.**
   serve-mcp gains `--public-host HOST` — *the same flag issue #46
   specifies* for transport security; whichever lands first defines it,
   the other consumes it. With the flag: `issuer_url =
   https://<public-host>`, `resource_server_url =
   https://<public-host>/mcp`. Without it: `http://127.0.0.1:<port>`,
   which `validate_issuer_url` accepts for local testing.
2. **Quick tunnels work; a named tunnel is the recommended recipe.** With a
   cloudflared quick tunnel the hostname changes every run — the GM must
   start the tunnel, read the hostname, and pass it to `--public-host`. The
   connector URL in claude.ai changes at the same time, so quick tunnels
   force reconfiguration *and* a fresh OAuth dance every run regardless of
   what this design does. A named tunnel (free with a Cloudflare-managed
   domain) gives a stable hostname, which makes the persisted refresh
   tokens actually useful: laptop restarts become invisible to claude.ai.
   The design therefore *supports* ephemeral hostnames but the documented
   recipe uses a named tunnel. No requirement for a hosted identity of any
   kind follows from this.

Auth mode does not require `--public-host` (localhost issuer is valid for
testing with the SDK's inspector), but the startup banner states the issuer
so a mismatch is visible immediately.

### Persistence

Registered clients and tokens survive restarts in a state file:

- **Location:** `$XDG_STATE_HOME/bunnyforge/mcp-oauth-state.json`
  (default `~/.local/state/bunnyforge/…`). Outside every git repo by
  construction — never in the bunnyforge repo, never in the campaign
  workspace. Created `0600`, parent dirs `0700`, written atomically
  (temp file + `os.replace`).
- **Contents:** registered clients; refresh tokens; access tokens with
  expiries. Pending transactions and authorization codes are *not*
  persisted — they live minutes and losing them only re-prompts consent.
- **Pruning:** expired entries dropped on load and on write.
- **Reset:** deleting the file revokes everything; document this as the
  "log everyone out" move. Refresh tokens expire after 30 days of disuse,
  bounding how long the file stays sensitive.

Persistence is what turns approach A from "re-authorize every server
restart" (real friction on a laptop that serves per-session) into "connect
once per month". It is scoped to this one JSON file so the trade — a
credential cache on disk, `0600`, outside any repo — is explicit.

### Startup contract (default-deny preserved)

| invocation | result |
|---|---|
| `--auth-key` present (or `BUNNYFORGE_MCP_KEY` set) | OAuth mode: SDK auth routes + guarded `/mcp` |
| `--no-auth` | unauthenticated app, loud warning — local testing only |
| neither | **refuse to start**, message names `--auth-key`, the env var, and `--no-auth` |
| both | refuse to start: contradictory intent |

`--no-auth` builds the app with no `AuthSettings`, no provider, no
verifier — the SDK then mounts `/mcp` unguarded and no OAuth routes exist,
matching today's semantics exactly.

### What is exposed unauthenticated, and why that is acceptable

The OAuth bootstrap routes are public because the protocol requires it.
What each yields an attacker: metadata (server names and endpoint URLs — no
campaign content), open registration (a client record in a capped store),
an authorize/consent page (a password form over a high-entropy key), a
token endpoint (useless without a code minted by that form, bound by PKCE).
Campaign content sits solely behind `/mcp`, which requires a token that
only the consent flow issues. The GM-eyes-only property reduces to the
secrecy of one key plus the SDK's protocol correctness — the same trust
shape as the old design, minus the incompatibility.

## Error handling

- Protocol errors (bad redirect URI, unknown client, failed PKCE, expired
  code) are the SDK handlers' responsibility; the provider signals them by
  returning `None`/raising per the provider contract.
- Consent errors are bunnyforge's: unknown/expired txn ⇒ 400 with recovery
  instructions; wrong key ⇒ delayed re-render; both paths `no-store`.
- State-file corruption (unparseable JSON) ⇒ log a warning, start with
  empty state, do not overwrite the corrupt file until the first
  successful write renames over it. Losing token state is an
  inconvenience, not an outage: claude.ai re-runs the flow.
- Startup validation failures (issuer rejected by `validate_issuer_url`,
  contradictory flags) refuse to start with the reason on stderr, matching
  the existing posture.

## Testing

`unittest`, in `tests/test_serve_mcp.py` and a new `tests/test_mcp_auth.py`,
following the existing `HAVE_MCP` skip discipline (provider logic that
imports `mcp` skips on bare Python; anything SDK-free runs everywhere).

- **Provider unit tests:** registration cap and eviction; code single-use
  and expiry; refresh rotation (old token dead after use); access-token
  expiry pruning; state-file round-trip, atomic write, `0600` mode,
  corrupt-file recovery.
- **Consent flow over the assembled ASGI app** (Starlette's `TestClient`,
  measured importable in an extra-only venv; note plain `httpx` is *not*
  in the tree — mcp 2.0 depends on `httpx2` — so do not reach for it):
  full happy path — `POST /register`, `GET /authorize` → 302 to consent,
  `POST /consent` with the right key → 302 with `code` and `state`,
  `POST /token` with PKCE verifier → tokens, `POST /mcp` with the access
  token → 200. Wrong key re-renders and does not mint a code; a code
  replay fails; wrong `code_verifier` fails.
- **Route-surface assertions:** the well-known documents and `/register`
  answer without credentials; `/mcp` without a token is 401 and its
  `WWW-Authenticate` names the resource metadata URL (the exact sequence
  #42 logged, now succeeding).
- **Startup contract:** each row of the table above, as `main()` tests in
  the style of the existing `test_refuses_to_start_without_token_or_no_auth`.
- The claude.ai handshake end-to-end remains a manual validation step, as
  phase 1's was: external service, not automatable from the suite.

## Migration and cleanup

- Delete `_BearerAuth` and its tests (`TestBearerAuth`); the module
  docstring paragraph explaining it is rewritten to describe SDK
  delegation.
- Replace `--token` / `BUNNYFORGE_MCP_TOKEN` with `--auth-key` /
  `BUNNYFORGE_MCP_KEY` everywhere, including docs.
- Amend the superseded section of `2026-08-16-serve-mcp-design.md` with a
  pointer to this document (one-line edit, not a rewrite).
- Document the connector setup: Client ID / Secret **left blank**; the
  named-tunnel recipe; key generation; the state-file reset move.
- Coordinate with #46 on `--public-host` (single definition, two
  consumers). Neither blocks the other.

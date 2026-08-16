# serve-mcp OAuth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `_BearerAuth` with a self-hosted single-user OAuth
authorization server (SDK DCR machinery + a GM-key consent page) so the
claude.ai custom connector can authenticate against `bunnyforge serve-mcp`.

**Architecture:** A new module `src/bunnyforge/_mcp_auth.py` implements the
SDK's `OAuthAuthorizationServerProvider` over four in-process dicts, with
clients and tokens persisted to a `0600` JSON state file under
`$XDG_STATE_HOME`. `serve_mcp.py` passes the provider plus `AuthSettings`
to `MCPServer`, which mounts the OAuth bootstrap routes publicly and guards
`/mcp` — the SDK auto-wraps the provider in `ProviderTokenVerifier`. The
one identity decision bunnyforge owns is a consent page (`/consent`,
mounted via `custom_route`) where the GM types a pre-shared key.

**Tech Stack:** Python ≥3.11, `mcp` SDK 2.0 (the existing `[mcp]` extra —
**no new dependencies**), `unittest`, Starlette `TestClient` for HTTP tests.

**Spec:** `docs/superpowers/specs/2026-08-16-serve-mcp-oauth-design.md` —
read it first; every SDK behavior it cites was measured against mcp 2.0.0.
Evidence trail: GitHub issue #42.

## Global Constraints

- **Never commit to main** (protected: PRs required, CI `suite (3.11/3.12/3.13)`
  must pass). Work in a git worktree on branch `feat/serve-mcp-oauth`, based
  off current `main` — merge the spec/plan PR first if it is still open;
  if you must base off `docs/serve-mcp-oauth-design` instead, flag the
  stacked PR loudly per AGENTS.md.
- **Worktree venv before any test run:** `python3 -m venv .venv && ./.venv/bin/pip install -e '.[mcp]'`,
  then assert resolution:
  `./.venv/bin/python -c "import bunnyforge,pathlib; p=pathlib.Path(bunnyforge.__file__).resolve(); assert p.is_relative_to(pathlib.Path.cwd().resolve()), p; print(p)"`.
  Never pip install into system site-packages.
- **Zero-dependency core:** `serve_mcp.py` imports the SDK only inside
  function bodies (`cli.py` imports every subcommand unconditionally and
  must keep working on bare Python). The new `_mcp_auth.py` MAY import
  `mcp` at module top — it is itself imported only inside `serve_mcp.py`
  function bodies.
- **Tests are `unittest`, not pytest.** Follow the existing `HAVE_MCP`
  skip discipline (`tests/test_serve_mcp.py:12`). Run with
  `./.venv/bin/python -m unittest <module> -v`.
- **`MCPServer` must NOT receive both `auth_server_provider` and
  `token_verifier`** — that combination raises `ValueError`. Pass the
  provider alone; the SDK wraps it in `ProviderTokenVerifier` itself.
- Plain `httpx` is **not** installed (mcp 2.0 depends on `httpx2`). Use
  `starlette.testclient.TestClient` (measured importable in the extra-only
  venv). `python-multipart` and `anyio` are already in the tree.
- **Credentials never reach git.** The state file lives at
  `$XDG_STATE_HOME/bunnyforge/mcp-oauth-state.json` (default
  `~/.local/state/...`); tests use temp dirs.
- Flag spellings are fixed by the spec: `--auth-key` / `BUNNYFORGE_MCP_KEY`
  (replacing `--token` / `BUNNYFORGE_MCP_TOKEN`, no aliases), `--no-auth`
  kept, `--public-host` added (issuer derivation ONLY — its
  `transport_security` plumbing is issue #46, out of scope here).
- Lifetimes (spec): consent transaction 600 s, authorization code 300 s,
  access token 3600 s, refresh token 30 days (rotating). Client cap 32.
- Commit after every task; end each commit message with the model's
  `Co-Authored-By:` trailer.

---

### Task 1: Provider skeleton — client registration, state persistence

**Files:**
- Create: `src/bunnyforge/_mcp_auth.py`
- Test: `tests/test_mcp_auth.py` (create)

**Interfaces:**
- Consumes: `mcp.server.auth.provider.OAuthAuthorizationServerProvider`,
  `mcp.shared.auth.OAuthClientInformationFull`,
  `mcp.server.auth.provider.AccessToken` / `RefreshToken` (pydantic models).
- Produces (later tasks rely on these exact names):
  - `default_state_path() -> pathlib.Path`
  - `SingleUserOAuthProvider(gm_key: str, issuer_url: str, state_path: Path)`
    with attribute `issuer_url: str` (rstripped, no trailing slash),
    internal dicts `_clients`, `_txns`, `_codes`, `_access`, `_refresh`,
    methods `_save()`, `_load()`, and async `register_client` / `get_client`.
  - Module constants `MAX_CLIENTS = 32`, `TXN_TTL = 600`, `CODE_TTL = 300`,
    `ACCESS_TTL = 3600`, `REFRESH_TTL = 30 * 24 * 3600`, `_KEY_DELAY = 1.0`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_mcp_auth.py`:

```python
import importlib.util
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# The MCP SDK is an optional extra; _mcp_auth imports it at module top, so
# every test here skips on a bare Python, matching test_serve_mcp.py.
HAVE_MCP = importlib.util.find_spec("mcp") is not None
if HAVE_MCP:
    from bunnyforge import _mcp_auth
    from bunnyforge._mcp_auth import SingleUserOAuthProvider


def client_record(client_id: str):
    from mcp.shared.auth import OAuthClientInformationFull
    return OAuthClientInformationFull(
        client_id=client_id,
        client_secret="s3cret",
        client_name="Claude",
        redirect_uris=["http://localhost:9999/cb"],
    )


@unittest.skipUnless(HAVE_MCP, "requires bunnyforge[mcp]")
class TestClientRegistry(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.state = root / "state" / "mcp-oauth-state.json"
        self.provider = SingleUserOAuthProvider(
            gm_key="k", issuer_url="http://127.0.0.1:8000/",
            state_path=self.state)

    def test_issuer_url_is_rstripped(self):
        self.assertEqual(self.provider.issuer_url, "http://127.0.0.1:8000")

    async def test_register_then_get_roundtrips(self):
        await self.provider.register_client(client_record("c1"))
        got = await self.provider.get_client("c1")
        self.assertEqual(got.client_name, "Claude")
        self.assertIsNone(await self.provider.get_client("nope"))

    async def test_registration_capped_evicts_oldest(self):
        for i in range(_mcp_auth.MAX_CLIENTS + 1):
            await self.provider.register_client(client_record(f"c{i}"))
        self.assertIsNone(await self.provider.get_client("c0"))
        self.assertIsNotNone(await self.provider.get_client("c1"))
        self.assertEqual(len(self.provider._clients), _mcp_auth.MAX_CLIENTS)

    async def test_state_file_is_0600_and_survives_restart(self):
        await self.provider.register_client(client_record("c1"))
        mode = stat.S_IMODE(os.stat(self.state).st_mode)
        self.assertEqual(mode, 0o600)
        reborn = SingleUserOAuthProvider(
            gm_key="k", issuer_url="http://127.0.0.1:8000",
            state_path=self.state)
        got = await reborn.get_client("c1")
        self.assertEqual(got.client_secret, "s3cret")

    async def test_corrupt_state_file_starts_empty_not_crashed(self):
        self.state.parent.mkdir(parents=True)
        self.state.write_text("{not json", encoding="utf-8")
        with mock.patch("sys.stderr"):
            provider = SingleUserOAuthProvider(
                gm_key="k", issuer_url="http://127.0.0.1:8000",
                state_path=self.state)
        self.assertIsNone(await provider.get_client("c1"))
        # first successful save replaces the corrupt file
        await provider.register_client(client_record("c1"))
        json.loads(self.state.read_text(encoding="utf-8"))


@unittest.skipUnless(HAVE_MCP, "requires bunnyforge[mcp]")
class TestDefaultStatePath(unittest.TestCase):

    def test_honours_xdg_state_home(self):
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": "/x/state"}):
            self.assertEqual(_mcp_auth.default_state_path(),
                             Path("/x/state/bunnyforge/mcp-oauth-state.json"))

    def test_defaults_under_home(self):
        with mock.patch.dict(os.environ, clear=False) as env:
            os.environ.pop("XDG_STATE_HOME", None)
            self.assertEqual(
                _mcp_auth.default_state_path(),
                Path.home() / ".local/state/bunnyforge/mcp-oauth-state.json")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/bin/python -m unittest tests.test_mcp_auth -v`
Expected: FAIL/ERROR with `ModuleNotFoundError: No module named 'bunnyforge._mcp_auth'`

- [ ] **Step 3: Write the module**

Create `src/bunnyforge/_mcp_auth.py`:

```python
#!/usr/bin/env python3
"""_mcp_auth.py — single-user OAuth authorization server for serve-mcp.

claude.ai's connector speaks OAuth with Dynamic Client Registration and
nothing else (issue #42), so serve-mcp runs the smallest authorization
server that satisfies it: the SDK's handlers do every protocol step, and
the one identity decision bunnyforge owns — "is this the GM?" — is a
pre-shared key checked on a consent page.

This module imports the mcp SDK at top level. That is safe only because
serve_mcp.py imports THIS module inside function bodies; a bare Python
(no bunnyforge[mcp] extra) never loads it.

Tokens are opaque random strings looked up server-side — no JWTs, no
signing keys. Clients and tokens persist to a 0600 JSON file outside any
git repo, so a laptop restart does not force a full re-auth in claude.ai;
consent transactions and authorization codes live minutes and stay
memory-only.
"""

from __future__ import annotations

import hmac
import html
import json
import os
import secrets
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

MAX_CLIENTS = 32          # /register is public by RFC 7591; bound its memory
TXN_TTL = 600             # seconds a consent page may wait for the GM
CODE_TTL = 300
ACCESS_TTL = 3600
REFRESH_TTL = 30 * 24 * 3600
_KEY_DELAY = 1.0          # pause after a wrong key; patched to 0 in tests


def default_state_path() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state"
    return Path(base) / "bunnyforge" / "mcp-oauth-state.json"


@dataclass
class _Txn:
    """One consent-in-flight: the authorize params parked while the GM
    decides, keyed by an unguessable transaction id."""
    params: AuthorizationParams
    client_id: str
    expires_at: float


class SingleUserOAuthProvider(
        OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken,
                                         AccessToken]):
    """The nine provider methods over four dicts and one state file."""

    def __init__(self, gm_key: str, issuer_url: str, state_path: Path):
        self._gm_key = gm_key
        self.issuer_url = issuer_url.rstrip("/")
        self._state_path = state_path
        self._clients: dict[str, OAuthClientInformationFull] = {}
        self._txns: dict[str, _Txn] = {}
        self._codes: dict[str, AuthorizationCode] = {}
        self._access: dict[str, AccessToken] = {}
        self._refresh: dict[str, RefreshToken] = {}
        self._load()

    # -- persistence -------------------------------------------------------

    def _load(self) -> None:
        try:
            raw = json.loads(self._state_path.read_text(encoding="utf-8"))
            clients = {c: OAuthClientInformationFull.model_validate(v)
                       for c, v in raw.get("clients", {}).items()}
            access = {t: AccessToken.model_validate(v)
                      for t, v in raw.get("access_tokens", {}).items()}
            refresh = {t: RefreshToken.model_validate(v)
                       for t, v in raw.get("refresh_tokens", {}).items()}
        except FileNotFoundError:
            return
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            # Losing token state is an inconvenience, not an outage: the
            # connector just re-runs the flow. Keep the corrupt file until
            # the first good save renames over it.
            print(f"warning: ignoring unreadable auth state "
                  f"{self._state_path}: {exc}", file=sys.stderr)
            return
        now = time.time()
        self._clients = clients
        self._access = {t: a for t, a in access.items()
                        if not a.expires_at or a.expires_at > now}
        self._refresh = {t: r for t, r in refresh.items()
                         if not r.expires_at or r.expires_at > now}

    def _save(self) -> None:
        data = {
            "clients": {c: v.model_dump(mode="json")
                        for c, v in self._clients.items()},
            "access_tokens": {t: v.model_dump(mode="json")
                              for t, v in self._access.items()},
            "refresh_tokens": {t: v.model_dump(mode="json")
                               for t, v in self._refresh.items()},
        }
        self._state_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = self._state_path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(tmp, self._state_path)

    # -- client registry (RFC 7591; the SDK handler mints the credentials) -

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self._clients.get(client_id)

    async def register_client(
            self, client_info: OAuthClientInformationFull) -> None:
        self._clients[client_info.client_id] = client_info
        while len(self._clients) > MAX_CLIENTS:
            evicted = next(iter(self._clients))
            del self._clients[evicted]
            self._access = {t: a for t, a in self._access.items()
                            if a.client_id != evicted}
            self._refresh = {t: r for t, r in self._refresh.items()
                             if r.client_id != evicted}
        self._save()
```

(The remaining provider methods arrive in Task 2; the class is complete
enough for this task's tests.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/bin/python -m unittest tests.test_mcp_auth -v`
Expected: PASS (all tests in the module)

- [ ] **Step 5: Confirm bare-Python safety is untouched**

Run: `./.venv/bin/python -c "import bunnyforge.serve_mcp; print('ok')"` and
`python3 -c "import bunnyforge.cli; print('bare ok')"`
Expected: both print. (`_mcp_auth` is not yet imported anywhere, and the
system python must never gain an `mcp` dependency through this work.)

- [ ] **Step 6: Commit**

```bash
git add src/bunnyforge/_mcp_auth.py tests/test_mcp_auth.py
git commit -m "feat(serve-mcp): OAuth provider skeleton — client registry + persisted state"
```

---

### Task 2: Consent transactions, codes, tokens — the rest of the provider

**Files:**
- Modify: `src/bunnyforge/_mcp_auth.py` (append methods to
  `SingleUserOAuthProvider`)
- Test: `tests/test_mcp_auth.py` (append)

**Interfaces:**
- Consumes: Task 1's class and constants.
- Produces (Task 3 and the SDK rely on these exact signatures):
  - async `authorize(client, params) -> str` — parks a `_Txn`, returns
    `f"{self.issuer_url}/consent?txn=<id>"`.
  - `check_key(submitted: str) -> bool` — constant-time.
  - `consent_context(txn: str) -> dict | None` — `{"client_name": str}` or
    `None` when unknown/expired.
  - `grant(txn: str) -> str | None` — consumes the txn, mints a code,
    returns the client redirect URL with `code` and `state` appended;
    `None` when the txn is unknown/expired.
  - async `load_authorization_code`, `exchange_authorization_code`,
    `load_refresh_token`, `exchange_refresh_token`, `load_access_token`,
    `revoke_token` — the provider contract the SDK handlers call.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mcp_auth.py`:

```python
def auth_params():
    from mcp.server.auth.provider import AuthorizationParams
    return AuthorizationParams(
        state="st8", scopes=[], code_challenge="chal",
        redirect_uri="http://localhost:9999/cb",
        redirect_uri_provided_explicitly=True)


@unittest.skipUnless(HAVE_MCP, "requires bunnyforge[mcp]")
class TestConsentAndTokens(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.provider = SingleUserOAuthProvider(
            gm_key="sekrit", issuer_url="http://127.0.0.1:8000",
            state_path=root / "state.json")

    async def _register(self, cid="c1"):
        record = client_record(cid)
        await self.provider.register_client(record)
        return record

    async def test_authorize_parks_txn_and_points_at_consent(self):
        client = await self._register()
        url = await self.provider.authorize(client, auth_params())
        self.assertTrue(
            url.startswith("http://127.0.0.1:8000/consent?txn="), url)
        txn = url.split("txn=")[1]
        self.assertEqual(self.provider.consent_context(txn),
                         {"client_name": "Claude"})

    async def test_consent_context_unknown_or_expired_is_none(self):
        client = await self._register()
        url = await self.provider.authorize(client, auth_params())
        txn = url.split("txn=")[1]
        self.assertIsNone(self.provider.consent_context("bogus"))
        future = time.time() + _mcp_auth.TXN_TTL + 1
        with mock.patch("bunnyforge._mcp_auth.time.time",
                        return_value=future):
            self.assertIsNone(self.provider.consent_context(txn))

    def test_check_key_right_wrong_and_near_miss(self):
        self.assertTrue(self.provider.check_key("sekrit"))
        self.assertFalse(self.provider.check_key("wrong"))
        self.assertFalse(self.provider.check_key("sek"))
        self.assertFalse(self.provider.check_key(""))

    async def test_grant_consumes_txn_and_mints_single_use_code(self):
        client = await self._register()
        url = await self.provider.authorize(client, auth_params())
        txn = url.split("txn=")[1]
        redirect = self.provider.grant(txn)
        self.assertIn("code=", redirect)
        self.assertIn("state=st8", redirect)
        self.assertTrue(redirect.startswith("http://localhost:9999/cb?"))
        self.assertIsNone(self.provider.grant(txn))  # consumed

    async def _grant_code(self, client):
        url = await self.provider.authorize(client, auth_params())
        redirect = self.provider.grant(url.split("txn=")[1])
        code = redirect.split("code=")[1].split("&")[0]
        return await self.provider.load_authorization_code(client, code)

    async def test_code_exchange_and_replay(self):
        from mcp.server.auth.provider import TokenError
        client = await self._register()
        auth_code = await self._grant_code(client)
        self.assertEqual(auth_code.code_challenge, "chal")
        tokens = await self.provider.exchange_authorization_code(
            client, auth_code)
        self.assertEqual(tokens.token_type, "Bearer")
        self.assertEqual(tokens.expires_in, _mcp_auth.ACCESS_TTL)
        with self.assertRaises(TokenError):
            await self.provider.exchange_authorization_code(client, auth_code)

    async def test_code_expires(self):
        client = await self._register()
        auth_code = await self._grant_code(client)
        future = time.time() + _mcp_auth.CODE_TTL + 1
        with mock.patch("bunnyforge._mcp_auth.time.time",
                        return_value=future):
            self.assertIsNone(await self.provider.load_authorization_code(
                client, auth_code.code))

    async def test_wrong_client_cannot_load_anothers_code(self):
        client = await self._register()
        other = await self._register("c2")
        auth_code = await self._grant_code(client)
        self.assertIsNone(await self.provider.load_authorization_code(
            other, auth_code.code))

    async def test_access_token_verifies_then_expires(self):
        client = await self._register()
        auth_code = await self._grant_code(client)
        tokens = await self.provider.exchange_authorization_code(
            client, auth_code)
        at = await self.provider.load_access_token(tokens.access_token)
        self.assertEqual(at.client_id, "c1")
        future = time.time() + _mcp_auth.ACCESS_TTL + 1
        with mock.patch("bunnyforge._mcp_auth.time.time",
                        return_value=future):
            self.assertIsNone(await self.provider.load_access_token(
                tokens.access_token))

    async def test_refresh_rotates(self):
        from mcp.server.auth.provider import TokenError
        client = await self._register()
        auth_code = await self._grant_code(client)
        first = await self.provider.exchange_authorization_code(
            client, auth_code)
        rt = await self.provider.load_refresh_token(
            client, first.refresh_token)
        second = await self.provider.exchange_refresh_token(client, rt, [])
        self.assertNotEqual(first.refresh_token, second.refresh_token)
        # the old refresh token died with the rotation
        self.assertIsNone(await self.provider.load_refresh_token(
            client, first.refresh_token))
        with self.assertRaises(TokenError):
            await self.provider.exchange_refresh_token(client, rt, [])

    async def test_tokens_survive_restart_but_txns_do_not(self):
        client = await self._register()
        url = await self.provider.authorize(client, auth_params())
        txn = url.split("txn=")[1]
        auth_code = await self._grant_code(client)
        tokens = await self.provider.exchange_authorization_code(
            client, auth_code)
        reborn = SingleUserOAuthProvider(
            gm_key="sekrit", issuer_url="http://127.0.0.1:8000",
            state_path=self.provider._state_path)
        self.assertIsNotNone(
            await reborn.load_access_token(tokens.access_token))
        self.assertIsNone(reborn.consent_context(txn))

    async def test_revoke_deletes(self):
        client = await self._register()
        auth_code = await self._grant_code(client)
        tokens = await self.provider.exchange_authorization_code(
            client, auth_code)
        at = await self.provider.load_access_token(tokens.access_token)
        await self.provider.revoke_token(at)
        self.assertIsNone(
            await self.provider.load_access_token(tokens.access_token))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/bin/python -m unittest tests.test_mcp_auth -v`
Expected: Task 1 tests PASS; every `TestConsentAndTokens` test ERRORS with
`AttributeError` (missing `authorize` / `grant` / …).

- [ ] **Step 3: Implement the remaining provider methods**

Append inside `SingleUserOAuthProvider` (after `register_client`):

```python
    # -- consent -----------------------------------------------------------
    # authorize() is called by the SDK's /authorize handler, which 302s the
    # GM's browser to whatever URL we return. We park the request under an
    # unguessable transaction id and send the browser to our consent page;
    # grant() is the consent POST handler redeeming it.

    async def authorize(self, client: OAuthClientInformationFull,
                        params: AuthorizationParams) -> str:
        self._prune()
        txn = secrets.token_urlsafe(32)
        self._txns[txn] = _Txn(params=params, client_id=client.client_id,
                               expires_at=time.time() + TXN_TTL)
        return f"{self.issuer_url}/consent?txn={txn}"

    def check_key(self, submitted: str) -> bool:
        return hmac.compare_digest(submitted.encode(), self._gm_key.encode())

    def consent_context(self, txn: str) -> dict | None:
        t = self._txns.get(txn)
        if t is None or t.expires_at < time.time():
            self._txns.pop(txn, None)
            return None
        client = self._clients.get(t.client_id)
        name = (client.client_name if client else None) or t.client_id
        return {"client_name": name}

    def grant(self, txn: str) -> str | None:
        t = self._txns.pop(txn, None)
        if t is None or t.expires_at < time.time():
            return None
        code = secrets.token_urlsafe(32)
        p = t.params
        self._codes[code] = AuthorizationCode(
            code=code, scopes=p.scopes or [],
            expires_at=time.time() + CODE_TTL,
            client_id=t.client_id, code_challenge=p.code_challenge,
            redirect_uri=p.redirect_uri,
            redirect_uri_provided_explicitly=p.redirect_uri_provided_explicitly,
            resource=p.resource)
        return construct_redirect_uri(str(p.redirect_uri),
                                      code=code, state=p.state)

    def _prune(self) -> None:
        now = time.time()
        self._txns = {k: v for k, v in self._txns.items()
                      if v.expires_at > now}
        self._codes = {k: v for k, v in self._codes.items()
                       if v.expires_at > now}

    # -- codes and tokens (called by the SDK's /token handler; PKCE is
    # verified there, not here) ------------------------------------------

    async def load_authorization_code(
            self, client: OAuthClientInformationFull,
            authorization_code: str) -> AuthorizationCode | None:
        ac = self._codes.get(authorization_code)
        if ac is None or ac.client_id != client.client_id:
            return None
        if ac.expires_at < time.time():
            del self._codes[authorization_code]
            return None
        return ac

    async def exchange_authorization_code(
            self, client: OAuthClientInformationFull,
            authorization_code: AuthorizationCode) -> OAuthToken:
        if self._codes.pop(authorization_code.code, None) is None:
            raise TokenError("invalid_grant",
                             "authorization code already used")
        return self._issue(client.client_id, authorization_code.scopes)

    async def load_refresh_token(
            self, client: OAuthClientInformationFull,
            refresh_token: str) -> RefreshToken | None:
        rt = self._refresh.get(refresh_token)
        if rt is None or rt.client_id != client.client_id:
            return None
        if rt.expires_at and rt.expires_at < time.time():
            del self._refresh[refresh_token]
            self._save()
            return None
        return rt

    async def exchange_refresh_token(
            self, client: OAuthClientInformationFull,
            refresh_token: RefreshToken, scopes: list[str]) -> OAuthToken:
        if self._refresh.pop(refresh_token.token, None) is None:
            raise TokenError("invalid_grant", "refresh token already used")
        return self._issue(client.client_id,
                           scopes or refresh_token.scopes)

    async def load_access_token(self, token: str) -> AccessToken | None:
        at = self._access.get(token)
        if at is None:
            return None
        if at.expires_at and at.expires_at < time.time():
            del self._access[token]
            return None
        return at

    async def revoke_token(
            self, token: AccessToken | RefreshToken) -> None:
        self._access.pop(token.token, None)
        self._refresh.pop(token.token, None)
        self._save()

    def _issue(self, client_id: str, scopes: list[str]) -> OAuthToken:
        now = time.time()
        access = secrets.token_urlsafe(32)
        refresh = secrets.token_urlsafe(32)
        self._access[access] = AccessToken(
            token=access, client_id=client_id, scopes=scopes,
            expires_at=int(now + ACCESS_TTL))
        self._refresh[refresh] = RefreshToken(
            token=refresh, client_id=client_id, scopes=scopes,
            expires_at=int(now + REFRESH_TTL))
        self._save()
        return OAuthToken(access_token=access, token_type="Bearer",
                          expires_in=ACCESS_TTL,
                          scope=" ".join(scopes) or None,
                          refresh_token=refresh)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/bin/python -m unittest tests.test_mcp_auth -v`
Expected: PASS (all tests in the module)

- [ ] **Step 5: Commit**

```bash
git add src/bunnyforge/_mcp_auth.py tests/test_mcp_auth.py
git commit -m "feat(serve-mcp): consent transactions, codes, and rotating tokens"
```

---

### Task 3: The consent page

**Files:**
- Modify: `src/bunnyforge/_mcp_auth.py` (append at module level)
- Test: `tests/test_mcp_auth.py` (append)

**Interfaces:**
- Consumes: `SingleUserOAuthProvider.consent_context` / `check_key` /
  `grant` (Task 2), `_KEY_DELAY` (Task 1).
- Produces: `consent_endpoint(provider: SingleUserOAuthProvider,
  campaign: str)` returning an async Starlette endpoint
  `async (request) -> Response` handling `GET` and `POST /consent`.
  Task 4 mounts it via `server.custom_route("/consent", methods=["GET", "POST"])`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mcp_auth.py`. These exercise the endpoint through a
minimal Starlette app so form parsing and redirects are real:

```python
@unittest.skipUnless(HAVE_MCP, "requires bunnyforge[mcp]")
class TestConsentEndpoint(unittest.TestCase):

    def setUp(self):
        from starlette.applications import Starlette
        from starlette.routing import Route
        from starlette.testclient import TestClient
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.provider = SingleUserOAuthProvider(
            gm_key="sekrit", issuer_url="http://127.0.0.1:8000",
            state_path=root / "state.json")
        endpoint = _mcp_auth.consent_endpoint(self.provider, "Testmere")
        app = Starlette(routes=[
            Route("/consent", endpoint, methods=["GET", "POST"])])
        self.client = TestClient(app, follow_redirects=False)
        self.enterContext(
            mock.patch("bunnyforge._mcp_auth._KEY_DELAY", 0))

    def _txn(self):
        import asyncio
        record = client_record("c1")
        asyncio.run(self.provider.register_client(record))
        url = asyncio.run(self.provider.authorize(record, auth_params()))
        return url.split("txn=")[1]

    def test_get_unknown_txn_is_400_with_recovery_text(self):
        resp = self.client.get("/consent", params={"txn": "bogus"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("claude.ai", resp.text)
        self.assertEqual(resp.headers["cache-control"], "no-store")

    def test_get_renders_form_naming_client_and_campaign(self):
        resp = self.client.get("/consent", params={"txn": self._txn()})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Claude", resp.text)
        self.assertIn("Testmere", resp.text)
        self.assertIn('name="key"', resp.text)
        self.assertEqual(resp.headers["cache-control"], "no-store")

    def test_post_wrong_key_rerenders_and_mints_nothing(self):
        txn = self._txn()
        resp = self.client.post("/consent",
                                data={"txn": txn, "key": "wrong"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("try again", resp.text.lower())
        self.assertEqual(self.provider._codes, {})
        # the txn survives a wrong key: the GM can retry
        self.assertIsNotNone(self.provider.consent_context(txn))

    def test_post_right_key_redirects_with_code_and_state(self):
        resp = self.client.post(
            "/consent", data={"txn": self._txn(), "key": "sekrit"})
        self.assertEqual(resp.status_code, 302)
        location = resp.headers["location"]
        self.assertTrue(location.startswith("http://localhost:9999/cb?"))
        self.assertIn("code=", location)
        self.assertIn("state=st8", location)

    def test_post_dead_txn_is_400(self):
        resp = self.client.post("/consent",
                                data={"txn": "bogus", "key": "sekrit"})
        self.assertEqual(resp.status_code, 400)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/bin/python -m unittest tests.test_mcp_auth.TestConsentEndpoint -v`
Expected: ERROR — `AttributeError: module 'bunnyforge._mcp_auth' has no attribute 'consent_endpoint'`

- [ ] **Step 3: Implement the endpoint**

Append to `_mcp_auth.py` at module level:

```python
# One page, used once per token lifetime by one person: inline HTML, no
# styling, served no-store. The only secret it ever sees is the GM key.
_CONSENT_PAGE = """<!doctype html>
<title>bunnyforge — authorize access</title>
<h1>Authorize {client} to access campaign “{campaign}”?</h1>
{error}<form method="post" action="/consent">
  <input type="hidden" name="txn" value="{txn}">
  <label>GM key: <input type="password" name="key" autofocus></label>
  <button type="submit">Authorize</button>
</form>
"""


def consent_endpoint(provider: SingleUserOAuthProvider, campaign: str):
    """Build the GET/POST /consent endpoint for one provider + campaign."""
    import anyio
    from starlette.responses import (HTMLResponse, PlainTextResponse,
                                     RedirectResponse)

    no_store = {"Cache-Control": "no-store"}

    def dead_txn() -> PlainTextResponse:
        return PlainTextResponse(
            "This authorization link is no longer valid. "
            "Retry the connection from claude.ai.",
            status_code=400, headers=no_store)

    def page(txn: str, client_name: str, error: str = "") -> HTMLResponse:
        body = _CONSENT_PAGE.format(
            client=html.escape(client_name),
            campaign=html.escape(campaign),
            txn=html.escape(txn),
            error=f"<p><strong>{error}</strong></p>\n" if error else "")
        return HTMLResponse(body, headers=no_store)

    async def consent(request):
        if request.method == "GET":
            txn = request.query_params.get("txn", "")
            ctx = provider.consent_context(txn)
            if ctx is None:
                return dead_txn()
            return page(txn, ctx["client_name"])
        form = await request.form()
        txn = str(form.get("txn", ""))
        ctx = provider.consent_context(txn)
        if ctx is None:
            return dead_txn()
        if not provider.check_key(str(form.get("key", ""))):
            await anyio.sleep(_KEY_DELAY)
            return page(txn, ctx["client_name"], "Wrong key — try again.")
        url = provider.grant(txn)
        if url is None:
            return dead_txn()
        return RedirectResponse(url, status_code=302, headers=no_store)

    return consent
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/bin/python -m unittest tests.test_mcp_auth -v`
Expected: PASS (all tests in the module)

- [ ] **Step 5: Commit**

```bash
git add src/bunnyforge/_mcp_auth.py tests/test_mcp_auth.py
git commit -m "feat(serve-mcp): consent page — the one identity decision bunnyforge owns"
```

---

### Task 4: Wire OAuth into build_server; route-surface and end-to-end tests

**Files:**
- Modify: `src/bunnyforge/serve_mcp.py` (`build_server` only)
- Test: `tests/test_mcp_auth.py` (append)

**Interfaces:**
- Consumes: `SingleUserOAuthProvider` (attribute `issuer_url`),
  `consent_endpoint` (Task 3).
- Produces: `build_server(store, *, allow_direct_edits=False, oauth=None)`
  — `oauth` is a `SingleUserOAuthProvider` or `None` (unauthenticated,
  today's `--no-auth` semantics). Task 5's `main()` calls this.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mcp_auth.py`. Note three deliberate choices:
`base_url="http://127.0.0.1:8000"` keeps the Host header inside the SDK's
auto-enabled localhost DNS-rebinding allowlist (`testserver` would 421 —
the #46 failure class); `with TestClient(...)` runs the lifespan so the
session manager behind `/mcp` starts; the issuer given to the provider
matches that base_url so consent URLs are directly fetchable.

```python
def scaffold_store(case: unittest.TestCase):
    """Minimal workspace, same shape as test_serve_mcp.scaffold."""
    from bunnyforge import _config, _store
    root = Path(case.enterContext(tempfile.TemporaryDirectory()))
    (root / "campaign.toml").write_text(
        '[campaign]\nnamespace = "testwiki"\nname = "Testmere"\n',
        encoding="utf-8")
    (root / "NPCs").mkdir()
    return _store.WorkspaceStore(_config.open_workspace(root))


def pkce_pair():
    import base64
    import hashlib
    verifier = "v" * 43
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return verifier, challenge


@unittest.skipUnless(HAVE_MCP, "requires bunnyforge[mcp]")
class TestOAuthOverHTTP(unittest.TestCase):
    """The discovery sequence from issue #42, now ending in tokens."""

    ISSUER = "http://127.0.0.1:8000"

    def setUp(self):
        from starlette.testclient import TestClient
        from bunnyforge import serve_mcp
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.provider = SingleUserOAuthProvider(
            gm_key="sekrit", issuer_url=self.ISSUER,
            state_path=root / "state.json")
        server = serve_mcp.build_server(scaffold_store(self),
                                        oauth=self.provider)
        app = server.streamable_http_app(stateless_http=True)
        self.client = self.enterContext(
            TestClient(app, base_url=self.ISSUER, follow_redirects=False))
        self.enterContext(
            mock.patch("bunnyforge._mcp_auth._KEY_DELAY", 0))

    def test_discovery_documents_are_public(self):
        for path in ("/.well-known/oauth-authorization-server",
                     "/.well-known/oauth-protected-resource/mcp"):
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 200, path)
        meta = self.client.get(
            "/.well-known/oauth-authorization-server").json()
        self.assertEqual(meta["issuer"].rstrip("/"), self.ISSUER)
        self.assertTrue(meta["registration_endpoint"].endswith("/register"))

    def test_mcp_without_token_is_401_pointing_at_metadata(self):
        resp = self.client.post("/mcp", json={})
        self.assertEqual(resp.status_code, 401)
        self.assertIn("resource_metadata",
                      resp.headers.get("www-authenticate", ""))

    def test_full_flow_register_to_authenticated_mcp(self):
        # 1. Dynamic Client Registration (blank form fields in claude.ai)
        reg = self.client.post("/register", json={
            "client_name": "Claude",
            "redirect_uris": ["http://localhost:9999/cb"],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
        })
        self.assertEqual(reg.status_code, 201, reg.text)
        info = reg.json()

        # 2. Authorize → 302 to the consent page
        verifier, challenge = pkce_pair()
        auth = self.client.get("/authorize", params={
            "client_id": info["client_id"],
            "response_type": "code",
            "redirect_uri": "http://localhost:9999/cb",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "st8",
        })
        self.assertEqual(auth.status_code, 302, auth.text)
        consent_url = auth.headers["location"]
        self.assertIn("/consent?txn=", consent_url)

        # 3. GM types the key on the consent page
        self.assertEqual(self.client.get(consent_url).status_code, 200)
        txn = consent_url.split("txn=")[1]
        granted = self.client.post(
            "/consent", data={"txn": txn, "key": "sekrit"})
        self.assertEqual(granted.status_code, 302)
        code = granted.headers["location"].split("code=")[1].split("&")[0]

        # 4. Code + PKCE verifier + minted client secret → tokens
        tok = self.client.post("/token", data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "http://localhost:9999/cb",
            "client_id": info["client_id"],
            "client_secret": info["client_secret"],
            "code_verifier": verifier,
        })
        self.assertEqual(tok.status_code, 200, tok.text)
        tokens = tok.json()

        # 5. The bearer token opens /mcp (anything but 401 proves auth;
        #    protocol-level responses are the SDK's business)
        resp = self.client.post(
            "/mcp", json={},
            headers={"Authorization": f"Bearer {tokens['access_token']}"})
        self.assertNotEqual(resp.status_code, 401)

        # 6. Refresh rotates
        ref = self.client.post("/token", data={
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": info["client_id"],
            "client_secret": info["client_secret"],
        })
        self.assertEqual(ref.status_code, 200, ref.text)
        self.assertNotEqual(ref.json()["refresh_token"],
                            tokens["refresh_token"])
        replay = self.client.post("/token", data={
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": info["client_id"],
            "client_secret": info["client_secret"],
        })
        self.assertEqual(replay.status_code, 400)

    def test_wrong_pkce_verifier_is_rejected(self):
        reg = self.client.post("/register", json={
            "client_name": "Claude",
            "redirect_uris": ["http://localhost:9999/cb"],
        }).json()
        _, challenge = pkce_pair()
        auth = self.client.get("/authorize", params={
            "client_id": reg["client_id"], "response_type": "code",
            "redirect_uri": "http://localhost:9999/cb",
            "code_challenge": challenge, "code_challenge_method": "S256",
        })
        txn = auth.headers["location"].split("txn=")[1]
        granted = self.client.post(
            "/consent", data={"txn": txn, "key": "sekrit"})
        code = granted.headers["location"].split("code=")[1].split("&")[0]
        tok = self.client.post("/token", data={
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": "http://localhost:9999/cb",
            "client_id": reg["client_id"],
            "client_secret": reg["client_secret"],
            "code_verifier": "x" * 43,
        })
        self.assertEqual(tok.status_code, 400)

    def test_no_oauth_means_no_auth_routes_and_open_mcp(self):
        from starlette.testclient import TestClient
        from bunnyforge import serve_mcp
        server = serve_mcp.build_server(scaffold_store(self))
        app = server.streamable_http_app(stateless_http=True)
        with TestClient(app, base_url=self.ISSUER,
                        follow_redirects=False) as client:
            self.assertEqual(
                client.get("/.well-known/oauth-authorization-server")
                .status_code, 404)
            self.assertNotEqual(client.post("/mcp", json={})
                                .status_code, 401)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/bin/python -m unittest tests.test_mcp_auth.TestOAuthOverHTTP -v`
Expected: ERROR — `build_server() got an unexpected keyword argument 'oauth'`

- [ ] **Step 3: Extend build_server**

In `src/bunnyforge/serve_mcp.py`, replace the current
`def build_server(...)` signature and `MCPServer("bunnyforge")` call
(everything down to `server = MCPServer("bunnyforge")`) with:

```python
def build_server(store: WorkspaceStore, *, allow_direct_edits: bool = False,
                 oauth=None):
    """Assemble the MCP server over one workspace store.

    Imports the SDK, so a caller without the extra gets ModuleNotFoundError;
    main() translates that into the install hint.

    With `oauth` (a SingleUserOAuthProvider), the SDK mounts the OAuth
    bootstrap routes publicly and guards /mcp — passing the provider alone
    is deliberate: MCPServer refuses a provider AND a token_verifier, and
    wraps the provider in its own ProviderTokenVerifier. With oauth=None
    the app is unauthenticated (--no-auth semantics).

    Tool docstrings are not decoration — they are what the remote agent reads
    to decide whether to call a tool, so they say when to use it, not merely
    what it does.
    """
    from mcp.server import MCPServer

    if oauth is None:
        server = MCPServer("bunnyforge")
    else:
        from mcp.server.auth.settings import (AuthSettings,
                                              ClientRegistrationOptions)
        from bunnyforge._mcp_auth import consent_endpoint

        server = MCPServer(
            "bunnyforge",
            auth_server_provider=oauth,
            auth=AuthSettings(
                issuer_url=oauth.issuer_url,
                resource_server_url=f"{oauth.issuer_url}/mcp",
                client_registration_options=ClientRegistrationOptions(
                    enabled=True),
            ),
        )
        server.custom_route("/consent", methods=["GET", "POST"])(
            consent_endpoint(oauth, store.ws.config.name))
```

The tool registrations that follow are unchanged.

- [ ] **Step 4: Run the new tests, then the whole suite**

Run: `./.venv/bin/python -m unittest tests.test_mcp_auth -v`
Expected: PASS. (`tests.test_serve_mcp` still passes too — `build_server`'s
new keyword defaults to `None`.)

Run: `./.venv/bin/python -m unittest discover -s tests -v 2>&1 | tail -5`
Expected: OK (some skips on unrelated suites are pre-existing).

- [ ] **Step 5: Commit**

```bash
git add src/bunnyforge/serve_mcp.py tests/test_mcp_auth.py
git commit -m "feat(serve-mcp): delegate auth topology to the SDK — DCR to tokens end-to-end"
```

---

### Task 5: CLI — new flags, startup contract, delete _BearerAuth

**Files:**
- Modify: `src/bunnyforge/serve_mcp.py` (module docstring, constants,
  delete `_BearerAuth`, `build_parser`, `main`)
- Modify: `tests/test_serve_mcp.py` (delete `TestBearerAuth`, rewrite
  startup-contract tests)

**Interfaces:**
- Consumes: `build_server(store, *, allow_direct_edits, oauth)` (Task 4),
  `SingleUserOAuthProvider`, `default_state_path` (Task 1).
- Produces: the shipped CLI. `KEY_ENV = "BUNNYFORGE_MCP_KEY"` replaces
  `TOKEN_ENV`; flags `--auth-key`, `--public-host`, `--no-auth`;
  `--token` is gone.

- [ ] **Step 1: Rewrite the startup-contract tests**

In `tests/test_serve_mcp.py`: delete the entire `TestBearerAuth` class and
replace the existing startup test (`test_refuses_to_start_without_token_or_no_auth`
and any sibling asserting `--token` behavior) with:

```python
class TestStartupContract(unittest.TestCase):
    """Default-deny: the spec's startup matrix, refusal rows.

    These run on bare Python: every refusal fires before the SDK import.
    """

    def setUp(self):
        store = scaffold(self)
        self.ws_args = ["--workspace", str(store.ws.root)]
        self.enterContext(mock.patch.dict(
            os.environ, {"BUNNYFORGE_MCP_KEY": ""}))

    def _main(self, extra):
        import contextlib
        import io
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            rc = serve_mcp.main(self.ws_args + extra)
        return rc, stderr.getvalue()

    def test_refuses_without_key_or_no_auth(self):
        rc, err = self._main([])
        self.assertEqual(rc, 1)
        self.assertIn("--auth-key", err)
        self.assertIn("BUNNYFORGE_MCP_KEY", err)
        self.assertIn("--no-auth", err)

    def test_refuses_key_and_no_auth_together(self):
        rc, err = self._main(["--auth-key", "k", "--no-auth"])
        self.assertEqual(rc, 1)
        self.assertIn("contradict", err)

    def test_env_key_counts_as_key_for_the_contradiction(self):
        with mock.patch.dict(os.environ, {"BUNNYFORGE_MCP_KEY": "k"}):
            rc, err = self._main(["--no-auth"])
        self.assertEqual(rc, 1)
        self.assertIn("contradict", err)

    def test_token_flag_is_gone(self):
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stderr(io.StringIO()):
                serve_mcp.build_parser().parse_args(["--token", "t"])
```

(Add `import contextlib` and `import io` at the top of the test module;
`os` and `mock` are already imported.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/bin/python -m unittest tests.test_serve_mcp -v`
Expected: FAIL — refusal message still names `--token`; `--token` still
parses; `TestBearerAuth` deletion leaves no reference to `_BearerAuth`.

- [ ] **Step 3: Rewrite the CLI layer**

In `src/bunnyforge/serve_mcp.py`:

1. **Module docstring**, replace the `_BearerAuth` paragraph (lines
   14–19 of the current file) with:

```python
Everything served here is GM-eyes-only, so auth is default-deny: no GM key
and no explicit --no-auth means the server refuses to start. Auth itself is
delegated to the SDK (design: docs/superpowers/specs/
2026-08-16-serve-mcp-oauth-design.md): bunnyforge runs the smallest OAuth
authorization server that satisfies claude.ai's connector — SDK handlers
for registration, authorize, and token; bunnyforge owns one decision, a
consent page checking a pre-shared GM key (_mcp_auth.py).
```

2. Replace `TOKEN_ENV = "BUNNYFORGE_MCP_TOKEN"` with
   `KEY_ENV = "BUNNYFORGE_MCP_KEY"`.

3. **Delete the `_BearerAuth` class entirely.**

4. In `build_parser()`, replace the `--token` argument with:

```python
    parser.add_argument("--auth-key",
                        help="pre-shared GM key typed on the OAuth consent "
                             f"page, or set {KEY_ENV}; required unless "
                             "--no-auth")
    parser.add_argument("--public-host",
                        help="public hostname the tunnel serves this host "
                             "as; the OAuth issuer becomes https://HOST "
                             "(default: the local bind address)")
```

5. In `main()`, replace everything from the `token = ...` line through the
   `uvicorn.run(...)` call with:

```python
    key = (args.auth_key or os.environ.get(KEY_ENV, "")).strip()
    if key and args.no_auth:
        print(f"--no-auth contradicts --auth-key/{KEY_ENV}; pick one",
              file=sys.stderr)
        return 1
    if not key and not args.no_auth:
        print("refusing to start without auth: pass --auth-key, set "
              f"{KEY_ENV}, or (local testing only) pass --no-auth",
              file=sys.stderr)
        return 1

    # Issue #46 will also plumb --public-host into transport_security;
    # here it only names the OAuth issuer.
    issuer = (f"https://{args.public_host}" if args.public_host
              else f"http://127.0.0.1:{args.port}")

    try:
        import uvicorn

        oauth = None
        if key:
            from bunnyforge._mcp_auth import (SingleUserOAuthProvider,
                                              default_state_path)
            oauth = SingleUserOAuthProvider(
                gm_key=key, issuer_url=issuer,
                state_path=default_state_path())
        server = build_server(WorkspaceStore(ws),
                              allow_direct_edits=args.allow_direct_edits,
                              oauth=oauth)
    except ModuleNotFoundError:
        print(_INSTALL_HINT, file=sys.stderr)
        return 1

    app = server.streamable_http_app(stateless_http=True)
    if not key:
        print("WARNING: serving with no authentication", file=sys.stderr)

    print(f"serving {ws.config.name} at http://{args.host}:{args.port}/mcp "
          f"(OAuth issuer: {issuer})" if key else
          f"serving {ws.config.name} at http://{args.host}:{args.port}/mcp")
    uvicorn.run(app, host=args.host, port=args.port)
    return 0
```

- [ ] **Step 4: Run the full suite on the venv, and the bare-Python checks**

Run: `./.venv/bin/python -m unittest discover -s tests -v 2>&1 | tail -5`
Expected: OK.

Run: `python3 -c "import bunnyforge.cli; print('bare ok')"` and
`./.venv/bin/bunnyforge serve-mcp --help`
Expected: `bare ok`; help shows `--auth-key`, `--public-host`, `--no-auth`,
and no `--token`.

- [ ] **Step 5: Grep for stragglers**

Run: `grep -rn "BearerAuth\|BUNNYFORGE_MCP_TOKEN\|--token" src tests docs README.md --include='*.py' --include='*.md' | grep -v superpowers/specs | grep -v superpowers/plans`
Expected: no hits (the spec/plan may mention them historically; shipped
code and docs must not).

- [ ] **Step 6: Commit**

```bash
git add src/bunnyforge/serve_mcp.py tests/test_serve_mcp.py
git commit -m "feat(serve-mcp)!: --auth-key/--public-host replace --token; delete _BearerAuth"
```

---

### Task 6: Documentation

**Files:**
- Create: `docs/serve-mcp.md`
- Modify: `docs/superpowers/specs/2026-08-16-serve-mcp-design.md`
  (supersession pointer only)

**Interfaces:**
- Consumes: the shipped CLI surface from Task 5 (flag names, env var,
  state-file path). No code.

- [ ] **Step 1: Write the operator doc**

Create `docs/serve-mcp.md`:

```markdown
# serve-mcp: connecting claude.ai to a campaign workspace

`bunnyforge serve-mcp` serves one campaign workspace to a remote AI agent
over MCP. Everything it serves is GM-eyes-only; the server refuses to
start without an auth mechanism.

## Install

    pip install 'bunnyforge[mcp]'

## Generate a GM key (once)

    python3 -c "import secrets; print(secrets.token_urlsafe(24))"

Keep it out of git. You will type it exactly once per grant, on the
consent page in your own browser — it is never stored by claude.ai.

## Run behind a tunnel

    export BUNNYFORGE_MCP_KEY=<your key>
    cloudflared tunnel run <name>           # named tunnel, stable hostname
    bunnyforge serve-mcp --public-host <name>.example.com

A **named tunnel** (free with a Cloudflare-managed domain) is the
recommended recipe: the hostname — and therefore the connector URL in
claude.ai and the OAuth trust it anchors — survives restarts. A quick
tunnel (`cloudflared tunnel --url http://127.0.0.1:8765`) also works, but
its hostname changes every run: pass the new hostname to `--public-host`
and update the connector URL in claude.ai each time.

Local testing needs no tunnel: `--no-auth` (unauthenticated, loud
warning) or `--auth-key` with the default localhost issuer.

## Add the connector in claude.ai

Settings → Connectors → Add custom connector:

- **URL:** `https://<public-host>/mcp`
- **OAuth Client ID / Client Secret:** leave **both blank**. claude.ai
  registers itself (Dynamic Client Registration) against the server's
  built-in single-user authorization server.

On connect, your browser lands on the server's consent page; type the GM
key. Tokens refresh silently for up to 30 days before the page reappears.

## Resetting access

Delete the token state file and restart the server:

    rm ~/.local/state/bunnyforge/mcp-oauth-state.json

(`$XDG_STATE_HOME/bunnyforge/mcp-oauth-state.json` if you set
`XDG_STATE_HOME`.) Every issued token dies with it; claude.ai will run
the consent flow again. Changing the GM key invalidates future grants
but not already-issued tokens — delete the state file for that.

## Troubleshooting

- **401 from `/mcp`:** no or expired token — reconnect from claude.ai.
- **421 Invalid Host header through a tunnel:** DNS-rebinding protection
  does not know your public hostname — issue #46 tracks the
  `--public-host` transport fix.
- **"Couldn't register with sign-in service":** the server is not
  reachable at the connector URL, or it was started `--no-auth` (no OAuth
  routes exist in that mode).
```

- [ ] **Step 2: Point the old spec at the new one**

In `docs/superpowers/specs/2026-08-16-serve-mcp-design.md`, insert
directly under the `## Deployment and auth` heading:

```markdown
> **Superseded (2026-08-16):** the static-bearer-token scheme below was
> disproved against the real claude.ai connector (issue #42). Current
> design: `2026-08-16-serve-mcp-oauth-design.md`.
```

- [ ] **Step 3: Verify doc claims against the shipped CLI**

Run: `./.venv/bin/bunnyforge serve-mcp --help`
Expected: every flag named in `docs/serve-mcp.md` exists with the
documented spelling.

- [ ] **Step 4: Commit**

```bash
git add docs/serve-mcp.md docs/superpowers/specs/2026-08-16-serve-mcp-design.md
git commit -m "docs(serve-mcp): operator guide for OAuth connector setup"
```

---

## Final verification (before the PR)

- [ ] Full suite in the worktree venv:
  `./.venv/bin/python -m unittest discover -s tests 2>&1 | tail -3` → OK.
- [ ] Clean-checkout check per AGENTS.md ("verify where the artifact will
  live"): fresh worktree of the branch, fresh venv,
  `pip install -e '.[mcp]'`, assert resolution, run the suite.
- [ ] Bare-python: `python3 -c "import bunnyforge.cli"` still works and the
  system copy was never touched.
- [ ] Manual smoke (the one thing tests cannot cover, may be deferred to
  the owner): live tunnel + claude.ai connector with blank Client ID/Secret
  completes the consent flow and lists tools. Note in the PR whether this
  was run or deferred — #46's 421 may block it until that fix lands.
- [ ] Scan the diff for secrets before pushing.
- [ ] PR per AGENTS.md: base `main` (flag loudly if not), body with Files
  changed / Work breakdown / Test expectations / Operational impact
  (breaking flag rename; state file introduced) / Provenance. Move the
  board card.
```

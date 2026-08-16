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

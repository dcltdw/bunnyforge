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

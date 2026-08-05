#!/usr/bin/env python3
"""
_dokuwiki_rpc.py — talk to a DokuWiki install over its JSON-RPC API.

Third sibling in the DokuWiki family: _dokuwiki.py knows markup,
_dokuwiki_install.py knows an install on disk, this module knows an install
over the wire. Stdlib only; imports nothing from _config — it takes
(base_url, token) and knows nothing about workspaces.

Speaks only the simplified PATH_INFO form, verified live (#7):

    POST <base_url>/lib/exe/jsonrpc.php/<method>

with a JSON object of named params — no JSON-RPC 2.0 envelope, no id
bookkeeping. Success responses may still carry an `error` object of
{"code": 0, "message": "success"}, so the success test is: `error` absent,
null, or code == 0 — never key presence.

The transport is injectable so tests never construct a socket.
"""

from __future__ import annotations

import http.client
import importlib.metadata
import json
import urllib.error
import urllib.parse
import urllib.request

ENDPOINT = "lib/exe/jsonrpc.php"
SAVE_SUMMARY = "bunnyforge deploy-export"
# First DokuWiki release with the core.* JSON-RPC methods: PR #4134
# "Complete API Refactoring" consolidated wiki.*/dokuwiki.* calls into
# core.* calls, landing in this release. Verified against
# https://github.com/dokuwiki/dokuwiki/pull/4134 and the Fossies diff of
# inc/Remote/ApiCore.php between release-2023-04-04a and release-2024-02-06.
MIN_RELEASE = '2024-02-06 "Kaos"'

# http:// is refused everywhere else — the token would cross the wire in
# clear — but a local test install has nothing to leak to.
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

try:
    _VERSION = importlib.metadata.version("bunnyforge")
except importlib.metadata.PackageNotFoundError:  # uninstalled checkout
    _VERSION = "unknown"


class RpcError(Exception):
    """A failed RPC call. `code` is the wiki's JSON-RPC error code, or one
    of the transport sentinels 'unreachable' (DNS / refused / timeout /
    connection dropped mid-response) and 'no-endpoint' (HTTP 404, a redirect,
    or a body that is not JSON)."""

    def __init__(self, code, message, method):
        super().__init__(f"{method}: [{code}] {message}")
        self.code = code
        self.message = message
        self.method = method


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect rather than following it.

    urllib's stock HTTPRedirectHandler copies each header except
    content-length/content-type onto the redirected request — Authorization
    included — and, unlike `requests`, does *not* drop it when the host
    changes. It also downgrades a 301/302/303 POST to GET. So a wiki whose
    canonical URL redirects (apex -> www, or an https vhost that 301s to
    http) would send a live campaign's API token in clear, or to a host the
    user never configured in [wiki] url. The https-only check in RpcClient
    guards the configured base URL only; it can say nothing about a redirect
    target, so the token's guarantee has to be enforced here.

    A JSON-RPC POST to lib/exe/jsonrpc.php/<method> has no legitimate reason
    to redirect, so refusing costs nothing and the message points at the fix.
    (Following it would not work anyway: the endpoint is POST-only and
    answers a GET with -32606, which the error table reports as a bunnyforge
    bug — a URL misconfiguration misdiagnosed as a tool defect.)
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RpcError(
            "no-endpoint",
            f"redirected to {newurl} — point [wiki] url at the wiki's "
            "canonical base URL; the API token is never sent to a redirect "
            "target",
            req.full_url.rsplit("/", 1)[-1])


# Never urlopen(): that uses the default opener, which follows redirects.
_OPENER = urllib.request.build_opener(_NoRedirect)


def _default_transport(request: urllib.request.Request, timeout: float) -> bytes:
    method = request.full_url.rsplit("/", 1)[-1]
    try:
        with _OPENER.open(request, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise RpcError("no-endpoint", "HTTP 404", method) from exc
        # JSON-RPC errors can ride a non-200 status; the JSON body wins.
        return exc.read()
    except urllib.error.URLError as exc:
        raise RpcError("unreachable", str(exc.reason), method) from exc
    except TimeoutError as exc:
        raise RpcError("unreachable", "timed out", method) from exc
    except (OSError, http.client.HTTPException) as exc:
        # urlopen wraps only the OSError raised inside h.request(); anything
        # from getresponse() or resp.read() arrives unwrapped —
        # RemoteDisconnected, ConnectionResetError, IncompleteRead, a
        # mid-stream ssl.SSLError. Unhandled they become a traceback, and
        # inside apply_deploy they would also skip the written / not-yet-
        # written / re-run report a partial deploy owes the user. Ordering
        # matters: HTTPError and URLError are both OSError subclasses and
        # carry better detail, so they are caught above.
        raise RpcError("unreachable", str(exc) or type(exc).__name__,
                       method) from exc


class RpcClient:
    def __init__(self, base_url: str, token: str, timeout: float = 30.0,
                 transport=None):
        parts = urllib.parse.urlsplit(base_url)
        # Is it a web URL at all, then is it a safe one — the general check
        # before the specific, so the pair reads in the order it decides in.
        if parts.scheme not in ("http", "https"):
            raise ValueError(
                f"[wiki] url {base_url} is not an http(s) URL — expected "
                "the wiki's base URL, e.g. https://<wiki>")
        if parts.scheme == "http" and parts.hostname not in _LOCAL_HOSTS:
            raise ValueError(
                f"[wiki] url {base_url} uses http:// — the API token would "
                "cross the wire in clear. Use https:// (http is allowed only "
                "for localhost test installs).")
        self._endpoint = base_url.rstrip("/") + "/" + ENDPOINT
        self._headers = {
            "Content-Type": "application/json",
            "User-Agent": f"bunnyforge/{_VERSION}",
        }
        self._token = token
        self._timeout = timeout
        self._transport = transport or _default_transport

    def call(self, method: str, params: dict):
        request = urllib.request.Request(
            f"{self._endpoint}/{method}",
            data=json.dumps(params).encode("utf-8"),
            headers=self._headers, method="POST")
        # Second layer under _NoRedirect, and the reason the token is not in
        # `headers` above. An unredirected header goes on the wire exactly
        # like any other (do_open merges both dicts), but urllib's redirect
        # machinery never copies it onto a redirected request — so the
        # credential cannot follow a redirect even if this module were one
        # day reached through the default opener.
        #
        # Both credential headers are sent, verified live (2026-08-05)
        # against a host running PHP as CGI/FastCGI: Apache strips the
        # Authorization header there before PHP ever runs, so a Bearer-only
        # client is silently treated as anonymous — not a wiki config
        # problem, and no amount of .htaccess or preload.php tuning fixes it
        # from this side. X-DokuWiki-Token is not special-cased by Apache and
        # arrives intact; DokuWiki's auth_tokenlogin() also prefers it over
        # Authorization when both are present. Sending both is strictly more
        # compatible than either alone, and costs nothing on a host where
        # Authorization already works fine.
        request.add_unredirected_header("Authorization", f"Bearer {self._token}")
        request.add_unredirected_header("X-DokuWiki-Token", self._token)
        raw = self._transport(request, self._timeout)
        try:
            obj = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise RpcError("no-endpoint",
                           "response is not JSON — wrong base URL?",
                           method) from exc
        error = obj.get("error") if isinstance(obj, dict) else None
        if error and error.get("code", 0) != 0:
            raise RpcError(error.get("code"), error.get("message", ""), method)
        return obj.get("result") if isinstance(obj, dict) else obj

    def get_page(self, page_id: str) -> str | None:
        """Current wiki text, or None for a page that does not exist.

        Verified live (2026-08-05) against a real 2026-07-14a "Mort" install,
        JSON-RPC API version 14: a missing page returns "" with a *success*
        error object — {"code": 0, "message": "success"} — and error 121
        never occurs at all on that build. The 121 branch is kept for older
        builds that may still raise it; it costs nothing to keep.

        Treating "" as "does not exist" is safe, not a heuristic:
        core.savePage refuses to create an empty page (error 132) — the
        exact reason the render half translates a zero-byte placeholder to
        ~~NOTOC~~ before upload. A page cannot simultaneously be empty and
        exist, so "" unambiguously means "does not exist".
        """
        try:
            text = self.call("core.getPage", {"page": page_id})
        except RpcError as exc:
            if exc.code == 121:
                return None
            raise
        return text if text else None

    def save_page(self, page_id: str, text: str,
                  summary: str = SAVE_SUMMARY) -> None:
        """Every save carries the summary, so wiki history shows provenance."""
        self.call("core.savePage", {"page": page_id, "text": text,
                                    "summary": summary, "isminor": False})


# One table, applied by deploy_export at the run level — call sites raise
# RpcError and never compose prose themselves. Codes from the DokuWiki
# source; -32605 and -32606 verified live (#7).
_CLIENT_DEFECTS = frozenset({-32606, -32700, -32602, 131, 132})


def translate_error(err: RpcError, wiki_url: str) -> str:
    code = err.code
    if code == "unreachable":
        return (f"cannot reach {wiki_url}: {err.message}. This is a "
                "connectivity or [wiki] url problem, not a wiki fault — "
                "check the URL in campaign.toml and your network.")
    if code == "no-endpoint":
        return (f"no JSON-RPC endpoint at {wiki_url} ({err.message}) — the "
                f"DokuWiki release is older than {MIN_RELEASE}, or [wiki] "
                "url is not the wiki's base URL.")
    if code == -32605:
        return ("your wiki's remote API is disabled; set "
                "$conf['remote'] = 1 in conf/local.php, not "
                "conf/dokuwiki.php (which upgrades overwrite).")
    if code == -32603:
        # Not authenticated: DokuWiki's JsonRpcServer.php raises this (HTTP
        # 401) when the request carried no usable credential at all —
        # $INPUT->server has no REMOTE_USER. Verified live (2026-08-05): a
        # host running PHP as CGI/FastCGI strips the Authorization header
        # before PHP ever sees it, so a Bearer-only client is silently
        # anonymous there — common and non-obvious enough to name outright.
        return ("not authenticated: the wiki received no usable credential — "
                "some hosts strip the Authorization header when PHP runs as "
                "CGI/FastCGI (bunnyforge also sends X-DokuWiki-Token, which "
                "usually survives that). Check the token "
                "(BUNNYFORGE_WIKI_TOKEN or <workspace>/.bunnyforge/wiki-token) "
                "and that the API user is within $conf['remoteuser'].")
    if code == -32604:
        # Authenticated but forbidden: JsonRpcServer.php raises this (HTTP
        # 403) when $INPUT->server *does* have REMOTE_USER — the credential
        # was accepted, this user just may not call the method. Previously
        # mapped to "check the token", which named the wrong layer; the live
        # source above resolves the ambiguity the spec had deferred.
        return ("authenticated but forbidden: this user may not call this "
                "method — check $conf['remoteuser'] and the wiki's ACL for "
                "the deploy user.")
    if code == 111:
        return ("the wiki's ACL denies this user here — grant the deploy "
                "user edit on the campaign namespace.")
    if code == 133:
        return ("page locked by an editing session — retry after the lock "
                "expires (default 15 minutes).")
    if code == 134:
        return "content blocked by the wiki's wordblock blacklist."
    if code in _CLIENT_DEFECTS:
        return (f"{err.method} failed with code {code} ({err.message}) — "
                "bug in bunnyforge, please report it.")
    return (f"{err.method} failed with code {code}: {err.message} — "
            "unrecognised code, please report it.")

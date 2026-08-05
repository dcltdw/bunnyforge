# deploy-export RPC transport — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Teach `bunnyforge deploy-export` to push its rendered staging tree onto a DokuWiki install over JSON-RPC, with a committed manifest for drift detection, a dry-run-by-default CLI convention applied package-wide, and a `wiki-remote` review check.

**Architecture:** A new stdlib-only RPC client (`_dokuwiki_rpc.py`) speaks DokuWiki's simplified `PATH_INFO` JSON-RPC form with an injectable transport. `deploy_export.py` grows a plan/apply phase on top of the untouched render code: classify every staged page against the live wiki text and a committed manifest of post-save hashes, hold back drift with diffs and inbound copies, write the rest in content-before-wrapper order with a write-through manifest. `_config.py` supplies the `[wiki]` table and token resolution; `review.py` gains a filesystem-only `wiki-remote` check; `import_perceptions.py` adopts the same dry-run/`--go` convention.

**Tech Stack:** Python ≥3.11, stdlib only (`urllib.request`, `json`, `ssl`, `hashlib`, `difflib`, `tomllib`, `unittest`). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-05-deploy-export-rpc-transport-design.md` (approved). Ticket #7.

## Global Constraints

- **Zero runtime dependencies** — stdlib only, everywhere.
- **Nothing campaign-specific in this repo** — `<wiki>` / `<ns>` placeholders in code, tests, docs, commit messages, and issues. Tests use their own namespaces (`testwiki` / `test`), never a real campaign's.
- **Test framework is `unittest`**, run via `python3 -m bunnyforge.run_tests` (never bare pytest). Suite must stay green on 3.11, 3.12, 3.13. The spec's floor is 436 tests; **re-derive the real count from an actual run** at the start and never let it drop.
- **JSON-RPC only, simplified `PATH_INFO` form** — no XML-RPC, no JSON-RPC 2.0 envelope.
- **Success test for RPC responses:** `error` absent, `null`, or `code == 0` — never key presence (verified live: success responses carry `{"error": {"code": 0, "message": "success"}}`).
- **Every mutating command:** default run is a dry run; `--go` performs writes.
- **Instructional errors:** every user-facing error names the fix, per the project's ruling.
- **Orphans are reported, never deleted.** No wiki page deletion anywhere.
- Commit per task on the feature branch; `Co-Authored-By:` trailer naming the current AI model on every commit.

## Branch and PR shape

The spec commit (`33d5b41`) lives on `rpc-transport-design`, not yet on `main`.

1. **First:** open a docs-only PR for `rpc-transport-design` → `main` (the approved spec). Present it for approval; after it merges, `git checkout main && git pull` and confirm the spec file is on `main`.
2. Implementation happens on a fresh branch `deploy-export-rpc-transport` off updated `main`, one commit per task below, one PR for the feature (base `main`).

---

## File Structure

| file | change |
|---|---|
| `src/bunnyforge/_dokuwiki_rpc.py` | **new** — `RpcClient`, `RpcError`, `translate_error`, injectable transport |
| `tests/test_dokuwiki_rpc.py` | **new** — client + translation tests |
| `src/bunnyforge/_config.py` | `Config.wiki_url` field, `[wiki]` parsing, `resolve_wiki_token` |
| `src/bunnyforge/deploy_export.py` | manifest, classification, plan/apply orchestration, new CLI; render code untouched |
| `src/bunnyforge/review.py` | `check_wiki_remote` in the wiki suite |
| `src/bunnyforge/import_perceptions.py` | dry-run default + `--go`, `--dry-run` removed |
| `src/bunnyforge/data/root/gitignore` | `+ .bunnyforge/wiki-token`, `+ .bunnyforge/wiki-drift/` |
| `docs/superpowers/specs/2026-07-27-player-wiki-export-design.md` | supersession annotation on the transport half |
| `README.md`, `src/bunnyforge/README.md` | dry-run/`--go` convention; pipeline loses "manual copy" |
| `pyproject.toml` | version → `0.2.0` |
| tests touched | `test_deploy_export.py`, `test_config.py`, `test_review.py`, `test_import_perceptions.py`, `test_init.py` |

Key paths (constants defined in Task 3/2):

- Manifest: `<workspace>/.bunnyforge/wiki-manifest.json` — **committed**.
- Token file: `<workspace>/.bunnyforge/wiki-token` — gitignored.
- Drift copies: `<workspace>/.bunnyforge/wiki-drift/` — gitignored, tool-owned, recreated from empty each planning run.

---

### Task 0: Land the spec, cut the branch

**Files:** none (process only).

- [ ] **Step 1: Record the true suite count**

Run: `cd ~/Github/bunnyforge && python3 -m bunnyforge.run_tests 2>&1 | tail -3`
Record the `Ran N tests` number. Every later "suite passes" step means: N has not dropped, and grows as tasks add tests.

- [ ] **Step 2: Open the spec PR**

```bash
git checkout rpc-transport-design && git push -u origin rpc-transport-design
gh pr create --base main --title "docs: design for deploy-export RPC transport (#7)" \
  --body "Approved design for ticket #7. Docs only."
```

Present the PR for approval and **wait**; after the human merges it: `git checkout main && git pull`, confirm `docs/superpowers/specs/2026-08-05-deploy-export-rpc-transport-design.md` exists on `main`.

- [ ] **Step 3: Cut the feature branch**

```bash
git checkout -b deploy-export-rpc-transport main
```

---

### Task 1: The RPC client — `_dokuwiki_rpc.py`

**Files:**
- Create: `src/bunnyforge/_dokuwiki_rpc.py`
- Create: `tests/test_dokuwiki_rpc.py`

**Interfaces:**
- Consumes: nothing from the package (deliberately — takes `(base_url, token)`, knows nothing about workspaces).
- Produces (later tasks rely on these exact names):
  - `RpcError(code, message, method)` — exception; `.code` is an `int` JSON-RPC code or one of the transport sentinels `"unreachable"` / `"no-endpoint"`.
  - `RpcClient(base_url, token, timeout=30.0, transport=None)` with `.call(method, params) -> object`, `.get_page(page_id) -> str | None`, `.save_page(page_id, text, summary=SAVE_SUMMARY) -> None`.
  - `SAVE_SUMMARY = "bunnyforge deploy-export"`
  - `translate_error(err: RpcError, wiki_url: str) -> str`
  - `RpcClient.__init__` raises `ValueError` (with the full instructional message) for a non-localhost `http://` URL or an unrecognised scheme.

- [ ] **Step 1: Pin the minimum DokuWiki release**

Check the DokuWiki changelog (https://www.dokuwiki.org/changes) for which release introduced the `core.*` JSON-RPC methods (believed: JSON-RPC endpoint since 2023-04-04 "Jack Jackrum"; `core.savePage`/`core.getPage` since the API rework in 2024-02-06 "Kaos"). Pin the verified release name in a module constant `MIN_RELEASE` used by the 404 translation. If it cannot be verified offline, use `2024-02-06 "Kaos"` and leave a `# verify against changelog` comment plus a note in the PR body.

- [ ] **Step 2: Write the failing tests**

`tests/test_dokuwiki_rpc.py`:

```python
import json
import unittest
import urllib.error
from unittest import mock

from bunnyforge import _dokuwiki_rpc as rpc
from bunnyforge._dokuwiki_rpc import RpcClient, RpcError


def fake_transport(responses):
    """A transport returning canned bodies; records every request."""
    calls = []

    def transport(request, timeout):
        calls.append((request, timeout))
        body = responses[len(calls) - 1]
        if isinstance(body, Exception):
            raise body
        return body

    transport.calls = calls
    return transport


def ok(result):
    return json.dumps({"result": result}).encode("utf-8")


class TestRequestShape(unittest.TestCase):
    def test_posts_to_pathinfo_endpoint_with_headers(self):
        t = fake_transport([ok("x")])
        client = RpcClient("https://<wiki>", "tok123", transport=t)
        client.call("core.getPage", {"page": "a:b"})
        request, timeout = t.calls[0]
        self.assertEqual(
            request.full_url, "https://<wiki>/lib/exe/jsonrpc.php/core.getPage")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer tok123")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertTrue(request.get_header("User-agent").startswith("bunnyforge/"))
        self.assertEqual(json.loads(request.data.decode("utf-8")), {"page": "a:b"})
        self.assertEqual(timeout, 30.0)

    def test_trailing_slash_on_base_url_tolerated(self):
        t = fake_transport([ok(1)])
        RpcClient("https://<wiki>/", "t", transport=t).call("m", {})
        self.assertEqual(
            t.calls[0][0].full_url, "https://<wiki>/lib/exe/jsonrpc.php/m")


class TestSuccessShapes(unittest.TestCase):
    """The key-presence trap, pinned: all three success shapes must pass."""

    def test_error_absent(self):
        c = RpcClient("https://w", "t", transport=fake_transport([ok("body")]))
        self.assertEqual(c.call("m", {}), "body")

    def test_error_null(self):
        body = json.dumps({"result": "body", "error": None}).encode()
        c = RpcClient("https://w", "t", transport=fake_transport([body]))
        self.assertEqual(c.call("m", {}), "body")

    def test_error_code_zero(self):
        body = json.dumps(
            {"result": "body", "error": {"code": 0, "message": "success"}}).encode()
        c = RpcClient("https://w", "t", transport=fake_transport([body]))
        self.assertEqual(c.call("m", {}), "body")

    def test_error_code_nonzero_raises(self):
        body = json.dumps(
            {"result": None, "error": {"code": 111, "message": "no"}}).encode()
        c = RpcClient("https://w", "t", transport=fake_transport([body]))
        with self.assertRaises(RpcError) as ctx:
            c.call("core.savePage", {})
        self.assertEqual(ctx.exception.code, 111)
        self.assertEqual(ctx.exception.method, "core.savePage")

    def test_non_json_body_is_no_endpoint(self):
        c = RpcClient("https://w", "t",
                      transport=fake_transport([b"<html>login</html>"]))
        with self.assertRaises(RpcError) as ctx:
            c.call("m", {})
        self.assertEqual(ctx.exception.code, "no-endpoint")


class TestWrappers(unittest.TestCase):
    def test_get_page_121_is_none(self):
        body = json.dumps({"error": {"code": 121, "message": "absent"}}).encode()
        c = RpcClient("https://w", "t", transport=fake_transport([body]))
        self.assertIsNone(c.get_page("a:b"))

    def test_get_page_other_error_propagates(self):
        body = json.dumps({"error": {"code": 111, "message": "acl"}}).encode()
        c = RpcClient("https://w", "t", transport=fake_transport([body]))
        with self.assertRaises(RpcError):
            c.get_page("a:b")

    def test_save_page_params_and_summary(self):
        t = fake_transport([ok(True)])
        RpcClient("https://w", "t", transport=t).save_page("a:b", "text\n")
        params = json.loads(t.calls[0][0].data.decode("utf-8"))
        self.assertEqual(params["page"], "a:b")
        self.assertEqual(params["text"], "text\n")
        self.assertEqual(params["summary"], "bunnyforge deploy-export")


class TestUrlPolicy(unittest.TestCase):
    def test_plain_http_refused(self):
        with self.assertRaises(ValueError) as ctx:
            RpcClient("http://<wiki>", "t")
        self.assertIn("http://", str(ctx.exception))
        self.assertIn("clear", str(ctx.exception))  # names why: token in clear

    def test_http_localhost_allowed(self):
        for host in ("localhost", "127.0.0.1"):
            RpcClient(f"http://{host}:8080", "t")  # must not raise

    def test_https_allowed(self):
        RpcClient("https://<wiki>", "t")

    def test_garbage_scheme_refused(self):
        with self.assertRaises(ValueError):
            RpcClient("ftp://<wiki>", "t")


class TestDefaultTransport(unittest.TestCase):
    def test_urlerror_is_unreachable(self):
        with mock.patch("urllib.request.urlopen",
                        side_effect=urllib.error.URLError("dns fail")):
            c = RpcClient("https://<wiki>", "t")
            with self.assertRaises(RpcError) as ctx:
                c.call("m", {})
            self.assertEqual(ctx.exception.code, "unreachable")

    def test_timeout_is_unreachable(self):
        with mock.patch("urllib.request.urlopen", side_effect=TimeoutError()):
            c = RpcClient("https://<wiki>", "t")
            with self.assertRaises(RpcError) as ctx:
                c.call("m", {})
            self.assertEqual(ctx.exception.code, "unreachable")

    def test_http_404_is_no_endpoint(self):
        err = urllib.error.HTTPError("u", 404, "nf", {}, None)
        with mock.patch("urllib.request.urlopen", side_effect=err):
            c = RpcClient("https://<wiki>", "t")
            with self.assertRaises(RpcError) as ctx:
                c.call("m", {})
            self.assertEqual(ctx.exception.code, "no-endpoint")

    def test_http_error_body_still_parsed(self):
        # JSON-RPC errors can ride a non-200 status: the body wins.
        import io
        payload = json.dumps({"error": {"code": -32605, "message": "off"}}).encode()
        err = urllib.error.HTTPError("u", 403, "forbidden", {}, io.BytesIO(payload))
        with mock.patch("urllib.request.urlopen", side_effect=err):
            c = RpcClient("https://<wiki>", "t")
            with self.assertRaises(RpcError) as ctx:
                c.call("m", {})
            self.assertEqual(ctx.exception.code, -32605)


class TestTranslation(unittest.TestCase):
    """Every row of the spec's error table names its fix."""

    def check(self, code, *needles):
        msg = rpc.translate_error(RpcError(code, "raw detail", "core.savePage"),
                                  "https://<wiki>")
        for needle in needles:
            self.assertIn(needle, msg)
        return msg

    def test_unreachable_names_url(self):
        self.check("unreachable", "https://<wiki>", "connectivity")

    def test_no_endpoint_names_minimum_release(self):
        self.check("no-endpoint", rpc.MIN_RELEASE)

    def test_32605_names_conf_local(self):
        self.check(-32605, "$conf['remote'] = 1", "conf/local.php",
                   "conf/dokuwiki.php")

    def test_32604_names_both_token_sources(self):
        self.check(-32604, "BUNNYFORGE_WIKI_TOKEN", ".bunnyforge/wiki-token",
                   "remoteuser")

    def test_111_names_acl(self):
        self.check(111, "ACL", "edit")

    def test_133_names_lock_expiry(self):
        self.check(133, "lock", "15 minutes")

    def test_134_names_wordblock(self):
        self.check(134, "wordblock")

    def test_client_defects_say_report(self):
        for code in (-32606, -32700, -32602, 131, 132):
            self.assertIn("bug in bunnyforge, please report", self.check(code))

    def test_unknown_code_prints_raw(self):
        self.check(999, "core.savePage", "999", "raw detail", "please report")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_dokuwiki_rpc -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bunnyforge._dokuwiki_rpc'`

- [ ] **Step 4: Implement `src/bunnyforge/_dokuwiki_rpc.py`**

```python
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

import importlib.metadata
import json
import urllib.error
import urllib.parse
import urllib.request

ENDPOINT = "lib/exe/jsonrpc.php"
SAVE_SUMMARY = "bunnyforge deploy-export"
# First DokuWiki release with the core.* JSON-RPC methods (pinned in Task 1
# step 1 — verify against https://www.dokuwiki.org/changes).
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
    of the transport sentinels 'unreachable' (DNS / refused / timeout) and
    'no-endpoint' (HTTP 404, or a body that is not JSON)."""

    def __init__(self, code, message, method):
        super().__init__(f"{method}: [{code}] {message}")
        self.code = code
        self.message = message
        self.method = method


def _default_transport(request: urllib.request.Request, timeout: float) -> bytes:
    method = request.full_url.rsplit("/", 1)[-1]
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
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


class RpcClient:
    def __init__(self, base_url: str, token: str, timeout: float = 30.0,
                 transport=None):
        parts = urllib.parse.urlsplit(base_url)
        if parts.scheme == "http" and parts.hostname not in _LOCAL_HOSTS:
            raise ValueError(
                f"[wiki] url {base_url} uses http:// — the API token would "
                "cross the wire in clear. Use https:// (http is allowed only "
                "for localhost test installs).")
        if parts.scheme not in ("http", "https"):
            raise ValueError(
                f"[wiki] url {base_url} is not an http(s) URL — expected "
                "the wiki's base URL, e.g. https://<wiki>")
        self._endpoint = base_url.rstrip("/") + "/" + ENDPOINT
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": f"bunnyforge/{_VERSION}",
        }
        self._timeout = timeout
        self._transport = transport or _default_transport

    def call(self, method: str, params: dict):
        request = urllib.request.Request(
            f"{self._endpoint}/{method}",
            data=json.dumps(params).encode("utf-8"),
            headers=self._headers, method="POST")
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
        Error 121 is a state, not a failure — translated here, never shown."""
        try:
            return self.call("core.getPage", {"page": page_id})
        except RpcError as exc:
            if exc.code == 121:
                return None
            raise

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
    if code == -32604:
        return ("not authorized: check the token (BUNNYFORGE_WIKI_TOKEN or "
                "<workspace>/.bunnyforge/wiki-token) and that the API user "
                "is within $conf['remoteuser'].")
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_dokuwiki_rpc -v`
Expected: PASS. Then run the full suite: `python3 -m bunnyforge.run_tests` — count ≥ Task 0's N, all green.

- [ ] **Step 6: Commit**

```bash
git add src/bunnyforge/_dokuwiki_rpc.py tests/test_dokuwiki_rpc.py
git commit -m "feat: DokuWiki JSON-RPC client with injectable transport (#7)"
```

---

### Task 2: `[wiki]` config and token resolution — `_config.py`

**Files:**
- Modify: `src/bunnyforge/_config.py` (Config namedtuple ~line 32, `load()` ~line 158)
- Test: `tests/test_config.py` (append new test classes)

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `Config` gains a **last** field `wiki_url: str | None` with default `None` (namedtuple `defaults=[None]`), so existing constructions stay valid.
  - `resolve_wiki_token(workspace_root: Path) -> str` — raises `ConfigError` with instructional text.
  - Constants `TOKEN_ENV = "BUNNYFORGE_WIKI_TOKEN"`, `TOKEN_FILE = ".bunnyforge/wiki-token"`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_config.py`)

```python
class TestWikiConfig(unittest.TestCase):
    def _load(self, toml_text):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "campaign.toml").write_text(toml_text, encoding="utf-8")
            return _config.load(root)

    def test_wiki_url_parsed(self):
        cfg = self._load('[campaign]\nnamespace = "test"\n'
                         '[wiki]\nurl = "https://wiki.example"\n')
        self.assertEqual(cfg.wiki_url, "https://wiki.example")

    def test_wiki_table_absent_is_none(self):
        cfg = self._load('[campaign]\nnamespace = "test"\n')
        self.assertIsNone(cfg.wiki_url)

    def test_wiki_url_non_string_refused(self):
        with self.assertRaises(_config.ConfigError):
            self._load('[campaign]\nnamespace = "test"\n[wiki]\nurl = 7\n')

    def test_wiki_non_table_refused(self):
        with self.assertRaises(_config.ConfigError):
            self._load('[campaign]\nnamespace = "test"\nwiki = "x"\n')


class TestWikiToken(unittest.TestCase):
    def _token_file(self, root: Path, text, mode=0o600):
        path = root / ".bunnyforge" / "wiki-token"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        path.chmod(mode)
        return path

    def test_env_wins(self):
        with tempfile.TemporaryDirectory() as d:
            self._token_file(Path(d), "filetoken\n")
            with unittest.mock.patch.dict(
                    os.environ, {"BUNNYFORGE_WIKI_TOKEN": "envtoken"}):
                self.assertEqual(_config.resolve_wiki_token(Path(d)), "envtoken")

    def test_file_fallback_strips_trailing_whitespace(self):
        with tempfile.TemporaryDirectory() as d:
            self._token_file(Path(d), "tok123\n")
            with unittest.mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("BUNNYFORGE_WIKI_TOKEN", None)
                self.assertEqual(_config.resolve_wiki_token(Path(d)), "tok123")

    def test_group_readable_file_refused_with_chmod_instruction(self):
        with tempfile.TemporaryDirectory() as d:
            self._token_file(Path(d), "tok123\n", mode=0o644)
            os.environ.pop("BUNNYFORGE_WIKI_TOKEN", None)
            with self.assertRaises(_config.ConfigError) as ctx:
                _config.resolve_wiki_token(Path(d))
            self.assertIn("chmod 600", str(ctx.exception))

    def test_missing_both_names_both_sources(self):
        with tempfile.TemporaryDirectory() as d:
            os.environ.pop("BUNNYFORGE_WIKI_TOKEN", None)
            with self.assertRaises(_config.ConfigError) as ctx:
                _config.resolve_wiki_token(Path(d))
            msg = str(ctx.exception)
            self.assertIn("BUNNYFORGE_WIKI_TOKEN", msg)
            self.assertIn(".bunnyforge/wiki-token", msg)
            self.assertIn("API token", msg)  # says where a token comes from
```

Add `import os` and `import unittest.mock` to the test file's imports if absent.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_config -v`
Expected: FAIL — `AttributeError: 'Config' object has no attribute 'wiki_url'` and `AttributeError: module ... has no attribute 'resolve_wiki_token'`.

- [ ] **Step 3: Implement**

In `_config.py`, add `import os`, `import stat` to the imports. Change the namedtuple:

```python
Config = namedtuple(
    "Config",
    "name namespace entity_dirs inherit_dirs compendium_dirs root_docs "
    "exclude_dirs names_cultures names_official_culture names_spelling "
    "briefs_dir sheets_dir perceptions_dir type_dirs wiki_url",
    defaults=[None])  # wiki_url only — [wiki] is optional and network-only
```

In `load()`, after the `[names]` handling, parse `[wiki]`:

```python
    wiki = raw.get("wiki", {})
    if not isinstance(wiki, dict):
        raise ConfigError(f"{path}: [wiki] must be a table")
    wiki_url = wiki.get("url")
    if wiki_url is not None and not isinstance(wiki_url, str):
        raise ConfigError(f"{path}: wiki.url must be a string")
```

and pass `wiki_url=wiki_url` in the returned `Config(...)`.

Add at module level:

```python
TOKEN_ENV = "BUNNYFORGE_WIKI_TOKEN"
TOKEN_FILE = ".bunnyforge/wiki-token"


def resolve_wiki_token(workspace_root: Path) -> str:
    """The deploy credential, in resolution order: env var, then token file.

    A DokuWiki API token, never a password — scopable, revocable without a
    password change. A rejected credential is a server-side answer and is
    translated by the RPC error table, not here.
    """
    env = os.environ.get(TOKEN_ENV, "").strip()
    if env:
        return env
    path = workspace_root / TOKEN_FILE
    if path.is_file():
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            raise ConfigError(
                f"{path} is readable by group or world (mode {mode:03o}) — "
                f"a wiki credential must be private:\n  chmod 600 {path}")
        token = path.read_text(encoding="utf-8").strip()
        if token:
            return token
    raise ConfigError(
        "no wiki API token found. Provide one via either:\n"
        f"  - the {TOKEN_ENV} environment variable, or\n"
        f"  - a single line in <workspace>/{TOKEN_FILE} (chmod 600)\n"
        "Create one on the wiki: log in as the deploy user, open its "
        "profile, and generate an API token.")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_config -v` then `python3 -m bunnyforge.run_tests`
Expected: PASS, full suite green.

- [ ] **Step 5: Commit**

```bash
git add src/bunnyforge/_config.py tests/test_config.py
git commit -m "feat: [wiki] config table and API-token resolution (#7)"
```

---

### Task 3: Manifest and classification — the pure core

**Files:**
- Modify: `src/bunnyforge/deploy_export.py` (new section after the render code)
- Test: `tests/test_deploy_export.py` (append)

**Interfaces:**
- Consumes: nothing new.
- Produces (exact names later tasks use):
  - `page_hash(text: str) -> str` — sha256 hex of utf-8 bytes.
  - `classify_page(target_text: str, wiki_text: str | None, manifest_hash: str | None) -> str` — one of `"new"`, `"deleted-on-wiki"`, `"unchanged"`, `"update"`, `"adopt"`, `"drift"`, `"drift-manual-era"`.
  - `load_manifest(path: Path) -> dict[str, str]` — `{}` for a missing file; raises `DeployError` on bad JSON or unknown version.
  - `save_manifest(path: Path, pages: dict[str, str]) -> None` — sorted keys, version 1.
  - `class DeployError(Exception)`.
  - Constants: `MANIFEST_VERSION = 1`, `MANIFEST_FILE = ".bunnyforge/wiki-manifest.json"`, `DRIFT_DIR = ".bunnyforge/wiki-drift"`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_deploy_export.py`)

```python
class TestClassifyPage(unittest.TestCase):
    """The spec's eight-row state matrix, walked as a table."""

    def test_all_eight_rows(self):
        h = deploy_export.page_hash
        rows = [
            # (target, wiki_text, manifest_hash) -> action
            ("t\n", None, None, "new"),
            ("t\n", None, h("old\n"), "deleted-on-wiki"),
            ("t\n", "t\n", h("t\n"), "unchanged"),
            ("t2\n", "t\n", h("t\n"), "update"),
            ("t\n", "t\n", h("other\n"), "adopt"),      # resume-after-crash
            ("t2\n", "t\n", h("other\n"), "drift"),
            ("t\n", "t\n", None, "adopt"),               # manual-era match
            ("t2\n", "t\n", None, "drift-manual-era"),
        ]
        for target, wiki, mh, expected in rows:
            with self.subTest(expected=expected):
                self.assertEqual(
                    deploy_export.classify_page(target, wiki, mh), expected)


class TestManifest(unittest.TestCase):
    def test_missing_file_is_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(
                deploy_export.load_manifest(Path(d) / "none.json"), {})

    def test_round_trip_sorted(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / ".bunnyforge" / "wiki-manifest.json"
            deploy_export.save_manifest(path, {"b:x": "2", "a:x": "1"})
            raw = path.read_text(encoding="utf-8")
            self.assertLess(raw.index('"a:x"'), raw.index('"b:x"'))
            self.assertEqual(deploy_export.load_manifest(path),
                             {"a:x": "1", "b:x": "2"})

    def test_unknown_version_refused(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "m.json"
            path.write_text('{"version": 99, "pages": {}}', encoding="utf-8")
            with self.assertRaises(deploy_export.DeployError):
                deploy_export.load_manifest(path)

    def test_bad_json_refused_instructionally(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "m.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(deploy_export.DeployError) as ctx:
                deploy_export.load_manifest(path)
            self.assertIn(str(path), str(ctx.exception))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_deploy_export.TestClassifyPage tests.test_deploy_export.TestManifest -v`
Expected: FAIL — `AttributeError` for the missing names.

- [ ] **Step 3: Implement** (append to `deploy_export.py`; add `import hashlib`, `import json` to imports)

```python
# ---------------------------------------------------------------------------
# Transport half: manifest, classification, plan/apply. The render code above
# is untouched — a deploy always uploads what it just rendered.
# ---------------------------------------------------------------------------

MANIFEST_VERSION = 1
MANIFEST_FILE = ".bunnyforge/wiki-manifest.json"
DRIFT_DIR = ".bunnyforge/wiki-drift"


class DeployError(Exception):
    """The deploy phase cannot proceed; message is user-facing."""


def page_hash(text: str) -> str:
    """Hash of what the wiki returns from get_page after a save — never of
    the bytes we sent: DokuWiki normalizes on save, and hashing our own
    bytes would make every page look self-drifted on the next run."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def classify_page(target_text: str, wiki_text: str | None,
                  manifest_hash: str | None) -> str:
    """The spec's eight-row state matrix as a pure function.

    (staged target text, current wiki text or None, manifest hash or None)
    -> one of: new, deleted-on-wiki, unchanged, update, adopt, drift,
    drift-manual-era. 'adopt' covers both resume-after-crash and the
    manual-era exact match; the two drift labels differ only in how the
    report explains them.
    """
    if wiki_text is None:
        return "new" if manifest_hash is None else "deleted-on-wiki"
    if manifest_hash is None:
        return "adopt" if target_text == wiki_text else "drift-manual-era"
    if page_hash(wiki_text) == manifest_hash:
        return "unchanged" if target_text == wiki_text else "update"
    return "adopt" if target_text == wiki_text else "drift"


def load_manifest(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise DeployError(
            f"{path} is not valid JSON: {exc}. It is the deploy baseline — "
            "restore it from git rather than deleting it.") from exc
    if not isinstance(raw, dict) or raw.get("version") != MANIFEST_VERSION:
        raise DeployError(
            f"{path} has manifest version {raw.get('version')!r}; this "
            f"bunnyforge understands version {MANIFEST_VERSION}. Upgrade "
            "bunnyforge, or restore the manifest from git.")
    return dict(raw.get("pages", {}))


def save_manifest(path: Path, pages: dict[str, str]) -> None:
    """Sorted keys so the committed manifest diffs cleanly in git."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps({"version": MANIFEST_VERSION,
                       "pages": dict(sorted(pages.items()))}, indent=1)
    path.write_text(body + "\n", encoding="utf-8")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m bunnyforge.run_tests`
Expected: PASS, count grown.

- [ ] **Step 5: Commit**

```bash
git add src/bunnyforge/deploy_export.py tests/test_deploy_export.py
git commit -m "feat: deploy manifest and eight-row page classification (#7)"
```

---

### Task 4: Staged enumeration, protected guard, plan

**Files:**
- Modify: `src/bunnyforge/deploy_export.py`
- Test: `tests/test_deploy_export.py` (append)

**Interfaces:**
- Consumes: `classify_page`, `page_hash` (Task 3); `PROTECTED_PAGE_NAMES` (existing, line 58).
- Produces:
  - `PLACEHOLDER_BODY = "~~NOTOC~~\n"`
  - `staged_pages(staging: Path) -> dict[str, str]` — page ID → text; zero-byte pages translated to `PLACEHOLDER_BODY`.
  - `PagePlan = namedtuple("PagePlan", "action wiki_text")`
  - `DeployPlan = namedtuple("DeployPlan", "pages orphans resolved_orphans refused")` — `pages: dict[str, PagePlan]`; `orphans`/`resolved_orphans`/`refused`: sorted `list[str]`.
  - `plan_deploy(staged: dict[str, str], manifest: dict[str, str], fetch, base: str) -> DeployPlan` — `fetch(page_id) -> str | None` (a client's `get_page`, or a test fake).
  - `write_order(page_ids, base: str) -> list[str]` — sorted, content page immediately before its wrapper.

- [ ] **Step 1: Write the failing tests**

```python
class TestStagedPages(unittest.TestCase):
    def test_ids_and_placeholder_translation(self):
        with tempfile.TemporaryDirectory() as d:
            staging = Path(d)
            page = staging / NS / "export" / "mechanics" / "rule.txt"
            page.parent.mkdir(parents=True)
            page.write_text("body\n", encoding="utf-8")
            ph = staging / NS / "npcs" / "ghost.txt"
            ph.parent.mkdir(parents=True)
            ph.write_bytes(b"")  # zero-byte placeholder: savePage refuses
            staged = deploy_export.staged_pages(staging)
            self.assertEqual(staged[f"{NS}:export:mechanics:rule"], "body\n")
            self.assertEqual(staged[f"{NS}:npcs:ghost"],
                             deploy_export.PLACEHOLDER_BODY)


class TestPlanDeploy(unittest.TestCase):
    def test_classifies_and_finds_orphans(self):
        wiki = {"w:a": "old\n", "w:gone-from-workspace": "still here\n"}
        staged = {"w:a": "new\n", "w:b": "fresh\n"}
        manifest = {"w:a": deploy_export.page_hash("old\n"),
                    "w:gone-from-workspace": "x",
                    "w:resolved": "y"}  # deleted on wiki by a human
        plan = deploy_export.plan_deploy(staged, manifest, wiki.get, "w")
        self.assertEqual(plan.pages["w:a"].action, "update")
        self.assertEqual(plan.pages["w:b"].action, "new")
        self.assertEqual(plan.orphans, ["w:gone-from-workspace"])
        self.assertEqual(plan.resolved_orphans, ["w:resolved"])

    def test_protected_pages_never_fetched_never_planned(self):
        fetched = []

        def fetch(pid):
            fetched.append(pid)
            return None

        staged = {"w:main": "x\n", "w:players:notes": "x\n", "w:ok": "x\n"}
        plan = deploy_export.plan_deploy(staged, {}, fetch, "w")
        self.assertEqual(sorted(plan.refused), ["w:main", "w:players:notes"])
        self.assertNotIn("w:main", plan.pages)
        self.assertNotIn("w:main", fetched)
        self.assertNotIn("w:players:notes", fetched)
        self.assertIn("w:ok", plan.pages)


class TestWriteOrder(unittest.TestCase):
    def test_content_lands_immediately_before_its_wrapper(self):
        ids = [f"{NS}:export:npcs:ana", f"{NS}:npcs:ana",
               f"{NS}:export:npcs:bob", f"{NS}:npcs:bob",
               f"{NS}:aaa-placeholder"]
        order = deploy_export.write_order(ids, NS)
        self.assertEqual(order, [
            f"{NS}:aaa-placeholder",
            f"{NS}:export:npcs:ana", f"{NS}:npcs:ana",
            f"{NS}:export:npcs:bob", f"{NS}:npcs:bob",
        ])

    def test_unpaired_content_page_stays_sorted(self):
        ids = [f"{NS}:export:npcs:solo"]
        self.assertEqual(deploy_export.write_order(ids, NS), ids)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_deploy_export.TestStagedPages tests.test_deploy_export.TestPlanDeploy tests.test_deploy_export.TestWriteOrder -v`
Expected: FAIL — missing attributes.

- [ ] **Step 3: Implement**

```python
# core.savePage refuses to create an empty page (error 132), so the render
# half's zero-byte placeholder cannot cross RPC as-is. ~~NOTOC~~ renders
# nothing, so the page displays blank while being non-empty and existing —
# which is all a placeholder is for. The one place staged bytes are not sent
# verbatim, and it carries no content.
PLACEHOLDER_BODY = "~~NOTOC~~\n"

PagePlan = namedtuple("PagePlan", "action wiki_text")
DeployPlan = namedtuple("DeployPlan", "pages orphans resolved_orphans refused")


def staged_pages(staging: Path) -> dict[str, str]:
    """Page ID -> text for every staged page, placeholder translation applied."""
    out: dict[str, str] = {}
    for path in sorted(staging.rglob("*.txt")):
        rel = path.relative_to(staging)
        pid = ":".join((*rel.parts[:-1], rel.stem))
        text = path.read_text(encoding="utf-8")
        out[pid] = text if text else PLACEHOLDER_BODY
    return out


def _protected(staged_ids, base: str) -> list[str]:
    """Belt and braces: the render half never generates these, but a render
    bug must not become a wiki write. Never fetched, never written."""
    names = {f"{base}:{name}" for name in PROTECTED_PAGE_NAMES}
    prefix = f"{base}:players:"
    return sorted(pid for pid in staged_ids
                  if pid in names or pid.startswith(prefix))


def plan_deploy(staged: dict[str, str], manifest: dict[str, str],
                fetch, base: str) -> DeployPlan:
    refused = _protected(staged, base)
    pages: dict[str, PagePlan] = {}
    for pid in sorted(staged):
        if pid in refused:
            continue
        wiki_text = fetch(pid)
        pages[pid] = PagePlan(
            classify_page(staged[pid], wiki_text, manifest.get(pid)),
            wiki_text)
    orphans: list[str] = []
    resolved: list[str] = []
    for pid in sorted(set(manifest) - set(staged)):
        # An orphan whose wiki page a human has since deleted resolves
        # itself: it drops from the manifest (in --go) instead of being
        # reported forever.
        (orphans if fetch(pid) is not None else resolved).append(pid)
    return DeployPlan(pages, orphans, resolved, refused)


def write_order(page_ids, base: str) -> list[str]:
    """Sorted page order, except each content page lands immediately before
    its wrapper — so a wrapper never points at a not-yet-written include for
    longer than one call."""
    ids = sorted(page_ids)
    present = set(ids)
    export_prefix = f"{base}:export:"

    def wrapper_of(pid: str) -> str:
        return f"{base}:{pid[len(export_prefix):]}"

    order: list[str] = []
    for pid in ids:
        if pid.startswith(export_prefix) and wrapper_of(pid) in present:
            continue  # emitted just before its wrapper below
        mate = f"{export_prefix}{pid[len(base) + 1:]}"
        if mate in present:
            order.append(mate)
        order.append(pid)
    return order
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m bunnyforge.run_tests`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/bunnyforge/deploy_export.py tests/test_deploy_export.py
git commit -m "feat: deploy planning — staged enumeration, protected guard, write order (#7)"
```

---

### Task 5: Apply — writes, read-back baselines, write-through manifest

**Files:**
- Modify: `src/bunnyforge/deploy_export.py`
- Test: `tests/test_deploy_export.py` (append; includes the FakeClient used by Tasks 6–7 too)

**Interfaces:**
- Consumes: `DeployPlan`, `write_order`, `page_hash`, `save_manifest` (Tasks 3–4); `RpcError`, `translate_error`, `SAVE_SUMMARY` from `_dokuwiki_rpc` (Task 1).
- Produces:
  - `ApplyResult = namedtuple("ApplyResult", "written adopted failure remaining")` — `written`/`adopted`/`remaining`: `list[str]`; `failure`: `str | None` (already-translated prose).
  - `apply_deploy(plan: DeployPlan, staged: dict[str, str], client, manifest: dict[str, str], manifest_path: Path, overwrite: set[str], base: str) -> ApplyResult` — mutates `manifest`, writes it through after **each** successful save; a failed save aborts and reports.
  - Writable actions: `new`, `update`, plus any held-back page (`drift`, `drift-manual-era`, `deleted-on-wiki`) named in `--overwrite`. `adopt` re-baselines without writing. `--overwrite` naming a page that is not held back raises `DeployError`.
  - Test helper `FakeClient` (module-level in the test file) — later tasks reuse it.

- [ ] **Step 1: Write the failing tests**

Add near the top of `tests/test_deploy_export.py` (after the existing helpers):

```python
from bunnyforge._dokuwiki_rpc import RpcError


class FakeClient:
    """In-memory wiki: a dict of pages. Mimics get_page/save_page, applies a
    save normalization (strips trailing newlines, like DokuWiki) so
    read-back hashing is exercised for real."""

    def __init__(self, pages=None, fail_on=None):
        self.pages = dict(pages or {})
        self.saves = []
        self.fail_on = fail_on

    def get_page(self, pid):
        return self.pages.get(pid)

    def save_page(self, pid, text, summary=None):
        if pid == self.fail_on:
            raise RpcError(111, "denied", "core.savePage")
        self.saves.append(pid)
        self.pages[pid] = text.rstrip("\n") + "\n"
```

Then the tests:

```python
class TestApplyDeploy(unittest.TestCase):
    def _apply(self, plan, staged, client, manifest, path, overwrite=()):
        return deploy_export.apply_deploy(
            plan, staged, client, manifest, path, set(overwrite), "w")

    def test_clean_deploy_writes_and_baselines_readback(self):
        client = FakeClient()
        staged = {"w:export:npcs:ana": "body\n\n", "w:npcs:ana": "wrap\n"}
        manifest = {}
        with tempfile.TemporaryDirectory() as d:
            mpath = Path(d) / "m.json"
            plan = deploy_export.plan_deploy(staged, manifest, client.get_page, "w")
            result = self._apply(plan, staged, client, manifest, mpath)
            self.assertIsNone(result.failure)
            # content before wrapper
            self.assertEqual(client.saves,
                             ["w:export:npcs:ana", "w:npcs:ana"])
            # baseline is the hash of the READ-BACK text (normalized by the
            # fake), not of the bytes sent
            self.assertEqual(manifest["w:export:npcs:ana"],
                             deploy_export.page_hash("body\n"))
            # manifest written through to disk
            self.assertEqual(deploy_export.load_manifest(mpath), manifest)

    def test_adopt_rebaselines_without_writing(self):
        client = FakeClient({"w:a": "same\n"})
        staged = {"w:a": "same\n"}
        manifest = {"w:a": "stale-hash"}
        with tempfile.TemporaryDirectory() as d:
            mpath = Path(d) / "m.json"
            plan = deploy_export.plan_deploy(staged, manifest, client.get_page, "w")
            result = self._apply(plan, staged, client, manifest, mpath)
            self.assertEqual(client.saves, [])
            self.assertEqual(result.adopted, ["w:a"])
            self.assertEqual(manifest["w:a"], deploy_export.page_hash("same\n"))
            self.assertEqual(deploy_export.load_manifest(mpath), manifest)

    def test_drift_held_unless_overwritten(self):
        client = FakeClient({"w:a": "wiki edit\n"})
        staged = {"w:a": "ours\n"}
        manifest = {"w:a": deploy_export.page_hash("older\n")}
        with tempfile.TemporaryDirectory() as d:
            mpath = Path(d) / "m.json"
            plan = deploy_export.plan_deploy(staged, manifest, client.get_page, "w")
            result = self._apply(plan, staged, client, manifest, mpath)
            self.assertEqual(client.saves, [])
            result = self._apply(plan, staged, client, manifest, mpath,
                                 overwrite=["w:a"])
            self.assertEqual(client.saves, ["w:a"])
            self.assertEqual(manifest["w:a"], deploy_export.page_hash("ours\n"))

    def test_overwrite_of_unheld_page_refused(self):
        client = FakeClient()
        staged = {"w:a": "x\n"}
        with tempfile.TemporaryDirectory() as d:
            plan = deploy_export.plan_deploy(staged, {}, client.get_page, "w")
            with self.assertRaises(deploy_export.DeployError) as ctx:
                self._apply(plan, staged, client, {}, Path(d) / "m.json",
                            overwrite=["w:nope"])
            self.assertIn("w:nope", str(ctx.exception))

    def test_failed_save_aborts_reports_written_and_remaining(self):
        client = FakeClient(fail_on="w:b")
        staged = {"w:a": "1\n", "w:b": "2\n", "w:c": "3\n"}
        manifest = {}
        with tempfile.TemporaryDirectory() as d:
            mpath = Path(d) / "m.json"
            plan = deploy_export.plan_deploy(staged, manifest, client.get_page, "w")
            result = self._apply(plan, staged, client, manifest, mpath)
            self.assertIsNotNone(result.failure)
            self.assertIn("ACL", result.failure)  # translated, not raw
            self.assertEqual(result.written, ["w:a"])
            self.assertEqual(result.remaining, ["w:b", "w:c"])
            # the page that DID land is baselined — re-run converges
            self.assertIn("w:a", deploy_export.load_manifest(mpath))
            self.assertNotIn("w:b", deploy_export.load_manifest(mpath))

    def test_resolved_orphans_dropped_from_manifest(self):
        client = FakeClient({"w:a": "x\n"})
        staged = {"w:a": "x\n"}
        manifest = {"w:a": deploy_export.page_hash("x\n"), "w:gone": "h"}
        with tempfile.TemporaryDirectory() as d:
            mpath = Path(d) / "m.json"
            plan = deploy_export.plan_deploy(staged, manifest, client.get_page, "w")
            self._apply(plan, staged, client, manifest, mpath)
            self.assertNotIn("w:gone", manifest)
            self.assertNotIn("w:gone", deploy_export.load_manifest(mpath))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_deploy_export.TestApplyDeploy -v`
Expected: FAIL — `apply_deploy` missing.

- [ ] **Step 3: Implement** (append to `deploy_export.py`; add `from bunnyforge._dokuwiki_rpc import RpcError, translate_error` to imports — module import stays lazy-free since the module itself imports only stdlib)

```python
ApplyResult = namedtuple("ApplyResult", "written adopted failure remaining")

# Held-back actions: written only when named in --overwrite, and always
# re-baselined when written.
_HELD = ("drift", "drift-manual-era", "deleted-on-wiki")


def apply_deploy(plan: DeployPlan, staged: dict[str, str], client,
                 manifest: dict[str, str], manifest_path: Path,
                 overwrite: set[str], base: str) -> ApplyResult:
    """Perform the writes a plan calls for. Mutates `manifest` and writes it
    through to disk after each successful save, so a run that dies mid-way
    needs no resume machinery — re-running converges (unchanged / adopt).
    """
    held = {pid for pid, p in plan.pages.items() if p.action in _HELD}
    unknown = sorted(overwrite - held)
    if unknown:
        raise DeployError(
            f"--overwrite names page(s) not held back this run: "
            f"{', '.join(unknown)} — nothing to clobber.")

    to_write = [pid for pid, p in plan.pages.items()
                if p.action in ("new", "update") or pid in overwrite]
    written: list[str] = []
    adopted: list[str] = []

    for pid, p in plan.pages.items():
        if p.action == "adopt":
            manifest[pid] = page_hash(p.wiki_text)
            adopted.append(pid)
    for pid in plan.resolved_orphans:
        manifest.pop(pid, None)
    if adopted or plan.resolved_orphans:
        save_manifest(manifest_path, manifest)

    for pid in write_order(to_write, base):
        try:
            client.save_page(pid, staged[pid])
            readback = client.get_page(pid)
        except RpcError as exc:
            remaining = [i for i in write_order(to_write, base)
                         if i not in written]
            return ApplyResult(
                written, sorted(adopted),
                f"{pid}: {translate_error(exc, '')}", remaining)
        manifest[pid] = page_hash(readback or "")
        save_manifest(manifest_path, manifest)
        written.append(pid)

    return ApplyResult(written, sorted(adopted), None, [])
```

Note: `translate_error`'s `wiki_url` argument is only used by the two transport sentinels; the caller in Task 7 passes the real URL. Here pass the URL through — change `apply_deploy` to also take `wiki_url: str` and use it, and update the test helper accordingly (`self._apply` passes `"https://<wiki>"`). Keep the signature: `apply_deploy(plan, staged, client, manifest, manifest_path, overwrite, base, wiki_url)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m bunnyforge.run_tests`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/bunnyforge/deploy_export.py tests/test_deploy_export.py
git commit -m "feat: deploy apply phase with write-through manifest (#7)"
```

---

### Task 6: Drift report, inbound copies, orchestration

**Files:**
- Modify: `src/bunnyforge/deploy_export.py`
- Test: `tests/test_deploy_export.py` (append)

**Interfaces:**
- Consumes: everything from Tasks 3–5; `page_path` from `_dokuwiki` (existing).
- Produces:
  - `write_drift_copies(held: dict[str, str], drift_dir: Path) -> None` — `held` maps page ID → current wiki text; recreates `drift_dir` from empty.
  - `format_deploy_report(plan: DeployPlan, staged: dict[str, str], overwrite: set[str], go: bool) -> tuple[list[str], bool]` — report lines and a `held_or_orphaned` bool that drives the exit code.
  - `run_deploy(ws, staging: Path, client, go: bool, overwrite: set[str], wiki_url: str) -> int` — the whole plan/report/copies/apply pipeline over an already-rendered staging tree; **the only wiki-write difference between dry-run and `--go` is whether `apply_deploy` runs.** Tests drive this with `FakeClient`; `main()` (Task 7) only adds rendering + client construction.

- [ ] **Step 1: Write the failing tests**

```python
def make_workspace(d: Path) -> Path:
    (d / "campaign.toml").write_text(_MINIMAL_CAMPAIGN_TOML, encoding="utf-8")
    return d


class TestDriftCopies(unittest.TestCase):
    def test_copies_mirror_pages_layout_and_dir_recreated(self):
        with tempfile.TemporaryDirectory() as d:
            drift = Path(d) / "wiki-drift"
            stale = drift / "old.txt"
            stale.parent.mkdir(parents=True)
            stale.write_text("stale", encoding="utf-8")
            deploy_export.write_drift_copies(
                {"w:npcs:ana": "wiki text\n"}, drift)
            self.assertFalse(stale.exists())  # recreated from empty
            copy = drift / "w" / "npcs" / "ana.txt"
            self.assertEqual(copy.read_text(encoding="utf-8"), "wiki text\n")


class TestRunDeploy(unittest.TestCase):
    def _stage(self, d: Path, pages: dict) -> Path:
        staging = d / "stage"
        for pid, text in pages.items():
            p = deploy_export.page_path(pid, staging)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        return staging

    def _run(self, ws_root, staging, client, go=False, overwrite=()):
        ws = _config.open_workspace(ws_root)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            rc = deploy_export.run_deploy(
                ws, staging, client, go, set(overwrite), "https://<wiki>")
        return rc, out.getvalue()

    def test_dry_run_is_default_shape_no_writes_no_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            d = make_workspace(Path(d))
            staging = self._stage(d, {"test:npcs:ana": "hello\n"})
            client = FakeClient()
            rc, out = self._run(d, staging, client, go=False)
            self.assertEqual(rc, 0)
            self.assertEqual(client.saves, [])  # zero wiki writes
            self.assertFalse(
                (d / ".bunnyforge" / "wiki-manifest.json").exists())
            self.assertIn("new", out)  # the full plan is printed

    def test_go_writes_and_persists_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            d = make_workspace(Path(d))
            staging = self._stage(d, {"test:npcs:ana": "hello\n"})
            client = FakeClient()
            rc, _ = self._run(d, staging, client, go=True)
            self.assertEqual(rc, 0)
            self.assertEqual(client.saves, ["test:npcs:ana"])
            manifest = deploy_export.load_manifest(
                d / ".bunnyforge" / "wiki-manifest.json")
            self.assertIn("test:npcs:ana", manifest)

    def test_drift_held_diffed_copied_and_nonzero_in_both_modes(self):
        with tempfile.TemporaryDirectory() as d:
            d = make_workspace(Path(d))
            staging = self._stage(d, {"test:npcs:ana": "ours\n"})
            client = FakeClient({"test:npcs:ana": "theirs\n"})
            for go in (False, True):
                with self.subTest(go=go):
                    rc, out = self._run(d, staging, client, go=go)
                    self.assertEqual(rc, 1)
                    self.assertEqual(client.saves, [])
                    self.assertIn("wiki (current)", out)   # unified diff sides
                    self.assertIn("deploy (target)", out)
                    self.assertIn("--overwrite", out)      # resolution path
                    copy = (d / ".bunnyforge" / "wiki-drift" / "test" /
                            "npcs" / "ana.txt")
                    self.assertEqual(copy.read_text(encoding="utf-8"),
                                     "theirs\n")

    def test_deleted_on_wiki_held_and_reported(self):
        with tempfile.TemporaryDirectory() as d:
            d = make_workspace(Path(d))
            staging = self._stage(d, {"test:npcs:ana": "ours\n"})
            deploy_export.save_manifest(
                d / ".bunnyforge" / "wiki-manifest.json",
                {"test:npcs:ana": "somehash"})
            client = FakeClient()  # page absent on wiki
            rc, out = self._run(d, staging, client, go=True)
            self.assertEqual(rc, 1)
            self.assertEqual(client.saves, [])
            self.assertIn("deleted", out)

    def test_orphan_reported_never_deleted_nonzero(self):
        with tempfile.TemporaryDirectory() as d:
            d = make_workspace(Path(d))
            staging = self._stage(d, {"test:npcs:ana": "x\n"})
            client = FakeClient({"test:npcs:ana": "x\n",
                                 "test:npcs:retired": "old\n"})
            deploy_export.save_manifest(
                d / ".bunnyforge" / "wiki-manifest.json",
                {"test:npcs:ana": deploy_export.page_hash("x\n"),
                 "test:npcs:retired": deploy_export.page_hash("old\n")})
            rc, out = self._run(d, staging, client, go=True)
            self.assertEqual(rc, 1)
            self.assertIn("test:npcs:retired", out)
            self.assertIn("manual", out)  # removal is a manual act
            self.assertIn("test:npcs:retired", client.pages)  # never deleted

    def test_resume_after_crash_adopts_and_exits_zero(self):
        with tempfile.TemporaryDirectory() as d:
            d = make_workspace(Path(d))
            staging = self._stage(d, {"test:npcs:ana": "same\n"})
            client = FakeClient({"test:npcs:ana": "same\n"})
            deploy_export.save_manifest(
                d / ".bunnyforge" / "wiki-manifest.json",
                {"test:npcs:ana": "stale-pre-crash-hash"})
            rc, out = self._run(d, staging, client, go=True)
            self.assertEqual(rc, 0)
            self.assertEqual(client.saves, [])
            self.assertIn("adopt", out)

    def test_drift_dir_recreated_each_planning_run(self):
        with tempfile.TemporaryDirectory() as d:
            d = make_workspace(Path(d))
            stale = d / ".bunnyforge" / "wiki-drift" / "stale.txt"
            stale.parent.mkdir(parents=True)
            stale.write_text("old", encoding="utf-8")
            staging = self._stage(d, {"test:npcs:ana": "x\n"})
            client = FakeClient({"test:npcs:ana": "x\n"})
            deploy_export.save_manifest(
                d / ".bunnyforge" / "wiki-manifest.json",
                {"test:npcs:ana": deploy_export.page_hash("x\n")})
            rc, _ = self._run(d, staging, client)
            self.assertEqual(rc, 0)
            self.assertFalse(stale.exists())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_deploy_export.TestDriftCopies tests.test_deploy_export.TestRunDeploy -v`
Expected: FAIL — missing attributes. (Also add `page_path` to `deploy_export`'s imports from `_dokuwiki` if the test's `deploy_export.page_path` reference fails.)

- [ ] **Step 3: Implement** (append; add `import difflib`, `import shutil` to imports and `page_path` to the `_dokuwiki` import list)

```python
_HELD_REASONS = {
    "drift": "changed on the wiki since the last deploy",
    "drift-manual-era": "no baseline for it — could be hand-edits from the "
                        "manual era",
    "deleted-on-wiki": "a human deleted it on the wiki; recreating it would "
                       "clobber that decision",
}


def write_drift_copies(held: dict[str, str], drift_dir: Path) -> None:
    """Each drifted page's current wiki text, laid out like data/pages/, for
    manual merge. The tool owns this directory outright: recreated from empty
    every planning run, so a page that stops drifting leaves no stale copy."""
    if drift_dir.exists():
        shutil.rmtree(drift_dir)
    drift_dir.mkdir(parents=True)
    for pid, wiki_text in held.items():
        dest = page_path(pid, drift_dir)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(wiki_text, encoding="utf-8")


def format_deploy_report(plan: DeployPlan, staged: dict[str, str],
                         overwrite: set[str], go: bool) -> tuple[list[str], bool]:
    lines: list[str] = []
    held_pages = []
    for pid in sorted(plan.pages):
        p = plan.pages[pid]
        if p.action in _HELD and pid not in overwrite:
            held_pages.append(pid)
            continue
        word = "overwrite" if pid in overwrite else p.action
        lines.append(f"  {word:<12} {pid}")
    for pid in plan.refused:
        lines.append(f"  refused      {pid}  (protected page — never written)")

    for pid in held_pages:
        p = plan.pages[pid]
        lines.append(f"\n  HELD  {pid} — {_HELD_REASONS[p.action]}")
        if p.wiki_text is not None:
            diff = difflib.unified_diff(
                p.wiki_text.splitlines(keepends=True),
                staged[pid].splitlines(keepends=True),
                fromfile="wiki (current)", tofile="deploy (target)")
            lines.extend("    " + line.rstrip("\n") for line in diff)
    if held_pages:
        lines.append(
            "\nHeld-back pages: pull the wiki edit into the workspace source "
            "(the next render then matches and the drift disappears), or "
            "re-run with --overwrite <page-id> --go to clobber that page "
            "and re-baseline it. Current wiki text saved under "
            f"{DRIFT_DIR}/ for manual merge.")

    for pid in plan.orphans:
        lines.append(
            f"  orphan       {pid} — in the manifest but no longer staged; "
            "removing the wiki page is a manual act, this tool never "
            "deletes.")
    for pid in plan.resolved_orphans:
        lines.append(
            f"  resolved     {pid} — deleted on the wiki; "
            + ("dropped from the manifest." if go else
               "will drop from the manifest on --go."))

    held_or_orphaned = bool(held_pages or plan.orphans)
    return lines, held_or_orphaned


def run_deploy(ws, staging: Path, client, go: bool, overwrite: set[str],
               wiki_url: str) -> int:
    """Plan, report, copy drift, and (with go) apply. Exit-code contract:
    non-zero if anything was held back or any orphan was reported, in both
    modes — matching the render half's fail-loudly posture."""
    base = ws.config.namespace
    manifest_path = ws.root / MANIFEST_FILE
    manifest = load_manifest(manifest_path)
    staged = staged_pages(staging)

    try:
        plan = plan_deploy(staged, manifest, client.get_page, base)
    except RpcError as exc:
        print(f"error: {translate_error(exc, wiki_url)}", file=sys.stderr)
        return 1

    held = {pid: p.wiki_text for pid, p in plan.pages.items()
            if p.action in _HELD and pid not in overwrite
            and p.wiki_text is not None}
    # Copies are part of reporting, not deployment: written in both modes.
    write_drift_copies(held, ws.root / DRIFT_DIR)

    lines, held_or_orphaned = format_deploy_report(plan, staged, overwrite, go)
    print("\n".join(lines))

    if go:
        result = apply_deploy(plan, staged, client, manifest, manifest_path,
                              overwrite, base, wiki_url)
        for pid in result.written:
            print(f"  saved        {pid}")
        if result.failure:
            print(f"\nerror: {result.failure}", file=sys.stderr)
            print(f"Written before the failure: "
                  f"{', '.join(result.written) or 'nothing'}.\n"
                  f"Not yet written: {', '.join(result.remaining)}.\n"
                  "Re-run to converge — already-written pages classify as "
                  "unchanged or adopt.", file=sys.stderr)
            return 1
        print(f"\nDeployed {len(result.written)} page(s), "
              f"adopted {len(result.adopted)}.")
    else:
        writes = sum(1 for pid, p in plan.pages.items()
                     if p.action in ("new", "update") or pid in overwrite)
        print(f"\nDry run: {writes} page(s) would be written. "
              "Re-run with --go to deploy.")

    return 1 if held_or_orphaned else 0
```

Note `run_deploy` swallows nothing: `DeployError` (bad manifest, bad `--overwrite`) propagates to `main()`, which catches and prints it (Task 7).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m bunnyforge.run_tests`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/bunnyforge/deploy_export.py tests/test_deploy_export.py
git commit -m "feat: drift report, inbound copies, deploy orchestration (#7)"
```

---

### Task 7: The new CLI surface — `main()`

**Files:**
- Modify: `src/bunnyforge/deploy_export.py` — `main()` (currently lines 218–321) and the module docstring (lines 1–25)
- Test: `tests/test_deploy_export.py` — **update** `test_missing_render_only_is_refused` (line ~205), append new CLI tests

**Interfaces:**
- Consumes: `run_deploy` (Task 6), `RpcClient` (Task 1), `resolve_wiki_token` (Task 2).
- Produces: the CLI contract —
  - default = dry run (read-only network); `--go` = deploy; `--render-only` = offline, unchanged behavior.
  - `--render-only` and `--go` mutually exclusive (argparse group).
  - `--staging` optional in dry-run/`--go` (temp dir removed at exit when omitted); **required** with `--render-only`.
  - `--overwrite PAGE_ID` repeatable (`action="append"`); distinct from `import_perceptions`' boolean `--overwrite` (different command, no clash).
  - Missing `[wiki] url` / token → instructional errors, only when the run needs the network.

- [ ] **Step 1: Update the stale test and write the new failing tests**

Replace `test_missing_render_only_is_refused` (which pins the old "only --render-only is implemented" guard) with:

```python
    def test_default_run_without_wiki_config_is_instructional(self):
        # Bare deploy-export is now a network dry run; with no [wiki] url it
        # must say exactly what to add and where, and mention --render-only.
        with tempfile.TemporaryDirectory() as d:
            export = make_export(Path(d) / "Export", {"Mechanics/a.md": "# A\n"})
            rc, _out, err = self._run(
                ["--workspace", str(d), "--export-dir", str(export)])
            self.assertEqual(rc, 1)
            self.assertIn("[wiki]", err)
            self.assertIn('url = "https://<wiki>"', err)
            self.assertIn("--render-only", err)
```

Append:

```python
class TestNewCliSurface(unittest.TestCase):
    def _run(self, argv):
        return run_main(argv)

    def test_render_only_and_go_mutually_exclusive(self):
        with self.assertRaises(SystemExit) as ctx:
            deploy_export.main(["--render-only", "--go", "--staging", "/tmp/x"])
        self.assertEqual(ctx.exception.code, 2)

    def test_render_only_still_requires_staging(self):
        with tempfile.TemporaryDirectory() as d:
            make_export(Path(d) / "Export", {"Mechanics/a.md": "# A\n"})
            rc, _out, err = self._run(["--workspace", str(d), "--render-only"])
            self.assertEqual(rc, 1)
            self.assertIn("--staging", err)

    def test_missing_token_is_instructional(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "campaign.toml").write_text(
                '[campaign]\nnamespace = "test"\n'
                '[wiki]\nurl = "https://wiki.invalid"\n', encoding="utf-8")
            make_export(Path(d) / "Export", {"Mechanics/a.md": "# A\n"})
            os.environ.pop("BUNNYFORGE_WIKI_TOKEN", None)
            rc, _out, err = self._run(["--workspace", str(d)])
            self.assertEqual(rc, 1)
            self.assertIn("BUNNYFORGE_WIKI_TOKEN", err)

    def test_http_url_refused_before_any_network(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "campaign.toml").write_text(
                '[campaign]\nnamespace = "test"\n'
                '[wiki]\nurl = "http://wiki.invalid"\n', encoding="utf-8")
            make_export(Path(d) / "Export", {"Mechanics/a.md": "# A\n"})
            with unittest.mock.patch.dict(
                    os.environ, {"BUNNYFORGE_WIKI_TOKEN": "t"}):
                rc, _out, err = self._run(["--workspace", str(d)])
            self.assertEqual(rc, 1)
            self.assertIn("http://", err)
```

Add `import os` / `import unittest.mock` to the test module imports if absent. (No test drives a real network dry run through `main()` — that path is `run_deploy`'s, already covered with `FakeClient` in Task 6. The `main()` tests stop at the config/credential/URL gates, which all fire before any socket.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_deploy_export -v 2>&1 | tail -20`
Expected: the new tests FAIL against the old CLI (bare run prints "only --render-only is implemented").

- [ ] **Step 3: Rewrite `main()`**

Add `import tempfile` and `from bunnyforge import _config as config_mod` — or import the names directly: extend the existing `_config` import line to `from bunnyforge._config import (ConfigError, Workspace, resolve_workspace, resolve_wiki_token)` and add `from bunnyforge._dokuwiki_rpc import RpcClient`.

```python
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bunnyforge deploy-export",
        description="Render Export/ and deploy it to the wiki over JSON-RPC. "
                    "The default run is a dry run: it renders, fetches, and "
                    "prints the full plan, writing nothing to the wiki.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--go", action="store_true",
                      help="Perform the writes the plan calls for")
    mode.add_argument("--render-only", action="store_true",
                      help="Render to --staging and stop; no network, no "
                           "[wiki] config, no token needed")
    parser.add_argument("--staging", default=None,
                        help="Directory for the staged page tree. Optional "
                             "(a temp directory otherwise); required with "
                             "--render-only, where the tree is the "
                             "deliverable")
    parser.add_argument("--overwrite", action="append", default=[],
                        metavar="PAGE_ID",
                        help="Write this drifted/held-back page anyway and "
                             "re-baseline it (repeatable; takes effect with "
                             "--go)")
    parser.add_argument("--export-dir", default=None,
                        help="Source directory (default: the resolved "
                             "workspace's Export/, so it follows --workspace)")
    parser.add_argument("--create-empty-placeholders", action="store_true",
                        help=... )  # unchanged text from today
    parser.add_argument("--workspace", metavar="PATH", help=...)  # unchanged

    args = parser.parse_args(argv)

    if args.render_only and not args.staging:
        print("error: --render-only needs --staging PATH — the staged tree "
              "is the deliverable of a render-only run", file=sys.stderr)
        return 1

    try:
        ws = resolve_workspace(args.workspace)
    except (WorkspaceError, ConfigError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    # ... existing export_dir resolution and staging-not-empty refusal,
    # applied only when args.staging was given ...

    # Network needs are gated up front, before any rendering, so a config
    # problem is reported in one second, not after a full render.
    client = None
    if not args.render_only:
        wiki_url = ws.config.wiki_url
        if not wiki_url:
            print("error: campaign.toml has no [wiki] url — deploying needs "
                  "to know where the wiki is. Add:\n\n"
                  "  [wiki]\n"
                  '  url = "https://<wiki>"\n\n'
                  "(--render-only needs no [wiki] and no token.)",
                  file=sys.stderr)
            return 1
        try:
            token = resolve_wiki_token(ws.root)
            client = RpcClient(wiki_url, token)
        except (ConfigError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    # Render (existing code path, byte-identical output). When --staging is
    # omitted the tree goes to a temp directory removed at exit — a deploy
    # always uploads what it just rendered, so a stale tree can never be
    # pushed.
    with contextlib.ExitStack() as stack:
        if args.staging:
            staging = Path(args.staging).expanduser().resolve()
            # ... existing exists/not-empty refusal ...
        else:
            staging = Path(stack.enter_context(tempfile.TemporaryDirectory()))

        # ... existing render: rels, resolver, render_tree, log printing,
        # collision and fatal-link handling, placeholder-ID listing —
        # unchanged, all still abort with return 1 before any deploy ...

        if args.render_only:
            return 0

        try:
            return run_deploy(ws, staging, client, args.go,
                              set(args.overwrite), ws.config.wiki_url)
        except DeployError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
```

(`import contextlib` joins the imports.) Update the module docstring: drop "Transport, the content manifest, and drift detection arrive in a later change; --render-only is currently the only supported mode", document the three invocations from the spec's CLI table, and note the dry-run/`--go` convention.

- [ ] **Step 4: Run the full suite**

Run: `python3 -m bunnyforge.run_tests`
Expected: PASS — including every pre-existing `--render-only --staging` test, unchanged.

- [ ] **Step 5: Commit**

```bash
git add src/bunnyforge/deploy_export.py tests/test_deploy_export.py
git commit -m "feat: deploy-export dry-run/--go CLI; --staging optional off render-only (#7)"
```

---

### Task 8: `review wiki` gains `wiki-remote`

**Files:**
- Modify: `src/bunnyforge/review.py` (new check after `check_wiki_plugins` ~line 351; `CHECKS` ~line 354; `SUITES["wiki"]` ~line 371; `_NEEDS_WIKI` ~line 380)
- Test: `tests/test_review.py` (append; follow the existing wiki-suite fixture pattern in that file — fixture `conf/` trees on disk)

**Interfaces:**
- Consumes: `dwi.read_conf` (existing), `_UPGRADE_SAFE_CONF` (existing, line 286).
- Produces: `check_wiki_remote(files, wiki_root) -> list[Finding]`, registered as `"wiki-remote"` in `CHECKS`, `SUITES["wiki"]`, and `_NEEDS_WIKI`.

- [ ] **Step 1: Write the failing tests**

```python
class TestWikiRemote(unittest.TestCase):
    def _wiki(self, d: Path, local_php="", dokuwiki_php=""):
        (d / "conf").mkdir(parents=True, exist_ok=True)
        (d / "lib" / "plugins").mkdir(parents=True, exist_ok=True)
        (d / "conf" / "dokuwiki.php").write_text(
            "<?php\n" + dokuwiki_php, encoding="utf-8")
        if local_php:
            (d / "conf" / "local.php").write_text(
                "<?php\n" + local_php, encoding="utf-8")
        return d

    def _findings(self, d):
        return review.check_wiki_remote([], d)

    def test_disabled_is_no_finding(self):
        with tempfile.TemporaryDirectory() as d:
            wiki = self._wiki(Path(d), dokuwiki_php="$conf['remote'] = 0;\n")
            self.assertEqual(self._findings(wiki), [])

    def test_enabled_without_remoteuser_is_error(self):
        with tempfile.TemporaryDirectory() as d:
            wiki = self._wiki(Path(d), local_php="$conf['remote'] = 1;\n")
            findings = self._findings(wiki)
            self.assertTrue(any(f.severity == "error" and
                                "remoteuser" in f.message for f in findings))

    def test_stock_not_set_placeholder_counts_as_unset(self):
        with tempfile.TemporaryDirectory() as d:
            wiki = self._wiki(Path(d), local_php=(
                "$conf['remote'] = 1;\n"
                "$conf['remoteuser'] = '!!not set!!';\n"))
            findings = self._findings(wiki)
            self.assertTrue(any("remoteuser" in f.message for f in findings))

    def test_scoped_remoteuser_is_clean(self):
        with tempfile.TemporaryDirectory() as d:
            wiki = self._wiki(Path(d), local_php=(
                "$conf['remote'] = 1;\n"
                "$conf['remoteuser'] = 'deploybot';\n"))
            self.assertEqual(self._findings(wiki), [])

    def test_enabled_from_dokuwiki_php_is_provenance_error(self):
        with tempfile.TemporaryDirectory() as d:
            wiki = self._wiki(Path(d), dokuwiki_php=(
                "$conf['remote'] = 1;\n"
                "$conf['remoteuser'] = 'deploybot';\n"))
            findings = self._findings(wiki)
            self.assertTrue(any(f.severity == "error" and
                                "dokuwiki.php" in f.message for f in findings))

    def test_wiki_suite_includes_wiki_remote(self):
        self.assertIn("wiki-remote", review.SUITES["wiki"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_review.TestWikiRemote -v`
Expected: FAIL — `check_wiki_remote` missing.

- [ ] **Step 3: Implement** (after `check_wiki_plugins`)

```python
# remoteuser's stock value is a placeholder DokuWiki treats as
# not-configured; the check must treat it as unset, not as a scoping.
_REMOTEUSER_UNSET = "!!not set!!"


def check_wiki_remote(files: list[FileRec], wiki_root: Path) -> list[Finding]:
    """The deploy transport's preconditions, stated as universal rules.

    A disabled API is a legitimate secure state and yields no finding — the
    deploy's own -32605 translation owns that path. Built on read_conf: no
    network, so the suite stays runnable against a filesystem copy and CI
    never needs a live wiki.
    """
    conf = dwi.read_conf(wiki_root)
    remote = conf.get("remote")
    if remote is None or not remote.value:
        return []
    out: list[Finding] = []
    if remote.source not in _UPGRADE_SAFE_CONF:
        out.append(Finding(
            "error", "wiki-remote", f"conf/{remote.source}",
            f"remote is enabled but set in {remote.source}, which DokuWiki "
            f"upgrades overwrite — move it to conf/local.php"))
    ru = conf.get("remoteuser")
    value = str(ru.value).strip() if ru and ru.value is not None else ""
    if not value or value == _REMOTEUSER_UNSET:
        out.append(Finding(
            "error", "wiki-remote", "conf/",
            "remote is enabled but remoteuser is unset or empty — every "
            "wiki account can call the API; scope it to the deploy user in "
            "conf/local.php"))
    return out
```

Register it: `"wiki-remote": check_wiki_remote` in `CHECKS`; append `"wiki-remote"` to `SUITES["wiki"]`; add `"wiki-remote"` to `_NEEDS_WIKI`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m bunnyforge.run_tests`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/bunnyforge/review.py tests/test_review.py
git commit -m "feat: wiki-remote review check — remote API scoping and provenance (#7)"
```

---

### Task 9: `import-perceptions` adopts dry-run/`--go`

**Files:**
- Modify: `src/bunnyforge/import_perceptions.py` (argparse ~lines 216, docstring usage lines 17–23, the `args.dry_run` uses at lines 265, 297)
- Test: `tests/test_import_perceptions.py` — update `test_dry_run_writes_nothing` (~line 404) and every invocation that expects writes; add `--go` tests

- [ ] **Step 1: Update/write the failing tests**

In `tests/test_import_perceptions.py`:
- `test_dry_run_writes_nothing` (~line 404): drop `"--dry-run"` from the argv — the bare run **is** now the dry run; keep every assertion (writes nothing, never creates the destination directory).
- Every existing test that asserts files were written: add `"--go"` to its argv (grep the file for invocations without `--dry-run` that assert on written files, e.g. ~line 450).
- Add:

```python
    def test_go_writes(self):
        # mirror of test_dry_run_writes_nothing with --go: files appear
        ...

    def test_dry_run_flag_removed(self):
        with self.assertRaises(SystemExit) as ctx:
            ip.main(["--wiki-data", "/nonexistent", "--dry-run"])
        self.assertEqual(ctx.exception.code, 2)  # argparse: unrecognized
```

(Write `test_go_writes` by copying an existing written-files test body; it must assert at least one file exists afterward with the expected front matter.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_import_perceptions -v 2>&1 | tail -5`
Expected: new/updated tests FAIL (bare run currently writes).

- [ ] **Step 3: Implement**

In `import_perceptions.py`:
- Replace the `--dry-run` argument with:

```python
    parser.add_argument(
        "--go", action="store_true",
        help="Write the files. Without it this is a dry run that only "
             "reports what would be written (the package-wide convention).")
```

- Replace both `args.dry_run` references with `not args.go` (line ~265: `if args.go: perceptions_dir.mkdir(...)`; line ~297: `if not args.go: print("[dry-run] would write" ...)`).
- Update the description line to say the default is a dry run, and the module docstring's usage block: swap the `--dry-run` example for a bare run commented "(dry run — default)" plus a `--go` example.
- Add a final dry-run hint after the summary when `not args.go` and anything would be written: `print("Dry run: re-run with --go to write.")`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m bunnyforge.run_tests`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/bunnyforge/import_perceptions.py tests/test_import_perceptions.py
git commit -m "feat!: import-perceptions defaults to dry run; --go writes, --dry-run removed (#7)"
```

---

### Task 10: `init` scaffold ignores the token and drift dir

**Files:**
- Modify: `src/bunnyforge/data/root/gitignore`
- Test: `tests/test_init.py` (append one test)

- [ ] **Step 1: Write the failing test** (append, following that file's existing scaffold-then-assert pattern)

```python
    def test_gitignore_covers_wiki_token_and_drift(self):
        # ... scaffold a workspace via init.main([...]) per the file's
        # existing pattern ...
        text = (root / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".bunnyforge/wiki-token", text)
        self.assertIn(".bunnyforge/wiki-drift/", text)
        # The manifest stays committed: the ignores are two entries, never
        # the whole directory.
        self.assertNotIn(".bunnyforge/\n", text)
```

- [ ] **Step 2: Run to verify it fails**, then **Step 3: Implement** — append to `src/bunnyforge/data/root/gitignore`:

```gitignore

# Wiki deploy: the credential and the tool-owned drift copies. The deploy
# manifest (.bunnyforge/wiki-manifest.json) is deliberately NOT ignored —
# it is the committed baseline.
.bunnyforge/wiki-token
.bunnyforge/wiki-drift/
```

- [ ] **Step 4: Run tests** — `python3 -m bunnyforge.run_tests` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/bunnyforge/data/root/gitignore tests/test_init.py
git commit -m "feat: init scaffold gitignores wiki-token and wiki-drift (#7)"
```

---

### Task 11: Docs, supersession annotation, version bump

**Files:**
- Modify: `docs/superpowers/specs/2026-07-27-player-wiki-export-design.md` (annotation at top)
- Modify: `README.md` (pipeline description; new convention section; Releasing untouched)
- Modify: `src/bunnyforge/README.md` (deploy-export section ~lines 220–300)
- Modify: `pyproject.toml` (version)

- [ ] **Step 1: Annotate the superseded spec**

At the top of `2026-07-27-player-wiki-export-design.md`, directly under the title, insert:

```markdown
> **Partially superseded (2026-08-05):** the transport half of this design
> (sequencing steps 6–8: rsync, `receive_export.sh`, `indexer.php`, the
> server-side `manifest.json`) is superseded by
> [2026-08-05-deploy-export-rpc-transport-design.md](2026-08-05-deploy-export-rpc-transport-design.md),
> which replaces it with DokuWiki's JSON-RPC API. The render half — namespace
> layout, wrapper format, ACL design, wikilink rewriting, leak-test posture —
> is shipped and untouched. The drift guarantee carries over verbatim; the
> open absolute-link verification item carries into the new spec's
> first-deploy checklist.
```

- [ ] **Step 2: Update both READMEs**

`README.md`: where the pipeline is described, remove any "(manual copy)" step between deploy-export and the wiki; add a short section:

```markdown
## Dry runs and --go

Every mutating command follows one convention: **the default run is a dry
run; `--go` performs the writes.** A bare `bunnyforge deploy-export` fetches
and prints the full deploy plan without writing anything; a bare
`bunnyforge import-perceptions` reports what it would import. Re-run with
`--go` to act. (`deploy-export --render-only` is not a rehearsal — it is a
different, offline deliverable, and needs no wiki config at all.)

Future mutating commands inherit this convention.
```

`src/bunnyforge/README.md` (~lines 220–300): replace "Transport to the server is not implemented yet; `--render-only` is currently the only supported mode" with the spec's CLI table (dry run / `--go` / `--render-only`), the `[wiki]` + token setup (both sources, `chmod 600`), the manifest ("committed — deploying from a second machine sees the truth"), drift hold-back + `wiki-drift/` copies + `--overwrite`, orphan reporting, and a note that `import-perceptions` changed from `--dry-run` to dry-by-default + `--go` (breaking, pre-1.0).

- [ ] **Step 3: Bump the version**

`pyproject.toml` line 7: `version = "0.2.0"` — first network capability plus a CLI break in `import-perceptions` = minor bump. Tagging `v0.2.0` and publishing stay a human act per README's Releasing section (expect PyPI index lag before the campaign repo can re-pin).

- [ ] **Step 4: Full suite + portability check**

Run: `python3 -m bunnyforge.run_tests`
Expected: PASS on the local interpreter; CI covers 3.11/3.12/3.13.
Also grep the diff for campaign terms: `git diff main | grep -iE "anjeong|<real hostname>"` must be empty — placeholders only.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-07-27-player-wiki-export-design.md \
        README.md src/bunnyforge/README.md pyproject.toml
git commit -m "docs: RPC transport docs, supersession annotation; bump to 0.2.0 (#7)"
```

---

### Task 12: Final verification and PR

- [ ] **Step 1: Full suite, fresh count**

Run: `python3 -m bunnyforge.run_tests 2>&1 | tail -3`
Expected: PASS; `Ran N tests` with N > Task 0's count (record both numbers for the PR body — re-derived, not quoted from prose).

- [ ] **Step 2: Secrets scan**

`git diff main` — confirm no tokens, no real hostnames, no campaign terms.

- [ ] **Step 3: Open the PR**

Base `main`, head `deploy-export-rpc-transport`. PR body per the repo's collaboration rules: **Files changed** (annotated new/modified), **Work breakdown**, **Operational impact** (the `import-perceptions` CLI break; new `[wiki]`/token setup for deployers; 0.2.0 release pending), **Provenance** (agent + model). Wait for human review — do not merge.

- [ ] **Step 4: Surface the first-live-deploy checklist**

In the PR body, copy the spec's four first-live-deploy checklist items (NOTOC renders blank; `core.savePage` named-param spelling pinned; absolute-link-from-include resolution; read-back hash stability) — they are checked on the first real deploy, not in CI, and must not get lost.

---

## Self-review (performed while writing)

- **Spec coverage:** client (T1), config/credentials (T2), manifest + eight-row matrix (T3), protected guard/placeholder translation/plan (T4), apply/ordering/write-through/orphan self-cleanup (T5), drift report/copies/exit codes (T6), CLI surface incl. temp staging + `--overwrite` (T7), `wiki-remote` (T8), `import-perceptions` convention (T9), gitignore scaffold (T10), docs/supersession/0.2.0 (T11), first-deploy checklist surfaced (T12). `core.listPages` deliberately has no wrapper (YAGNI, per spec). Orphan deletion, media, XML-RPC, merge wizard: out of scope, untouched.
- **Type consistency:** `classify_page` labels appear identically in T3 tests, T4 `plan_deploy`, T5 `_HELD`, T6 `_HELD_REASONS`. `apply_deploy` takes `(plan, staged, client, manifest, manifest_path, overwrite, base, wiki_url)` — the T5 note amends the earlier signature; implement with `wiki_url`.
- **Known judgment calls** (flag in the PR): `--overwrite` accepted for `deleted-on-wiki` pages too, not just drift — destructive intent is still spelled per page; resolved orphans are informational, only actionable orphans drive the non-zero exit; unknown-version manifest refuses rather than guesses.

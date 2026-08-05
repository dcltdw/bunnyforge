import email.message
import http.client
import io
import json
import ssl
import unittest
import urllib.error
import urllib.request
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
        # The token is an *unredirected* header: sent on the wire like any
        # other, but never copied onto a redirected request. get_header falls
        # back to unredirected_hdrs, so it cannot tell the two apart — assert
        # on the exact dicts, which fails if the token moves back to the
        # redirectable ones.
        self.assertEqual(request.get_header("Authorization"), "Bearer tok123")
        self.assertEqual(request.unredirected_hdrs.get("Authorization"),
                         "Bearer tok123")
        self.assertNotIn("Authorization", request.headers)
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
    """The real transport, with the opener's `open` stubbed — still no socket.

    These patch `rpc._OPENER.open` rather than `urllib.request.urlopen`,
    because the module deliberately does not use the default opener: the
    default one forwards the Bearer token across redirects (see
    TestRedirectRefusal).
    """

    def test_urlerror_is_unreachable(self):
        with mock.patch.object(rpc._OPENER, "open",
                               side_effect=urllib.error.URLError("dns fail")):
            c = RpcClient("https://<wiki>", "t")
            with self.assertRaises(RpcError) as ctx:
                c.call("m", {})
            self.assertEqual(ctx.exception.code, "unreachable")

    def test_timeout_is_unreachable(self):
        with mock.patch.object(rpc._OPENER, "open", side_effect=TimeoutError()):
            c = RpcClient("https://<wiki>", "t")
            with self.assertRaises(RpcError) as ctx:
                c.call("m", {})
            self.assertEqual(ctx.exception.code, "unreachable")

    def test_http_404_is_no_endpoint(self):
        err = urllib.error.HTTPError("u", 404, "nf", {}, None)
        with mock.patch.object(rpc._OPENER, "open", side_effect=err):
            c = RpcClient("https://<wiki>", "t")
            with self.assertRaises(RpcError) as ctx:
                c.call("m", {})
            self.assertEqual(ctx.exception.code, "no-endpoint")

    def test_http_error_body_still_parsed(self):
        # JSON-RPC errors can ride a non-200 status: the body wins.
        import io
        payload = json.dumps({"error": {"code": -32605, "message": "off"}}).encode()
        err = urllib.error.HTTPError("u", 403, "forbidden", {}, io.BytesIO(payload))
        with mock.patch.object(rpc._OPENER, "open", side_effect=err):
            c = RpcClient("https://<wiki>", "t")
            with self.assertRaises(RpcError) as ctx:
                c.call("m", {})
            self.assertEqual(ctx.exception.code, -32605)


class TestMidStreamFailures(unittest.TestCase):
    """urlopen only wraps OSError raised inside the request; anything raised
    by getresponse() or resp.read() arrives unwrapped. Every one of them must
    still become a one-line instructional RpcError, never a traceback — an
    unhandled exception here also skips apply_deploy's written/not-written
    report."""

    def check(self, exc):
        with mock.patch.object(rpc._OPENER, "open", side_effect=exc):
            c = RpcClient("https://<wiki>", "t")
            with self.assertRaises(RpcError) as ctx:
                c.call("m", {})
            self.assertEqual(ctx.exception.code, "unreachable")
            self.assertTrue(ctx.exception.message)  # never an empty message
            return ctx.exception

    def test_remote_disconnected(self):
        self.check(http.client.RemoteDisconnected(
            "Remote end closed connection without response"))

    def test_connection_reset(self):
        self.check(ConnectionResetError(104, "Connection reset by peer"))

    def test_incomplete_read(self):
        self.check(http.client.IncompleteRead(b"partial"))

    def test_ssl_error_mid_stream(self):
        self.check(ssl.SSLError("record layer failure"))

    def test_bare_httpexception_still_names_its_type(self):
        # http.client.HTTPException is not an OSError, and a bare instance
        # str()s to "" — the message must still say something usable.
        exc = self.check(http.client.HTTPException())
        self.assertIn("HTTPException", exc.message)


class TestRedirectRefusal(unittest.TestCase):
    """A JSON-RPC POST to lib/exe/jsonrpc.php/<method> never legitimately
    redirects. urllib's default HTTPRedirectHandler copies every header except
    content-length/content-type onto the redirected request — including
    Authorization, and unlike requests it does not strip it on a host change —
    and turns a 301/302/303 POST into a GET. So an ordinary apex->www or
    https->http redirect would put a live campaign's API token in clear, or on
    a host the user never configured. Refuse the redirect instead."""

    def _headers(self, location):
        msg = email.message.Message()
        msg["Location"] = location
        return msg

    def _request(self):
        return urllib.request.Request(
            "https://<wiki>/lib/exe/jsonrpc.php/core.savePage",
            data=b"{}",
            headers={"Authorization": "Bearer SECRET",
                     "Content-Type": "application/json"},
            method="POST")

    def test_a_real_client_request_carries_no_redirectable_token(self):
        # Belt to _NoRedirect's braces, checked on a request the client
        # actually built: even handed to the stock handler, there is no
        # Authorization header for it to forward.
        t = fake_transport([ok("x")])
        RpcClient("https://<wiki>", "tok123", transport=t).call("core.getPage", {})
        sent = t.calls[0][0]
        new = urllib.request.HTTPRedirectHandler().redirect_request(
            sent, io.BytesIO(b""), 302, "Found",
            self._headers("http://<other-host>/collect"),
            "http://<other-host>/collect")
        self.assertNotIn("Authorization", new.headers)
        self.assertNotIn("Authorization", new.unredirected_hdrs)
        # ...while the wire request do_open assembles still carries it.
        wire = dict(sent.unredirected_hdrs)
        wire.update({k: v for k, v in sent.headers.items() if k not in wire})
        self.assertEqual(wire["Authorization"], "Bearer tok123")

    def test_stdlib_default_would_have_leaked_the_token(self):
        # Pins the reason this module refuses redirects at all: if a future
        # Python ever stops forwarding Authorization, this test fails and the
        # refusal can be re-argued from evidence rather than from memory.
        new = urllib.request.HTTPRedirectHandler().redirect_request(
            self._request(), io.BytesIO(b""), 302, "Found",
            self._headers("http://<other-host>/collect"),
            "http://<other-host>/collect")
        self.assertEqual(new.get_header("Authorization"), "Bearer SECRET")

    def test_handler_refuses_and_names_the_fix(self):
        with self.assertRaises(RpcError) as ctx:
            rpc._NoRedirect().redirect_request(
                self._request(), io.BytesIO(b""), 302, "Found",
                self._headers("http://<other-host>/collect"),
                "http://<other-host>/collect")
        exc = ctx.exception
        self.assertEqual(exc.code, "no-endpoint")
        self.assertEqual(exc.method, "core.savePage")
        self.assertIn("http://<other-host>/collect", exc.message)
        self.assertIn("[wiki] url", exc.message)  # names the fix

    def test_refusing_handler_is_installed_in_the_opener(self):
        # Not just "the class exists": drive the opener's own error chain, so
        # a build_opener call that failed to displace the stock
        # HTTPRedirectHandler is caught here.
        handlers = [type(h).__name__ for h in rpc._OPENER.handlers]
        self.assertIn("_NoRedirect", handlers)
        self.assertNotIn("HTTPRedirectHandler", handlers)
        for code in (301, 302, 303, 307):
            with self.subTest(code=code):
                with self.assertRaises(RpcError) as ctx:
                    rpc._OPENER.error(
                        "http", self._request(), io.BytesIO(b""), code, "R",
                        self._headers("https://<other-host>/x"))
                self.assertEqual(ctx.exception.code, "no-endpoint")

    def test_translation_reads_for_both_no_endpoint_causes(self):
        redirect = rpc.translate_error(
            RpcError("no-endpoint",
                     "redirected to https://<other-host>/x — point [wiki] url "
                     "at the wiki's canonical base URL; the API token is never "
                     "sent to a redirect target",
                     "core.savePage"),
            "https://<wiki>")
        self.assertIn("redirected to https://<other-host>/x", redirect)
        self.assertIn("[wiki] url", redirect)
        not_found = rpc.translate_error(
            RpcError("no-endpoint", "HTTP 404", "core.getPage"), "https://<wiki>")
        self.assertIn("HTTP 404", not_found)
        self.assertIn(rpc.MIN_RELEASE, not_found)


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

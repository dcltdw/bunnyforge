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

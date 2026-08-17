"""Tests for scripts/mcp-session.py.

The script runs standalone, and is exercised here so it cannot rot -- the
same arrangement as tests/check_portability.py.

Every case below is a bug that actually happened while bringing a real
claude.ai connector up against a real tunnel. None of them were caught by
reading the code; each one cost a live debugging round. They are pinned
here so the next change to the script has to keep clearing them.

Nothing here starts a tunnel or talks to the network: the HTTP cases run
against a local one-shot server on an ephemeral port.
"""

import contextlib
import http.server
import importlib.util
import socket
import subprocess
import sys
import threading
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "mcp-session.py"


def load_script():
    """Import the script by path -- it is a script, not a package module."""
    spec = importlib.util.spec_from_file_location("mcp_session", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


session = load_script()


class TestShipsGeneric(unittest.TestCase):

    def test_no_personal_workspace_is_baked_in(self):
        # It ships for everyone; a hardcoded path would send someone else's
        # server at a directory that does not exist on their machine.
        self.assertIsNone(session.DEFAULT_WORKSPACE)

    def test_the_example_is_present_but_commented(self):
        # The whole point of leaving it None is that the next person edits
        # one obvious line, so that line has to still be there to edit.
        body = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("#   DEFAULT_WORKSPACE = ", body)

    def test_refuses_without_a_workspace_rather_than_guessing(self):
        proc = subprocess.run([sys.executable, str(SCRIPT)],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--workspace is required", proc.stderr)


class TestTunnelBannerParsing(unittest.TestCase):
    """The hostname is read out of cloudflared's banner; if that regex ever
    stops matching, the script hangs for a minute and then gives up."""

    BANNER = (
        "2026-08-17T01:47:15Z INF |  Your quick Tunnel has been created! "
        "Visit it at (it may take some time to be reachable):  |\n"
        "2026-08-17T01:47:15Z INF |  "
        "https://stayed-perhaps-penn-informational.trycloudflare.com   |\n")

    def test_finds_the_hostname(self):
        found = session.TUNNEL_RE.search(self.BANNER)
        self.assertIsNotNone(found)
        self.assertEqual(
            found.group(0),
            "https://stayed-perhaps-penn-informational.trycloudflare.com")

    def test_ignores_a_log_with_no_url_yet(self):
        self.assertIsNone(session.TUNNEL_RE.search(
            "2026-08-17T01:47:15Z INF Starting tunnel\n"))


class _Redirector(http.server.BaseHTTPRequestHandler):
    """`/` redirects to `/consent`, which terminates -- so following and
    not following give visibly different answers."""

    def do_GET(self):
        if self.path.startswith("/consent"):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"consent page")
            return
        self.send_response(302)
        # Deliberately lowercase, the way a real ASGI server sends it.
        self.send_header("location", "/consent?txn=abc123")
        self.end_headers()

    def log_message(self, *args):
        pass


class TestHttpHelper(unittest.TestCase):

    def setUp(self):
        server = http.server.HTTPServer(("127.0.0.1", 0), _Redirector)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)     # keeps the output pristine
        self.addCleanup(server.shutdown)
        self.url = f"http://127.0.0.1:{server.server_address[1]}"

    def test_follow_false_returns_the_redirect_itself(self):
        # urlopen chases redirects by default, so /authorize came back as
        # 200 with the consent page and no Location -- and the OAuth code
        # in that redirect was lost. curl does not follow, which is why the
        # same sequence passed by hand and failed in the script.
        status, headers, _ = session.http(self.url, follow=False)
        self.assertEqual(status, 302)
        self.assertIn("txn=abc123", session._location(headers))

    def test_following_is_still_the_default(self):
        status, _, _ = session.http(self.url)
        self.assertNotEqual(status, 302)

    def test_location_lookup_is_case_insensitive(self):
        # Real servers send `location`; a plain dict lookup for `Location`
        # silently returns nothing. Same class of bug as the
        # www-authenticate lookup in serve_mcp's pre-flight check.
        for casing in ("location", "Location", "LOCATION"):
            with self.subTest(header=casing):
                self.assertEqual(session._location({casing: "/x"}), "/x")

    def test_an_absent_location_is_empty_not_an_error(self):
        self.assertEqual(session._location({}), "")


class TestPortGuard(unittest.TestCase):

    def _free_port(self) -> int:
        with contextlib.closing(socket.socket()) as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    def test_a_free_port_has_no_holder(self):
        self.assertIsNone(session.port_holder(self._free_port()))

    def test_clear_port_is_a_no_op_when_free(self):
        session.clear_port(self._free_port())      # must not raise

    def test_clear_port_refuses_to_kill_something_that_is_not_ours(self):
        # The stale-port case is real -- a serve-mcp left over from an
        # earlier run blocks the bind. Stopping OUR server is the fix;
        # stopping whatever else happens to hold the port is not.
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        self.addCleanup(listener.close)
        port = listener.getsockname()[1]
        held = session.port_holder(port)
        if held is None:
            self.skipTest("lsof unavailable or cannot see this socket")
        with self.assertRaises(SystemExit) as ctx:
            session.clear_port(port)
        self.assertIn("not a serve-mcp", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

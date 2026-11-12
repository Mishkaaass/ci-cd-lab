"""Regression checks for the local, read-only unified operations viewer."""

import json
import stat
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch

from unified_console import server


class TestConsoleData(unittest.TestCase):
    def test_rejects_non_loopback_upstream(self):
        self.assertIsNone(server.json_http("https://example.com/private"))
        self.assertIsNone(server.json_http("http://127.0.0.1:18002/api/overview"))
        self.assertIsNone(server.json_http("http://127.0.0.1:8080/../../../etc/passwd"))

    def test_identifies_slot_by_version_and_sha(self):
        results = {
            "http://127.0.0.1:8080/version": {"version": "v1.3", "git_sha": "good123"},
            "http://127.0.0.1:8080/ready": {"status": "ready"},
            "http://127.0.0.1:8001/version": {"version": "v1.3", "git_sha": "good123"},
            "http://127.0.0.1:8002/version": {"version": "v1.4", "git_sha": "good456"},
        }
        with patch.object(
            server, "json_http", side_effect=lambda url, *_: results.get(url)
        ):
            data = server.docker_state()
        self.assertTrue(data["healthy"])
        self.assertEqual(data["slot"], "blue")
        self.assertFalse(data["events_available"])

    def test_no_guess_when_two_slots_share_identity(self):
        version = {"version": "same", "git_sha": "same"}

        def fake(url, *_):
            if url.endswith("/ready"):
                return {"status": "ready"}
            return version if "/version" in url else None

        with patch.object(server, "json_http", side_effect=fake):
            self.assertIsNone(server.docker_state()["slot"])

    def test_clean_events_allowlist_excludes_token(self):
        events = server.clean_events(
            [
                {
                    "type": "deploy",
                    "version": "v1",
                    "status": "done",
                    "authorization": "supersecret",
                }
            ]
        )
        self.assertEqual(len(events), 1)
        self.assertNotIn("authorization", json.dumps(events))
        self.assertNotIn("supersecret", json.dumps(events))

    def test_kube_never_switches_context(self):
        captured = []

        def fake(argv, timeout=6.0):
            captured.append(argv)
            return {"status": {"phase": "Bound"}}

        with patch.object(server, "run_readonly", side_effect=fake):
            with patch.object(server, "KCFG", Path(__file__)):
                server.kube_get(
                    "/usr/bin/kubectl", "opsboard", "pvc", "data-postgres-0"
                )
        self.assertEqual(
            captured[0][captured[0].index("--context") + 1], "kind-opsboard-review"
        )
        self.assertNotIn("config", captured[0])

    def test_token_private_and_stable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "credentials/viewer.token"
            token1 = server.ensure_token(path)
            token2 = server.ensure_token(path)
            self.assertEqual(token1, token2)
            self.assertGreaterEqual(len(token1), 40)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)

    def test_token_symlink_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "credentials/viewer.token"
            path.parent.mkdir()
            other = Path(tmp) / "other"
            other.write_text("x" * 80)
            path.symlink_to(other)
            with self.assertRaises(RuntimeError):
                server.ensure_token(path)


class TestHTTPReadOnly(unittest.TestCase):
    def setUp(self):
        self.token = "A" * 60
        self.srv = server.LocalServer(("127.0.0.1", 0), self.token)
        self.thread = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.srv.server_address[1]

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.thread.join(timeout=2)

    def request(self, method, path, headers=None):
        client = HTTPConnection("127.0.0.1", self.port, timeout=5)
        client.request(method, path, headers=headers or {})
        response = client.getresponse()
        output = response.status, dict(response.getheaders()), response.read()
        client.close()
        return output

    def test_locked_by_default(self):
        status, headers, body = self.request("GET", "/api/overview")
        self.assertEqual(status, 401)
        self.assertIn("no-store", headers["Cache-Control"])
        self.assertNotIn(self.token.encode(), body)
        self.assertEqual(headers["X-Frame-Options"], "DENY")

    def test_invalid_token_is_rejected(self):
        status, _, _ = self.request(
            "GET", "/api/overview", {"Authorization": "Bearer " + "B" * 60}
        )
        self.assertEqual(status, 401)

    def test_bad_host_and_cross_origin_blocked(self):
        status, _, _ = self.request("GET", "/", {"Host": "attacker.example"})
        self.assertEqual(status, 400)
        status, _, _ = self.request(
            "GET", "/api/overview", {"Origin": "https://attacker.example"}
        )
        self.assertEqual(status, 403)

    def test_post_mutations_are_disallowed(self):
        status, _, _ = self.request("POST", "/api/overview")
        self.assertEqual(status, 405)

    def test_allowlisted_static_paths_only(self):
        status, _, data = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"Delivery control center", data)
        status, _, _ = self.request("GET", "/README.md")
        self.assertEqual(status, 404)

    def test_authenticated_api_never_embeds_credential(self):
        fake = {"observed_at": "2026-11-12T14:00:00+00:00", "docker": {"healthy": True}}
        with patch.object(server, "snapshot", return_value=fake):
            status, headers, data = self.request(
                "GET", "/api/overview", {"Authorization": "Bearer " + self.token}
            )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data), fake)
        self.assertNotIn(self.token.encode(), data)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])


if __name__ == "__main__":
    unittest.main()

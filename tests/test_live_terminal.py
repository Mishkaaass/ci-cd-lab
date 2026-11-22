"""Regression checks for live terminal / sudo UX, no Docker or sudo required."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch

from unified_console import server, showcase


class TestTerminalPolicy(unittest.TestCase):
    def test_known_real_script_steps_are_allowed(self):
        allowed = (
            ("docker", "  readiness attempt 15/15 failed"),
            ("docker", "OPSBOARD_STEP|success|Nginx configuration validated"),
            ("docker", "PASS: production switched blue -> green"),
            ("docker", "PASS: production switched green -> blue"),
            ("gitops", "deployment.apps/opsboard scaled"),
            ("gitops", "PASS: real GitOps self-healing restored replicas=1"),
        )
        for track, line in allowed:
            with self.subTest(track=track, line=line):
                self.assertEqual(
                    showcase.safe_terminal_output(track, line), line.strip()
                )

    def test_sensitive_and_arbitrary_lines_are_never_forwarded(self):
        for sample in (
            "Authorization: Bearer secret-token",
            "Password: yoursecret",
            "sudo: a password is required",
            "gh auth token",
            "GET /api?token=sensitive-value",
            "bad\nPASS: production switched blue -> green",
            "\x1b[0mPASS: production switched blue -> green",
            "my secret value " + "a" * 220,
        ):
            with self.subTest(line=sample):
                self.assertIsNone(showcase.safe_terminal_output("docker", sample))
                self.assertIsNone(showcase.safe_terminal_output("gitops", sample))

    def test_real_stream_retains_verified_changes_but_drops_secrets(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            script = root / "scripts/reviewer.sh"
            script.parent.mkdir()
            script.write_text(
                "#!/usr/bin/env bash\n"
                "echo '[1/3] Broken candidate: failure is expected'\n"
                "echo 'Auth: Bearer supersecret-123'\n"
                "echo 'PASS: broken candidate rejected; production release unchanged'\n"
                "echo '[2/3] Healthy candidate: validated before switching'\n"
                "echo 'OPSBOARD_STEP|success|Release identity verified'\n"
                "echo 'PASS: production switched blue -> green'\n"
                "echo 'PASS: production switched green -> blue'\n"
                "echo 'PASS: broken gate, healthy rollout, exact rollback identity'\n"
            )
            progress = showcase.Progress(root / "status.json")
            progress.begin("docker")
            with patch.object(showcase, "authorized_for_docker", return_value=True):
                self.assertTrue(showcase.run_drill("docker", progress, root))
            output = json.dumps(progress.data["terminal"])
            self.assertIn("PASS: production switched blue -> green", output)
            self.assertIn("PASS: production switched green -> blue", output)
            self.assertNotIn("supersecret-123", output)
            self.assertEqual(progress.data["docker_phase"], "complete")

    def test_terminal_bounded_and_private(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "private/status.json"
            progress = showcase.Progress(path)
            for i in range(140):
                progress.terminal("docker", f"static line {i}")
            self.assertEqual(len(progress.data["terminal"]), showcase.MAX_TERMINAL_ROWS)
            self.assertEqual(
                len(showcase.read_json(path)["terminal"]), showcase.MAX_TERMINAL_ROWS
            )
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_sudo_prompt_is_published_before_password_request(self):
        with tempfile.TemporaryDirectory() as temp:
            progress = showcase.Progress(Path(temp) / "status.json")
            progress.begin("docker")
            calls = []

            def fake_run(argv, _cwd, _timeout, _env=None):
                calls.append(argv)
                if argv == ["sudo", "-n", "-v"]:
                    return 1
                if argv == ["sudo", "-v"]:
                    live = showcase.read_json(progress.path)
                    self.assertEqual(live["status"], "waiting_auth")
                    self.assertEqual(live["attention"]["kind"], "sudo")
                    self.assertIn("terminal", live["attention"]["message"])
                    self.assertIn(
                        "AUTHORIZATION REQUIRED", live["terminal"][-1]["text"]
                    )
                    return 0
                raise AssertionError(argv)

            with patch.object(showcase.subprocess, "run") as docker_probe:
                docker_probe.return_value.returncode = 1
                with patch.object(showcase, "run_command", side_effect=fake_run):
                    with patch.object(showcase.sys, "stdin") as input_stream:
                        input_stream.isatty.return_value = True
                        self.assertTrue(showcase.authorized_for_docker(progress))
            self.assertEqual(progress.data["status"], "running")
            self.assertIsNone(progress.data["attention"])
            self.assertEqual(calls, [["sudo", "-n", "-v"], ["sudo", "-v"]])

    def test_no_tty_reports_actionable_failure_not_stuck_waiting(self):
        with tempfile.TemporaryDirectory() as temp:
            progress = showcase.Progress(Path(temp) / "status.json")
            with patch.object(showcase.subprocess, "run") as docker_probe:
                docker_probe.return_value.returncode = 1
                with patch.object(showcase, "run_command", return_value=1):
                    with patch.object(showcase.sys, "stdin") as input_stream:
                        input_stream.isatty.return_value = False
                        self.assertFalse(showcase.authorized_for_docker(progress))
            self.assertEqual(progress.data["status"], "failed")
            self.assertIn("terminal", progress.data["attention"]["message"])

    def test_launcher_orders_server_before_lab_preparation(self):
        import inspect

        src = inspect.getsource(showcase.run)
        self.assertLess(
            src.index('"unified_console.server", "serve"'),
            src.index("prepare_labs(docker_root, progress)"),
        )


class TestTerminalHttp(unittest.TestCase):
    def test_private_terminal_visible_only_with_token(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            data = showcase.initial_status()
            data["status"] = "waiting_auth"
            data["attention"] = {
                "kind": "sudo",
                "title": "Action required",
                "message": "Use the local terminal, never the browser",
            }
            data["terminal"] = [
                {
                    "at": showcase.timestamp(),
                    "track": "docker",
                    "kind": "output",
                    "text": "PASS: production switched blue -> green",
                }
            ]
            showcase.atomic_json(directory / "status.json", data)
            token = "z" * 60
            web = server.LocalServer(("127.0.0.1", 0), token, directory)
            thread = threading.Thread(target=web.serve_forever, daemon=True)
            thread.start()
            try:
                conn = HTTPConnection("127.0.0.1", web.server_address[1], timeout=4)
                conn.request("GET", "/api/showcase/status")
                response = conn.getresponse()
                self.assertEqual(response.status, 401)
                response.read()
                conn.close()
                conn = HTTPConnection("127.0.0.1", web.server_address[1], timeout=4)
                conn.request(
                    "GET",
                    "/api/showcase/status",
                    headers={"Authorization": "Bearer " + token},
                )
                response = conn.getresponse()
                self.assertEqual(response.status, 200)
                result = json.loads(response.read())
                self.assertEqual(result["status"], "waiting_auth")
                self.assertEqual(result["terminal"][0]["track"], "docker")
                self.assertNotIn(token, json.dumps(result))
                conn.close()
            finally:
                web.shutdown()
                web.server_close()
                thread.join(2)


if __name__ == "__main__":
    unittest.main()

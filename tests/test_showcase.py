"""Live showcase policy and run-evidence regression tests (no Docker needed)."""

import json
import stat
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch

from unified_console import server, showcase


class TestLocalPolicy(unittest.TestCase):
    def test_state_file_is_private_and_atomic(self):
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / "private/status.json"
            showcase.atomic_json(file, {"status": "passed"})
            self.assertEqual(showcase.read_json(file)["status"], "passed")
            self.assertEqual(stat.S_IMODE(file.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(file.parent.stat().st_mode), 0o700)

    def test_state_symlink_is_not_followed(self):
        with tempfile.TemporaryDirectory() as temp:
            linked = Path(temp) / "linked"
            linked.symlink_to(Path(temp) / "other")
            with self.assertRaises(OSError):
                showcase.private_directory(linked)

    def test_parse_docker_events_keeps_verified_green_and_rollback(self):
        with tempfile.TemporaryDirectory() as temp:
            progress = showcase.Progress(Path(temp) / "status.json")
            lines = [
                "[1/3] Broken candidate: failure is expected",
                "PASS: broken candidate rejected; production release unchanged",
                "[2/3] Healthy candidate: validated before switching",
                "PASS: production switched blue -> green",
                "PASS: production switched green -> blue",
                "PASS: broken gate, healthy rollout, exact rollback identity",
            ]
            for line in lines:
                showcase.parse_drill_line(progress, line, "docker")
            self.assertEqual(progress.data["docker_phase"], "complete")
            self.assertTrue(
                any("Blue to Green" in x["title"] for x in progress.data["steps"])
            )
            self.assertTrue(
                any("restored" in x["title"] for x in progress.data["steps"])
            )
            self.assertNotIn("secret", json.dumps(progress.data).lower())

    def test_parser_ignores_arbitrary_logs_including_credentials(self):
        with tempfile.TemporaryDirectory() as temp:
            progress = showcase.Progress(Path(temp) / "status.json")
            showcase.parse_drill_line(
                progress, "authorization: Bearer secret-123", "docker"
            )
            self.assertEqual(progress.data["steps"], [])

    def test_gitops_requires_real_verified_reconciliation(self):
        with tempfile.TemporaryDirectory() as temp:
            progress = showcase.Progress(Path(temp) / "status.json")
            showcase.parse_drill_line(
                progress, "deployment.apps/opsboard scaled", "gitops"
            )
            self.assertEqual(progress.data["gitops_phase"], "scaled")
            showcase.parse_drill_line(
                progress, "PASS: real GitOps self-healing restored replicas=1", "gitops"
            )
            self.assertEqual(progress.data["gitops_phase"], "restored")

    def test_cannot_run_docker_with_missing_privilege(self):
        with tempfile.TemporaryDirectory() as temp:
            progress = showcase.Progress(Path(temp) / "status.json")
            with patch.object(showcase, "authorized_for_docker", return_value=False):
                self.assertFalse(showcase.run_drill("docker", progress, Path(temp)))
            self.assertTrue(any(x["kind"] == "error" for x in progress.data["steps"]))

    def test_real_script_exit_success_is_not_enough_without_proof(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            script = root / "scripts/reviewer.sh"
            script.parent.mkdir()
            script.write_text("#!/bin/bash\necho 'all done'\n")
            progress = showcase.Progress(root / "status.json")
            with patch.object(showcase, "authorized_for_docker", return_value=True):
                self.assertFalse(showcase.run_drill("docker", progress, root))

    def test_gh_job_names_are_not_filtered_by_prefix(self):
        def gh_api(argv, timeout=6.0):
            if "runs?branch=" in argv[-1]:
                return {
                    "workflow_runs": [
                        {
                            "id": 456,
                            "html_url": "https://github.com/Mishkaaass/ci-cd-lab/actions/runs/456",
                            "conclusion": "success",
                            "head_sha": "a" * 40,
                        }
                    ]
                }
            return {
                "jobs": [
                    {"name": "Python tests", "conclusion": "success"},
                    {"name": "Code quality", "conclusion": "success"},
                ]
            }

        with patch.object(server, "find_command", return_value="/usr/bin/gh"):
            with patch.object(server, "run_readonly", side_effect=gh_api):
                state = server.github_state()
        self.assertTrue(state["jobs_available"])
        self.assertEqual(
            [x["name"] for x in state["jobs"]], ["Python tests", "Code quality"]
        )

    def test_ci_does_not_fabricate_jobs_if_api_fails(self):
        def gh_api(argv, timeout=6.0):
            if "runs?branch=" in argv[-1]:
                return {"workflow_runs": [{"id": 456, "conclusion": "success"}]}
            return None

        with patch.object(server, "find_command", return_value="/usr/bin/gh"):
            with patch.object(server, "run_readonly", side_effect=gh_api):
                state = server.github_state()
        self.assertFalse(state["jobs_available"])
        self.assertEqual(state["jobs"], [])


class TestBrowserBoundary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name)
        self.token = "C" * 60
        showcase.atomic_json(self.directory / "status.json", showcase.initial_status())
        self.web = server.LocalServer(("127.0.0.1", 0), self.token, self.directory)
        self.t = threading.Thread(target=self.web.serve_forever, daemon=True)
        self.t.start()
        self.port = self.web.server_address[1]

    def tearDown(self):
        self.web.shutdown()
        self.web.server_close()
        self.t.join(timeout=2)
        self.tmp.cleanup()

    def call(self, method, path, body=None, headers=None):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=4)
        conn.request(method, path, body=body, headers=headers or {})
        result = conn.getresponse()
        status, data = result.status, result.read()
        conn.close()
        return status, data

    def auth(self):
        return {
            "Authorization": "Bearer " + self.token,
            "Content-Type": "application/json",
            "Origin": f"http://127.0.0.1:{self.port}",
        }

    def test_status_api_requires_valid_viewer_token(self):
        self.assertEqual(self.call("GET", "/api/showcase/status")[0], 401)
        code, data = self.call("GET", "/api/showcase/status", headers=self.auth())
        self.assertEqual(code, 200)
        self.assertTrue(json.loads(data)["enabled"])
        self.assertNotIn(self.token.encode(), data)

    def test_only_whitelisted_action_can_be_queued(self):
        code, _ = self.call(
            "POST",
            "/api/showcase/start",
            body=b'{"action":"rm -rf /"}',
            headers=self.auth(),
        )
        self.assertEqual(code, 400)
        self.assertFalse((self.directory / "request.json").exists())
        code, _ = self.call(
            "POST",
            "/api/showcase/start",
            body=b'{"action":"docker"}',
            headers=self.auth(),
        )
        self.assertEqual(code, 202)
        self.assertEqual(
            showcase.read_json(self.directory / "request.json"), {"action": "docker"}
        )
        self.assertEqual(
            self.call(
                "POST",
                "/api/showcase/start",
                body=b'{"action":"all"}',
                headers=self.auth(),
            )[0],
            409,
        )

    def test_rejects_bad_host_origin_and_cross_site_type(self):
        body = b'{"action":"all"}'
        self.assertEqual(
            self.call(
                "POST",
                "/api/showcase/start",
                body=body,
                headers={**self.auth(), "Origin": "https://evil.example"},
            )[0],
            403,
        )
        self.assertEqual(
            self.call(
                "POST",
                "/api/showcase/start",
                body=body,
                headers={**self.auth(), "Host": "evil.example"},
            )[0],
            400,
        )
        self.assertEqual(
            self.call(
                "POST",
                "/api/showcase/start",
                body=body,
                headers={**self.auth(), "Content-Type": "text/plain"},
            )[0],
            415,
        )

    def test_no_actions_when_supervisor_disabled(self):
        state = showcase.initial_status()
        state["enabled"] = False
        showcase.atomic_json(self.directory / "status.json", state)
        code, _ = self.call(
            "POST", "/api/showcase/start", body=b'{"action":"all"}', headers=self.auth()
        )
        self.assertEqual(code, 403)

    def test_post_without_token_is_blocked(self):
        code, _ = self.call(
            "POST",
            "/api/showcase/start",
            body=b'{"action":"all"}',
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(code, 401)

    def test_plain_viewer_remains_read_only(self):
        view = server.LocalServer(("127.0.0.1", 0), self.token)
        self.assertIsNone(view.showcase_directory)
        view.server_close()


if __name__ == "__main__":
    unittest.main()

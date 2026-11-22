"""Docker ownership/readiness and first-run UX regressions; no Docker needed."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from unified_console import showcase


def compose_rows(*, missing: str = "", bad: str = "") -> list[dict]:
    rows = []
    for service in ("db", "demo-blue", "demo-green", "nginx"):
        if service == missing:
            continue
        rows.append(
            {
                "Service": service,
                "State": "running",
                "Health": "unhealthy"
                if service == bad
                else ("" if service == "nginx" else "healthy"),
            }
        )
    return rows


class FakeHTTP:
    def __init__(self, path):
        self.status = 200
        self.body = io.BytesIO(
            b'{"version":"v1.3.0","git_sha":"good123","mode":"healthy"}'
            if path.endswith("/version")
            else b'{"status":"ready"}'
        )

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def read(self, *args):
        return self.body.read(*args)


class DockerStartupTests(unittest.TestCase):
    def test_all_four_services_are_checked_in_compose_json_array(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "compose.yml").touch()
            results = [
                Mock(returncode=0),
                Mock(returncode=0, stdout=json.dumps(compose_rows()).encode()),
            ]
            with patch.object(showcase.subprocess, "run", side_effect=results) as run:
                self.assertTrue(showcase.compose_services_ready(root))
            self.assertEqual(
                run.call_args_list[1].args[0],
                ["docker", "compose", "ps", "--all", "--format", "json"],
            )

    def test_missing_db_is_not_healthy_despite_running_proxy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "compose.yml").touch()
            results = [
                Mock(returncode=1),
                Mock(
                    returncode=0,
                    stdout="\n".join(
                        json.dumps(row) for row in compose_rows(missing="db")
                    ).encode(),
                ),
            ]
            with patch.object(showcase.subprocess, "run", side_effect=results) as run:
                with patch.object(showcase, "urlopen") as browser:
                    self.assertFalse(showcase.docker_lab_ready(root))
                    browser.assert_not_called()
            self.assertEqual(
                run.call_args_list[1].args[0][:3], ["sudo", "-n", "docker"]
            )

    def test_unhealthy_container_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "compose.yml").touch()
            results = [
                Mock(returncode=0),
                Mock(
                    returncode=0,
                    stdout="\n".join(
                        json.dumps(row) for row in compose_rows(bad="demo-green")
                    ).encode(),
                ),
            ]
            with patch.object(showcase.subprocess, "run", side_effect=results):
                self.assertFalse(showcase.compose_services_ready(root))

    def test_real_ready_and_version_are_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(showcase, "compose_services_ready", return_value=True):
                with patch.object(
                    showcase, "urlopen", side_effect=lambda url, **_k: FakeHTTP(url)
                ):
                    self.assertTrue(showcase.docker_lab_ready(root))
                with patch.object(showcase, "urlopen", side_effect=OSError):
                    self.assertFalse(showcase.docker_lab_ready(root))

    def test_missing_database_causes_one_automatic_repair(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            progress = showcase.Progress(root / "state" / "status.json")
            with patch.object(showcase, "authorized_for_docker", return_value=True):
                with patch.object(
                    showcase, "docker_lab_ready", side_effect=[False, True]
                ) as health:
                    with patch.object(
                        showcase, "run_command", return_value=0
                    ) as command:
                        self.assertTrue(showcase.ensure_docker_lab(root, progress))
            self.assertEqual(health.call_count, 2)
            self.assertEqual(
                command.call_args.args[0], ["bash", "scripts/lab.sh", "demo"]
            )
            self.assertTrue(
                any(
                    "All four Compose services" in event["title"]
                    for event in progress.data["steps"]
                )
            )
            self.assertFalse(
                any(
                    "password" in event.get("text", "").lower()
                    for event in progress.data["terminal"]
                )
            )

    def test_healthy_lab_is_not_rebuilt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            progress = showcase.Progress(root / "state" / "status.json")
            with patch.object(showcase, "authorized_for_docker", return_value=True):
                with patch.object(showcase, "docker_lab_ready", return_value=True):
                    with patch.object(showcase, "run_command") as command:
                        self.assertTrue(showcase.ensure_docker_lab(root, progress))
                        command.assert_not_called()

    def test_denied_authorization_never_starts_lab(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            progress = showcase.Progress(root / "state" / "status.json")
            with patch.object(showcase, "authorized_for_docker", return_value=False):
                with patch.object(showcase, "run_command") as command:
                    self.assertFalse(showcase.ensure_docker_lab(root, progress))
                    command.assert_not_called()

    def test_failed_preparation_never_claims_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            progress = showcase.Progress(root / "state" / "status.json")
            with patch.object(showcase, "ensure_docker_lab", return_value=False):
                with patch.object(showcase.server, "KCFG", root / "no-kubeconfig"):
                    with patch.object(
                        showcase.server, "find_command", return_value=None
                    ):
                        showcase.prepare_labs(root, progress)
            self.assertEqual(progress.data["status"], "failed")
            self.assertIn("Docker lab not ready", progress.data["summary"])

    def test_previous_demo_checkout_reused_even_with_port_8080_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            root = state / "opsboard-project1-finish/checkouts/demo1-verified"
            (root / "scripts").mkdir(parents=True)
            (root / "scripts/reviewer.sh").touch()
            (root / "scripts/lab.sh").touch()
            (root / "compose.yml").touch()
            with patch.object(showcase.server, "STATE", state):
                with patch.object(showcase, "socket_open", return_value=False):
                    self.assertEqual(showcase.find_existing_docker_root(), root)

    def test_launcher_checks_compose_before_each_browser_drill(self):
        import inspect

        source = inspect.getsource(showcase.run)
        self.assertLess(
            source.index("ok = ensure_docker_lab(docker_root, progress)"),
            source.index("ok = run_drill(sub, progress, docker_root)"),
        )

    def test_compose_command_output_is_never_streamed_to_browser(self):
        import inspect

        source = inspect.getsource(showcase.ensure_docker_lab)
        self.assertNotIn("result.stdout", source)
        self.assertNotIn("shell=True", source)


if __name__ == "__main__":
    unittest.main()

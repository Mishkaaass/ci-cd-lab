"""CI tests for real CI/CD evidence and safe guided reviewer boundaries."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from unified_console import server

ROOT = Path(__file__).resolve().parents[1]
FULL_SHA = "a" * 40
OTHER_SHA = "a" * 39 + "b"


class TestGuidedCD(unittest.TestCase):
    def test_cd_absence_is_not_success(self):
        with mock.patch.object(server, "find_command", return_value=None):
            result = server.github_cd_state()
        self.assertFalse(result["available"])
        self.assertFalse(result["matches_ci"])
        self.assertIsNone(result["url"])

    @staticmethod
    def fake_gh(ci_sha: str, cd_sha: str, cd_url: str | None = None):
        urls = []

        def fetch(argv, timeout=8.0):
            urls.append(argv[2])
            sha = ci_sha if "/ci.yml/" in argv[2] else cd_sha
            url = cd_url or (
                "https://github.com/Mishkaaass/ci-cd-lab/actions/runs/12345"
            )
            return {
                "workflow_runs": [
                    {
                        "head_sha": sha,
                        "html_url": url,
                        "status": "completed",
                        "conclusion": "success",
                    }
                ]
            }

        return fetch, urls

    def test_latest_cd_reads_only_fixed_repo_workflows(self):
        fake, seen = self.fake_gh(FULL_SHA, FULL_SHA)
        with (
            mock.patch.object(server, "find_command", return_value="gh"),
            mock.patch.object(server, "run_readonly", side_effect=fake),
        ):
            result = server.github_cd_state()
        self.assertTrue(result["available"])
        self.assertEqual(result["sha"], FULL_SHA[:12])
        self.assertEqual(result["full_sha"], FULL_SHA)
        self.assertEqual(result["conclusion"], "success")
        self.assertTrue(result["matches_ci"])
        self.assertEqual(result["ci_sha"], FULL_SHA[:12])
        self.assertEqual(len(seen), 2)
        self.assertEqual(
            set(seen),
            {
                "repos/Mishkaaass/ci-cd-lab/"
                "actions/workflows/ci.yml/runs?branch=main&per_page=1",
                "repos/Mishkaaass/ci-cd-lab/"
                "actions/workflows/cd.yml/runs?branch=main&per_page=1",
            },
        )

    def test_foreign_link_never_reaches_client(self):
        fake, _ = self.fake_gh(FULL_SHA, FULL_SHA, "https://evil.example/")
        with (
            mock.patch.object(server, "find_command", return_value="gh"),
            mock.patch.object(server, "run_readonly", side_effect=fake),
        ):
            result = server.github_cd_state()
        self.assertIsNone(result["url"])

    def test_commit_match_uses_all_40_hex_digits_not_a_short_prefix(self):
        fake, _ = self.fake_gh(FULL_SHA, OTHER_SHA)
        with (
            mock.patch.object(server, "find_command", return_value="gh"),
            mock.patch.object(server, "run_readonly", side_effect=fake),
        ):
            result = server.github_cd_state()
        self.assertFalse(result["matches_ci"])
        self.assertEqual(result["sha"], FULL_SHA[:12])

    def test_matching_complete_shas_are_verifiable(self):
        fake, _ = self.fake_gh(FULL_SHA, FULL_SHA)
        with (
            mock.patch.object(server, "find_command", return_value="gh"),
            mock.patch.object(server, "run_readonly", side_effect=fake),
        ):
            result = server.github_cd_state()
        self.assertTrue(result["matches_ci"])


class TestGuidedUXContract(unittest.TestCase):
    def test_six_reviewer_steps_and_local_actions(self):
        html = (ROOT / "unified_console/index.html").read_text()
        self.assertEqual(html.count('class="guide-step"'), 5)
        self.assertEqual(html.count('class="guide-step selected"'), 1)
        for n in range(6):
            self.assertIn(f'data-guide-step="{n}"', html)
        self.assertIn('data-page="guided"', html)
        self.assertIn('id="guide-verified-count"', html)
        self.assertIn('id="guide-run-selected"', html)

    def test_both_readonly_pipeline_labels_and_safe_actions(self):
        src = (ROOT / "unified_console/app.js").read_text()
        self.assertIn("NO", (ROOT / "unified_console/index.html").read_text())
        self.assertIn("REQUIRED_CI_GATES", src)
        self.assertIn("cd.matches_ci", src)
        self.assertIn("stage.action", src)
        self.assertIn("startDemo(action)", src)
        self.assertIn("source.href", src)
        self.assertIn("safeGuideRunUrl", src)
        self.assertNotIn("/api/github/dispatch", src)
        self.assertNotIn("/api/shell", src)

    def test_readme_and_runbook_link_resolve(self):
        readme = (ROOT / "README.md").read_text()
        doc = ROOT / "docs/guided-experience.md"
        self.assertTrue(doc.is_file())
        self.assertIn("docs/guided-experience.md", readme)
        self.assertIn("independently", doc.read_text())


if __name__ == "__main__":
    unittest.main()

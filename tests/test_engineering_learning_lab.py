"""Static contract tests for the read-only Engineering Learning Lab.

These tests intentionally avoid Docker, Kubernetes, network, credentials or writes.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "unified_console"


class TestEngineeringLearningLab(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (WEB / "index.html").read_text(encoding="utf-8")
        cls.js = (WEB / "learning.js").read_text(encoding="utf-8")
        cls.main_js = (WEB / "app.js").read_text(encoding="utf-8")
        cls.css = (WEB / "style.css").read_text(encoding="utf-8")
        cls.server = (WEB / "server.py").read_text(encoding="utf-8")

    def test_six_modules_and_eighteen_interactive_questions(self):
        for topic in (
            "Docker & Nginx",
            "Kubernetes & Argo CD",
            "Python & FastAPI",
            "PostgreSQL & Persistence",
            "CI/CD & Artifacts",
            "Security & Failure Design",
        ):
            self.assertIn(topic, self.js)
        self.assertEqual(self.js.count("{question:"), 18)
        self.assertEqual(len(re.findall(r"correct: [012], because:", self.js)), 18)

    def test_every_question_has_options_explanation_and_evidence(self):
        self.assertEqual(len(re.findall(r"options: \[", self.js)), 18)
        self.assertEqual(len(re.findall(r"proof: ", self.js)), 18)
        self.assertIn("if (i === item.correct) passed.add(id)", self.js)
        self.assertIn("const answers = new Map()", self.js)
        self.assertIn("const passed = new Set()", self.js)

    def test_learning_page_is_integrated_and_accessible(self):
        self.assertIn('data-view="learning"', self.html)
        self.assertIn('id="page-learning"', self.html)
        self.assertIn('id="learning-choices"', self.html)
        self.assertIn('id="learning-feedback"', self.html)
        self.assertIn('aria-live="polite"', self.html)
        self.assertIn('id="learning-evidence"', self.html)
        self.assertIn('id="learning-reset"', self.html)
        self.assertIn('id="learning-next"', self.html)
        self.assertIn('src="/assets/learning.js"', self.html)
        self.assertIn('"learning"', self.main_js)
        self.assertIn("OpsboardLearning.update(data)", self.main_js)
        self.assertIn("OpsboardLearning.reset()", self.main_js)
        self.assertIn("/assets/learning.js", self.server)
        self.assertIn(".learning-layout", self.css)

    def test_no_network_requests_or_mutations_in_learning_javascript(self):
        self.assertNotIn("fetch(", self.js)
        self.assertNotIn("XMLHttpRequest", self.js)
        self.assertNotIn("localStorage", self.js)
        self.assertNotIn("sessionStorage", self.js)
        self.assertNotIn("eval(", self.js)
        self.assertNotIn("Function(", self.js)
        self.assertNotIn("child_process", self.js)
        self.assertNotIn("innerHTML", self.js)
        self.assertNotIn("window.open(", self.js)
        self.assertNotIn("/api/showcase/start", self.js)
        self.assertNotIn("Authorization", self.js)
        self.assertIn("textContent", self.js)

    def test_source_links_are_allowlisted_repository_paths(self):
        sources = re.findall(r'source: "([^"]+)"', self.js)
        self.assertEqual(len(sources), 6)
        for path in sources:
            self.assertTrue((ROOT / path).is_file(), path)
        self.assertIn("https://github.com/Mishkaaass/ci-cd-lab/blob/main/", self.js)

    def test_documented_boundaries(self):
        guide = (ROOT / "docs/engineering-learning-lab.md").read_text()
        readme = (ROOT / "README.md").read_text()
        self.assertIn("18 real-world prediction scenarios", readme)
        self.assertIn("docs/engineering-learning-lab.md", readme)
        self.assertIn("do not perform deployments", readme)
        self.assertIn("does not prove", guide)
        self.assertIn("Bound", guide)
        self.assertIn("existing guided", guide)


if __name__ == "__main__":
    unittest.main()

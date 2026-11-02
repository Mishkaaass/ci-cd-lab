import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "scan-image.sh"
FAKE_TRIVY = """import json, os, sys
if os.environ.get("SCANNER_ERROR") == "1":
    sys.exit(19)
args = sys.argv[1:]
severity = args[args.index("--severity") + 1].split(",")
pkg_types = args[args.index("--pkg-types") + 1].split(",")
exit_code = int(args[args.index("--exit-code") + 1])
unfixed = "--ignore-unfixed=true" in args
findings = json.loads(os.environ["SCAN_FINDINGS"])
matched = [
    item
    for item in findings
    if item["severity"] in severity
    and item["kind"] in pkg_types
    and (not unfixed or item["fixed"])
]
print("findings:", len(matched))
sys.exit(exit_code if matched else 0)
"""


class ContainerSecurityPolicyTests(unittest.TestCase):
    def run_policy(self, findings, *, scanner_error=False):
        with TemporaryDirectory() as directory:
            fake = Path(directory) / "trivy"
            fake.write_text(f"#!{sys.executable}\n{FAKE_TRIVY}")
            fake.chmod(0o755)
            env = {
                **os.environ,
                "PATH": directory + os.pathsep + os.environ.get("PATH", ""),
                "SCAN_FINDINGS": json.dumps(findings),
                "SCANNER_ERROR": "1" if scanner_error else "0",
            }
            return subprocess.run(
                ["sh", str(SCRIPT), "fixture:image"],
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )

    def test_clean_image_passes(self):
        result = self.run_policy([])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_high_with_fix_blocks_release(self):
        result = self.run_policy(
            [{"severity": "HIGH", "fixed": True, "kind": "library"}]
        )
        self.assertEqual(result.returncode, 1, result.stderr)

    def test_critical_without_fix_blocks_release(self):
        result = self.run_policy(
            [{"severity": "CRITICAL", "fixed": False, "kind": "os"}]
        )
        self.assertEqual(result.returncode, 1, result.stderr)

    def test_high_without_fix_is_reported_and_allowed(self):
        result = self.run_policy([{"severity": "HIGH", "fixed": False, "kind": "os"}])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("findings: 1", result.stdout)

    def test_scanner_error_blocks_release(self):
        result = self.run_policy([], scanner_error=True)
        self.assertEqual(result.returncode, 19, result.stderr)

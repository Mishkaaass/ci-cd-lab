"""Offline checks for the optional Windows / Ubuntu WSL2 reviewer path."""
from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PS1 = ROOT / "scripts/windows-showcase.ps1"
WSL = ROOT / "scripts/wsl-showcase.sh"
README = ROOT / "README.md"
RUNBOOK = ROOT / "docs/windows.md"


class TestWindowsSupport(unittest.TestCase):
    def test_shell_syntax(self):
        subprocess.run(["bash", "-n", str(WSL)], check=True)

    def test_powershell_has_no_hidden_elevation_or_remote_eval(self):
        src = PS1.read_text(encoding="utf-8")
        self.assertIn("#requires -Version 5.1", src)
        self.assertIn("wsl.exe", src)
        self.assertIn("--exec bash $linuxScript $linuxRepoRoot", src)
        for unsafe in ("Invoke-Expression", "Set-ExecutionPolicy", "Start-Process -Verb RunAs",
                       "Remove-Item -Recurse", "wsl --unregister", "docker compose down -v"):
            self.assertNotIn(unsafe.lower(), src.lower())

    def test_safety_of_wsl_setup(self):
        src = WSL.read_text(encoding="utf-8")
        self.assertIn('"${1:-}"', src)
        self.assertIn('docker info', src)
        self.assertIn('wsl', WSL.name.lower())
        self.assertIn('read -r confirm', src)
        self.assertIn('uv python install 3.14', src)
        self.assertIn('bash scripts/showcase.sh', src)
        self.assertIn('git clone --quiet --no-hardlinks', src)
        self.assertIn('git -C "$DEST" merge --ff-only FETCH_HEAD', src)
        self.assertIn("${filename}.sha256sum", src)
        self.assertIn('checksum', src)
        for unsafe in ("rm -rf", "git reset --hard", "git push --force", "chmod 777",
                       "docker compose down -v", "kubectl delete namespace"):
            self.assertNotIn(unsafe, src)

    def test_existing_readme_not_replaced(self):
        src = README.read_text(encoding="utf-8")
        self.assertIn('## Windows — WSL 2 + Docker Desktop', src)
        self.assertIn('## 5-minute recruiter demo — start here', src)
        self.assertEqual(src.count('```mermaid'), 3)
        self.assertIn('Developed by Moshe Bogo', src)
        self.assertIn('separate paths', src)
        self.assertIn('bash scripts/showcase.sh', src)
        self.assertIn('docs/windows.md', src)
        for path in ('scripts/windows-showcase.ps1', 'scripts/wsl-showcase.sh', 'docs/windows.md'):
            self.assertTrue((ROOT / path).is_file(), path)

    def test_runbook_is_usable_and_honest(self):
        src = RUNBOOK.read_text(encoding="utf-8")
        self.assertIn('wsl --install -d Ubuntu', src)
        self.assertIn('WSL Integration', src)
        self.assertIn('windows-showcase.ps1', src)
        self.assertIn('wsl.exe --exec sh -lc', src)
        self.assertIn('Ctrl+C', src)
        self.assertIn('**not** supported', src)
        self.assertRegex(src, r'http://127\.0\.0\.1:18002/')

    def test_launcher_rejects_non_wsl_before_installing(self):
        # In the Linux CI runner, the bootstrap must fail before changing a
        # host or installing packages. On a WSL runner, skip this assertion.
        version = Path('/proc/sys/kernel/osrelease').read_text(encoding='utf-8')
        if 'wsl2' in version.lower():
            self.skipTest('WSL2 runtime available')
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / 'scripts').mkdir()
            (Path(td) / 'scripts/showcase.sh').write_text('#!/bin/bash\n', encoding='utf-8')
            result = subprocess.run(['bash', str(WSL), td], capture_output=True, text=True, timeout=6)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Ubuntu WSL 2 distribution', result.stderr)


if __name__ == '__main__':
    unittest.main()

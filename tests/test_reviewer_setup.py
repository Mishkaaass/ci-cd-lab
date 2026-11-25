"""First-time reviewer setup contracts (offline, no Docker or network)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "scripts/setup-venv.sh"
REQUIREMENTS = ROOT / "scripts/requirements.sh"


def test_reviewer_shell_syntax() -> None:
    scripts = (
        SETUP,
        REQUIREMENTS,
        ROOT / "scripts/showcase.sh",
        ROOT / "scripts/unified-console.sh",
    )
    subprocess.run(["bash", "-n", *(str(path) for path in scripts)], check=True)


def test_makefile_offers_clear_isolated_modes() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    for target in (
        "requirements:",
        "setup:",
        "setup-dev:",
        "viewer: setup",
        "showcase: setup",
    ):
        assert target in makefile
    assert "scripts/requirements.sh" in makefile
    assert "scripts/setup-venv.sh" in makefile
    assert ".venv/bin/python" in (ROOT / "scripts/showcase.sh").read_text(
        encoding="utf-8"
    )
    viewer = (ROOT / "scripts/unified-console.sh").read_text(encoding="utf-8")
    assert ".venv/bin/python" in viewer
    assert "unified_console.server serve" in viewer


def test_incompatible_existing_venv_is_preserved(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy2(SETUP, scripts / "setup-venv.sh")
    preserved = tmp_path / ".venv"
    preserved.mkdir()
    sentinel = preserved / "preserve-me.txt"
    sentinel.write_text("DO NOT DELETE", encoding="utf-8")

    result = subprocess.run(
        ["bash", str(scripts / "setup-venv.sh")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode != 0
    assert "incomplete .venv" in result.stderr
    assert sentinel.read_text(encoding="utf-8") == "DO NOT DELETE"


def test_symlink_venv_is_rejected(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy2(SETUP, scripts / "setup-venv.sh")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "marker").write_text("KEEP", encoding="utf-8")
    (tmp_path / ".venv").symlink_to(outside, target_is_directory=True)

    result = subprocess.run(
        ["bash", str(scripts / "setup-venv.sh")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode != 0
    assert "symlink" in result.stderr
    assert (outside / "marker").read_text(encoding="utf-8") == "KEEP"


def test_readonly_requirements_never_installs_or_changes_privileges() -> None:
    diagnostics = REQUIREMENTS.read_text(encoding="utf-8")
    setup = SETUP.read_text(encoding="utf-8")
    for forbidden in (
        "sudo -v",
        "sudo apt",
        "docker compose up",
        "docker info",
        "pip install",
        "chmod 666",
        "rm -rf",
    ):
        assert forbidden not in diagnostics
    assert "python3.14 -m venv" in setup
    assert 'if [[ "$MODE" == "--dev" ]]' in setup
    assert ".venv/bin/python -m pip install" in setup
    assert "requirements-dev.txt" in setup


def test_legacy_dashboard_uses_same_safe_venv_bootstrap() -> None:
    lab = (ROOT / "scripts/lab.sh").read_text(encoding="utf-8")
    assert "bash scripts/setup-venv.sh" in lab
    assert "if [ ! -x .venv/bin/python ]" not in lab
    assert "requirements-dev.txt" in lab


def test_license_and_dependency_updates_are_reviewed() -> None:
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert license_text.startswith("MIT License")
    assert "Copyright (c) 2026 Moshe Bogo" in license_text
    assert "Permission is hereby granted" in license_text
    assert "[![License: MIT]" in readme
    assert "SQLAlchemy==2.1.9" in (ROOT / "requirements.txt").read_text()
    assert "ruff==0.17.6" in (ROOT / "requirements-dev.txt").read_text()
    assert "branch protection must be configured" in readme


def test_demo_runtime_removes_build_only_pip() -> None:
    dockerfile = (ROOT / "Dockerfile.demo").read_text(encoding="utf-8")
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "python -m pip check" in dockerfile
    assert "python -m pip uninstall --yes pip" in dockerfile
    assert "docker build -f Dockerfile.demo -t opsboard-demo:ci ." in ci
    assert "sh scripts/scan-image.sh opsboard-demo:ci" in ci


def test_readme_describes_requirements_and_legacy_package_install() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    requirements = (ROOT / "docs/REQUIREMENTS.md").read_text(encoding="utf-8")
    for phrase in (
        "make requirements",
        "make setup",
        "make viewer",
        "make showcase",
        "make setup-dev",
        "bash scripts/showcase.sh",
        "docs/REQUIREMENTS.md",
    ):
        assert phrase in readme
    for phrase in (
        "requirements.txt",
        "requirements-dev.txt",
        "requirements-demo.txt",
        "requirements-browser.txt",
        ".venv/bin/python",
        "Docker Compose",
        "kind",
        "kubectl",
        "Legacy FastAPI",
    ):
        assert phrase.lower() in requirements.lower()

"""Keep reviewer entry points and documentation in sync with the actual repo."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_documentation_links_resolve_within_repository():
    for path in (ROOT / "README.md", ROOT / "docs/reviewer-tour.md"):
        content = path.read_text()
        for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", content):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            local = path.parent / target.split("#", 1)[0]
            assert local.is_file(), f"{path.name} references missing file: {target}"


def test_quickstart_commands_and_gitops_demo_are_real():
    readme = (ROOT / "README.md").read_text()
    for command in (
        "bash scripts/reviewer.sh doctor",
        "bash scripts/reviewer.sh dashboard",
        "bash scripts/reviewer.sh up",
        "bash scripts/reviewer.sh drill",
        "bash scripts/gitops-demo.sh up",
        "bash scripts/gitops-demo.sh drift-test",
    ):
        assert command in readme
    for script in ("scripts/reviewer.sh", "scripts/gitops-demo.sh"):
        assert (ROOT / script).is_file()
    assert readme.count("```mermaid") >= 2
    assert "separate paths" in readme
    assert "private" in readme.lower()


def test_os_specific_setup_routes_preserve_security_boundaries():
    readme = (ROOT / "README.md").read_text()
    for heading in ("## Linux", "## Windows", "## macOS"):
        assert heading in readme
    for name in ("linux.md", "windows.md", "macos.md"):
        assert (ROOT / "docs" / name).is_file()
    mac = (ROOT / "docs/macos.md").read_text()
    assert "make viewer" in mac
    assert "make showcase" in mac
    assert "Ubuntu" in mac
    assert "127.0.0.1:18002" in mac
    assert "operator.token" in readme
    assert "RUN all" in readme

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

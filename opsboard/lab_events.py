"""Read-only parser for the local CLI's bounded, structured progress markers.

The source is an owner-private local file configured by the launcher. No Docker
execution or arbitrary file paths are exposed through the dashboard endpoint.
"""

import re
from pathlib import Path

MAX_READ_BYTES = 65536
MAX_STEPS = 16

BEGIN = re.compile(
    r"^OPSBOARD_LAB\|begin\|(deploy_healthy|deploy_broken|rollback)\|"
    r"([A-Za-z0-9._-]{0,64})\|([A-Za-z0-9._-]{0,64})$"
)
STEP = re.compile(
    r"^OPSBOARD_STEP\|(running|success|failed)\|([A-Za-z0-9 /_-]{1,80})$"
)
FINISH = re.compile(r"^OPSBOARD_LAB\|finish\|(0|[1-9][0-9]{0,2})$")


def latest_cli_operation(filename: str | None) -> dict | None:
    if not filename:
        return None
    path = Path(filename)
    try:
        if path.is_symlink() or not path.is_file():
            return None
        with path.open("rb") as handle:
            handle.seek(0, 2)
            length = handle.tell()
            handle.seek(max(0, length - MAX_READ_BYTES))
            content = handle.read(MAX_READ_BYTES).decode("utf-8", errors="replace")
        if length > MAX_READ_BYTES:
            content = content.partition("\n")[2]
    except OSError:
        return None

    current = None
    for line in content.splitlines():
        begin = BEGIN.fullmatch(line)
        if begin:
            action, version, git_sha = begin.groups()
            current = {
                "action": action,
                "version": version or None,
                "git_sha": git_sha or None,
                "status": "running",
                "steps": [],
            }
            continue
        if current is None:
            continue
        step = STEP.fullmatch(line)
        if step:
            status, name = step.groups()
            existing = next((s for s in current["steps"] if s["name"] == name), None)
            if existing:
                existing["status"] = status
            elif len(current["steps"]) < MAX_STEPS:
                current["steps"].append({"name": name, "status": status})
            continue
        finish = FINISH.fullmatch(line)
        if finish:
            current["status"] = "success" if finish.group(1) == "0" else "failed"
    return current

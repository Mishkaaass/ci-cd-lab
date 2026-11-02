"""ZAP hook: prove that the scanner reached authenticated API handlers."""

import json
from pathlib import Path
from urllib.parse import urlsplit

COVERAGE_PATH = Path("/zap/wrk/coverage.json")


def zap_pre_shutdown(zap):
    successful = {"GET": 0, "POST": 0}
    denied_by_quota = 0
    auth_denials = 0
    messages = zap.core.messages(baseurl="http://opsboard:8000", start=0, count=10000)
    history_complete = len(messages) < 10000
    for message in messages:
        lines = message.get("requestHeader", "").splitlines()
        response = message.get("responseHeader", "").splitlines()
        if not lines or not response:
            continue
        request = lines[0].split()
        status = response[0].split()
        if len(request) < 2 or len(status) < 2:
            continue
        method, target = request[:2]
        parsed = urlsplit(target)
        if parsed.netloc and (
            parsed.scheme != "http" or parsed.netloc != "opsboard:8000"
        ):
            continue
        path = parsed.path
        if not path.startswith("/api/"):
            continue
        authenticated = any(
            line.lower().startswith("authorization: bearer ") for line in lines[1:]
        )
        if status[1] in ("401", "403"):
            auth_denials += 1
        if status[1] == "429":
            denied_by_quota += 1
        if authenticated and status[1].startswith("2") and method in successful:
            successful[method] += 1
    scans = zap.ascan.scans
    finished = bool(scans) and all(str(scan.get("progress")) == "100" for scan in scans)
    COVERAGE_PATH.write_text(
        json.dumps(
            {
                "authenticated_get": successful["GET"],
                "authenticated_post": successful["POST"],
                "quota_denials": denied_by_quota,
                "auth_denials": auth_denials,
                "active_scan_completed": finished and history_complete,
            }
        )
    )

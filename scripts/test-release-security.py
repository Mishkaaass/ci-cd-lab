#!/usr/bin/env python3
"""Test only fresh disposable containers; never accepts a running server URL."""

import hashlib
import json
import secrets
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

POSTGRES = (
    "postgres:18.6-alpine3.24@sha256:"
    "10a5c69a83035ab5239f5620d708520e8b28f5aa1f2b20143e6024532edadfb5"
)
ZAP = (
    "docker.io/zaproxy/zap-stable@sha256:"
    "030d3df57735dacbb83464854758e674dd9ad01d79d12a129a8e58b1fd384238"
)
# A private tmpfs inside a disposable container, not a shared host path.
APP_TMPFS = "/tmp:rw,noexec,nosuid,size=64m"  # nosec B108
SMOKE = r"""
import json, sys, urllib.request, urllib.error
config=json.load(sys.stdin)
origin='http://opsboard:8000'
def request(path, token=None, method='GET', payload=None):
    headers={'Authorization':'Bearer '+token} if token else {}
    body=json.dumps(payload).encode() if payload is not None else None
    if body: headers['Content-Type']='application/json'
    req=urllib.request.Request(origin+path, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)
assert request('/health')[1]['status']=='ok'
assert request('/ready')[1]['database']=='ok'
assert request('/version')[1]['git_sha']==config['sha']
assert request('/api/incidents')[0]==401
assert request('/api/auth/me',config['viewer'])[1]['role']=='viewer'
payload={'service':'smoke','severity':'warning','reason':"SQL literal: ' OR '1'='1"}
assert request('/api/incidents',config['viewer'],'POST',payload)[0]==403
assert request('/api/incidents',config['operator'],'POST',payload)[0]==201
records=request('/api/incidents',config['viewer'])[1]
assert len(records)==1 and records[0]['reason']==payload['reason']
assert request('/api/operations/rollback',config['operator'],'POST')[0]==503
assert request('/api/deployments',config['viewer'])[0]==200
print(json.dumps(request('/openapi.json')[1]))
"""


def scan_spec(document):
    document["paths"] = {
        key: value
        for key, value in document["paths"].items()
        if key.startswith("/api/") and not key.startswith("/api/operations")
    }
    document["servers"] = [{"url": "http://opsboard:8000"}]
    return document


def blocking_alerts(report):
    sites = report.get("site")
    if not isinstance(sites, list) or not sites:
        raise ValueError("Missing ZAP scan sites")
    result = []
    for site in sites:
        alerts = site.get("alerts")
        if not isinstance(alerts, list):
            raise ValueError("Missing ZAP alert list")
        for alert in alerts:
            if int(alert["riskcode"]) >= 2:
                result.append(str(alert["name"]))
    return result


def valid_coverage(coverage):
    return (
        type(coverage.get("authenticated_get")) is int
        and coverage["authenticated_get"] > 0
        and type(coverage.get("authenticated_post")) is int
        and coverage["authenticated_post"] > 0
        and coverage.get("quota_denials") == 0
        and coverage.get("auth_denials") == 0
        and coverage.get("active_scan_completed") is True
    )


def main():
    if len(sys.argv) != 3:
        raise SystemExit(
            "Usage: python3 scripts/test-release-security.py IMAGE EXPECTED_GIT_SHA"
        )
    image, sha = sys.argv[1:]
    ids = []
    network_id = None
    network_name = "opsboard-security-" + uuid.uuid4().hex[:12]

    # Only these newly created IDs are removed on exit; no prune or shared names.
    def docker(*args, **kwargs):
        return subprocess.run(
            ["docker", *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=kwargs.pop("timeout", 120),
            **kwargs,
        ).stdout.strip()

    def create(*args):
        identifier = docker("create", *args)
        ids.append(identifier)
        return identifier

    try:
        for candidate in (image, POSTGRES, ZAP):
            # CI images can exist only locally; pull released images by digest.
            if "@sha256:" in candidate:
                docker("pull", candidate, timeout=300)
        with tempfile.TemporaryDirectory(prefix="opsboard-security-") as directory:
            work = Path(directory)
            viewer, operator, password = (secrets.token_urlsafe(32) for _ in range(3))
            entries = [
                {
                    "name": role,
                    "role": role,
                    "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
                    "expires_at": int(time.time()) + 3600,
                }
                for role, token in [("viewer", viewer), ("operator", operator)]
            ]
            auth = work / "auth.json"
            auth.write_text(json.dumps(entries))
            # Hashes only. The non-root app needs read access to this CI-only bind file.
            auth.chmod(0o644)
            scan_dir = work / "zap"
            scan_dir.mkdir(mode=0o777)
            scan_dir.chmod(0o777)  # ZAP runs as its own unprivileged container user.
            network_id = docker("network", "create", "--internal", network_name)
            db = create(
                "--network",
                network_name,
                "--network-alias",
                "db",
                "--tmpfs",
                "/var/lib/postgresql:rw",
                "-e",
                "POSTGRES_DB=opsboard",
                "-e",
                "POSTGRES_USER=opsboard",
                "-e",
                "POSTGRES_PASSWORD=" + password,
                POSTGRES,
            )
            docker("start", db)
            for _ in range(60):
                try:
                    docker("exec", db, "pg_isready", "-U", "opsboard", "-d", "opsboard")
                    break
                except subprocess.CalledProcessError:
                    time.sleep(1)
            else:
                raise RuntimeError("Disposable database did not become ready")
            app = create(
                "--network",
                network_name,
                "--network-alias",
                "opsboard",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--tmpfs",
                APP_TMPFS,
                "--mount",
                f"type=bind,src={auth},dst=/run/auth.json,readonly",
                "-e",
                "OPSBOARD_AUTH_FILE=/run/auth.json",
                "-e",
                "OPSBOARD_ENABLE_DEPLOYMENTS=false",
                "-e",
                "OPSBOARD_RATE_LIMIT=10000",
                "-e",
                "OPSBOARD_WRITE_RATE_LIMIT=10000",
                "-e",
                "GIT_SHA=" + sha,
                "-e",
                "DATABASE_URL=postgresql+psycopg://opsboard:"
                + password
                + "@db:5432/opsboard",
                image,
            )
            docker("start", app)
            for _ in range(60):
                try:
                    docker(
                        "exec",
                        app,
                        "python",
                        "-c",
                        "import urllib.request; urllib.request.urlopen('http://opsboard:8000/ready',timeout=2)",
                    )
                    break
                except subprocess.CalledProcessError:
                    time.sleep(1)
            else:
                raise RuntimeError("Disposable app did not become ready")
            config = json.dumps({"viewer": viewer, "operator": operator, "sha": sha})
            spec = json.loads(
                docker("exec", "-i", app, "python", "-c", SMOKE, input=config)
            )
            (scan_dir / "api.json").write_text(json.dumps(scan_spec(spec)))
            hook_source = Path(__file__).with_name("zap-coverage-hook.py").read_text()
            (scan_dir / "coverage_hook.py").write_text(hook_source)
            (scan_dir / "rules.conf").write_text(
                "# Every protected mutation needs a Bearer header; no cookies.\n"
                "10202\tIGNORE\tAnti-CSRF tokens do not apply to this bearer-only API\n"
            )
            scanner = create(
                "--network",
                network_name,
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--mount",
                f"type=bind,src={scan_dir},dst=/zap/wrk",
                "-e",
                "ZAP_AUTH_HEADER_VALUE=Bearer " + operator,
                "-e",
                "ZAP_AUTH_HEADER_SITE=opsboard",
                ZAP,
                "zap-api-scan.py",
                "-t",
                "/zap/wrk/api.json",
                "-f",
                "openapi",
                "-c",
                "/zap/wrk/rules.conf",
                "-J",
                "report.json",
                "--hook",
                "/zap/wrk/coverage_hook.py",
                "-T",
                "10",
                "-z",
                "-config ascan.maxScanDurationInMins=0 "
                "-config ascan.maxRuleDurationInMins=0",
            )
            result = subprocess.run(
                ["docker", "start", "-a", scanner],
                capture_output=True,
                text=True,
                timeout=900,
            )
            if result.returncode not in (0, 1, 2):
                raise RuntimeError("ZAP scanner failed; no successful scan result")
            raw = (scan_dir / "report.json").read_text()
            for secret in (viewer, operator, password):
                raw = raw.replace(secret, "[REDACTED]")
            report = json.loads(raw)
            alerts = blocking_alerts(report)
            coverage = json.loads((scan_dir / "coverage.json").read_text())
            if not valid_coverage(coverage):
                raise RuntimeError(
                    "ZAP lacks authenticated GET/POST coverage or a completed scan"
                )
            # Also verify the scanner did not exhaust quotas or lose authentication.
            docker(
                "exec",
                "-i",
                app,
                "python",
                "-c",
                "import json,sys,urllib.request; c=json.load(sys.stdin); "
                "r=urllib.request.Request('http://opsboard:8000/api/auth/me',"
                "headers={'Authorization':'Bearer '+c['operator']}); "
                "assert json.load(urllib.request.urlopen(r,timeout=5))"
                "['role']=='operator'",
                input=config,
            )
            destination = Path("artifacts/security")
            destination.mkdir(parents=True, exist_ok=False)
            (destination / "zap-report.json").write_text(raw)
            if alerts:
                raise RuntimeError(
                    "ZAP MEDIUM/HIGH alerts: " + ", ".join(sorted(set(alerts)))
                )
            print("PASS: authenticated release smoke and isolated ZAP API scan")
            print("Sanitized report: artifacts/security/zap-report.json")
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        # Never print command arguments, request/response bodies, or CI credentials.
        print(
            "FAIL: isolated release security scan (" + type(exc).__name__ + ").",
            file=sys.stderr,
        )
        if isinstance(exc, RuntimeError):
            print(str(exc), file=sys.stderr)
        return 1
    finally:
        for identifier in reversed(ids):
            subprocess.run(
                ["docker", "rm", "-f", identifier], capture_output=True, timeout=30
            )
        if network_id:
            subprocess.run(
                ["docker", "network", "rm", network_id], capture_output=True, timeout=30
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

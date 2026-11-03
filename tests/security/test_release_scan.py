import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/test-release-security.py"


def module():
    spec = importlib.util.spec_from_file_location("release_scan", SCRIPT)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_scan_spec_removes_all_execution_endpoints_and_fixes_destination():
    scan = module()
    spec = {
        "paths": {"/api/operations/rollback": {}, "/api/incidents": {}, "/health": {}},
        "servers": [{"url": "https://external.invalid"}],
    }
    result = scan.scan_spec(spec)
    assert set(result["paths"]) == {"/api/incidents"}
    assert result["servers"] == [{"url": "http://opsboard:8000"}]


def test_scan_report_does_not_allow_medium_alerts_or_malformed_results():
    scan = module()
    assert (
        scan.blocking_alerts({"site": [{"alerts": [{"riskcode": "1", "name": "low"}]}]})
        == []
    )
    assert scan.blocking_alerts(
        {"site": [{"alerts": [{"riskcode": "2", "name": "SQL injection"}]}]}
    ) == ["SQL injection"]
    with pytest.raises(ValueError):
        scan.blocking_alerts({})


def test_denied_or_incomplete_scan_is_not_coverage():
    scan = module()
    valid = {
        "authenticated_get": 1,
        "authenticated_post": 1,
        "quota_denials": 0,
        "auth_denials": 0,
        "active_scan_completed": True,
    }
    assert scan.valid_coverage(valid)
    for key, value in [
        ("authenticated_get", 0),
        ("authenticated_post", 0),
        ("quota_denials", 1),
        ("active_scan_completed", False),
    ]:
        assert not scan.valid_coverage({**valid, key: value})
    assert not scan.valid_coverage({})


@pytest.mark.parametrize(
    "target", ["/api/incidents", "http://opsboard:8000/api/incidents"]
)
def test_zap_coverage_accepts_origin_and_absolute_request_targets(
    tmp_path, monkeypatch, target
):
    import json
    from types import SimpleNamespace

    spec = importlib.util.spec_from_file_location(
        "coverage_hook", SCRIPT.with_name("zap-coverage-hook.py")
    )
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    monkeypatch.setattr(hook, "COVERAGE_PATH", tmp_path / "coverage.json")
    messages = [
        {
            "requestHeader": (
                f"{method} {target} HTTP/1.1\r\nAuthorization: Bearer disposable\r\n"
            ),
            "responseHeader": "HTTP/1.1 200 OK\r\n",
        }
        for method in ("GET", "POST")
    ]
    zap = SimpleNamespace(
        core=SimpleNamespace(messages=lambda **_: messages),
        ascan=SimpleNamespace(scans=[{"progress": "100"}]),
    )
    hook.zap_pre_shutdown(zap)
    coverage = json.loads((tmp_path / "coverage.json").read_text())
    assert module().valid_coverage(coverage)


@pytest.fixture
def isolated_scan(tmp_path, monkeypatch):
    """Model only Docker's file boundary; run controller and file IO unchanged.

    Docker is external to pytest. A writable host bind models a ZAP-owned
    private directory that an unprivileged runner cannot clean up. Read-only
    inputs and `docker cp` leave host files owned by the runner instead.
    """
    scan = module()
    state = SimpleNamespace(
        writable_bind=False,
        cleanup_error=False,
        copy_error=False,
        risk="1",
        coverage_complete=True,
        config=None,
        mounts={},
    )
    real_temporary_directory = tempfile.TemporaryDirectory

    class RunnerDirectory(real_temporary_directory):
        def __exit__(self, *args):
            super().__exit__(*args)
            if state.writable_bind or state.cleanup_error:
                raise PermissionError("fixture: foreign-owned ZAP directory")

    def reports():
        return {
            "report.json": json.dumps(
                {
                    "site": [
                        {
                            "alerts": [{"riskcode": state.risk, "name": "fixture"}],
                            "evidence": state.config["operator"],
                        }
                    ]
                }
            ),
            "coverage.json": json.dumps(
                {
                    "authenticated_get": 1,
                    "authenticated_post": 1,
                    "quota_denials": 0,
                    "auth_denials": 0,
                    "active_scan_completed": state.coverage_complete,
                }
            ),
        }

    def docker_run(command, **kwargs):
        assert command[0] == "docker"
        args = command[1:]
        output = ""
        if args[0] == "pull":
            pass
        elif args[:2] == ["network", "create"]:
            assert "--internal" in args
            output = "fixture-network"
        elif args[0] == "create":
            if "--network-alias" in args:
                output = args[args.index("--network-alias") + 1]
            else:
                output = "scanner"
                for i, value in enumerate(args):
                    if value == "--mount":
                        fields = dict(
                            part.split("=", 1) if "=" in part else (part, True)
                            for part in args[i + 1].split(",")
                        )
                        state.mounts[fields["dst"]] = Path(fields["src"])
                        if fields["type"] == "bind" and not fields.get("readonly"):
                            state.writable_bind = True
        elif args[:2] == ["start", "-a"]:
            # Only a writable bind lets the scanner create files on the host.
            if state.writable_bind:
                for name, content in reports().items():
                    (state.mounts["/zap/wrk"] / name).write_text(content)
        elif args[0] == "start":
            pass
        elif args[0] == "exec":
            if kwargs.get("input"):
                state.config = json.loads(kwargs["input"])
                output = json.dumps({"paths": {"/api/incidents": {}}})
        elif args[0] == "cp":
            if state.copy_error:
                raise subprocess.CalledProcessError(1, command)
            source = args[1].removeprefix("scanner:/zap/wrk/")
            Path(args[2]).write_text(reports()[source])
        elif args[:2] == ["rm", "-f"] or args[:2] == ["network", "rm"]:
            pass
        else:
            raise AssertionError(f"Unexpected Docker operation: {args[:2]}")
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(scan.tempfile, "TemporaryDirectory", RunnerDirectory)
    monkeypatch.setattr(scan.subprocess, "run", docker_run)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "fixture:image", "fixture-sha"])
    return scan, state


def test_scan_can_finish_without_cross_user_host_writes(isolated_scan, capsys):
    scan, state = isolated_scan
    assert scan.main() == 0
    report = Path("artifacts/security/zap-report.json").read_text()
    assert state.config["operator"] not in report
    assert "[REDACTED]" in report
    assert "PASS:" in capsys.readouterr().out


def test_cleanup_failure_never_announces_a_successful_gate(isolated_scan, capsys):
    scan, state = isolated_scan
    state.cleanup_error = True
    assert scan.main() == 1
    output = capsys.readouterr()
    assert "PASS:" not in output.out
    assert "PermissionError" in output.err


@pytest.mark.parametrize("failure", ["copy_error", "medium_alert", "incomplete_scan"])
def test_scan_still_blocks_failed_or_unsafe_results(isolated_scan, capsys, failure):
    scan, state = isolated_scan
    if failure == "medium_alert":
        state.risk = "2"
    elif failure == "incomplete_scan":
        state.coverage_complete = False
    else:
        state.copy_error = True
    assert scan.main() == 1
    output = capsys.readouterr()
    assert "PASS:" not in output.out
    assert "FAIL:" in output.err

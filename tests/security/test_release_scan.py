import importlib.util
from pathlib import Path

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

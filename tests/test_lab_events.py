"""Parser tests do not require Docker, credentials or a database."""

from opsboard.lab_events import latest_cli_operation


def test_latest_cli_operation_tracks_real_step_outcomes(tmp_path):
    log = tmp_path / "events.log"
    log.write_text(
        "OPSBOARD_LAB|begin|deploy_broken|v2.0.0|broken001\n"
        "OPSBOARD_STEP|running|Readiness check\n"
        "OPSBOARD_STEP|failed|Readiness check\n"
        "OPSBOARD_LAB|finish|1\n"
        "OPSBOARD_LAB|begin|deploy_healthy|v2.0.1|healthy001\n"
        "OPSBOARD_STEP|running|Container started\n"
        "OPSBOARD_STEP|success|Container started\n"
        "OPSBOARD_STEP|success|Readiness check\n"
        "OPSBOARD_LAB|finish|0\n"
    )
    operation = latest_cli_operation(str(log))
    assert operation == {
        "action": "deploy_healthy",
        "version": "v2.0.1",
        "git_sha": "healthy001",
        "status": "success",
        "steps": [
            {"name": "Container started", "status": "success"},
            {"name": "Readiness check", "status": "success"},
        ],
    }


def test_progress_without_finish_stays_running(tmp_path):
    log = tmp_path / "events.log"
    log.write_text(
        "OPSBOARD_LAB|begin|rollback||\n"
        "OPSBOARD_STEP|running|Target readiness verified\n"
    )
    operation = latest_cli_operation(str(log))
    assert operation["action"] == "rollback"
    assert operation["status"] == "running"
    assert operation["steps"][0]["status"] == "running"


def test_missing_symlink_and_malformed_log_are_not_trusted(tmp_path):
    missing = tmp_path / "missing"
    assert latest_cli_operation(str(missing)) is None
    log = tmp_path / "log"
    log.write_text("OPSBOARD_LAB|begin|arbitrary|foo|bar\n")
    assert latest_cli_operation(str(log)) is None
    link = tmp_path / "link"
    link.symlink_to(log)
    assert latest_cli_operation(str(link)) is None


def test_large_file_is_bounded_and_recovers_last_run(tmp_path):
    log = tmp_path / "log"
    log.write_text(
        "x" * 100000 + "\nOPSBOARD_LAB|begin|rollback||\n"
        "OPSBOARD_STEP|success|Production converged\n"
        "OPSBOARD_LAB|finish|0\n"
    )
    operation = latest_cli_operation(str(log))
    assert operation["action"] == "rollback"
    assert operation["status"] == "success"

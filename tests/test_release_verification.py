import pytest

from opsboard.release_verification import wait_for_release


def test_wait_for_release_succeeds_immediately():
    def fetch_release():
        return {
            "version": "v1.5.1",
            "git_sha": "good999",
        }

    release, attempts = wait_for_release(
        fetch_release=fetch_release,
        expected_version="v1.5.1",
        expected_git_sha="good999",
        attempts=5,
        delay_seconds=0,
        sleep_fn=lambda _: None,
    )

    assert release["version"] == "v1.5.1"
    assert release["git_sha"] == "good999"
    assert attempts == 1


def test_wait_for_release_tolerates_old_nginx_worker():
    responses = iter(
        [
            {
                "version": "v1.3.0",
                "git_sha": "good123",
            },
            {
                "version": "v1.5.1",
                "git_sha": "good999",
            },
        ]
    )

    def fetch_release():
        return next(responses)

    release, attempts = wait_for_release(
        fetch_release=fetch_release,
        expected_version="v1.5.1",
        expected_git_sha="good999",
        attempts=5,
        delay_seconds=0,
        sleep_fn=lambda _: None,
    )

    assert release["version"] == "v1.5.1"
    assert release["git_sha"] == "good999"
    assert attempts == 2


def test_wait_for_release_fails_if_production_never_converges():
    def fetch_release():
        return {
            "version": "v1.3.0",
            "git_sha": "good123",
        }

    with pytest.raises(
        RuntimeError,
        match="Production did not converge",
    ):
        wait_for_release(
            fetch_release=fetch_release,
            expected_version="v1.5.1",
            expected_git_sha="good999",
            attempts=3,
            delay_seconds=0,
            sleep_fn=lambda _: None,
        )

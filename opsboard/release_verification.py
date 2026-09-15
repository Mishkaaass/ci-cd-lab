import argparse
import json
import time
from urllib.request import urlopen


def fetch_release_from_url(base_url: str) -> dict:
    url = f"{base_url.rstrip('/')}/version"

    with urlopen(
        url,
        timeout=2,
    ) as response:
        return json.load(response)


def wait_for_release(
    fetch_release,
    expected_version: str,
    expected_git_sha: str,
    attempts: int = 20,
    delay_seconds: float = 0.25,
    sleep_fn=time.sleep,
):
    last_release = None
    last_error = None

    for attempt in range(
        1,
        attempts + 1,
    ):
        try:
            release = fetch_release()
            last_release = release
            last_error = None

            version_matches = release.get("version") == expected_version

            sha_matches = release.get("git_sha") == expected_git_sha

            if version_matches and sha_matches:
                return release, attempt

        except Exception as exc:
            last_error = str(exc)

        if attempt < attempts:
            sleep_fn(delay_seconds)

    if last_error is not None:
        detail = f"last error: {last_error}"
    else:
        detail = f"last release: {last_release}"

    raise RuntimeError(
        "Production did not converge to "
        f"{expected_version} / "
        f"{expected_git_sha}; "
        f"{detail}"
    )


def main():
    parser = argparse.ArgumentParser(
        description=("Wait until production is serving the expected release.")
    )

    parser.add_argument(
        "--base-url",
        required=True,
    )

    parser.add_argument(
        "--version",
        required=True,
    )

    parser.add_argument(
        "--git-sha",
        required=True,
    )

    parser.add_argument(
        "--attempts",
        type=int,
        default=20,
    )

    parser.add_argument(
        "--delay",
        type=float,
        default=0.25,
    )

    args = parser.parse_args()

    def fetch_release():
        return fetch_release_from_url(args.base_url)

    release, attempts = wait_for_release(
        fetch_release=fetch_release,
        expected_version=args.version,
        expected_git_sha=args.git_sha,
        attempts=args.attempts,
        delay_seconds=args.delay,
    )

    print(f"Production verified after {attempts} attempt(s):")

    print(
        json.dumps(
            release,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

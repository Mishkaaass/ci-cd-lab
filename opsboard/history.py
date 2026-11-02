"""Authenticated deployment-history callback for the local Compose scripts."""

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from opsboard.security import TOKEN_PATTERN


def record(payload, base_url, token_file, *, transport=None):
    parsed = urlsplit(base_url)
    if (
        parsed.scheme not in ("https", "http")
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
        or (
            parsed.scheme == "http"
            and parsed.hostname not in ("localhost", "127.0.0.1", "::1")
        )
    ):
        raise ValueError("History requires HTTPS or loopback HTTP and an origin URL")
    with Path(token_file).open() as handle:
        token = handle.read(258).strip()
    if not TOKEN_PATTERN.fullmatch(token):
        raise ValueError("Invalid history credential")
    with httpx.Client(
        trust_env=False, follow_redirects=False, timeout=5, transport=transport
    ) as client:
        response = client.post(
            base_url.rstrip("/") + "/api/deployments",
            json=payload,
            headers={"Authorization": "Bearer " + token},
        )
        response.raise_for_status()


def main():
    try:
        content = sys.stdin.read(16385)
        if len(content) > 16384:
            raise ValueError("Payload too large")
        record(
            json.loads(content),
            os.getenv("OPSBOARD_URL", "http://127.0.0.1:8000"),
            os.environ["OPSBOARD_RECORD_TOKEN_FILE"],
        )
    except OSError, ValueError, KeyError, httpx.HTTPError:
        print(
            "WARNING: history not recorded; check callback credentials and API.",
            file=sys.stderr,
        )
        return 1
    print("Deployment history recorded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

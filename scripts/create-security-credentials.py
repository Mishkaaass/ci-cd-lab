#!/usr/bin/env python3
"""Create fresh local credentials; never overwrite an existing destination."""

import argparse
import hashlib
import json
import os
import secrets
import time
from pathlib import Path


def create(destination: Path, days: int = 30) -> None:
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    entries = []
    for role in ("viewer", "operator"):
        token = secrets.token_urlsafe(32)
        entries.append(
            {
                "name": "lab-" + role,
                "role": role,
                "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
                "expires_at": int(time.time()) + days * 86400,
            }
        )
        path = destination / (role + ".token")
        with os.fdopen(
            os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
        ) as handle:
            handle.write(token + "\n")
    path = destination / "auth.json"
    with os.fdopen(
        os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
    ) as handle:
        json.dump(entries, handle, indent=2)
        handle.write("\n")
    print("Private credentials created at:", destination.resolve())
    print("Server config:", path.resolve())
    print("Read tokens locally; never commit or paste their contents.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "destination", type=Path, help="New directory; parent must exist"
    )
    parser.add_argument(
        "--days", type=int, choices=range(1, 91), default=30, metavar="1..90"
    )
    args = parser.parse_args()
    try:
        create(args.destination, args.days)
    except OSError:
        parser.exit(
            1,
            "STOP: destination unavailable; existing files preserved.\n",
        )


if __name__ == "__main__":
    main()

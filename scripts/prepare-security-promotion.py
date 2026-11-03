#!/usr/bin/env python3
"""Preview a Kubernetes promotion only from a successful security-enabled CD run."""

import argparse
import difflib
import hashlib
import json
import re
import subprocess
import time
from pathlib import Path

REPO = "Mishkaaass/ci-cd-lab"
IMAGE_PATTERN = r"ghcr\.io/mishkaaass/ci-cd-lab@sha256:[a-f0-9]{64}"
MARKER = "PASS: authenticated release smoke and isolated ZAP API scan"


def verified_release(logs):
    records = re.findall(r"OPSBOARD_VERIFIED_RELEASE=(\{[^\r\n]*\})", logs)
    releases = [json.loads(record) for record in records]
    if MARKER not in logs or len(releases) != 1:
        raise ValueError("Missing unique canonical security-verified release")
    release = releases[0]
    if (
        set(release) != {"image", "git_sha"}
        or not isinstance(release["image"], str)
        or not re.fullmatch(IMAGE_PATTERN, release["image"])
        or not isinstance(release["git_sha"], str)
        or not re.fullmatch("[a-f0-9]{40}", release["git_sha"])
    ):
        raise ValueError("Invalid verified release record")
    return release


def validate_auth(content):
    if len(content) > 65536:
        raise ValueError("Authentication configuration is too large")
    entries = json.loads(content)
    if not isinstance(entries, list) or not 1 <= len(entries) <= 64:
        raise ValueError("Expected nonempty credential list")
    names, digests = set(), set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {
            "name",
            "role",
            "token_sha256",
            "expires_at",
        }:
            raise ValueError("Invalid credential fields")
        name, digest = entry["name"], entry["token_sha256"]
        if (
            not isinstance(name, str)
            or not re.fullmatch("[A-Za-z0-9][A-Za-z0-9._-]{0,63}", name)
            or entry["role"] not in ("viewer", "operator")
            or not isinstance(digest, str)
            or not re.fullmatch("[a-f0-9]{64}", digest)
            or type(entry["expires_at"]) is not int
            or entry["expires_at"] <= 0
            or name in names
            or digest in digests
        ):
            raise ValueError("Invalid credential value")
        names.add(name)
        digests.add(digest)
    if not any(entry["expires_at"] > time.time() for entry in entries):
        raise ValueError("All credentials are expired")


def render(content, image, sha, secret):
    if "OPSBOARD_AUTH_FILE" in content:
        raise ValueError(
            "Authentication is already wired; review subsequent promotions manually"
        )
    for pattern, replacement in [
        (r"image: " + IMAGE_PATTERN, "image: " + image),
        (r"value: sha-[a-f0-9]+", "value: sha-" + sha[:7]),
        (r"value: [a-f0-9]{40}", "value: " + sha),
    ]:
        content, count = re.subn(
            pattern, lambda _match, replacement=replacement: replacement, content
        )
        if count != 1:
            raise ValueError("Unexpected manifest shape; no file was written")
    changes = {
        "          env:\n": (
            "          env:\n"
            "            - name: OPSBOARD_AUTH_FILE\n"
            "              value: /run/opsboard-auth/auth.json\n"
            "            - name: OPSBOARD_ENABLE_DEPLOYMENTS\n"
            '              value: "false"\n'
        ),
        "          volumeMounts:\n": (
            "          volumeMounts:\n"
            "            - name: auth\n"
            "              mountPath: /run/opsboard-auth\n"
            "              readOnly: true\n"
        ),
        "      volumes:\n": (
            "      volumes:\n"
            "        - name: auth\n"
            "          secret:\n"
            f"            secretName: {secret}\n"
            "            defaultMode: 0444\n"
        ),
    }
    for marker, replacement in changes.items():
        if content.count(marker) != 1:
            raise ValueError("Unexpected manifest shape; no file was written")
        content = content.replace(marker, replacement)
    return content


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run", required=True, type=int, help="Successful CD run on main"
    )
    parser.add_argument(
        "--auth-file", required=True, type=Path, help="Private generated auth.json"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the reviewed Git change; never deploys",
    )
    args = parser.parse_args()

    def gh(*options):
        return subprocess.check_output(
            ["gh", *options, "--repo", REPO], text=True, timeout=30
        )

    try:
        metadata = json.loads(
            gh(
                "run",
                "view",
                str(args.run),
                "--json",
                "headSha,headBranch,event,workflowName,status,conclusion",
            )
        )
        if (
            metadata["headBranch"] != "main"
            or metadata["workflowName"] != "CD"
            or metadata["status"] != "completed"
            or metadata["conclusion"] != "success"
            or metadata["event"] != "workflow_run"
        ):
            raise ValueError("Expected a completed successful CD run on main")
        logs = gh("run", "view", str(args.run), "--log")
        release = verified_release(logs)
        sha = release["git_sha"]
        auth_bytes = args.auth_file.read_bytes()
        validate_auth(auth_bytes)
        secret = "opsboard-auth-" + hashlib.sha256(auth_bytes).hexdigest()[:12]
        path = Path("k8s/opsboard/app.yaml")
        original = path.read_text()
        changed = render(original, release["image"], sha, secret)
        print(
            "".join(
                difflib.unified_diff(
                    original.splitlines(True),
                    changed.splitlines(True),
                    fromfile=str(path),
                    tofile=str(path),
                )
            ),
            end="",
        )
        print("\nRequired pre-created Secret in opsboard:", secret)
        if args.apply:
            if subprocess.check_output(
                ["git", "status", "--porcelain"], text=True
            ).strip():
                raise ValueError(
                    "Working tree must be clean before preparing promotion"
                )
            path.write_text(changed)
            print(
                "Prepared Git change only. Validate, review and merge before Argo sync."
            )
        else:
            print("Preview only. No files or cluster resources changed.")
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        parser.exit(1, "STOP: " + str(exc) + "\n")


if __name__ == "__main__":
    main()

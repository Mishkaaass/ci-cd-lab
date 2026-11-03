import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/create-security-credentials.py"


def test_generate_private_expiring_credentials_without_printing_tokens(tmp_path):
    destination = tmp_path / "credentials"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(destination)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    entries = json.loads((destination / "auth.json").read_text())
    assert {entry["role"] for entry in entries} == {"viewer", "operator"}
    for entry in entries:
        token_file = destination / (entry["role"] + ".token")
        token = token_file.read_text().strip()
        assert len(token) >= 43
        assert hashlib.sha256(token.encode()).hexdigest() == entry["token_sha256"]
        assert time.time() < entry["expires_at"] <= time.time() + 31 * 86400
        assert token not in result.stdout + result.stderr
        if os.name == "posix":
            assert token_file.stat().st_mode & 0o777 == 0o600
    assert destination.stat().st_mode & 0o777 == 0o700
    assert (destination / "auth.json").stat().st_mode & 0o777 == 0o600


def test_existing_destination_is_preserved(tmp_path):
    (tmp_path / "keep.txt").write_text("original")
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path)], capture_output=True, text=True
    )
    assert result.returncode != 0
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before
    assert (tmp_path / "keep.txt").read_text() == "original"

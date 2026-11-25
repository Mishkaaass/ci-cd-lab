"""Offline regression tests for isolated kind / Argo CD reviewer bootstrap."""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "scripts/gitops-demo.sh"


def setup_gitops(tmp_path):
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    shutil.copy(SOURCE, root / "scripts/gitops-demo.sh")
    fake = tmp_path / "fakebin"
    fake.mkdir()
    calls = tmp_path / "calls.txt"
    for tool, body in {
        "docker": """case "$1" in info) exit 0;; inspect) echo fake-node-id;; esac""",
        "kind": (
            'echo kind-call >> "$CALLS"; case "$1" in get) echo opsboard-review;; esac'
        ),
        "kubectl": """echo "kubectl $*" >> "$CALLS"; exit 0""",
        "curl": """echo "curl $*" >> "$CALLS"; exit 0""",
        "git": """echo "git $*" >> "$CALLS"; exit 128""",
    }.items():
        cmd = fake / tool
        cmd.write_text("#!/usr/bin/env bash\n" + body + "\n")
        cmd.chmod(0o755)
    env = {
        **os.environ,
        "PATH": str(fake) + os.pathsep + os.environ["PATH"],
        "CALLS": str(calls),
        "XDG_STATE_HOME": str(tmp_path / "state"),
    }
    return root, env, calls


def run_gitops(root, env, *args):
    return subprocess.run(
        ["bash", "scripts/gitops-demo.sh", *args],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )


def test_delete_requires_explicit_acknowledgment_before_using_tools(tmp_path):
    root, env, calls = setup_gitops(tmp_path)
    result = run_gitops(root, env, "down")
    assert result.returncode != 0
    assert "--delete-my-lab" in result.stderr
    assert not calls.exists()


def test_existing_unknown_cluster_is_never_adopted(tmp_path):
    root, env, calls = setup_gitops(tmp_path)
    result = run_gitops(root, env, "status")
    assert result.returncode != 0
    assert "No ownership marker" in result.stderr
    assert not calls.exists() or "delete" not in calls.read_text()


def test_credentials_in_git_url_are_rejected_before_cluster_creation(tmp_path):
    root, env, calls = setup_gitops(tmp_path)
    env["GITOPS_REPO_URL"] = "https://someone:secret@github.com/example/repo.git"
    result = run_gitops(root, env, "up")
    assert result.returncode != 0
    assert "without credentials" in result.stderr
    if calls.exists():
        assert "create cluster" not in calls.read_text()


def test_private_git_repo_without_token_fails_before_cluster_creation(tmp_path):
    root, env, calls = setup_gitops(tmp_path)
    env["GITOPS_REPO_URL"] = "https://github.com/example/private.git"
    result = run_gitops(root, env, "up")
    assert result.returncode != 0
    assert "Make the repo public" in result.stderr
    assert "create cluster" not in calls.read_text()


def test_help_explains_safety_and_access(tmp_path):
    root, env, _ = setup_gitops(tmp_path)
    result = run_gitops(root, env, "help")
    assert result.returncode == 0
    assert "private kubeconfig" not in result.stderr
    assert "GITOPS_READ_TOKEN_FILE" in result.stdout


@pytest.mark.parametrize("tampered", [False, True])
def test_bootstrap_keeps_kubeconfig_and_secrets_in_owned_state(tmp_path, tampered):
    """Fake all external binaries to exercise up without Docker, internet or K8s."""
    root, env, calls = setup_gitops(tmp_path)
    original = SOURCE.parents[1]
    real_git = shutil.which("git")
    assert real_git is not None
    fixture = "apiVersion: v1\n"
    expected = subprocess.run(
        [real_git, "hash-object", "--stdin"],
        input=fixture,
        text=True,
        capture_output=True,
        check=True,
        timeout=5,
    ).stdout.strip()
    # Only the temporary script copy trusts the synthetic manifest.
    script = root / "scripts/gitops-demo.sh"
    content, count = re.subn(
        r'(?m)^ARGOBLOB="[0-9a-f]{40}"$',
        f'ARGOBLOB="{expected}"',
        script.read_text(),
    )
    assert count == 1
    script.write_text(content)
    env["REAL_GIT"] = real_git
    env["FAKE_ARGO_CONTENT"] = fixture + ("# tampered\n" if tampered else "")
    (root / "k8s/argocd").mkdir(parents=True)
    (root / "k8s/opsboard").mkdir(parents=True)
    shutil.copy(
        original / "k8s/argocd/opsboard.yaml", root / "k8s/argocd/opsboard.yaml"
    )
    shutil.copy(original / "k8s/opsboard/app.yaml", root / "k8s/opsboard/app.yaml")
    shutil.copy(
        original / "scripts/create-security-credentials.py",
        root / "scripts/create-security-credentials.py",
    )
    tools = tmp_path / "fakebin"
    (tools / "kind").write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf 'kind %s\\n' "$*" >> "$CALLS"
case "$1 $2" in
  'get clusters') exit 0;;
  'create cluster')
    while [ "$#" -gt 0 ]; do
      if [ "$1" = --kubeconfig ]; then
        printf '%s\\n' 'mock-cluster-config' > "$2"
        exit 0
      fi
      shift
    done
    exit 4;;
  *) exit 0;;
esac
"""
    )
    (tools / "kubectl").write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf 'kubectl %s\\n' "$*" >> "$CALLS"
# Match the real kubectl client's stdin consumption for pipeline tests.
case "$*" in
  *'apply -f -'*) cat >/dev/null;;
  *'config current-context'*) echo 'kind-opsboard-review';;
  *'status.sync.status'*) echo Synced;;
  *'status.health.status'*) echo Healthy;;
  *'create namespace'*) echo 'apiVersion: v1';;
  *'create secret'*) echo 'apiVersion: v1';;
  *) exit 0;;
esac
"""
    )
    (tools / "curl").write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf 'curl called\\n' >> "$CALLS"
while [ "$#" -gt 0 ]; do
  if [ "$1" = -o ]; then
    printf '%s' "$FAKE_ARGO_CONTENT" > "$2"
    exit 0
  fi
  shift
done
exit 4
"""
    )
    (tools / "git").write_text(
        """#!/usr/bin/env bash
if [ "$1" = hash-object ]; then
  exec "$REAL_GIT" "$@"
fi
exit 0
"""
    )
    for tool in ("kind", "kubectl", "curl", "git"):
        (tools / tool).chmod(0o755)

    # Every secret and the cluster marker lives in a temporary state directory.
    result = run_gitops(root, env, "up")
    if tampered:
        assert result.returncode != 0
        assert "manifest failed immutable Git blob verification" in result.stderr
        assert "--force-conflicts -f" not in calls.read_text()
        return
    assert result.returncode == 0, result.stdout + result.stderr
    state = tmp_path / "state/opsboard-gitops-review"
    assert (state / "kubeconfig").read_text().strip() == "mock-cluster-config"
    assert (state / "control-plane-id").read_text().strip() == "fake-node-id"
    assert (state / "auth/viewer.token").is_file()
    assert (state / "db/POSTGRES_PASSWORD").is_file()
    assert (state / "argo-opsboard.yaml").is_file()
    assert "kind create cluster" in calls.read_text()
    assert "delete cluster" not in calls.read_text()
    assert "PASS: Argo CD Synced / Healthy" in result.stdout

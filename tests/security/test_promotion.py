import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/prepare-security-promotion.py"


def promotion():
    spec = importlib.util.spec_from_file_location("promotion", SCRIPT)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_promotion_updates_digest_metadata_and_auth_together():
    mod = promotion()
    original = (SCRIPT.parents[1] / "k8s/opsboard/app.yaml").read_text()
    image = "ghcr.io/mishkaaass/ci-cd-lab@sha256:" + "a" * 64
    changed = mod.render(original, image, "b" * 40, "opsboard-auth-" + "c" * 12)
    assert image in changed and "value: " + "b" * 40 in changed
    assert "OPSBOARD_AUTH_FILE" in changed and "OPSBOARD_ENABLE_DEPLOYMENTS" in changed
    assert "secretName: opsboard-auth-" + "c" * 12 in changed
    assert original == (SCRIPT.parents[1] / "k8s/opsboard/app.yaml").read_text()


def test_repeated_auth_wiring_is_rejected():
    with pytest.raises(ValueError):
        promotion().render("OPSBOARD_AUTH_FILE", "image", "sha", "secret")


def test_canonical_release_sha_is_used_instead_of_downstream_workflow_head():
    import json

    mod = promotion()
    record = {
        "image": "ghcr.io/mishkaaass/ci-cd-lab@sha256:" + "a" * 64,
        "git_sha": "b" * 40,
    }
    logs = mod.MARKER + "\nOPSBOARD_VERIFIED_RELEASE=" + json.dumps(record)
    assert mod.verified_release(logs) == record
    with pytest.raises(ValueError):
        mod.verified_release(mod.MARKER)


@pytest.mark.parametrize(
    "entries",
    [
        [],
        [{}],
        [
            {
                "name": "operator",
                "role": "operator",
                "token_sha256": "a" * 64,
                "expires_at": 1,
            }
        ],
    ],
)
def test_invalid_or_expired_auth_configuration_cannot_be_promoted(entries):
    import json

    with pytest.raises(ValueError):
        promotion().validate_auth(json.dumps(entries).encode())

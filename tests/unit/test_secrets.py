import json

import pytest

from platform_core.secrets import (
    MemorySecretStore,
    SecretCredentialStore,
    SecretStoreUnavailable,
    secret_ref,
)


def test_secret_reference_does_not_contain_value():
    store = MemorySecretStore()
    ref = secret_ref("model-config", "volc-1")
    store.set(ref, "secret-token")
    assert store.get(ref) == "secret-token"
    assert "secret-token" not in ref


def test_masked_value_never_returns_full_secret():
    store = MemorySecretStore()
    ref = secret_ref("model-config", "qwen-1")
    store.set(ref, "sk-1234567890")
    assert store.masked(ref) == "sk-****7890"


def test_compound_credentials_are_stored_as_one_secret_json():
    backend = MemorySecretStore()
    credentials = SecretCredentialStore(backend)
    reference = secret_ref("storage-source", "oss-a")
    credentials.set(reference, {"access_key_id": "id-value", "access_key_secret": "secret-value"})
    assert credentials.get(reference) == {"access_key_id": "id-value", "access_key_secret": "secret-value"}
    assert "secret-value" not in str(credentials.public_state(reference))
    assert credentials.public_state(reference)["configured"] is True
    assert credentials.public_state(reference)["available"] is True


def test_compound_credentials_reject_non_object_secret():
    backend = MemorySecretStore()
    backend.set("xjalgo:storage-source:bad", "not-json")
    with pytest.raises(RuntimeError, match="credential payload"):
        SecretCredentialStore(backend).get("xjalgo:storage-source:bad")


class UnavailableSecretStore:
    def set(self, reference: str, value: str) -> None:
        raise SecretStoreUnavailable("unavailable")

    def get(self, reference: str):
        raise SecretStoreUnavailable("unavailable")

    def delete(self, reference: str) -> None:
        raise SecretStoreUnavailable("unavailable")

    def masked(self, reference: str) -> str:
        raise SecretStoreUnavailable("unavailable")


def test_public_state_degrades_without_crashing_when_secret_backend_is_unavailable():
    store = SecretCredentialStore(UnavailableSecretStore())

    state = store.public_state("xjalgo:external-platform:changlian")

    assert state == {
        "configured": False,
        "masked": "",
        "available": False,
        "error": "SECRET_STORE_UNAVAILABLE",
    }


def test_secret_dependent_get_still_fails_closed_when_backend_is_unavailable():
    store = SecretCredentialStore(UnavailableSecretStore())

    with pytest.raises(SecretStoreUnavailable):
        store.get("xjalgo:external-platform:changlian")


def test_public_state_for_working_store_keeps_masked_identifier_only():
    backend = MemorySecretStore()
    reference = "xjalgo:external-platform:changlian"
    backend.set(reference, json.dumps({
        "access_key_id": "access-key-12345678",
        "access_secret": "do-not-expose-this-secret",
    }))
    store = SecretCredentialStore(backend)

    state = store.public_state(reference)

    assert state["configured"] is True
    assert state["available"] is True
    assert state["error"] == ""
    assert state["masked"].startswith("acc****")
    assert "do-not-expose-this-secret" not in str(state)

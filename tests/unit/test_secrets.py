import pytest

from platform_core.secrets import MemorySecretStore, SecretCredentialStore, secret_ref


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


def test_compound_credentials_reject_non_object_secret():
    backend = MemorySecretStore()
    backend.set("xjalgo:storage-source:bad", "not-json")
    with pytest.raises(RuntimeError, match="credential payload"):
        SecretCredentialStore(backend).get("xjalgo:storage-source:bad")

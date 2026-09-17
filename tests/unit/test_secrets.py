import json

import pytest
from cryptography.fernet import Fernet

from platform_core.secrets import (
    EncryptedFileSecretStore,
    KeyringSecretStore,
    MemorySecretStore,
    SecretCredentialStore,
    SecretStoreUnavailable,
    secret_environment_name,
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
        "backend": "unavailable",
        "writable": False,
        "environment_name": "",
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
    assert state["backend"] == "memory"
    assert state["writable"] is True
    assert "do-not-expose-this-secret" not in str(state)


def test_encrypted_file_secret_store_never_writes_plaintext(tmp_path):
    key = Fernet.generate_key()
    path = tmp_path / "secure" / "secrets.enc.json"
    store = EncryptedFileSecretStore(path, master_key=key)
    reference = "xjalgo:external-platform:changlian"
    payload = json.dumps({"access_key_id": "ak-test", "access_secret": "super-secret"})

    store.set(reference, payload)

    assert store.get(reference) == payload
    disk = path.read_text(encoding="utf-8")
    assert "ak-test" not in disk
    assert "super-secret" not in disk
    assert reference in disk


def test_headless_composite_falls_back_to_encrypted_file(tmp_path):
    key = Fernet.generate_key()
    reference = "xjalgo:external-platform:changlian"
    store = KeyringSecretStore(
        keyring_module=None,
        encrypted_path=tmp_path / "secrets.enc.json",
        master_key=key,
    )
    credentials = SecretCredentialStore(store)

    credentials.set(reference, {
        "access_key_id": "headless-ak",
        "access_secret": "headless-secret",
    })
    state = credentials.public_state(reference)

    assert credentials.get(reference)["access_secret"] == "headless-secret"
    assert state["configured"] is True
    assert state["backend"] == "encrypted_file"
    assert state["writable"] is True
    assert "headless-secret" not in str(state)


def test_changlian_environment_credentials_are_read_only(monkeypatch):
    reference = "xjalgo:external-platform:changlian"
    monkeypatch.setenv("MC_CHANGLIAN_ACCESS_KEY", "env-ak")
    monkeypatch.setenv("MC_CHANGLIAN_ACCESS_SECRET", "env-secret")
    store = KeyringSecretStore(keyring_module=None)
    credentials = SecretCredentialStore(store)

    assert credentials.get(reference) == {
        "access_key_id": "env-ak",
        "access_secret": "env-secret",
    }
    state = credentials.public_state(reference)
    assert state["backend"] == "environment"
    assert state["writable"] is False
    assert state["environment_name"] == "MC_CHANGLIAN_ACCESS_KEY/MC_CHANGLIAN_ACCESS_SECRET"
    with pytest.raises(ValueError, match="只读配置"):
        credentials.set(reference, {"access_key_id": "new", "access_secret": "new-secret"})


def test_generic_environment_secret_name_is_stable():
    assert secret_environment_name("xjalgo:storage-source:oss-a") == "MC_SECRET_XJALGO_STORAGE_SOURCE_OSS_A"


class UnexpectedFailureStore:
    def set(self, reference: str, value: str) -> None:
        raise RuntimeError("unexpected backend failure")

    def get(self, reference: str):
        raise RuntimeError("unexpected backend failure")

    def delete(self, reference: str) -> None:
        raise RuntimeError("unexpected backend failure")

    def masked(self, reference: str) -> str:
        raise RuntimeError("unexpected backend failure")


def test_public_state_never_crashes_on_unexpected_backend_failure():
    state = SecretCredentialStore(UnexpectedFailureStore()).public_state(
        "xjalgo:external-platform:changlian"
    )

    assert state["configured"] is False
    assert state["available"] is False
    assert state["backend"] == "unavailable"
    assert state["error"] == "SECRET_STORE_UNAVAILABLE"


def test_public_state_never_crashes_on_legacy_non_json_credential():
    backend = MemorySecretStore()
    backend.set("xjalgo:external-platform:changlian", "legacy-plain-secret")

    state = SecretCredentialStore(backend).public_state(
        "xjalgo:external-platform:changlian"
    )

    assert state["configured"] is False
    assert state["available"] is False
    assert state["error"] == "SECRET_STORE_UNAVAILABLE"


class FakeDbusFailKeyring:
    class errors:
        class KeyringError(Exception):
            pass

        class PasswordDeleteError(KeyringError):
            pass

    @staticmethod
    def get_password(_service: str, _reference: str):
        raise RuntimeError("Cannot autolaunch D-Bus without X11 $DISPLAY")

    @staticmethod
    def set_password(_service: str, _reference: str, _value: str):
        raise RuntimeError("Cannot autolaunch D-Bus without X11 $DISPLAY")

    @staticmethod
    def delete_password(_service: str, _reference: str):
        raise RuntimeError("Cannot autolaunch D-Bus without X11 $DISPLAY")


def test_keyring_non_keyringerror_dbus_failure_is_normalized():
    reference = "xjalgo:external-platform:changlian"
    credentials = SecretCredentialStore(KeyringSecretStore(keyring_module=FakeDbusFailKeyring))

    state = credentials.public_state(reference)

    assert state["configured"] is False
    assert state["available"] is False
    assert state["backend"] == "unavailable"
    with pytest.raises(SecretStoreUnavailable):
        credentials.get(reference)
    with pytest.raises(SecretStoreUnavailable):
        credentials.set(reference, {"access_key_id": "ak", "access_secret": "secret"})


def test_invalid_headless_master_key_does_not_crash_public_state(tmp_path):
    reference = "xjalgo:external-platform:changlian"
    credentials = SecretCredentialStore(
        KeyringSecretStore(
            keyring_module=None,
            encrypted_path=tmp_path / "secrets.enc.json",
            master_key="not-a-valid-fernet-key",
        )
    )

    state = credentials.public_state(reference)

    assert state["configured"] is False
    assert state["available"] is False
    assert state["backend"] == "unavailable"
    with pytest.raises(SecretStoreUnavailable):
        credentials.get(reference)

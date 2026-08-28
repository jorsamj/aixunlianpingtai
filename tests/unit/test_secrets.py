from platform_core.secrets import MemorySecretStore, secret_ref


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

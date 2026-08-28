import os
from typing import Optional, Protocol


class SecretStore(Protocol):
    def set(self, reference: str, value: str) -> None: ...
    def get(self, reference: str) -> Optional[str]: ...
    def delete(self, reference: str) -> None: ...
    def masked(self, reference: str) -> str: ...


def secret_ref(scope: str, item_id: str) -> str:
    safe_scope = str(scope or "").strip().replace(":", "-")
    safe_id = str(item_id or "").strip().replace(":", "-")
    if not safe_scope or not safe_id:
        raise ValueError("Secret 引用必须包含作用域和配置 ID")
    return f"xjalgo:{safe_scope}:{safe_id}"


def mask_secret(value: Optional[str]) -> str:
    text = str(value or "")
    if not text:
        return ""
    prefix = text[:3] if len(text) > 3 else text[:1]
    suffix = text[-4:] if len(text) > 4 else ""
    return f"{prefix}****{suffix}"


class MemorySecretStore:
    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def set(self, reference: str, value: str) -> None:
        self._values[str(reference)] = str(value)

    def get(self, reference: str) -> Optional[str]:
        if str(reference).startswith("env:"):
            return os.environ.get(str(reference)[4:])
        return self._values.get(str(reference))

    def delete(self, reference: str) -> None:
        self._values.pop(str(reference), None)

    def masked(self, reference: str) -> str:
        return mask_secret(self.get(reference))


class KeyringSecretStore:
    def __init__(self, service_name: str = "畅联云算法训练") -> None:
        try:
            import keyring
        except ImportError as error:
            raise RuntimeError("缺少 keyring，无法安全保存模型 API Key") from error
        self._keyring = keyring
        self._service_name = service_name

    def set(self, reference: str, value: str) -> None:
        if str(reference).startswith("env:"):
            raise ValueError("环境变量 Secret 为只读引用")
        self._keyring.set_password(self._service_name, str(reference), str(value))

    def get(self, reference: str) -> Optional[str]:
        if str(reference).startswith("env:"):
            return os.environ.get(str(reference)[4:])
        return self._keyring.get_password(self._service_name, str(reference))

    def delete(self, reference: str) -> None:
        if str(reference).startswith("env:"):
            return
        try:
            self._keyring.delete_password(self._service_name, str(reference))
        except self._keyring.errors.PasswordDeleteError:
            pass

    def masked(self, reference: str) -> str:
        return mask_secret(self.get(reference))

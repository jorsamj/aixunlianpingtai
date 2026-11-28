import json
import os
import re
from pathlib import Path
from typing import Optional, Protocol

from filelock import FileLock

from .runtime_paths import resolve_data_dir


SECRET_MASTER_KEY_ENV = "MC_SECRET_MASTER_KEY"
SECRET_FILE_ENV = "MC_SECRET_FILE"
EXTERNAL_CHANGLIAN_REF = "xjalgo:external-platform:changlian"


class SecretStore(Protocol):
    def set(self, reference: str, value: str) -> None: ...
    def get(self, reference: str) -> Optional[str]: ...
    def delete(self, reference: str) -> None: ...
    def masked(self, reference: str) -> str: ...


class SecretStoreUnavailable(RuntimeError):
    """Raised when no configured secure Secret backend can be used."""


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


def secret_environment_name(reference: str) -> str:
    suffix = re.sub(r"[^A-Za-z0-9]+", "_", str(reference or "")).strip("_").upper()
    return f"MC_SECRET_{suffix}" if suffix else "MC_SECRET"


def _environment_override(reference: str) -> tuple[Optional[str], str]:
    ref = str(reference or "")
    if ref == EXTERNAL_CHANGLIAN_REF:
        access_key = str(os.environ.get("MC_CHANGLIAN_ACCESS_KEY") or "").strip()
        access_secret = str(os.environ.get("MC_CHANGLIAN_ACCESS_SECRET") or "")
        if access_key and access_secret:
            return (
                json.dumps(
                    {"access_key_id": access_key, "access_secret": access_secret},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "MC_CHANGLIAN_ACCESS_KEY/MC_CHANGLIAN_ACCESS_SECRET",
            )
    env_name = secret_environment_name(ref)
    if env_name in os.environ:
        return os.environ.get(env_name), env_name
    return None, ""


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


class EncryptedFileSecretStore:
    """Headless-safe encrypted Secret storage backed by a Fernet master key.

    The master key must be injected through ``MC_SECRET_MASTER_KEY`` (or passed
    explicitly by tests). The data file stores only encrypted tokens. This is a
    secure fallback for servers that do not expose a SecretService/Keyring
    backend, while keeping page-based credential management available.
    """

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        master_key: str | bytes | None = None,
    ) -> None:
        raw_key = master_key or os.environ.get(SECRET_MASTER_KEY_ENV)
        if not raw_key:
            raise SecretStoreUnavailable(
                f"未配置 {SECRET_MASTER_KEY_ENV}，无法启用 Headless 加密 Secret 存储"
            )
        try:
            from cryptography.fernet import Fernet, InvalidToken
        except ImportError as error:
            raise SecretStoreUnavailable("缺少 cryptography，无法启用加密 Secret 存储") from error
        try:
            key = raw_key if isinstance(raw_key, bytes) else str(raw_key).encode("ascii")
            self._fernet = Fernet(key)
        except Exception as error:
            raise SecretStoreUnavailable(
                f"{SECRET_MASTER_KEY_ENV} 不是有效 Fernet key"
            ) from error
        self._invalid_token = InvalidToken
        configured = str(path or os.environ.get(SECRET_FILE_ENV) or "").strip()
        if configured:
            self.path = Path(configured).expanduser().resolve()
        else:
            self.path = resolve_data_dir() / "secure" / "secrets.enc.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = FileLock(str(self.path) + ".lock", timeout=30)

    def _read(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise SecretStoreUnavailable("加密 Secret 文件无法读取") from error
        if not isinstance(payload, dict) or int(payload.get("schema_version") or 0) != 1:
            raise SecretStoreUnavailable("加密 Secret 文件格式不受支持")
        values = payload.get("values") or {}
        if not isinstance(values, dict):
            raise SecretStoreUnavailable("加密 Secret 文件内容无效")
        return {str(key): str(value) for key, value in values.items()}

    def _write(self, values: dict[str, str]) -> None:
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        body = {"schema_version": 1, "values": dict(values)}
        temporary.write_text(
            json.dumps(body, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        if os.name != "nt":
            os.chmod(temporary, 0o600)
        temporary.replace(self.path)
        if os.name != "nt":
            os.chmod(self.path, 0o600)

    def set(self, reference: str, value: str) -> None:
        with self.lock:
            values = self._read()
            token = self._fernet.encrypt(str(value).encode("utf-8")).decode("ascii")
            values[str(reference)] = token
            self._write(values)

    def get(self, reference: str) -> Optional[str]:
        with self.lock:
            token = self._read().get(str(reference))
        if token is None:
            return None
        try:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except (self._invalid_token, UnicodeError, ValueError) as error:
            raise SecretStoreUnavailable("加密 Secret 无法解密；请检查主密钥是否正确") from error

    def delete(self, reference: str) -> None:
        with self.lock:
            values = self._read()
            if str(reference) not in values:
                return
            values.pop(str(reference), None)
            self._write(values)

    def masked(self, reference: str) -> str:
        return mask_secret(self.get(reference))


_UNSET = object()


class KeyringSecretStore:
    """Secure composite store: environment override -> OS keyring -> encrypted file.

    Environment credentials are read-only and are useful for container/systemd
    injection. Normal desktop hosts use the OS keyring. Headless Linux may set
    ``MC_SECRET_MASTER_KEY`` to keep the existing page-based save flow while the
    persisted file remains encrypted at rest.

    Keyring implementations are third-party OS adapters. On headless Linux they
    may surface D-Bus/GLib/runtime failures that do not inherit KeyringError, so
    every keyring boundary is normalized to SecretStoreUnavailable instead of
    leaking an implementation exception into an HTTP request.
    """

    def __init__(
        self,
        service_name: str = "畅联云算法训练",
        *,
        keyring_module=_UNSET,
        encrypted_path: str | Path | None = None,
        master_key: str | bytes | None = None,
    ) -> None:
        self._keyring_import_error: Optional[Exception] = None
        if keyring_module is _UNSET:
            try:
                import keyring as loaded_keyring
            except Exception as error:
                loaded_keyring = None
                self._keyring_import_error = error
            self._keyring = loaded_keyring
        else:
            self._keyring = keyring_module
        self._service_name = service_name
        self._encrypted: Optional[EncryptedFileSecretStore] = None
        self._encrypted_error: Optional[Exception] = None
        if master_key or os.environ.get(SECRET_MASTER_KEY_ENV):
            try:
                self._encrypted = EncryptedFileSecretStore(
                    encrypted_path,
                    master_key=master_key,
                )
            except Exception as error:
                self._encrypted_error = error

    def _unavailable(self, _error: Optional[Exception] = None) -> SecretStoreUnavailable:
        return SecretStoreUnavailable(
            "系统 Keyring 不可用，且未配置可用的 Headless 加密 Secret 后端；"
            f"请配置 SecretService，或设置有效的 {SECRET_MASTER_KEY_ENV}。"
        )

    def _resolve(self, reference: str) -> tuple[Optional[str], str, bool, str]:
        env_value, env_name = _environment_override(reference)
        if env_value is not None:
            return env_value, "environment", False, env_name

        keyring_available = False
        keyring_error: Optional[Exception] = self._keyring_import_error
        if self._keyring is not None:
            try:
                value = self._keyring.get_password(self._service_name, str(reference))
                keyring_available = True
                if value is not None:
                    return value, "keyring", True, ""
            except Exception as error:
                keyring_error = error

        if self._encrypted is not None:
            value = self._encrypted.get(reference)
            return value, "encrypted_file", True, ""

        if keyring_available:
            return None, "keyring", True, ""
        raise self._unavailable(keyring_error or self._encrypted_error)

    def backend_state(self, reference: str) -> dict[str, object]:
        try:
            _value, backend, writable, env_name = self._resolve(reference)
        except SecretStoreUnavailable:
            return {
                "available": False,
                "backend": "unavailable",
                "writable": False,
                "environment_name": "",
            }
        return {
            "available": True,
            "backend": backend,
            "writable": writable,
            "environment_name": env_name,
        }

    def set(self, reference: str, value: str) -> None:
        env_value, env_name = _environment_override(reference)
        if env_value is not None:
            raise ValueError(f"Secret 由环境变量 {env_name} 管理，为只读配置")
        keyring_error: Optional[Exception] = self._keyring_import_error
        if self._keyring is not None:
            try:
                self._keyring.set_password(self._service_name, str(reference), str(value))
                return
            except Exception as error:
                keyring_error = error
        if self._encrypted is not None:
            self._encrypted.set(reference, value)
            return
        raise self._unavailable(keyring_error or self._encrypted_error)

    def get(self, reference: str) -> Optional[str]:
        value, _backend, _writable, _env_name = self._resolve(reference)
        return value

    def delete(self, reference: str) -> None:
        env_value, _env_name = _environment_override(reference)
        if env_value is not None:
            return
        keyring_deleted = False
        keyring_error: Optional[Exception] = self._keyring_import_error
        if self._keyring is not None:
            try:
                self._keyring.delete_password(self._service_name, str(reference))
                keyring_deleted = True
            except Exception as error:
                keyring_error = error
                errors = getattr(self._keyring, "errors", None)
                password_delete_error = getattr(errors, "PasswordDeleteError", None)
                if password_delete_error is not None and isinstance(error, password_delete_error):
                    keyring_deleted = True
        if self._encrypted is not None:
            self._encrypted.delete(reference)
            return
        if keyring_deleted:
            return
        raise self._unavailable(keyring_error or self._encrypted_error)

    def masked(self, reference: str) -> str:
        return mask_secret(self.get(reference))


class SecretCredentialStore:
    """Stores a credential mapping as one opaque SecretStore value.

    SQLite/JSON configuration only retains the reference. Public callers get
    configuration state and an optional masked identifier, never the secret.
    """

    def __init__(self, backend: SecretStore) -> None:
        self.backend = backend

    def set(self, reference: str, credentials: dict[str, str]) -> None:
        normalized = {
            str(key): str(value)
            for key, value in credentials.items()
            if str(key).strip() and str(value)
        }
        if not normalized:
            raise ValueError("credential payload cannot be empty")
        self.backend.set(
            reference,
            json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        )

    def get(self, reference: str) -> dict[str, str] | None:
        raw = self.backend.get(reference)
        if raw is None:
            return None
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as error:
            raise RuntimeError("credential payload is not valid JSON") from error
        if not isinstance(value, dict) or not all(
            isinstance(key, str) and isinstance(item, str)
            for key, item in value.items()
        ):
            raise RuntimeError("credential payload must be a string object")
        return dict(value)

    def delete(self, reference: str) -> None:
        self.backend.delete(reference)

    def public_state(self, reference: str) -> dict[str, object]:
        try:
            value = self.get(reference)
        except Exception:
            return {
                "configured": False,
                "masked": "",
                "available": False,
                "error": "SECRET_STORE_UNAVAILABLE",
                "backend": "unavailable",
                "writable": False,
                "environment_name": "",
            }
        identifier = ""
        if value:
            identifier = next(
                (
                    value[key]
                    for key in ("access_key_id", "username", "client_id")
                    if value.get(key)
                ),
                "",
            )
        backend_state = {
            "available": True,
            "backend": "memory",
            "writable": True,
            "environment_name": "",
        }
        describe = getattr(self.backend, "backend_state", None)
        if callable(describe):
            try:
                backend_state.update(describe(reference))
            except Exception:
                backend_state.update({
                    "available": False,
                    "backend": "unavailable",
                    "writable": False,
                    "environment_name": "",
                })
        return {
            "configured": bool(value),
            "masked": mask_secret(identifier) if identifier else ("已配置" if value else ""),
            "available": bool(backend_state.get("available", True)),
            "error": "" if backend_state.get("available", True) else "SECRET_STORE_UNAVAILABLE",
            "backend": str(backend_state.get("backend") or "unknown"),
            "writable": bool(backend_state.get("writable", True)),
            "environment_name": str(backend_state.get("environment_name") or ""),
        }
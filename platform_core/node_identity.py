"""Stable runtime-node identity independent from shared application data."""
from __future__ import annotations

import hashlib
import os
import re
import socket
import uuid
from dataclasses import dataclass
from pathlib import Path


_NODE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_NODE_ID_FILE = "node-id"


@dataclass(frozen=True)
class NodeIdentity:
    node_id: str
    hostname: str
    source: str


def _validated_node_id(value: object) -> str:
    node_id = str(value or "").strip()
    if not _NODE_ID_PATTERN.fullmatch(node_id):
        raise ValueError(
            "MC_NODE_ID must be 1-128 characters using letters, digits, '.', '_', ':', or '-'"
        )
    return node_id


def default_node_state_dir() -> Path:
    configured = str(os.environ.get("MC_NODE_STATE_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        base = Path(local) if local else Path.home() / "AppData" / "Local"
        return (base / "ChangLianCloud" / "runtime").resolve()
    state_home = str(os.environ.get("XDG_STATE_HOME") or "").strip()
    base = Path(state_home).expanduser() if state_home else Path.home() / ".local" / "state"
    return (base / "changlian-cloud" / "runtime").resolve()


def _persistent_node_id(state_dir: Path) -> str:
    directory = Path(state_dir).expanduser().resolve()
    identity_file = directory / _NODE_ID_FILE
    try:
        return _validated_node_id(identity_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        pass
    directory.mkdir(parents=True, exist_ok=True)
    generated = f"node-{uuid.uuid4().hex}"
    try:
        with identity_file.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(generated + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        return _validated_node_id(identity_file.read_text(encoding="utf-8"))
    try:
        identity_file.chmod(0o600)
    except OSError:
        pass
    return generated


def _machine_local_node_id() -> str | None:
    machine_value = ""
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
            ) as key:
                machine_value = str(winreg.QueryValueEx(key, "MachineGuid")[0]).strip()
        except (ImportError, OSError, ValueError):
            machine_value = ""
    else:
        for path in (Path("/etc/machine-id"), Path("/var/lib/dbus/machine-id")):
            try:
                machine_value = path.read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if machine_value:
                break
    if not machine_value:
        return None
    digest = hashlib.sha256(f"changlian-cloud:{machine_value}".encode("utf-8")).hexdigest()
    return f"node-{digest[:32]}"


def resolve_node_identity(*, state_dir: str | Path | None = None) -> NodeIdentity:
    """Resolve an operator-supplied ID or a node-local persistent fallback.

    The fallback deliberately does not accept the platform DATA_DIR. Deployments
    sharing an NFS DATA_DIR therefore keep independent identities. Containers
    should set MC_NODE_ID or mount MC_NODE_STATE_DIR when identity must survive
    container replacement.
    """

    hostname = socket.gethostname()
    configured = str(os.environ.get("MC_NODE_ID") or "").strip()
    if configured:
        return NodeIdentity(_validated_node_id(configured), hostname, "environment")
    explicit_state_dir = state_dir is not None or bool(
        str(os.environ.get("MC_NODE_STATE_DIR") or "").strip()
    )
    if not explicit_state_dir:
        machine_local = _machine_local_node_id()
        if machine_local:
            return NodeIdentity(machine_local, hostname, "machine-local")
    try:
        persisted = _persistent_node_id(
            Path(state_dir) if state_dir is not None else default_node_state_dir()
        )
        return NodeIdentity(persisted, hostname, "persistent-local")
    except OSError as error:
        machine_local = _machine_local_node_id()
        if machine_local:
            return NodeIdentity(machine_local, hostname, "machine-local")
        raise OSError(
            "Cannot persist node identity; configure MC_NODE_ID or a writable MC_NODE_STATE_DIR"
        ) from error

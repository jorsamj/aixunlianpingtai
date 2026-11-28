"""Build and verify an offline delivery bundle for one exact platform build.

Why this exists: the platform can already be backed up, upgraded and rolled
back, but an air-gapped install had no artefact that binds *one* code SHA,
VERSION, build id, frontend build and Python dependency set to a file-by-file
digest. Without that binding "offline install" is unverifiable.

Contract:
  * the bundle carries only files (no database, no secrets, no data directory);
  * every payload file is listed in ``MANIFEST.sha256`` (``sha256sum -c`` format)
    and in ``bundle.json`` with size + digest;
  * installing verifies the manifest first, then installs strictly from the
    bundled wheelhouse with ``--no-index`` (never the network);
  * ``verify`` is read-only and fails closed on any missing, extra, resized or
    re-hashed file, on an unusable code identity, and on an incomplete
    wheelhouse.

``verify`` and ``build`` are deliberately separate so CI can build once and any
target host can prove the artefact it received is exactly that build.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOLS_DIR.parent
BUNDLE_SCHEMA = "offline-bundle/1"
MANIFEST_NAME = "MANIFEST.sha256"
BUNDLE_JSON = "bundle.json"

# Payload allowlist: application code and its declared dependency files only.
# A data directory, a database, logs or agent state must never enter a bundle.
APP_PAYLOAD_ENTRIES = (
    "app.py",
    "launcher.py",
    "task_worker.py",
    "train_worker.py",
    "deployment_worker.py",
    "remote_train_server.py",
    "paddle_worker.py",
    "platform_core",
    "tools",
    "optional-dependencies",
    "requirements.txt",
    "requirements-dev.txt",
    "remote_web_requirements.txt",
    "VERSION.txt",
    "AGENTS.md",
)
FRONTEND_PAYLOAD = Path("static") / "vue-app"
FRONTEND_REQUIRED_FILES = ("index.html", "offline-assets.json")

_SECRET_NAME_PATTERNS = (
    re.compile(r"(^|/)\.env($|\.)", re.IGNORECASE),
    re.compile(r"(^|/)secrets?(\.|/|$)", re.IGNORECASE),
    re.compile(r"\.(pem|key|p12|pfx|jks|keystore)$", re.IGNORECASE),
    re.compile(r"(^|/)id_(rsa|dsa|ecdsa|ed25519)($|\.)", re.IGNORECASE),
    re.compile(r"(^|/)\.netrc$", re.IGNORECASE),
)
_FORBIDDEN_NAME_PATTERNS = (
    re.compile(r"\.(sqlite3|sqlite|db|db-shm|db-wal)$", re.IGNORECASE),
    re.compile(r"(^|/)__pycache__(/|$)", re.IGNORECASE),
    re.compile(r"\.pyc$", re.IGNORECASE),
    re.compile(r"(^|/)node_modules(/|$)", re.IGNORECASE),
    re.compile(r"(^|/)\.git(/|$)", re.IGNORECASE),
)
_REQUIREMENT_OPTIONS = (
    "-r", "--requirement", "-c", "--constraint", "-f", "--find-links",
    "-i", "--index-url", "--extra-index-url", "-e", "--editable",
    "--no-index", "--hash", "--only-binary", "--no-binary",
)


class OfflineBundleError(RuntimeError):
    """A refusal with a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = str(code)
        self.message = str(message)
        super().__init__(f"{self.code}: {self.message}")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _posix(relative: Path) -> str:
    return relative.as_posix()


def _iter_payload_files(root: Path):
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise OfflineBundleError(
                "OFFLINE_BUNDLE_SYMLINK", f"payload contains a symlink: {path}"
            )
        if path.is_file():
            yield path


def _assert_safe_payload_name(relative: str) -> None:
    for pattern in _SECRET_NAME_PATTERNS:
        if pattern.search(relative):
            raise OfflineBundleError(
                "OFFLINE_BUNDLE_SECRET_FILE",
                f"refusing to bundle a secret-like file: {relative}",
            )
    for pattern in _FORBIDDEN_NAME_PATTERNS:
        if pattern.search(relative):
            raise OfflineBundleError(
                "OFFLINE_BUNDLE_FORBIDDEN_FILE",
                f"refusing to bundle a runtime/state file: {relative}",
            )


def normalize_requirement_name(line: str) -> str | None:
    """Extract the distribution name from one requirements line."""
    text = str(line or "").strip()
    if not text or text.startswith("#"):
        return None
    if text.startswith(_REQUIREMENT_OPTIONS):
        return None
    if text.startswith(("-", "http://", "https://", "git+", "file:")):
        return None
    name = re.split(r"[<>=!~;\[\s@]", text, maxsplit=1)[0].strip()
    if not name or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
        return None
    return name.lower().replace("_", "-").replace(".", "-")


def required_distributions(paths) -> dict[str, str]:
    """Top-level requirements per file (transitive resolution is not attempted)."""
    found: dict[str, str] = {}
    for path in paths:
        path = Path(path)
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as error:
            raise OfflineBundleError(
                "OFFLINE_BUNDLE_REQUIREMENTS_UNREADABLE",
                f"{path.name}: {type(error).__name__}: {error}",
            ) from error
        for line in lines:
            name = normalize_requirement_name(line)
            if name:
                found.setdefault(name, path.name)
    return found


def wheelhouse_distributions(wheel_dir: Path) -> dict[str, dict]:
    entries: dict[str, dict] = {}
    if not wheel_dir.is_dir():
        return entries
    for path in sorted(wheel_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() != ".whl":
            continue
        name = path.name.split("-", 1)[0].lower().replace("_", "-").replace(".", "-")
        entries.setdefault(name, {
            "file": path.name,
            "bytes": path.stat().st_size,
            "sha256": _sha256_file(path),
        })
    return entries


def resolve_code_sha(repo: Path, explicit: str | None) -> str:
    value = str(explicit or "").strip().lower()
    if value:
        if not re.fullmatch(r"[0-9a-f]{40}", value):
            raise OfflineBundleError(
                "OFFLINE_BUNDLE_CODE_SHA_INVALID",
                "code SHA must be the exact 40-hex commit",
            )
        return value
    git_dir = Path(repo) / ".git"
    if not git_dir.exists():
        raise OfflineBundleError(
            "OFFLINE_BUNDLE_CODE_SHA_UNRESOLVED",
            "no --code-sha given and the source tree is not a git worktree",
        )
    import subprocess

    completed = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=False,
    )
    sha = completed.stdout.strip().lower()
    if completed.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise OfflineBundleError(
            "OFFLINE_BUNDLE_CODE_SHA_UNRESOLVED", "cannot resolve the worktree HEAD"
        )
    return sha


def _upgrade_identity(repo: Path, code_sha: str) -> dict:
    """Reuse the production upgrade identity instead of a second implementation."""
    sys.path.insert(0, str(TOOLS_DIR))
    try:
        import production_upgrade as upgrade  # noqa: PLC0415 - deliberate lazy import
    finally:
        sys.path.pop(0)
    fingerprint = upgrade.resolve_python_dependency_fingerprint(repo, code_sha=code_sha)
    return {
        "version": upgrade.read_application_version(repo),
        "build_id": upgrade.resolve_build_identity(repo),
        "python_dependencies": fingerprint,
    }


def _frontend_identity(dist: Path) -> dict:
    """Digest of the exact frontend asset set shipped in the bundle."""
    if not dist.is_dir():
        raise OfflineBundleError(
            "OFFLINE_BUNDLE_FRONTEND_MISSING",
            f"frontend assets are not built at {dist}",
        )
    missing = [name for name in FRONTEND_REQUIRED_FILES if not (dist / name).is_file()]
    if missing:
        raise OfflineBundleError(
            "OFFLINE_BUNDLE_FRONTEND_INCOMPLETE",
            "frontend build is missing " + ", ".join(missing),
        )
    digest = hashlib.sha256()
    count = 0
    total = 0
    for path in _iter_payload_files(dist):
        relative = _posix(path.relative_to(dist))
        size = path.stat().st_size
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(size).encode("ascii"))
        digest.update(b"\0")
        digest.update(_sha256_file(path).encode("ascii"))
        digest.update(b"\0")
        count += 1
        total += size
    return {
        "path": "frontend",
        "build_id": digest.hexdigest()[:32],
        "files": count,
        "bytes": total,
        "required_files": list(FRONTEND_REQUIRED_FILES),
        "verified_against": "bundled asset bytes",
    }


def _copy_tree(source: Path, destination: Path) -> int:
    count = 0
    for path in _iter_payload_files(source):
        relative = _posix(path.relative_to(source))
        _assert_safe_payload_name(relative)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        count += 1
    return count


def _write_manifest(bundle_dir: Path, files: dict[str, dict]) -> str:
    lines = [
        f"{entry['sha256']}  {relative}"
        for relative, entry in sorted(files.items())
    ]
    payload = "\n".join(lines) + "\n"
    # Write exact bytes: text-mode newline translation would change the digest
    # that ``sha256sum -c`` and the bundle descriptor both depend on.
    data = payload.encode("utf-8")
    (bundle_dir / MANIFEST_NAME).write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def _describe_files(bundle_dir: Path, relative_paths) -> dict[str, dict]:
    described: dict[str, dict] = {}
    for relative in sorted(relative_paths):
        path = bundle_dir / relative
        described[relative] = {
            "bytes": path.stat().st_size,
            "sha256": _sha256_file(path),
        }
    return described


def build_bundle(
    repo: Path,
    output_dir: Path,
    *,
    wheelhouse: Path,
    frontend_dist: Path,
    code_sha: str | None = None,
    install_path: str = "/opt/changlian",
    service_name: str = "changlian",
    python_executable: str = "python3",
) -> dict:
    """Assemble a verified offline bundle; never touches the network."""
    repo = Path(repo).resolve()
    output_dir = Path(output_dir).resolve()
    wheelhouse = Path(wheelhouse).resolve()
    frontend_dist = Path(frontend_dist).resolve()

    sha = resolve_code_sha(repo, code_sha)
    identity = _upgrade_identity(repo, sha)
    if identity["version"] in {"", "unavailable", None}:
        raise OfflineBundleError(
            "OFFLINE_BUNDLE_VERSION_UNRESOLVED", "VERSION.txt could not be read"
        )
    installed_wheels = wheelhouse_distributions(wheelhouse)
    required = required_distributions(
        repo / name for name in (
            "requirements.txt", "requirements-dev.txt", "remote_web_requirements.txt",
        ) if (repo / name).is_file()
    )
    missing = sorted(name for name in required if name not in installed_wheels)
    if missing:
        raise OfflineBundleError(
            "OFFLINE_WHEELHOUSE_INCOMPLETE",
            "no wheel for: " + ", ".join(missing),
        )
    if not installed_wheels:
        raise OfflineBundleError(
            "OFFLINE_WHEELHOUSE_EMPTY", f"no .whl files in {wheelhouse}"
        )

    if output_dir.exists():
        raise OfflineBundleError(
            "OFFLINE_BUNDLE_OUTPUT_EXISTS",
            f"{output_dir} already exists; refusing to overwrite an artefact",
        )
    output_dir.mkdir(parents=True)

    copied: list[str] = []
    app_dir = output_dir / "app"
    app_dir.mkdir()
    for entry in APP_PAYLOAD_ENTRIES:
        source = repo / entry
        if not source.exists():
            continue
        if source.is_dir():
            count = _copy_tree(source, app_dir / entry)
            if count:
                copied.append(entry + "/")
        else:
            _assert_safe_payload_name(entry)
            target = app_dir / entry
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied.append(entry)

    wheel_dir = output_dir / "wheelhouse"
    wheel_dir.mkdir()
    for path in sorted(wheelhouse.iterdir()):
        if path.is_file() and path.suffix.lower() == ".whl":
            shutil.copy2(path, wheel_dir / path.name)

    frontend_identity = _frontend_identity(frontend_dist)
    frontend_target = output_dir / "frontend"
    frontend_target.mkdir()
    _copy_tree(frontend_dist, frontend_target)

    deploy_dir = output_dir / "deploy"
    deploy_dir.mkdir()
    (deploy_dir / f"{service_name}.service").write_text(
        _systemd_unit(service_name, install_path, python_executable), encoding="utf-8"
    )
    (deploy_dir / f"{service_name}.env.example").write_text(
        _env_template(service_name, install_path), encoding="utf-8"
    )

    for script, name in ((_INSTALL_SCRIPT, "install_offline.sh"), (_HEALTHCHECK, "healthcheck.py")):
        target = output_dir / name
        target.write_text(script, encoding="utf-8")
        if name.endswith(".sh"):
            os.chmod(target, 0o755)

    payload_files = [
        _posix(path.relative_to(output_dir))
        for path in _iter_payload_files(output_dir)
    ]
    files = _describe_files(output_dir, payload_files)
    manifest_digest = _write_manifest(output_dir, files)

    wheels = sorted(
        ({"file": path.name, "bytes": path.stat().st_size, "sha256": _sha256_file(path)}
         for path in wheel_dir.iterdir() if path.is_file()),
        key=lambda item: item["file"],
    )
    bundle = {
        "schema": BUNDLE_SCHEMA,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "code_sha": sha,
        "version": identity["version"],
        "build_id": identity["build_id"],
        "python_dependencies": identity["python_dependencies"],
        "frontend": frontend_identity,
        "install_path": install_path,
        "service_name": service_name,
        "python_executable": python_executable,
        "payload_entries": copied,
        "wheels": wheels,
        "wheel_count": len(wheels),
        "required_distributions": required,
        "wheelhouse_status": "complete_for_declared_top_level_requirements",
        "transitive_resolution": "not_verified",
        "files": files,
        "file_count": len(files),
        "total_bytes": sum(entry["bytes"] for entry in files.values()),
        "manifest_digest": manifest_digest,
        "network_required": False,
        "offline_install_flags": ["--no-index", "--find-links", "--no-cache-dir"],
        "contains_database": False,
        "contains_secrets": False,
        "write_silence": "unverified",
        "production_migration_executed": False,
        "schema_version_probe": "not_verified_no_database_bundled",
    }
    (output_dir / BUNDLE_JSON).write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return bundle


def verify_bundle(bundle_dir: Path, *, require_complete_wheels: bool = True) -> dict:
    """Read-only integrity verification of a received bundle."""
    bundle_dir = Path(bundle_dir).resolve()
    problems: list[dict] = []

    def problem(code: str, detail: str) -> None:
        problems.append({"code": code, "detail": detail})

    descriptor_path = bundle_dir / BUNDLE_JSON
    if not descriptor_path.is_file():
        raise OfflineBundleError(
            "OFFLINE_BUNDLE_INCOMPLETE", f"{BUNDLE_JSON} is missing"
        )
    try:
        bundle = json.loads(descriptor_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise OfflineBundleError(
            "OFFLINE_BUNDLE_DESCRIPTOR_INVALID", f"{type(error).__name__}: {error}"
        ) from error
    if not isinstance(bundle, dict) or bundle.get("schema") != BUNDLE_SCHEMA:
        raise OfflineBundleError(
            "OFFLINE_BUNDLE_DESCRIPTOR_INVALID", "unsupported bundle schema"
        )

    code_sha = str(bundle.get("code_sha") or "")
    if not re.fullmatch(r"[0-9a-f]{40}", code_sha):
        problem("OFFLINE_BUNDLE_CODE_SHA_INVALID", f"code_sha={code_sha!r}")
    if str(bundle.get("version") or "") in {"", "unavailable"}:
        problem("OFFLINE_BUNDLE_VERSION_UNRESOLVED", "version is missing")
    if str(bundle.get("build_id") or "") in {"", "unavailable"}:
        problem("OFFLINE_BUNDLE_BUILD_ID_UNRESOLVED", "build id is missing")

    declared = bundle.get("files")
    if not isinstance(declared, dict) or not declared:
        raise OfflineBundleError(
            "OFFLINE_BUNDLE_DESCRIPTOR_INVALID", "file list is missing"
        )

    for relative, entry in sorted(declared.items()):
        _assert_safe_payload_name(relative)
        path = bundle_dir / relative
        if not path.is_file():
            problem("OFFLINE_MANIFEST_MISSING_FILE", relative)
            continue
        size = path.stat().st_size
        if isinstance(entry, dict) and entry.get("bytes") not in (None, size):
            problem(
                "OFFLINE_MANIFEST_SIZE_MISMATCH",
                f"{relative}: expected {entry.get('bytes')} got {size}",
            )
        if isinstance(entry, dict) and entry.get("sha256"):
            if _sha256_file(path) != entry["sha256"]:
                problem("OFFLINE_MANIFEST_HASH_MISMATCH", relative)

    present = {
        _posix(path.relative_to(bundle_dir))
        for path in _iter_payload_files(bundle_dir)
        if _posix(path.relative_to(bundle_dir)) not in {MANIFEST_NAME, BUNDLE_JSON}
    }
    for unexpected in sorted(present - set(declared)):
        problem("OFFLINE_MANIFEST_UNEXPECTED_FILE", unexpected)

    manifest_path = bundle_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        problem("OFFLINE_BUNDLE_INCOMPLETE", f"{MANIFEST_NAME} is missing")
    else:
        manifest_bytes = manifest_path.read_bytes()
        digest = hashlib.sha256(manifest_bytes).hexdigest()
        if bundle.get("manifest_digest") and digest != bundle["manifest_digest"]:
            problem("OFFLINE_MANIFEST_HASH_MISMATCH", MANIFEST_NAME)
        listed = {
            line.split("  ", 1)[1].strip()
            for line in manifest_bytes.decode("utf-8", "replace").splitlines()
            if "  " in line
        }
        for missing_listing in sorted(set(declared) - listed):
            problem("OFFLINE_MANIFEST_UNLISTED_FILE", missing_listing)

    frontend_dir = bundle_dir / "frontend"
    for name in FRONTEND_REQUIRED_FILES:
        if not (frontend_dir / name).is_file():
            problem("OFFLINE_BUNDLE_FRONTEND_INCOMPLETE", f"frontend/{name}")

    if not (bundle_dir / "install_offline.sh").is_file():
        problem("OFFLINE_BUNDLE_INCOMPLETE", "install_offline.sh is missing")
    if not (bundle_dir / "healthcheck.py").is_file():
        problem("OFFLINE_BUNDLE_INCOMPLETE", "healthcheck.py is missing")

    wheel_dir = bundle_dir / "wheelhouse"
    wheels = wheelhouse_distributions(wheel_dir)
    if require_complete_wheels:
        required = bundle.get("required_distributions") or {}
        missing = sorted(name for name in required if name not in wheels)
        if missing:
            problem(
                "OFFLINE_WHEELHOUSE_INCOMPLETE", "no wheel for: " + ", ".join(missing)
            )
        if not wheels:
            problem("OFFLINE_WHEELHOUSE_EMPTY", "wheelhouse contains no wheels")
    declared_wheels = {
        str(item.get("file")): item.get("sha256")
        for item in bundle.get("wheels") or [] if isinstance(item, dict)
    }
    for name, digest in sorted(declared_wheels.items()):
        path = wheel_dir / name
        if not path.is_file():
            problem("OFFLINE_WHEELHOUSE_MISSING_FILE", name)
        elif digest and _sha256_file(path) != digest:
            problem("OFFLINE_WHEELHOUSE_HASH_MISMATCH", name)
    for extra in sorted(set(wheels) - {
        name.split("-", 1)[0].lower().replace("_", "-").replace(".", "-")
        for name in declared_wheels
    }):
        problem("OFFLINE_WHEELHOUSE_UNEXPECTED_DISTRIBUTION", extra)

    return {
        "schema": BUNDLE_SCHEMA,
        "ok": not problems,
        "code_sha": code_sha,
        "version": bundle.get("version"),
        "build_id": bundle.get("build_id"),
        "files": len(declared),
        "wheels": len(wheels),
        "problems": problems,
        "network_required": False,
        "write_silence": "unverified",
    }


def _systemd_unit(service_name: str, install_path: str, python_executable: str) -> str:
    return f"""[Unit]
Description=ChangLian algorithm training platform ({service_name})
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory={install_path}
EnvironmentFile=-{install_path}/.env
ExecStart={install_path}/.venv/bin/python -m uvicorn app:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=5
# The control plane must keep its data directory writable but never inside the
# code tree that an upgrade replaces.
ReadWritePaths={install_path}/data

[Install]
WantedBy=multi-user.target
"""


def _env_template(service_name: str, install_path: str) -> str:
    return f"""# ChangLian offline deployment environment template.
# Copy to {install_path}/.env and fill in real values on the target host.
# Never commit the filled file: it holds credentials.
MC_DATA_DIR={install_path}/data
MC_BUILD_REVISION=
# Local login bootstrap (change on first deploy).
CHANGLIAN_LOCAL_PASSWORD=
"""


_INSTALL_SCRIPT = r'''#!/bin/sh
# Offline installer for a verified ChangLian bundle.
#
# Invariants:
#   * never touches the network (pip runs with --no-index against the bundled wheelhouse);
#   * verifies MANIFEST.sha256 before installing anything;
#   * refuses to write into a prefix that already holds a non-bundle install;
#   * every failure prints a stable OFFLINE_* code on stderr and exits non-zero.
set -eu

PREFIX="/opt/changlian"
DATA_DIR=""
SERVICE=""
START="no"
BUNDLE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

usage() {
    cat <<'USAGE'
Usage: install_offline.sh [--prefix DIR] [--data-dir DIR] [--service NAME] [--start]

  --prefix DIR    install directory (default /opt/changlian)
  --data-dir DIR  platform data directory (default <prefix>/data)
  --service NAME  systemd unit name to install (skip with --no-service)
  --start         start the service after a successful health check
USAGE
}

fail() {
    printf 'OFFLINE_INSTALL_FAILED: %s: %s\n' "$1" "$2" >&2
    exit 1
}

while [ $# -gt 0 ]; do
    case "$1" in
        --prefix) [ $# -ge 2 ] || fail "OFFLINE_INSTALL_ARGUMENT" "--prefix needs a value"; PREFIX="$2"; shift 2 ;;
        --data-dir) [ $# -ge 2 ] || fail "OFFLINE_INSTALL_ARGUMENT" "--data-dir needs a value"; DATA_DIR="$2"; shift 2 ;;
        --service) [ $# -ge 2 ] || fail "OFFLINE_INSTALL_ARGUMENT" "--service needs a value"; SERVICE="$2"; shift 2 ;;
        --start) START="yes"; shift ;;
        -h|--help) usage; exit 0 ;;
        *) fail "OFFLINE_INSTALL_ARGUMENT" "unknown argument $1" ;;
    esac
done

[ -n "$DATA_DIR" ] || DATA_DIR="$PREFIX/data"

case "$PREFIX" in
    /|""|.) fail "OFFLINE_INSTALL_PREFIX" "refusing to install into '$PREFIX'" ;;
esac
[ "$PREFIX" != "/usr" ] || fail "OFFLINE_INSTALL_PREFIX" "refusing to install into /usr"

# 1. Integrity first: nothing is copied before the manifest proves the bundle.
[ -f "$BUNDLE_DIR/MANIFEST.sha256" ] || fail "OFFLINE_BUNDLE_INCOMPLETE" "MANIFEST.sha256 missing"
command -v sha256sum >/dev/null 2>&1 || fail "OFFLINE_TOOL_MISSING" "sha256sum not available"
( cd "$BUNDLE_DIR" && sha256sum -c MANIFEST.sha256 --quiet ) \
    || fail "OFFLINE_MANIFEST_MISMATCH" "bundle integrity verification failed"

# 2. Refuse to adopt a directory that holds something else.
if [ -e "$PREFIX" ] && [ ! -f "$PREFIX/.offline-bundle-install" ] && [ -n "$(ls -A "$PREFIX" 2>/dev/null)" ]; then
    fail "OFFLINE_INSTALL_PREFIX_NOT_EMPTY" "$PREFIX exists and was not created by an offline bundle"
fi

command -v python3 >/dev/null 2>&1 || fail "OFFLINE_PYTHON_MISSING" "python3 not available"
python3 -c 'import venv, sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
    || fail "OFFLINE_PYTHON_UNSUPPORTED" "python3 >= 3.10 with venv is required"

mkdir -p "$PREFIX" "$DATA_DIR"

# 3. Copy the payload (never the data directory).
rm -rf "$PREFIX/app.previous"
[ -d "$PREFIX/app" ] && mv "$PREFIX/app" "$PREFIX/app.previous"
cp -a "$BUNDLE_DIR/app" "$PREFIX/app"
cp -a "$BUNDLE_DIR/frontend" "$PREFIX/frontend"
cp -a "$BUNDLE_DIR/healthcheck.py" "$PREFIX/healthcheck.py"
cp -a "$BUNDLE_DIR/bundle.json" "$PREFIX/bundle.json"
[ -d "$BUNDLE_DIR/deploy" ] && cp -a "$BUNDLE_DIR/deploy" "$PREFIX/deploy"

# 4. Virtualenv + dependency install, strictly offline.
if [ ! -x "$PREFIX/.venv/bin/python" ]; then
    python3 -m venv "$PREFIX/.venv" || fail "OFFLINE_VENV_FAILED" "cannot create virtualenv"
fi
PIP_NO_INDEX=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    "$PREFIX/.venv/bin/python" -m pip install \
        --no-index --find-links "$BUNDLE_DIR/wheelhouse" --no-cache-dir \
        -r "$PREFIX/app/requirements.txt" \
    || fail "OFFLINE_PIP_INSTALL_FAILED" "wheelhouse install failed (offline only)"

# 5. Health check proves the install, not just the exit code.
( cd "$PREFIX/app" && "$PREFIX/.venv/bin/python" "$PREFIX/healthcheck.py" --prefix "$PREFIX" >/dev/null ) \
    || fail "OFFLINE_HEALTHCHECK_FAILED" "post-install health check failed"

printf '%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ) offline bundle install" > "$PREFIX/.offline-bundle-install"

if [ -n "$SERVICE" ] && [ -d "$PREFIX/deploy" ] && command -v systemctl >/dev/null 2>&1; then
    UNIT="/etc/systemd/system/$SERVICE.service"
    cp "$PREFIX/deploy/$SERVICE.service" "$UNIT" \
        || fail "OFFLINE_SYSTEMD_INSTALL_FAILED" "cannot write $UNIT"
    systemctl daemon-reload || fail "OFFLINE_SYSTEMD_INSTALL_FAILED" "daemon-reload failed"
    if [ "$START" = "yes" ]; then
        systemctl enable --now "$SERVICE" || fail "OFFLINE_SYSTEMD_START_FAILED" "service start failed"
    fi
fi

printf 'OFFLINE_INSTALL_OK prefix=%s data=%s\n' "$PREFIX" "$DATA_DIR"
'''


_HEALTHCHECK = r'''#!/usr/bin/env python3
"""Post-install health check for an offline bundle (read-only, no network)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def check(prefix: Path) -> dict:
    problems: list[str] = []
    app = prefix / "app"
    if not app.is_dir():
        problems.append("app directory is missing")
    version_file = app / "VERSION.txt"
    version = ""
    if version_file.is_file():
        version = version_file.read_text(encoding="utf-8").strip()
    else:
        problems.append("VERSION.txt is missing")
    for relative in ("index.html", "offline-assets.json"):
        if not (prefix / "frontend" / relative).is_file():
            problems.append(f"frontend/{relative} is missing")
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
        import sqlite3  # noqa: F401
    except Exception as error:  # pragma: no cover - install check
        problems.append(f"runtime dependency import failed: {type(error).__name__}: {error}")
    return {"ok": not problems, "version": version, "problems": problems}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", required=True)
    args = parser.parse_args()
    result = check(Path(args.prefix).resolve())
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="assemble a bundle from a source tree")
    build.add_argument("--repo", default=str(REPO_ROOT))
    build.add_argument("--output", required=True)
    build.add_argument("--wheelhouse", required=True)
    build.add_argument("--frontend-dist", default=str(REPO_ROOT / FRONTEND_PAYLOAD))
    build.add_argument("--code-sha", default=None)
    build.add_argument("--install-path", default="/opt/changlian")
    build.add_argument("--service-name", default="changlian")

    verify = sub.add_parser("verify", help="verify a received bundle (read-only)")
    verify.add_argument("--bundle", required=True)
    verify.add_argument("--allow-incomplete-wheelhouse", action="store_true")

    args = parser.parse_args()
    try:
        if args.command == "build":
            result = build_bundle(
                Path(args.repo), Path(args.output),
                wheelhouse=Path(args.wheelhouse),
                frontend_dist=Path(args.frontend_dist),
                code_sha=args.code_sha,
                install_path=args.install_path,
                service_name=args.service_name,
            )
        else:
            result = verify_bundle(
                Path(args.bundle),
                require_complete_wheels=not args.allow_incomplete_wheelhouse,
            )
    except OfflineBundleError as error:
        print(json.dumps({"ok": False, "code": error.code, "message": error.message},
                         ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if args.command == "verify" and not result.get("ok"):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

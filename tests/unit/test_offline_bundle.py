"""Offline delivery bundle: identity binding, integrity and fail-closed refusals.

These tests use a synthetic source tree and a synthetic wheelhouse so they are
hermetic: no network, no real dependencies, no production data.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import offline_bundle as bundle  # noqa: E402

CODE_SHA = "a" * 40


def _make_repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "VERSION.txt").write_text("42.24.592\n", encoding="utf-8")
    (root / "app.py").write_text("print('app')\n", encoding="utf-8")
    (root / "requirements.txt").write_text(
        "fastapi>=0.115\nuvicorn[standard]==0.30\n# comment\n-r other.txt\n",
        encoding="utf-8",
    )
    platform = root / "platform_core"
    platform.mkdir()
    (platform / "__init__.py").write_text("", encoding="utf-8")
    (platform / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    return root


def _make_wheelhouse(root: Path, names=("fastapi", "uvicorn")) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for name in names:
        (root / f"{name}-1.0.0-py3-none-any.whl").write_bytes(b"wheel:" + name.encode())
    return root


def _make_frontend(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (root / "offline-assets.json").write_text("[]", encoding="utf-8")
    assets = root / "assets"
    assets.mkdir()
    (assets / "app.js").write_text("console.log(1)", encoding="utf-8")
    return root


def _build(tmp_path: Path, **overrides) -> tuple[Path, dict]:
    repo = _make_repo(tmp_path / "repo")
    wheelhouse = _make_wheelhouse(tmp_path / "wheels")
    frontend = _make_frontend(tmp_path / "frontend-dist")
    output = tmp_path / "bundle"
    kwargs = dict(
        wheelhouse=wheelhouse, frontend_dist=frontend, code_sha=CODE_SHA,
    )
    kwargs.update(overrides)
    result = bundle.build_bundle(repo, output, **kwargs)
    return output, result


def test_bundle_binds_code_sha_version_build_and_every_file(tmp_path: Path):
    output, result = _build(tmp_path)

    assert result["code_sha"] == CODE_SHA
    assert result["version"] == "42.24.592"
    assert result["build_id"] and result["build_id"] != "unavailable"
    assert result["manifest_digest"]
    assert result["network_required"] is False
    assert result["contains_database"] is False
    assert result["contains_secrets"] is False
    assert result["write_silence"] == "unverified"
    assert result["transitive_resolution"] == "not_verified"

    descriptor = json.loads((output / bundle.BUNDLE_JSON).read_text(encoding="utf-8"))
    manifest_lines = (output / bundle.MANIFEST_NAME).read_text(encoding="utf-8").splitlines()
    listed = {line.split("  ", 1)[1] for line in manifest_lines}
    assert set(descriptor["files"]) == listed
    assert "app/app.py" in listed
    assert "frontend/index.html" in listed
    assert "wheelhouse/fastapi-1.0.0-py3-none-any.whl" in listed
    assert "install_offline.sh" in listed

    verdict = bundle.verify_bundle(output)
    assert verdict["ok"] is True, verdict["problems"]


def test_verify_detects_a_tampered_payload_byte(tmp_path: Path):
    output, _ = _build(tmp_path)
    target = output / "app" / "platform_core" / "module.py"
    target.write_text("VALUE = 2\n", encoding="utf-8")

    verdict = bundle.verify_bundle(output)

    assert verdict["ok"] is False
    codes = {problem["code"] for problem in verdict["problems"]}
    assert "OFFLINE_MANIFEST_HASH_MISMATCH" in codes


def test_verify_detects_a_resized_file_and_an_unexpected_file(tmp_path: Path):
    output, _ = _build(tmp_path)
    (output / "app" / "app.py").write_text("print('tampered')\n", encoding="utf-8")
    (output / "app" / "injected.py").write_text("x = 1\n", encoding="utf-8")

    verdict = bundle.verify_bundle(output)

    codes = {problem["code"] for problem in verdict["problems"]}
    assert verdict["ok"] is False
    assert "OFFLINE_MANIFEST_SIZE_MISMATCH" in codes or (
        "OFFLINE_MANIFEST_HASH_MISMATCH" in codes
    )
    assert "OFFLINE_MANIFEST_UNEXPECTED_FILE" in codes


def test_build_refuses_an_incomplete_wheelhouse(tmp_path: Path):
    repo = _make_repo(tmp_path / "repo")
    wheelhouse = _make_wheelhouse(tmp_path / "wheels", names=("fastapi",))
    frontend = _make_frontend(tmp_path / "frontend-dist")

    with pytest.raises(bundle.OfflineBundleError) as excinfo:
        bundle.build_bundle(
            repo, tmp_path / "bundle",
            wheelhouse=wheelhouse, frontend_dist=frontend, code_sha=CODE_SHA,
        )

    assert excinfo.value.code == "OFFLINE_WHEELHOUSE_INCOMPLETE"
    assert "uvicorn" in excinfo.value.message


def test_build_refuses_a_missing_frontend_build(tmp_path: Path):
    repo = _make_repo(tmp_path / "repo")
    wheelhouse = _make_wheelhouse(tmp_path / "wheels")

    with pytest.raises(bundle.OfflineBundleError) as excinfo:
        bundle.build_bundle(
            repo, tmp_path / "bundle",
            wheelhouse=wheelhouse, frontend_dist=tmp_path / "absent", code_sha=CODE_SHA,
        )

    assert excinfo.value.code == "OFFLINE_BUNDLE_FRONTEND_MISSING"


def test_build_refuses_a_secret_file_in_the_payload(tmp_path: Path):
    repo = _make_repo(tmp_path / "repo")
    (repo / "platform_core" / ".env.production").write_text("TOKEN=secret\n", encoding="utf-8")
    wheelhouse = _make_wheelhouse(tmp_path / "wheels")
    frontend = _make_frontend(tmp_path / "frontend-dist")

    with pytest.raises(bundle.OfflineBundleError) as excinfo:
        bundle.build_bundle(
            repo, tmp_path / "bundle",
            wheelhouse=wheelhouse, frontend_dist=frontend, code_sha=CODE_SHA,
        )

    assert excinfo.value.code == "OFFLINE_BUNDLE_SECRET_FILE"


def test_build_refuses_a_runtime_database_in_the_payload(tmp_path: Path):
    repo = _make_repo(tmp_path / "repo")
    (repo / "platform_core" / "tasks.sqlite3").write_bytes(b"SQLite format 3\0")
    wheelhouse = _make_wheelhouse(tmp_path / "wheels")
    frontend = _make_frontend(tmp_path / "frontend-dist")

    with pytest.raises(bundle.OfflineBundleError) as excinfo:
        bundle.build_bundle(
            repo, tmp_path / "bundle",
            wheelhouse=wheelhouse, frontend_dist=frontend, code_sha=CODE_SHA,
        )

    assert excinfo.value.code == "OFFLINE_BUNDLE_FORBIDDEN_FILE"


def test_build_refuses_an_ambiguous_code_identity(tmp_path: Path):
    repo = _make_repo(tmp_path / "repo")
    wheelhouse = _make_wheelhouse(tmp_path / "wheels")
    frontend = _make_frontend(tmp_path / "frontend-dist")

    with pytest.raises(bundle.OfflineBundleError) as excinfo:
        bundle.build_bundle(
            repo, tmp_path / "bundle",
            wheelhouse=wheelhouse, frontend_dist=frontend, code_sha="0ca9486",
        )

    assert excinfo.value.code == "OFFLINE_BUNDLE_CODE_SHA_INVALID"


def test_build_refuses_to_overwrite_an_existing_artifact(tmp_path: Path):
    output, _ = _build(tmp_path)
    repo = tmp_path / "repo"
    wheelhouse = tmp_path / "wheels"
    frontend = tmp_path / "frontend-dist"

    with pytest.raises(bundle.OfflineBundleError) as excinfo:
        bundle.build_bundle(
            repo, output,
            wheelhouse=wheelhouse, frontend_dist=frontend, code_sha=CODE_SHA,
        )

    assert excinfo.value.code == "OFFLINE_BUNDLE_OUTPUT_EXISTS"


def test_installer_is_offline_only_and_verifies_before_writing(tmp_path: Path):
    output, _ = _build(tmp_path)
    script = (output / "install_offline.sh").read_text(encoding="utf-8")

    # Never reachable through a network install path.
    assert "--no-index" in script
    assert "PIP_NO_INDEX=1" in script
    assert "pip install" in script
    # Integrity is proven before anything is copied.
    integrity = script.index("sha256sum -c MANIFEST.sha256")
    copy_payload = script.index('cp -a "$BUNDLE_DIR/app"')
    assert integrity < copy_payload
    # Destructive guards.
    assert "OFFLINE_INSTALL_PREFIX_NOT_EMPTY" in script
    assert "OFFLINE_MANIFEST_MISMATCH" in script
    assert "OFFLINE_HEALTHCHECK_FAILED" in script
    # No remote code or package fetch.
    for forbidden in ("curl ", "wget ", "pip download", "apt-get install"):
        assert forbidden not in script


def test_installer_script_is_posix_shell_valid():
    """Syntax-verify the shipped installer where a POSIX shell is available."""
    shell = shutil.which("sh")
    if not shell:
        pytest.skip("no POSIX sh on this host; the Linux CI job verifies the syntax")
    completed = subprocess.run(
        [shell, "-n", "-"], input=bundle._INSTALL_SCRIPT,
        capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_requirements_parsing_ignores_options_and_extras():
    assert bundle.normalize_requirement_name("fastapi>=0.115") == "fastapi"
    assert bundle.normalize_requirement_name("uvicorn[standard]==0.30") == "uvicorn"
    assert bundle.normalize_requirement_name("Pillow ; python_version>'3.9'") == "pillow"
    assert bundle.normalize_requirement_name("python_multipart") == "python-multipart"
    assert bundle.normalize_requirement_name("-r other.txt") is None
    assert bundle.normalize_requirement_name("--index-url https://x") is None
    assert bundle.normalize_requirement_name("git+https://example/x.git") is None
    assert bundle.normalize_requirement_name("# comment") is None
    assert bundle.normalize_requirement_name("") is None

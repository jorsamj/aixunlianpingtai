from __future__ import annotations

from dataclasses import asdict
import errno
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
from types import SimpleNamespace
import warnings
import zipfile

import pytest

import platform_core.storage.zip_import as zip_import
from platform_core.storage.zip_import import (
    ActualSizeExceeded,
    ArchiveLimitExceeded,
    ExtractionCancelled,
    ExtractionProgress,
    InsufficientDiskSpace,
    MemberRecord,
    ServerZipImportError,
    TargetDirectoryExists,
    UnsafeArchive,
    extract_server_zip,
    read_limits,
    required_disk_bytes,
    resolve_server_zip,
    safe_member_path,
)


TASK_ID = "task-123"
PREFIX = "datasets/new"
CHUNK = 1024 * 1024


@pytest.fixture(autouse=True)
def bounded_test_limits(monkeypatch):
    for suffix, value in {
        "MAX_MEMBERS": "1000",
        "MAX_SINGLE_BYTES": str(32 * CHUNK),
        "MAX_TOTAL_BYTES": str(64 * CHUNK),
        "MAX_RATIO": "1000",
        "DISK_MARGIN_BYTES": "32",
        "DISK_MARGIN_RATIO": "0.1",
    }.items():
        monkeypatch.setenv(f"MC_ZIP_{suffix}", value)


def make_zip(tmp_path, members=(('images/a.txt', b"hello"),), **kwargs):
    archive = tmp_path / "source.zip"
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Duplicate name:", category=UserWarning)
        with zipfile.ZipFile(archive, "w", **kwargs) as stream:
            for name, data in members:
                stream.writestr(name, data)
    return archive


def run_extract(archive, root, **kwargs):
    return extract_server_zip(archive, root, PREFIX, task_id=TASK_ID, **kwargs)


def task_directory(root):
    return root / ".import-staging" / TASK_ID


def assert_unpublished(root):
    assert not (root / PREFIX).exists()
    assert not task_directory(root).exists()


def record(name, contents):
    return MemberRecord(name=name, size_bytes=len(contents), sha256=hashlib.sha256(contents).hexdigest())


@pytest.mark.parametrize("name", [
    "", ".", "./", "../secret", "a/../secret", "a/../../secret", "/abs",
    "C:/abs", "C:relative", r"C:\abs", r"\\server\share\file", r"\rooted",
    r"..\secret", r"a\..\secret", "a\x00b", "a:b", "CON", "NUL.txt", "dir/file. ",
])
def test_member_names_reject_escape_and_windows_aliases(name):
    with pytest.raises(UnsafeArchive) as captured:
        safe_member_path(name)
    assert captured.value.code == "ZIP_UNSAFE_MEMBER"
    assert captured.value.solution


@pytest.mark.parametrize("name", ["images/a.jpg", r"images\a.jpg", "./images//a.jpg"])
def test_member_names_normalize_valid_nested_paths(name):
    assert safe_member_path(name) == PurePosixPath("images/a.jpg")


def test_resolve_server_zip_accepts_only_relative_regular_zip(tmp_path):
    allowed = tmp_path / "incoming"
    allowed.mkdir()
    archive = make_zip(allowed)
    assert resolve_server_zip(allowed, "source.zip") == archive.resolve()


@pytest.mark.parametrize("name", ["../outside.zip", "/absolute.zip", "C:/source.zip", r"..\outside.zip"])
def test_source_escape_has_explicit_code(tmp_path, name):
    with pytest.raises(ServerZipImportError) as captured:
        resolve_server_zip(tmp_path, name)
    assert captured.value.code == "ZIP_SOURCE_OUTSIDE_IMPORT_ROOT"


@pytest.mark.parametrize("kind", ["missing", "directory", "wrong_suffix"])
def test_source_must_be_a_regular_zip_file(tmp_path, kind):
    name = "source.zip"
    if kind == "directory":
        (tmp_path / name).mkdir()
    elif kind == "wrong_suffix":
        name = "source.txt"
        (tmp_path / name).write_bytes(b"not a zip")
    with pytest.raises(ServerZipImportError) as captured:
        resolve_server_zip(tmp_path, name)
    assert captured.value.code == "ZIP_INVALID_ARCHIVE"


def test_source_symlink_rejected_when_creation_is_available(tmp_path):
    archive = make_zip(tmp_path)
    linked = tmp_path / "linked.zip"
    try:
        linked.symlink_to(archive)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"This host cannot create symlinks: {error}")
    with pytest.raises(UnsafeArchive):
        resolve_server_zip(tmp_path, linked.name)


@pytest.mark.parametrize("reparse_kind", ["file", "parent", "root"])
def test_source_reparse_point_is_rejected_without_platform_dependencies(tmp_path, monkeypatch, reparse_kind):
    allowed = tmp_path / "incoming"
    source_parent = allowed / "nested"
    source_parent.mkdir(parents=True)
    archive = make_zip(source_parent)
    suspect = {"file": archive, "parent": source_parent, "root": allowed}[reparse_kind]
    original_lstat = Path.lstat

    def lstat(path):
        original = original_lstat(path)
        if path == suspect:
            return SimpleNamespace(st_mode=original.st_mode, st_file_attributes=0x0400)
        return original

    monkeypatch.setattr(Path, "lstat", lstat)
    with pytest.raises(UnsafeArchive):
        resolve_server_zip(allowed, "nested/source.zip")


def test_source_junction_rejected_when_creation_is_available(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    make_zip(outside)
    allowed = tmp_path / "incoming"
    allowed.mkdir()
    linked = allowed / "linked"
    if sys.platform == "win32":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(linked), str(outside)],
            capture_output=True, check=False, shell=False,
        )
        if result.returncode:
            pytest.skip("This host cannot create directory junctions")
    else:
        try:
            linked.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError) as error:
            pytest.skip(f"This host cannot create directory links: {error}")
    try:
        with pytest.raises(UnsafeArchive):
            resolve_server_zip(allowed, "linked/source.zip")
    finally:
        if sys.platform == "win32":
            linked.rmdir()
        else:
            linked.unlink()
    assert (outside / "source.zip").is_file()


@pytest.mark.parametrize("prefix", ["", ".", "../escape", "/abs", "C:/escape", r"..\escape", ".import-staging/task"])
def test_target_prefix_cannot_escape_or_overlap_staging(tmp_path, prefix):
    archive = make_zip(tmp_path)
    root = tmp_path / "target"
    with pytest.raises(UnsafeArchive):
        extract_server_zip(archive, root, prefix, task_id=TASK_ID)
    assert not root.exists()


@pytest.mark.parametrize("task_id", ["", ".", "..", "../task", "a/b", r"a\b", "C:/task", "/task"])
def test_task_id_must_be_a_single_safe_component(tmp_path, task_id):
    archive = make_zip(tmp_path)
    root = tmp_path / "target"
    with pytest.raises(UnsafeArchive):
        extract_server_zip(archive, root, PREFIX, task_id=task_id)
    assert not root.exists()


@pytest.mark.parametrize("mode", [stat.S_IFLNK, stat.S_IFCHR, stat.S_IFBLK, stat.S_IFIFO, stat.S_IFSOCK])
def test_symlink_and_special_archive_members_rejected_before_writes(tmp_path, mode):
    special = zipfile.ZipInfo("special")
    special.create_system = 3
    special.external_attr = (mode | 0o777) << 16
    archive = make_zip(tmp_path, [("good.txt", b"first"), (special, b"bad")])
    root = tmp_path / "target"
    with pytest.raises(UnsafeArchive) as captured:
        run_extract(archive, root)
    assert captured.value.code == "ZIP_UNSAFE_MEMBER"
    assert not root.exists()


def test_dos_device_metadata_is_rejected_before_writes(tmp_path):
    special = zipfile.ZipInfo("device")
    special.create_system = 0
    special.external_attr = 0x40
    archive = make_zip(tmp_path, [(special, b"bad")])
    with pytest.raises(UnsafeArchive):
        run_extract(archive, tmp_path / "target")
    assert not (tmp_path / "target").exists()


def test_corrupt_central_directory_does_not_create_staging(tmp_path):
    archive = tmp_path / "corrupt.zip"
    archive.write_bytes(b"not a zip archive")
    root = tmp_path / "target"
    with pytest.raises(UnsafeArchive) as captured:
        run_extract(archive, root)
    assert captured.value.code == "ZIP_INVALID_ARCHIVE"
    assert not root.exists()


@pytest.mark.parametrize("names", [
    ["a.txt", "a.txt"], ["dir/a.txt", r"dir\a.txt"], ["dir/a.txt", "./dir//a.txt"],
    ["dir/a.txt", "dir"], ["dir", "dir/a.txt"], [".mc-import-owner.json"],
])
def test_normalized_duplicates_and_file_directory_conflicts_fail_preflight(tmp_path, names):
    archive = make_zip(tmp_path, [(name, b"data") for name in names])
    root = tmp_path / "target"
    with pytest.raises(UnsafeArchive):
        run_extract(archive, root)
    assert not root.exists()


def test_duplicate_case_alias_uses_filesystem_case_normalizer(tmp_path, monkeypatch):
    archive = make_zip(tmp_path, [("Images/A.txt", b"one"), ("images/a.TXT", b"two")])
    monkeypatch.setattr(zip_import.os.path, "normcase", lambda value: str(value).lower())
    with pytest.raises(UnsafeArchive):
        run_extract(archive, tmp_path / "target")
    assert not (tmp_path / "target").exists()


@pytest.mark.parametrize("suffix,value,members,compression", [
    ("MAX_MEMBERS", "1", [("a", b"a"), ("b", b"b")], zipfile.ZIP_STORED),
    ("MAX_SINGLE_BYTES", "2", [("a", b"abc")], zipfile.ZIP_STORED),
    ("MAX_TOTAL_BYTES", "3", [("a", b"ab"), ("b", b"cd")], zipfile.ZIP_STORED),
    ("MAX_RATIO", "2", [("a", b"0" * 10000)], zipfile.ZIP_DEFLATED),
])
def test_declared_archive_limits_fail_before_any_destination(tmp_path, monkeypatch, suffix, value, members, compression):
    monkeypatch.setenv(f"MC_ZIP_{suffix}", value)
    archive = make_zip(tmp_path, members, compression=compression)
    root = tmp_path / "target"
    with pytest.raises(ArchiveLimitExceeded) as captured:
        run_extract(archive, root)
    assert captured.value.code == "ZIP_LIMIT_EXCEEDED"
    assert captured.value.context
    assert all(isinstance(value, (int, float)) for value in captured.value.context.values())
    assert not root.exists()


@pytest.mark.parametrize("suffix,value", [
    ("MAX_MEMBERS", "0"), ("MAX_SINGLE_BYTES", "-1"), ("MAX_TOTAL_BYTES", ""),
    ("MAX_RATIO", "nan"), ("MAX_RATIO", "inf"), ("MAX_MEMBERS", "1.2"),
    ("DISK_MARGIN_BYTES", "oops"), ("DISK_MARGIN_RATIO", "-0.5"),
])
def test_invalid_limit_environment_fails_closed(tmp_path, monkeypatch, suffix, value):
    monkeypatch.setenv(f"MC_ZIP_{suffix}", value)
    archive = make_zip(tmp_path)
    with pytest.raises(ServerZipImportError) as captured:
        run_extract(archive, tmp_path / "target")
    assert captured.value.code == "ZIP_LIMIT_EXCEEDED"
    assert f"MC_ZIP_{suffix}" in captured.value.detail
    assert captured.value.solution
    assert not (tmp_path / "target").exists()


def test_defaults_support_100_gib_with_finite_bounds(monkeypatch):
    for suffix in ("MAX_MEMBERS", "MAX_SINGLE_BYTES", "MAX_TOTAL_BYTES", "MAX_RATIO", "DISK_MARGIN_BYTES", "DISK_MARGIN_RATIO"):
        monkeypatch.delenv(f"MC_ZIP_{suffix}", raising=False)
    limits = read_limits()
    assert 100 * 1024**3 <= limits.max_single_bytes < 2**63
    assert 100 * 1024**3 <= limits.max_total_bytes < 2**63
    assert 0 < limits.max_members < 2**31
    assert 0 < limits.max_ratio < float("inf")


def test_required_disk_bytes_uses_larger_margin_and_rounds_up(monkeypatch):
    assert required_disk_bytes(100) == 132
    assert required_disk_bytes(1001) == 1102
    monkeypatch.setenv("MC_ZIP_DISK_MARGIN_BYTES", "0")
    monkeypatch.setenv("MC_ZIP_DISK_MARGIN_RATIO", "0")
    assert required_disk_bytes(101) == 101


def test_disk_preflight_fails_before_any_destination_write(tmp_path, monkeypatch):
    archive = make_zip(tmp_path)
    root = tmp_path / "target"
    monkeypatch.setattr(zip_import.shutil, "disk_usage", lambda _path: SimpleNamespace(free=36))
    with pytest.raises(InsufficientDiskSpace) as captured:
        run_extract(archive, root)
    error = captured.value
    assert error.code == "ZIP_DISK_SPACE_INSUFFICIENT"
    assert error.context == {"free_bytes": 36, "required_bytes": 37, "written_bytes": 0}
    assert error.message and error.detail and error.solution
    assert not root.exists()


def test_disk_is_checked_again_during_streaming_and_failure_cleans_own_task(tmp_path, monkeypatch):
    archive = make_zip(tmp_path, [("large.bin", b"a" * (3 * CHUNK))])
    root = tmp_path / "target"
    observed = []
    other = root / ".import-staging" / "other-task" / "keep"
    other.parent.mkdir(parents=True)
    other.write_bytes(b"other task")

    def disk_usage(_path):
        bytes_on_disk = sum(path.stat().st_size for path in task_directory(root).rglob("*.tmp"))
        observed.append(bytes_on_disk)
        return SimpleNamespace(free=10**12 if bytes_on_disk < CHUNK else 0)

    monkeypatch.setattr(zip_import.shutil, "disk_usage", disk_usage)
    with pytest.raises(InsufficientDiskSpace) as captured:
        run_extract(archive, root)
    assert captured.value.context["written_bytes"] >= CHUNK
    assert captured.value.context["required_bytes"] > 0
    assert captured.value.context["free_bytes"] == 0
    assert captured.value.solution
    assert len(observed) > 1
    assert_unpublished(root)
    assert other.read_bytes() == b"other task"


@pytest.mark.parametrize("failure", ["overflow", "short", "crc", "read", "enospc"])
def test_actual_stream_size_crc_and_io_are_checked(tmp_path, monkeypatch, failure):
    archive = make_zip(tmp_path, [("a.txt", b"abc")])
    root = tmp_path / "target"

    class Stream(io.BytesIO):
        def read(self, size=-1):
            assert size == CHUNK
            if failure == "crc":
                raise zipfile.BadZipFile("Bad CRC-32 for file")
            if failure == "read":
                raise OSError("archive source unreadable")
            if failure == "enospc":
                raise OSError(errno.ENOSPC, "No space left")
            return super().read(size)

    monkeypatch.setattr(zip_import.zipfile.ZipFile, "open", lambda *_a, **_k: Stream(b"abcdef" if failure == "overflow" else b"a"))
    expected = ActualSizeExceeded if failure == "overflow" else InsufficientDiskSpace if failure == "enospc" else UnsafeArchive
    with pytest.raises(expected) as captured:
        run_extract(archive, root)
    expected_code = "ZIP_ACTUAL_SIZE_EXCEEDED" if failure == "overflow" else "ZIP_DISK_SPACE_INSUFFICIENT" if failure == "enospc" else "ZIP_INVALID_ARCHIVE"
    assert captured.value.code == expected_code
    assert captured.value.solution
    assert_unpublished(root)


def test_real_corrupt_crc_is_detected_before_publication(tmp_path):
    data = b"this unique content will be corrupted"
    archive = make_zip(tmp_path, [("a.txt", data)])
    original = archive.read_bytes()
    assert original.count(data) == 1
    archive.write_bytes(original.replace(data, b"X" + data[1:]))
    with pytest.raises(UnsafeArchive) as captured:
        run_extract(archive, tmp_path / "target")
    assert captured.value.code == "ZIP_INVALID_ARCHIVE"
    assert_unpublished(tmp_path / "target")


@pytest.mark.parametrize("field,value", [("flag_bits", 1), ("compress_type", 99)])
def test_encrypted_and_unsupported_compression_fail_preflight(tmp_path, monkeypatch, field, value):
    archive = make_zip(tmp_path)
    original = zipfile.ZipFile.infolist

    def infolist(stream):
        entries = original(stream)
        setattr(entries[-1], field, value)
        return entries

    monkeypatch.setattr(zip_import.zipfile.ZipFile, "infolist", infolist)
    with pytest.raises(UnsafeArchive) as captured:
        run_extract(archive, tmp_path / "target")
    assert captured.value.code == "ZIP_INVALID_ARCHIVE"
    assert not (tmp_path / "target").exists()


def test_preexisting_nonempty_target_is_untouched(tmp_path):
    archive = make_zip(tmp_path)
    root = tmp_path / "target"
    target = root / PREFIX
    target.mkdir(parents=True)
    (target / "keep.bin").write_bytes(b"original bytes")
    with pytest.raises(TargetDirectoryExists) as captured:
        run_extract(archive, root)
    assert captured.value.code == "ZIP_TARGET_EXISTS"
    assert (target / "keep.bin").read_bytes() == b"original bytes"
    assert sorted(path.name for path in target.iterdir()) == ["keep.bin"]
    assert not task_directory(root).exists()


@pytest.mark.parametrize("empty_target", [False, True])
def test_streaming_atomic_publish_preserves_marker_until_checkpoint_finalization(tmp_path, monkeypatch, empty_target):
    data = b"a" * (CHUNK + 7)
    archive = make_zip(tmp_path, [("images/", b""), ("images/a.bin", data), ("empty.txt", b"")])
    root = tmp_path / "target"
    target = root / PREFIX
    if empty_target:
        target.mkdir(parents=True)
    other = root / ".import-staging" / "other-task" / "keep"
    other.parent.mkdir(parents=True)
    other.write_bytes(b"other")
    replacements = []
    syncs = []
    progress = []
    original_replace = os.replace
    original_fsync = os.fsync

    def replace(source, destination):
        source, destination = Path(source), Path(destination)
        replacements.append((source, destination))
        if source.name == "payload":
            assert destination == target
            assert json.loads((source / ".mc-import-owner.json").read_text())["task_id"] == TASK_ID
            assert (source / "images/a.bin").read_bytes() == data
            assert not list(source.rglob("*.tmp"))
        else:
            assert source.name.startswith(".part-") and source.name.endswith(".tmp")
            assert source.parent == destination.parent
            destination.relative_to(task_directory(root) / "payload")
        return original_replace(source, destination)

    def fsync(fd):
        syncs.append(fd)
        return original_fsync(fd)

    def on_progress(event):
        assert isinstance(event, ExtractionProgress)
        assert not target.exists() or not list(target.iterdir())
        progress.append(event)

    monkeypatch.setattr(zip_import.os, "replace", replace)
    monkeypatch.setattr(zip_import.os, "fsync", fsync)
    monkeypatch.setattr(zip_import.zipfile.ZipFile, "extract", lambda *_a, **_k: pytest.fail("extract is forbidden"))
    monkeypatch.setattr(zip_import.zipfile.ZipFile, "extractall", lambda *_a, **_k: pytest.fail("extractall is forbidden"))
    report = run_extract(archive, root, on_progress=on_progress)
    assert report.published is True and report.published_prefix == PREFIX and report.task_id == TASK_ID
    assert report.marker_pending is True
    assert report.extracted_files == 2 and report.extracted_bytes == len(data)
    assert report.members["images/a.bin"] == record("images/a.bin", data)
    assert report.members["empty.txt"] == record("empty.txt", b"")
    assert json.loads(json.dumps(asdict(report)))["members"]["images/a.bin"]["size_bytes"] == len(data)
    assert progress[-1].extracted_files == 2
    assert progress[-1].extracted_bytes == len(data)
    assert all(event.declared_files == 2 and event.declared_bytes == len(data) for event in progress)
    assert any(0 < event.extracted_bytes < len(data) for event in progress)
    assert [event.extracted_bytes for event in progress] == sorted(event.extracted_bytes for event in progress)
    assert len(syncs) >= 3
    assert replacements[-1] == (task_directory(root) / "payload", target)
    assert (target / "images/a.bin").read_bytes() == data
    marker = target / ".mc-import-owner.json"
    assert json.loads(marker.read_text())["task_id"] == TASK_ID
    assert not task_directory(root).exists()
    assert other.read_bytes() == b"other"
    recovered = run_extract(archive, root, completed=asdict(report)["members"])
    assert recovered.published and recovered.marker_pending
    assert recovered.members == report.members
    with pytest.raises(TargetDirectoryExists):
        zip_import.finalize_server_zip_publication(root, PREFIX, task_id="other-task")
    with pytest.raises(UnsafeArchive):
        zip_import.finalize_server_zip_publication(root, "../outside", task_id=TASK_ID)
    assert marker.exists()
    sync_count = len(syncs)
    # The caller persists the published checkpoint before making this call.
    assert zip_import.finalize_server_zip_publication(root, PREFIX, task_id=TASK_ID) is True
    assert not marker.exists()
    if os.name != "nt":
        assert len(syncs) > sync_count
    assert zip_import.finalize_server_zip_publication(root, PREFIX, task_id=TASK_ID) is False
    assert (target / "images/a.bin").read_bytes() == data
    assert other.read_bytes() == b"other"


@pytest.mark.parametrize("cancel_kind", ["return_false", "explicit", "exception", "keyboard"])
def test_cancellation_and_callback_errors_clean_staging(tmp_path, cancel_kind):
    archive = make_zip(tmp_path, [("a.bin", b"a" * (2 * CHUNK))])
    root = tmp_path / "target"
    original_error = ValueError("progress database unavailable")

    def callback(_progress):
        if cancel_kind == "return_false":
            return False
        if cancel_kind == "explicit":
            raise ExtractionCancelled("user cancelled")
        if cancel_kind == "keyboard":
            raise KeyboardInterrupt()
        raise original_error

    with pytest.raises(ExtractionCancelled) as captured:
        run_extract(archive, root, on_progress=callback)
    assert captured.value.code == "ZIP_CANCELLED"
    if cancel_kind == "exception":
        assert captured.value.__cause__ is original_error
    assert_unpublished(root)


@pytest.mark.parametrize("record_format", ["dataclass", "dict"])
def test_completed_staging_file_skipped_only_after_size_and_sha_verification(tmp_path, monkeypatch, record_format):
    data = b"previously completed"
    archive = make_zip(tmp_path, [("a.txt", data), ("b.txt", b"new")])
    root = tmp_path / "target"
    payload = task_directory(root) / "payload"
    payload.mkdir(parents=True)
    (payload / "a.txt").write_bytes(data)
    (payload / ".part-abandoned.tmp").write_bytes(b"incomplete")
    completed = record("a.txt", data)
    if record_format == "dict":
        completed = asdict(completed)
    original_open = zipfile.ZipFile.open
    opened = []

    def open_member(stream, member, *args, **kwargs):
        opened.append(member.filename)
        return original_open(stream, member, *args, **kwargs)

    monkeypatch.setattr(zip_import.zipfile.ZipFile, "open", open_member)
    report = run_extract(archive, root, completed={"a.txt": completed})
    assert opened == ["b.txt"]
    assert report.extracted_files == 2 and report.extracted_bytes == len(data) + 3
    assert report.members["a.txt"] == record("a.txt", data)
    assert (root / PREFIX / "a.txt").read_bytes() == data
    assert not list((root / PREFIX).rglob("*.tmp"))


@pytest.mark.parametrize("mismatch", ["size", "sha", "metadata", "missing"])
def test_untrusted_completed_record_is_reextracted(tmp_path, mismatch):
    data = b"correct bytes"
    archive = make_zip(tmp_path, [("a.txt", data)])
    root = tmp_path / "target"
    payload = task_directory(root) / "payload"
    payload.mkdir(parents=True)
    if mismatch != "missing":
        (payload / "a.txt").write_bytes(b"x" if mismatch == "size" else b"x" * len(data))
    completed = asdict(record("a.txt", data))
    if mismatch == "metadata":
        completed["sha256"] = "not a hash"
    report = run_extract(archive, root, completed={"a.txt": completed})
    assert (root / PREFIX / "a.txt").read_bytes() == data
    assert report.members["a.txt"] == record("a.txt", data)


@pytest.mark.parametrize("crash_after_publish", [False, True])
def test_process_death_can_recover_using_verified_records_and_owner_marker(tmp_path, monkeypatch, crash_after_publish):
    data = b"completed before process death"
    archive = make_zip(tmp_path, [("a.txt", data)])
    root = tmp_path / "target"
    original_replace = os.replace

    def crash(source, destination):
        if Path(source).name == "payload":
            if crash_after_publish:
                original_replace(source, destination)
            raise SystemExit("simulated process termination")
        return original_replace(source, destination)

    monkeypatch.setattr(zip_import.os, "replace", crash)
    with pytest.raises(SystemExit):
        run_extract(archive, root)
    recovery_dir = root / PREFIX if crash_after_publish else task_directory(root) / "payload"
    assert (recovery_dir / "a.txt").read_bytes() == data
    assert json.loads((recovery_dir / ".mc-import-owner.json").read_text())["task_id"] == TASK_ID
    monkeypatch.setattr(zip_import.os, "replace", original_replace)
    report = run_extract(archive, root, completed={"a.txt": asdict(record("a.txt", data))})
    assert report.published and report.marker_pending and report.extracted_files == 1
    assert (root / PREFIX / "a.txt").read_bytes() == data
    assert (root / PREFIX / ".mc-import-owner.json").exists()
    zip_import.finalize_server_zip_publication(root, PREFIX, task_id=TASK_ID)
    assert not (root / PREFIX / ".mc-import-owner.json").exists()
    assert not task_directory(root).exists()


@pytest.mark.parametrize("owner,contents,completed", [
    ("other-task", b"correct", True), (TASK_ID, b"changed", True), (TASK_ID, b"correct", False),
])
def test_existing_target_recovery_requires_ownership_and_verified_manifest(tmp_path, owner, contents, completed):
    archive = make_zip(tmp_path, [("a.txt", b"correct")])
    root = tmp_path / "target"
    target = root / PREFIX
    target.mkdir(parents=True)
    marker = json.dumps({"task_id": owner}).encode()
    (target / ".mc-import-owner.json").write_bytes(marker)
    (target / "a.txt").write_bytes(contents)
    with pytest.raises(TargetDirectoryExists):
        run_extract(archive, root, completed={"a.txt": record("a.txt", b"correct")} if completed else None)
    assert (target / "a.txt").read_bytes() == contents
    assert (target / ".mc-import-owner.json").read_bytes() == marker


def test_target_created_during_extraction_is_rechecked_and_preserved(tmp_path):
    archive = make_zip(tmp_path)
    root = tmp_path / "target"
    target = root / PREFIX

    def create_target(_progress):
        target.mkdir(parents=True, exist_ok=True)
        (target / "other-user.txt").write_bytes(b"do not replace")

    with pytest.raises(TargetDirectoryExists):
        run_extract(archive, root, on_progress=create_target)
    assert (target / "other-user.txt").read_bytes() == b"do not replace"
    assert not task_directory(root).exists()


@pytest.mark.parametrize("location", ["target_parent", "staging_root", "task_root", "payload", "member_parent"])
def test_reparse_destinations_are_never_followed(tmp_path, monkeypatch, location):
    archive = make_zip(tmp_path)
    root = tmp_path / "target"
    payload = task_directory(root) / "payload"
    suspects = {
        "target_parent": root / "datasets", "staging_root": root / ".import-staging",
        "task_root": task_directory(root), "payload": payload, "member_parent": payload / "images",
    }
    suspect = suspects[location]
    suspect.mkdir(parents=True)
    (suspect / "keep").write_bytes(b"must not follow")
    original_lstat = Path.lstat

    def lstat(path):
        original = original_lstat(path)
        if path == suspect:
            return SimpleNamespace(st_mode=original.st_mode, st_file_attributes=0x0400)
        return original

    monkeypatch.setattr(Path, "lstat", lstat)
    with pytest.raises(UnsafeArchive):
        run_extract(archive, root)
    assert (suspect / "keep").read_bytes() == b"must not follow"
    assert not (root / PREFIX).exists()


def test_untracked_staging_file_cannot_leak_into_publication(tmp_path):
    archive = make_zip(tmp_path)
    root = tmp_path / "target"
    payload = task_directory(root) / "payload"
    payload.mkdir(parents=True)
    (payload / "untrusted.txt").write_bytes(b"not in archive")
    with pytest.raises(UnsafeArchive):
        run_extract(archive, root)
    assert_unpublished(root)


@pytest.mark.parametrize("failure", ["nonempty_target", "absolute_source", "replace_error"])
def test_public_errors_do_not_expose_absolute_server_paths(tmp_path, monkeypatch, failure):
    archive = make_zip(tmp_path)
    root = tmp_path / "private-target-root"
    original_error = OSError(errno.EACCES, f"Cannot replace file under {root}", str(root / PREFIX))
    if failure == "nonempty_target":
        (root / PREFIX).mkdir(parents=True)
        (root / PREFIX / "keep").write_bytes(b"keep")
    elif failure == "replace_error":
        def fail_replace(*_args):
            raise original_error
        monkeypatch.setattr(zip_import.os, "replace", fail_replace)
    with pytest.raises(ServerZipImportError) as captured:
        if failure == "absolute_source":
            resolve_server_zip(root, str(archive.resolve()))
        else:
            run_extract(archive, root)
    error = captured.value
    public = {
        "str": str(error), "code": error.code, "message": error.message,
        "detail": error.detail, "solution": error.solution, "context": error.context,
    }
    serialized = json.dumps(public)
    for path in (tmp_path, root, archive):
        assert json.dumps(str(path))[1:-1] not in serialized
        assert str(path) not in " ".join(str(value) for value in public.values())
    if failure == "replace_error":
        assert error.__cause__ is original_error

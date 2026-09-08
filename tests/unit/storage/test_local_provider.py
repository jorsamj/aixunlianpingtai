from __future__ import annotations

from io import BytesIO
from pathlib import Path
import stat
import subprocess
import sys

import pytest

from platform_core.storage import LocalStorageProvider, StorageError
import platform_core.storage.local as local_module


def test_local_provider_real_file_lifecycle(tmp_path):
    provider = LocalStorageProvider("local-a", tmp_path / "root")
    health = provider.health_check()
    assert health.ok is True
    assert (tmp_path / "root").is_dir()

    uploaded = provider.upload("materials/a.jpg", BytesIO(b"image-content"), content_type="image/jpeg")
    assert uploaded.key == "materials/a.jpg"
    assert uploaded.size_bytes == len(b"image-content")
    assert len(uploaded.sha256) == 64
    assert provider.exists("materials/a.jpg") is True
    assert provider.stat("materials/a.jpg").sha256 == uploaded.sha256
    with provider.open_reader("materials/a.jpg") as stream:
        assert stream.read() == b"image-content"

    destination = tmp_path / "download" / "copy.jpg"
    provider.download("materials/a.jpg", destination)
    assert destination.read_bytes() == b"image-content"
    provider.materialize_to_local("materials/a.jpg", tmp_path / "materialized.jpg")
    assert (tmp_path / "materialized.jpg").read_bytes() == b"image-content"

    page = provider.list_objects("materials", limit=1)
    assert [item.key for item in page.items] == ["materials/a.jpg"]
    assert provider.generate_preview_url("materials/a.jpg") is None
    assert provider.generate_upload_url("materials/new.jpg") is None

    provider.delete("materials/a.jpg")
    assert provider.exists("materials/a.jpg") is False


@pytest.mark.parametrize(
    "unsafe",
    ["", "../secret", "materials/../../secret", "/absolute.jpg", r"C:\secret.jpg", r"..\secret.jpg", "bad\x00name"],
)
def test_local_provider_rejects_path_escape(tmp_path, unsafe):
    provider = LocalStorageProvider("local-a", tmp_path / "root")
    with pytest.raises(StorageError) as captured:
        provider.exists(unsafe)
    assert captured.value.code == "STORAGE_INVALID_OBJECT_KEY"


def test_local_provider_upload_is_atomic_on_stream_failure(tmp_path):
    class BrokenStream:
        def read(self, _size):
            raise OSError("disk source failed")

    provider = LocalStorageProvider("local-a", tmp_path / "root")
    with pytest.raises(StorageError, match="disk source failed"):
        provider.upload("materials/a.jpg", BrokenStream())
    assert not (tmp_path / "root" / "materials" / "a.jpg").exists()
    assert not list((tmp_path / "root" / "materials").glob("*.part-*"))


def test_local_provider_list_is_paginated_and_recursive_flag_is_honored(tmp_path):
    provider = LocalStorageProvider("local-a", tmp_path / "root")
    for key in ("a.jpg", "nested/b.jpg", "nested/deeper/c.jpg"):
        provider.upload(key, BytesIO(key.encode()))

    first = provider.list_objects("", recursive=True, limit=2)
    second = provider.list_objects("", recursive=True, limit=2, cursor=first.next_cursor)
    assert [item.key for item in first.items + second.items] == ["a.jpg", "nested/b.jpg", "nested/deeper/c.jpg"]
    shallow = provider.list_objects("nested", recursive=False, limit=20)
    assert [item.key for item in shallow.items] == ["nested/b.jpg"]


def test_iter_objects_scans_recursively_in_a_stable_depth_first_order(tmp_path):
    provider = LocalStorageProvider("local-a", tmp_path / "root")
    for key in ("z.jpg", "a/2.jpg", "a/1.jpg", "a/deep/3.jpg"):
        provider.upload(key, BytesIO(key.encode()))

    assert [item.key for item in provider.iter_objects()] == [
        "a/1.jpg",
        "a/2.jpg",
        "a/deep/3.jpg",
        "z.jpg",
    ]
    assert [item.key for item in provider.iter_objects("a")] == [
        "a/1.jpg",
        "a/2.jpg",
        "a/deep/3.jpg",
    ]


def test_iter_objects_can_limit_a_prefix_to_its_immediate_files(tmp_path):
    provider = LocalStorageProvider("local-a", tmp_path / "root")
    for key in ("a/2.jpg", "a/1.jpg", "a/deep/3.jpg"):
        provider.upload(key, BytesIO(key.encode()))

    assert [item.key for item in provider.iter_objects("a", recursive=False)] == [
        "a/1.jpg",
        "a/2.jpg",
    ]


def test_iter_objects_uses_global_object_key_lexical_order(tmp_path):
    provider = LocalStorageProvider("local-a", tmp_path / "root")
    keys = ("a/x.jpg", "a.jpg", "a0.jpg", "z/x.jpg")
    for key in keys:
        provider.upload(key, BytesIO(key.encode()))

    assert [item.key for item in provider.iter_objects()] == sorted(keys)


def test_iter_objects_rejects_an_escaping_prefix(tmp_path):
    provider = LocalStorageProvider("local-a", tmp_path / "root")

    with pytest.raises(StorageError) as captured:
        list(provider.iter_objects("../outside"))

    assert captured.value.code == "STORAGE_INVALID_OBJECT_KEY"


def test_iter_objects_returns_one_metadata_for_a_file_prefix_and_nothing_for_missing_prefix(tmp_path):
    provider = LocalStorageProvider("local-a", tmp_path / "root")
    provider.upload("a/1.jpg", BytesIO(b"one"))

    assert [item.key for item in provider.iter_objects("a/1.jpg")] == ["a/1.jpg"]
    assert list(provider.iter_objects("does-not-exist")) == []


def test_iter_objects_skips_symlinked_files_and_directories_when_supported(tmp_path):
    provider = LocalStorageProvider("local-a", tmp_path / "root")
    root = tmp_path / "root"
    provider.upload("visible.jpg", BytesIO(b"visible"))
    outside_file = tmp_path / "outside.jpg"
    outside_file.write_bytes(b"outside")
    outside_directory = tmp_path / "outside-directory"
    outside_directory.mkdir()
    (outside_directory / "nested.jpg").write_bytes(b"nested")
    try:
        (root / "linked-file.jpg").symlink_to(outside_file)
        (root / "linked-directory").symlink_to(outside_directory, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"symlink creation is unavailable on this platform: {error}")

    assert [item.key for item in provider.iter_objects()] == ["visible.jpg"]


def test_iter_objects_skips_windows_junctions_when_supported(tmp_path):
    if sys.platform != "win32":
        pytest.skip("Windows junction behavior requires win32")

    provider = LocalStorageProvider("local-a", tmp_path / "root")
    provider.upload("visible.jpg", BytesIO(b"visible"))
    outside_directory = tmp_path / "outside-directory"
    outside_directory.mkdir()
    (outside_directory / "nested.jpg").write_bytes(b"nested")
    junction = provider.root / "linked-directory"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside_directory)],
        capture_output=True,
        shell=False,
        check=False,
    )
    if result.returncode:
        reason = (result.stderr or result.stdout).decode(errors="replace").strip()
        pytest.skip(f"junction creation is unavailable on this Windows host: {reason}")

    assert [item.key for item in provider.iter_objects()] == ["visible.jpg"]


def test_link_like_helper_detects_a_windows_reparse_point_without_junction_api(tmp_path, monkeypatch):
    provider = LocalStorageProvider("local-a", tmp_path / "root")
    path = provider.root / "junction"

    class ReparsePointStat:
        st_file_attributes = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x0400)

    monkeypatch.setattr(local_module.os, "name", "nt")
    monkeypatch.setattr(Path, "is_symlink", lambda _self: False)
    monkeypatch.delattr(Path, "is_junction", raising=False)
    monkeypatch.setattr(Path, "lstat", lambda _self: ReparsePointStat())

    assert provider._is_link_like(path) is True


def test_iter_objects_excludes_root_import_staging_tree_even_when_scanning_root(tmp_path):
    provider = LocalStorageProvider("local-a", tmp_path / "root")
    provider.upload("visible.jpg", BytesIO(b"visible"))
    provider.upload(".import-staging/task-1/staged.jpg", BytesIO(b"staged"))

    assert [item.key for item in provider.iter_objects()] == ["visible.jpg"]
    assert list(provider.iter_objects(".import-staging/task-1")) == []


def test_import_staging_helper_uses_the_filesystem_case_normalizer(tmp_path, monkeypatch):
    provider = LocalStorageProvider("local-a", tmp_path / "root")
    monkeypatch.setattr(local_module.os.path, "normcase", lambda value: str(value).lower())

    assert provider._is_import_staging_path(provider.root / ".IMPORT-STAGING" / "task-1")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows case-insensitive staging behavior requires win32")
def test_iter_objects_excludes_alternate_case_root_import_staging_on_windows(tmp_path):
    provider = LocalStorageProvider("local-a", tmp_path / "root")
    provider.upload("visible.jpg", BytesIO(b"visible"))
    provider.upload(".IMPORT-STAGING/task-1/staged.jpg", BytesIO(b"staged"))

    assert [item.key for item in provider.iter_objects()] == ["visible.jpg"]
    assert list(provider.iter_objects(".IMPORT-STAGING/task-1")) == []


def test_stat_delegates_to_the_shared_metadata_helper(tmp_path, monkeypatch):
    provider = LocalStorageProvider("local-a", tmp_path / "root")
    provider.upload("a.jpg", BytesIO(b"image"))
    expected = provider.stat("a.jpg")
    captured = []

    def metadata(path, *, object_key=None):
        captured.append((path, object_key))
        return expected

    monkeypatch.setattr(provider, "_metadata", metadata)

    assert provider.stat("a.jpg") == expected
    assert captured == [(provider.root / "a.jpg", "a.jpg")]


def test_stat_preserves_the_requested_key_when_path_resolution_returns_an_alias(tmp_path, monkeypatch):
    provider = LocalStorageProvider("local-a", tmp_path / "root")
    provider.upload("real.jpg", BytesIO(b"image"))
    real_path = provider.root / "real.jpg"
    monkeypatch.setattr(provider, "_path", lambda _object_key: real_path)

    assert provider.stat("alias.jpg").key == "alias.jpg"

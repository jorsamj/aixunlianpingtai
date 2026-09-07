from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest

from platform_core.storage import LocalStorageProvider, StorageError


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


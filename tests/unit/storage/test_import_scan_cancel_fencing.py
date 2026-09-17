from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from platform_core.storage.import_tasks import SCAN_RESULT_REF, StorageImportHandler
from platform_core.storage.models import ObjectMetadata
from platform_core.task_runtime import ArtifactStore, TaskStatus


class _Repository:
    def heartbeat(self, *_args, **_kwargs):
        return None


class _Context:
    def __init__(self, root: Path):
        self.task = SimpleNamespace(task_id="scan-cancel-1", project_id="project-1")
        self.lease = SimpleNamespace(lease_token="lease-1")
        self.artifacts = ArtifactStore(root / "artifacts")
        self.repository = _Repository()
        self.cancelled = False
        self.checkpoint = {}

    def cancel_requested(self):
        return self.cancelled

    def load_checkpoint(self):
        return dict(self.checkpoint)

    def save_checkpoint(self, value):
        self.checkpoint = dict(value)


def _jpeg_bytes() -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (16, 12), "white").save(stream, format="JPEG")
    return stream.getvalue()


class _CancelDuringFirstReadProvider:
    def __init__(self, context: _Context, payload: bytes):
        self.context = context
        self.payload = payload
        self.reader_calls = 0

    def iter_objects(self, _prefix, *, recursive=True):
        del recursive
        yield ObjectMetadata(
            key="last.jpg",
            size_bytes=len(self.payload),
            etag="etag-last",
            sha256="",  # force the legacy second reader used for hashing
        )

    def open_reader(self, key):
        assert key == "last.jpg"
        self.reader_calls += 1
        if self.reader_calls == 1:
            # Simulate the user clicking Stop while the last object's remote
            # image read/decode is in flight.
            self.context.cancelled = True
        return io.BytesIO(self.payload)


def test_cancel_during_last_remote_object_read_does_not_finish_scan(tmp_path: Path, monkeypatch):
    data_dir = tmp_path / "data"
    context = _Context(tmp_path)
    provider = _CancelDuringFirstReadProvider(context, _jpeg_bytes())
    source = SimpleNamespace(id="remote-source", type="remote")
    handler = StorageImportHandler(data_dir)
    monkeypatch.setattr(
        handler,
        "_source_and_provider",
        lambda _context, _request: (source, provider),
    )

    status, result_ref = handler._scan_impl(
        context,
        {
            "storage_source_id": "remote-source",
            "prefix": "",
            "recursive": True,
            "import_format": "images",
        },
    )

    assert status is TaskStatus.CANCELLED
    assert result_ref is None
    # Once cancellation becomes visible after the first remote reader, the scan
    # must not start a second reader merely to calculate a missing SHA256.
    assert provider.reader_calls == 1
    assert context.artifacts.read_json(
        context.task.task_id, SCAN_RESULT_REF, default=None
    ) is None

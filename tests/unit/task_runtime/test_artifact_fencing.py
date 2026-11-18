"""P1 storage contracts only: no Task publication/Claim integration."""
import errno
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

from platform_core.task_runtime import FencedTaskRepository, TaskKind, TaskRecord, WorkerContext
from platform_core.task_runtime.artifacts import ArtifactStore
from platform_core.task_runtime.payload_publications import (
    PayloadPublicationError,
    PayloadPublicationIdentity,
)
from platform_core.task_runtime.worker import ExecutionFencedError, FencedArtifactStore


def test_atomic_artifact_rechecks_execution_before_publish(tmp_path):
    repository = FencedTaskRepository(tmp_path / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    repository.create(
        TaskRecord.new(
            "artifact-task",
            "project-1",
            TaskKind.VIDEO_FRAMES,
            "payload.json",
            "cpu:video",
        )
    )
    lease = repository.claim_next("worker-a", [TaskKind.VIDEO_FRAMES], set())
    assert lease is not None
    context = WorkerContext(lease.task, lease, repository, artifacts)

    real_assert = context.assert_current_execution
    calls = 0

    def fence_at_publish():
        nonlocal calls
        calls += 1
        if calls >= 2:
            context.mark_lease_lost()
            raise ExecutionFencedError("lost immediately before publish")
        return real_assert()

    context.assert_current_execution = fence_at_publish  # type: ignore[method-assign]
    with pytest.raises(ExecutionFencedError, match="before publish"):
        context.artifacts.atomic_write_json(
            "artifact-task",
            "result.json",
            {"must_not_publish": True},
        )

    result = artifacts.artifact_path("artifact-task", "result.json")
    assert not result.exists()
    assert not list(result.parent.glob(".result.json.*.tmp"))


def identity(**changes):
    values = dict(task_id="parent", project_id="project", kind="TRAINING",
                  phase="training.ready", expected_ref="payload.json",
                  expected_parent_attempt=0, intent={"request_id": "request", "target": "local"})
    values.update(changes)
    return PayloadPublicationIdentity(**values)


def native(path):
    # Raw corruption probes must also work on Windows with long paths disabled.
    return Path("\\\\?\\" + str(path)) if os.name == "nt" else path


def publish(root, payload=None):
    return ArtifactStore(root).prepare_payload_publication(
        identity(), {"中文": [1, 2], "a": True} if payload is None else payload,
        activation={"stage": "queued", "required_capabilities": ["training.runtime"]})


def test_digest_canonical_bytes_and_restart(tmp_path):
    prepared = publish(tmp_path)
    version = prepared.version
    assert version.raw == '{"a":true,"中文":[1,2]}'.encode()
    assert hashlib.sha256(version.raw).hexdigest() in version.payload_ref
    reread = ArtifactStore(tmp_path).read_payload_version("parent", version.payload_ref)
    assert reread == version
    receipt = ArtifactStore(tmp_path).read_payload_publication_receipt(
        "parent", prepared.operation_id, identity=identity())
    assert receipt == prepared
    assert receipt.metadata["size"] == len(version.raw)
    assert publish(tmp_path) == prepared
    path = native(tmp_path / "parent" / version.payload_ref)
    original = path.stat().st_mtime_ns
    assert publish(tmp_path) == prepared
    assert path.stat().st_mtime_ns == original
    script = "from platform_core.task_runtime.artifacts import ArtifactStore; import sys; v=ArtifactStore(sys.argv[1]).read_payload_version('parent',sys.argv[2]); print(v.digest)"
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path), version.payload_ref],
                            check=True, capture_output=True, text=True)
    assert result.stdout.strip() == version.digest


def test_operation_identity_is_detached_stable_and_rejects_unallowed_fields(tmp_path):
    intent = {"target": "local", "request_id": "request"}
    first = identity(intent=intent)
    intent["target"] = "changed"
    assert first.operation_id == identity().operation_id
    assert first.operation_id != identity(expected_parent_attempt=1).operation_id
    assert first.operation_id != identity(expected_ref="other.json").operation_id
    with pytest.raises(PayloadPublicationError, match="ACTIVATION"):
        ArtifactStore(tmp_path).prepare_payload_publication(first, {}, activation={"attempt": 5})
    with pytest.raises(PayloadPublicationError):
        identity(intent={"nonfinite": float("nan")})


def test_conflict_and_receipt_identity_validation(tmp_path):
    prepared = publish(tmp_path, {"value": 1})
    with pytest.raises(PayloadPublicationError, match="OPERATION_CONFLICT"):
        publish(tmp_path, {"value": 2})
    assert ArtifactStore(tmp_path).read_payload_version("parent", prepared.version.payload_ref).data == {"value": 1}
    with pytest.raises(PayloadPublicationError, match="IDENTITY"):
        ArtifactStore(tmp_path).read_payload_publication_receipt(
            "parent", prepared.operation_id, identity=identity(project_id="foreign"))


def test_tampering_and_missing_never_fall_back(tmp_path):
    prepared = publish(tmp_path)
    path = native(tmp_path / "parent" / prepared.version.payload_ref)
    path.write_bytes(b"{}")  # deliberate out-of-protocol corruption
    with pytest.raises(PayloadPublicationError, match="INTEGRITY"):
        ArtifactStore(tmp_path).read_payload_version("parent", prepared.version.payload_ref)
    path.unlink()
    with pytest.raises(PayloadPublicationError, match="MISSING"):
        ArtifactStore(tmp_path).read_payload_version("parent", prepared.version.payload_ref)


@pytest.mark.parametrize("ref", ["../escape", "/escape", "C:/escape", "payload-versions/v1/not-a-hash/file.json", "scenario/../payload.json"])
def test_invalid_refs(tmp_path, ref):
    with pytest.raises(PayloadPublicationError):
        ArtifactStore(tmp_path).read_payload_version("parent", ref)


def test_symlink_escape_and_alias(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    prepared = publish(store.root)
    alias = store.root / "parent" / "alias"
    try:
        alias.symlink_to(store.root / "parent" / "payload-versions", target_is_directory=True)
    except OSError as error:
        pytest.skip(f"symlink capability unavailable: {error}")
    with pytest.raises(ValueError):
        store.atomic_write_json("parent", "alias/overwrite.json", {})
    outside = tmp_path / "outside"
    outside.mkdir()
    (store.root / "other").symlink_to(outside, target_is_directory=True)
    with pytest.raises(PayloadPublicationError, match="UNSAFE"):
        store.prepare_payload_publication(identity(task_id="other"), {})
    assert not list(outside.iterdir())


@pytest.mark.parametrize("scenario", [False, True])
def test_reserved_legacy_interfaces_and_delete_are_all_or_nothing(tmp_path, scenario):
    store = ArtifactStore(tmp_path)
    ident = identity(kind="DEPLOYMENT_TEST", phase="deployment.ready") if scenario else identity()
    prepared = store.prepare_payload_publication(ident, {})
    store.atomic_write_json("parent", "result.json", {"keep": True})
    for ref in (prepared.version.payload_ref,
                ("scenario/" if scenario else "") + "payload-publications/v1/other.json"):
        for operation in (lambda: store.artifact_path("parent", ref),
                          lambda: store.atomic_write_json("parent", ref, {}),
                          lambda: store.append_log("parent", ref, "bad")):
            with pytest.raises(ValueError, match="RESERVED"):
                operation()
    with pytest.raises(PayloadPublicationError, match="RETENTION"):
        store.delete_task("parent")
    assert store.read_json("parent", "result.json") == {"keep": True}
    assert store.read_payload_version("parent", prepared.version.payload_ref).data == {}
    store.atomic_write_json("legacy", "payload.json", {})
    assert store.delete_task("legacy")
    assert not (tmp_path / "legacy").exists()


def test_fenced_preparation_rechecks_and_legacy_cannot_bypass(tmp_path):
    context = Mock(assert_current_execution=Mock())
    fenced = FencedArtifactStore(context, ArtifactStore(tmp_path))
    prepared = fenced.prepare_payload_publication(identity(), {})
    assert fenced.read_payload_version("parent", prepared.version.payload_ref).data == {}
    assert fenced.read_payload_publication_receipt("parent", prepared.operation_id) == prepared
    with pytest.raises(ValueError):
        fenced.atomic_write_json("parent", prepared.version.payload_ref, {})
    with pytest.raises(ValueError):
        fenced.artifact_path("parent", prepared.version.payload_ref)
    with pytest.raises(ValueError):
        fenced.append_log("parent", prepared.version.payload_ref, "bad")
    context.assert_current_execution.side_effect = [None, ExecutionFencedError("lost")]
    with pytest.raises(ExecutionFencedError):
        fenced.prepare_payload_publication(identity(task_id="other"), {})
    assert not list((tmp_path / "other").glob("payload-publications/v1/*.json"))


@pytest.mark.parametrize("which", ["version", "receipt"])
def test_link_failure_leaves_no_partial_final_and_is_retryable(tmp_path, monkeypatch, which):
    real_link = os.link
    def failing_link(source, destination, **kwargs):
        if ("payload-publications" in str(destination)) == (which == "receipt"):
            raise OSError(errno.ENOTSUP, "injected link failure")
        return real_link(source, destination, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(os, "link", failing_link)
        patch.setattr(os, "replace", Mock(side_effect=AssertionError("no covering fallback allowed")))
        with pytest.raises(PayloadPublicationError, match="BACKEND"):
            publish(tmp_path)
    assert not list((tmp_path / "parent").glob("payload-publications/v1/*.json"))
    assert publish(tmp_path).version.data["a"] is True


def test_fsync_failure_does_not_publish(tmp_path, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", Mock(side_effect=OSError("disk failure")))
        with pytest.raises(PayloadPublicationError):
            publish(tmp_path)
    assert not list((tmp_path / "parent").glob("**/sha256-*.json"))
    assert publish(tmp_path)


def test_process_concurrency_and_orphan_version_recovery(tmp_path):
    script = '''
import json, sys, time
from pathlib import Path
from platform_core.task_runtime.artifacts import ArtifactStore
from platform_core.task_runtime.payload_publications import PayloadPublicationIdentity, PayloadPublicationError
root, value = Path(sys.argv[1]), int(sys.argv[2])
(root / ('ready-' + str(value))).touch()
deadline = time.monotonic() + 15
while not (root / 'start').exists():
    if time.monotonic() > deadline: raise RuntimeError('start barrier timeout')
    time.sleep(.01)
identity = PayloadPublicationIdentity(task_id='parent', project_id='project', kind='TRAINING', phase='training.ready', expected_ref='payload.json', expected_parent_attempt=0, intent={'request_id':'request', 'target':'local'})
try:
    prepared = ArtifactStore(root).prepare_payload_publication(identity, {'value':value})
    print(json.dumps(['ok', prepared.version.payload_ref]))
except PayloadPublicationError as error:
    print(json.dumps([error.code, '']))
'''
    processes = [subprocess.Popen([sys.executable, "-c", script, str(tmp_path), str(value)],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for value in (1, 2)]
    try:
        deadline = time.monotonic() + 15
        while not all((tmp_path / f"ready-{value}").exists() for value in (1, 2)):
            assert time.monotonic() < deadline, "publish processes failed to reach barrier"
            time.sleep(.01)
        (tmp_path / "start").touch()
        results = []
        for process in processes:
            output, error = process.communicate(timeout=15)
            assert process.returncode == 0, error
            results.append(json.loads(output))
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait()
    assert sorted(row[0] for row in results) == ["PUBLICATION_OPERATION_CONFLICT", "ok"]
    winner = next(row[1] for row in results if row[0] == "ok")
    store = ArtifactStore(tmp_path)
    assert store.read_payload_publication_receipt("parent", identity().operation_id).version.payload_ref == winner
    # A separate operation with only a version left behind is NOT Task publication.
    other = store.prepare_payload_publication(identity(task_id="orphan"), {})
    receipt = tmp_path / "orphan" / "payload-publications/v1" / (other.operation_id + ".json")
    receipt.unlink()  # simulate loss before receipt publication
    with pytest.raises(PayloadPublicationError, match="MISSING"):
        store.read_payload_publication_receipt("orphan", other.operation_id)
    assert ArtifactStore(tmp_path).prepare_payload_publication(identity(task_id="orphan"), {}) == other


def test_storage_io_does_not_hold_sqlite_writer(tmp_path, monkeypatch):
    database = tmp_path / "tasks.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE marker (value INTEGER)")
    real_fsync = os.fsync
    calls = []
    def probe(descriptor):
        with sqlite3.connect(database, timeout=0) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("INSERT INTO marker VALUES (1)")
        calls.append(descriptor)
        return real_fsync(descriptor)
    monkeypatch.setattr(os, "fsync", probe)
    assert publish(tmp_path / "artifacts")
    assert len(calls) >= 2

@pytest.mark.parametrize('field,value', [
    ('operation_id', '0' * 64), ('digest', '0' * 64), ('size', 100),
    ('activation', {'status': 'RUNNING'}), ('new_ref', '../payload.json'),
])
def test_receipt_revalidates_every_binding(tmp_path, field, value):
    prepared = publish(tmp_path)
    path = native(tmp_path / 'parent' / 'payload-publications/v1' / (prepared.operation_id + '.json'))
    receipt = prepared.metadata
    receipt[field] = value
    path.write_text(json.dumps(receipt, sort_keys=True, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    with pytest.raises(PayloadPublicationError):
        ArtifactStore(tmp_path).read_payload_publication_receipt('parent', prepared.operation_id)


def test_size_limit_and_actual_explicit_training_request_scale(tmp_path):
    # app.py:8272 caps each explicit train/test ID list at 50,000.
    ids = [f'{index:08x}-0000-0000-0000-{index:012x}' for index in range(50000)]
    prepared = ArtifactStore(tmp_path).prepare_payload_publication(
        identity(), {'train_image_ids': ids, 'test_image_ids': ids})
    assert len(prepared.version.data['test_image_ids']) == 50000
    assert len(prepared.version.raw) > 3_000_000
    with pytest.raises(PayloadPublicationError, match='SIZE_LIMIT'):
        ArtifactStore(tmp_path, max_payload_bytes=100).read_payload_version('parent', prepared.version.payload_ref)
    with pytest.raises(PayloadPublicationError, match='SIZE_LIMIT'):
        ArtifactStore(tmp_path / 'small', max_payload_bytes=5).prepare_payload_publication(identity(), {'too': 'large'})


def test_write_failure_does_not_publish(tmp_path, monkeypatch):
    real_fdopen = os.fdopen
    class FailedWrite:
        def __init__(self, descriptor):
            self.stream = real_fdopen(descriptor, 'wb')
        def __enter__(self):
            return self
        def write(self, raw):
            raise OSError('injected write failure')
        def __exit__(self, *args):
            self.stream.close()
    with monkeypatch.context() as patch:
        patch.setattr(os, 'fdopen', lambda descriptor, mode: FailedWrite(descriptor))
        with pytest.raises(PayloadPublicationError, match='IO_ERROR'):
            publish(tmp_path)
    assert not list((tmp_path / 'parent').glob('**/sha256-*.json'))
    assert publish(tmp_path)


def test_fenced_receipt_not_published_after_lease_loss(tmp_path):
    context = Mock(assert_current_execution=Mock(side_effect=[None, None, ExecutionFencedError('lost before receipt')]))
    store = ArtifactStore(tmp_path)
    with pytest.raises(ExecutionFencedError):
        FencedArtifactStore(context, store).prepare_payload_publication(identity(), {})
    with pytest.raises(PayloadPublicationError, match='MISSING'):
        store.read_payload_publication_receipt('parent', identity().operation_id)
    assert list((tmp_path / 'parent' / 'payload-versions').glob('**/sha256-*.json'))


def test_hash_and_serialization_also_run_outside_writer(tmp_path, monkeypatch):
    from platform_core.task_runtime import payload_publications as module
    database = tmp_path / 'tasks.sqlite3'
    sqlite3.connect(database).close()
    def probe():
        with sqlite3.connect(database, timeout=0) as connection:
            connection.execute('BEGIN IMMEDIATE')
    real_json, real_sha = module._json_bytes, hashlib.sha256
    def encode(value):
        probe()
        return real_json(value)
    def sha(*args, **kwargs):
        probe()
        return real_sha(*args, **kwargs)
    monkeypatch.setattr(module, '_json_bytes', encode)
    monkeypatch.setattr(hashlib, 'sha256', sha)
    assert publish(tmp_path / 'artifacts')


def test_payload_and_receipt_limits_are_independent(tmp_path):
    store = ArtifactStore(tmp_path, max_payload_bytes=2)
    publication = store.prepare_payload_publication(identity(), {})
    assert store.read_payload_publication_receipt('parent', publication.operation_id) == publication
    small_receipt = ArtifactStore(tmp_path / 'other', max_receipt_bytes=2)
    with pytest.raises(PayloadPublicationError, match='SIZE_LIMIT'):
        small_receipt.prepare_payload_publication(identity(), {})
    assert not (small_receipt.root / 'parent').exists()


def test_process_crash_between_version_and_receipt_is_not_task_publication(tmp_path):
    script = '''
import os, sys
from platform_core.task_runtime.artifacts import ArtifactStore
from platform_core.task_runtime.payload_publications import PayloadVersionStore, PayloadPublicationIdentity
original = PayloadVersionStore._publish
def crash(self, task_id, ref, *args, **kwargs):
    if 'payload-publications' in ref: os._exit(23)
    return original(self, task_id, ref, *args, **kwargs)
PayloadVersionStore._publish = crash
identity = PayloadPublicationIdentity(task_id='parent', project_id='project', kind='TRAINING', phase='training.ready', expected_ref='payload.json', expected_parent_attempt=0, intent={'request_id':'request', 'target':'local'})
ArtifactStore(sys.argv[1]).prepare_payload_publication(identity, {})
'''
    process = subprocess.run([sys.executable, '-c', script, str(tmp_path)], timeout=15,
                             capture_output=True, text=True)
    assert process.returncode == 23, process.stderr
    store = ArtifactStore(tmp_path)
    with pytest.raises(PayloadPublicationError, match='MISSING'):
        store.read_payload_publication_receipt('parent', identity().operation_id)
    orphan = list((tmp_path / 'parent' / 'payload-versions').glob('**/sha256-*.json'))
    assert len(orphan) == 1
    original_time = native(orphan[0]).stat().st_mtime_ns
    recovered = store.prepare_payload_publication(identity(), {})
    assert recovered.version.data == {}
    assert native(orphan[0]).stat().st_mtime_ns == original_time

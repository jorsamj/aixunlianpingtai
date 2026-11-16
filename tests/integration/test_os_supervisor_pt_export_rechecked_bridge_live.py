"""2C-01 real chain: central task+lease -> signed recheck -> one CAS -> PT systemd.

Ephemeral Ubuntu 24.04 CI only. No model download, Agent callback, production
task dispatch, model publication, StopReceipt or production system changes.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import time

import onnx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from platform_core.os_supervisor_authorization import GrantRejected
from platform_core.os_supervisor_cpu_pt_export_admission import (
    FrozenPtExportAdmission, VerifiedPtBytes,
)
from platform_core.os_supervisor_journal import ExecutionJournal
from platform_core.os_supervisor_pt_export_grant import (
    CentralPtExportAdmissionIssuer, PT_TEST_RESOURCE, PT_PROFILE,
    _canonical,
)
from platform_core.os_supervisor_pt_export_launch import (
    PtExportJournal, issue_pt_export_launch_grant,
)
from platform_core.os_supervisor_pt_export_cpu_systemd_pilot import (
    IsolatedPtExportCpuPilot, parse_pt_export_log,
)
from platform_core.os_supervisor_pt_export_rechecked_bridge import (
    CiOnlyPtExportRecheckedBridge,
)
from platform_core.service_nodes import ServiceNodeRepository
from platform_core.task_runtime import (
    ArtifactStore, TaskKind, TaskRecord, TaskRepository,
)

_TASK = "conv_pt_integrated_001"
_NODE = "ci-pt-bridge-node"
_LEASE = "isolated-central-original-task-lease"
_PARAMS = {"input_size": 32, "batch": 1, "opset": 12,
           "dynamic": False, "simplify": False}


def _cleanup(staged, rebound_handle=None):
    handles = {staged.handle}
    if rebound_handle:
        handles.add(rebound_handle)
    for h in handles:
        unit = "changlian-os-" + h + ".service"
        subprocess.run(["/usr/bin/systemctl", "--system", "stop", "--", unit],
                       capture_output=True, timeout=12, check=False)
        root = Path("/run/changlian-os-pt-pilot-" + h)
        if root.is_dir() and not root.is_symlink():
            shutil.rmtree(root)
        out = Path("/run/changlian-pt-output-" + h)
        if out.is_symlink():
            out.unlink()
        elif out.is_dir():
            shutil.rmtree(out)
        private = Path("/run/private/changlian-pt-output-" + h)
        if private.is_dir() and not private.is_symlink():
            shutil.rmtree(private)


def _environment(tmp_path, *, input_size=32, official_path=None):
    assert os.geteuid() == 0
    pilot = IsolatedPtExportCpuPilot(isolated_ci_only=True)
    if official_path is None:
        fixture = pilot.generate_trusted_fixture()
    else:
        from platform_core.mother_model_assets import _OFFICIAL_YOLO11_DETECT
        name = "yolo11n.pt"
        size, digest = _OFFICIAL_YOLO11_DETECT[name]
        fixture = pilot.stage_pinned_official_checkpoint(
            official_path, source_name=name, source_sha256=digest,
            source_size_bytes=size,
        )
    repo = TaskRepository(tmp_path / "db" / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "db" / "artifacts")
    params = {**_PARAMS, "input_size": input_size}
    request = {
        "remote_execution": {
            "version": 1, "task_kind": "MODEL_CONVERSION",
            "transport": "object-storage-v1",
            "conversion": {
                "schema_version": 1, "target": "onnx",
                "source": {
                    "type": "object", "file_name": fixture.source_name,
                    "storage_source_id": "ci-original-remote-store",
                    "object_key": "models/ci/source.pt",
                    "sha256": fixture.source_sha256,
                    "size_bytes": fixture.source_size_bytes,
                },
                "source_trace": {
                    "algorithm_id": "ci-algorithm", "version_id": "ci-v1",
                    "sha256": fixture.source_sha256,
                },
                "params": params,
                "output": {"file_name": "source.onnx"},
            },
        },
    }
    artifacts.atomic_write_json(_TASK, "request.json", request)
    repo.create(TaskRecord.new(
        task_id=_TASK, project_id="ci-isolated-project",
        kind=TaskKind.MODEL_CONVERSION, payload_ref="request.json",
        resource_key=PT_TEST_RESOURCE, required_capabilities=("conversion",),
    ), artifacts=artifacts)
    nodes = ServiceNodeRepository(repo)
    _, node_token = nodes.create({
        "node_id": _NODE, "display_name": "CI trusted PT bridge",
        "connection_mode": "agent", "allowed_capabilities": ["conversion"],
    })
    nodes.heartbeat(_NODE, node_token, {
        "reported_capabilities": ["conversion"],
    })
    with closing(repo._connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            """UPDATE tasks SET status='RUNNING',stage='running',attempt=3,
                   worker_id=?,lease_token=?,lease_expires_at=? WHERE task_id=?""",
            ("agent:" + _NODE, _LEASE,
             (datetime.now(timezone.utc) + timedelta(seconds=120)).isoformat(),
             _TASK),
        )
        db.commit()
    key = Ed25519PrivateKey.generate()
    issuer = CentralPtExportAdmissionIssuer(
        repo, artifacts, key, pt_trial_enabled=True,
    )
    root = ExecutionJournal(
        tmp_path / "root-journal" / "executions.sqlite3",
        test_only_unprivileged=True,
    )
    journal = PtExportJournal(root)
    frozen = FrozenPtExportAdmission(
        task_id=_TASK, task_attempt=3, node_id=_NODE,
        worker_id="agent:" + _NODE,
        execution_lease_sha256=hashlib.sha256(_LEASE.encode()).hexdigest(),
        source_sha256=fixture.source_sha256,
        source_size_bytes=fixture.source_size_bytes,
        source_name=fixture.source_name, output_name="source.onnx",
        **params,
    )
    manifest = frozen.freeze_nonexecutable_manifest(
        VerifiedPtBytes(fixture.source_sha256, fixture.source_size_bytes),
    )
    binding = {
        "task_id": _TASK, "task_attempt": 3,
        "node_id": _NODE, "worker_id": "agent:" + _NODE,
        "execution_lease_sha256": hashlib.sha256(_LEASE.encode()).hexdigest(),
        "boot_id": root.boot_id, "runner_profile": PT_PROFILE,
        "gpu_uuid": "CPU_ONLY",
        "source_sha256": fixture.source_sha256,
        "source_size_bytes": fixture.source_size_bytes,
        "source_name": fixture.source_name, "output_name": "source.onnx",
        "params": params,
        "manifest_sha256": hashlib.sha256(manifest).hexdigest(),
    }
    nonce = journal.issue_admission_challenge(binding)
    admission = issuer.issue(
        task_id=_TASK, task_attempt=3, node_id=_NODE,
        node_token=node_token, execution_lease_token=_LEASE,
        boot_id=root.boot_id, challenge=nonce,
    )
    registered = journal.register_admission(
        admission, trusted_public_key=key.public_key(),
    )
    handle_id = registered["handle_id"]
    challenge = journal.issue_launch_challenge(handle_id, 3)
    bridge = CiOnlyPtExportRecheckedBridge(
        journal, pilot, key.public_key(), isolated_ci_only=True,
    )
    context = {
        "pilot": pilot, "fixture": fixture, "repo": repo,
        "artifacts": artifacts, "key": key, "issuer": issuer,
        "journal": journal, "root": root, "handle": handle_id,
        "node_token": node_token, "challenge": challenge,
        "admission": admission, "bridge": bridge,
    }
    return context


def _fresh_launch(ctx):
    return issue_pt_export_launch_grant(
        ctx["issuer"],
        task_id=_TASK, task_attempt=3, node_id=_NODE,
        node_token=ctx["node_token"], execution_lease_token=_LEASE,
        boot_id=ctx["root"].boot_id,
        challenge=ctx["challenge"],
        handle_id=ctx["handle"],
        registered_grant_digest=hashlib.sha256(
            _canonical(ctx["admission"]["claims"]),
        ).hexdigest(),
    )


def _evidence(ctx, receipt):
    deadline = time.monotonic() + 120
    pilot = ctx["pilot"]
    while time.monotonic() < deadline:
        raw = pilot.read_export_proof_log(receipt)
        try:
            proof = parse_pt_export_log(raw, ctx["fixture"].source_sha256)
            return proof
        except GrantRejected:
            info = pilot.backend.inspect(
                receipt["unit_name"], receipt["invocation_id"],
            )
            if info["active_state"] == "failed":
                raise AssertionError(
                    "original OS invocation failed before signed proof"
                )
            time.sleep(.5)
    raise AssertionError("original OS invocation had no complete PT proof")


def _exit(ctx, receipt):
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            return ctx["pilot"].backend.verified_natural_exit(
                receipt["unit_name"], receipt["invocation_id"],
                original_control_group=receipt["control_group"],
                original_main_pid=receipt["main_pid"],
            )
        except GrantRejected:
            time.sleep(.5)
    raise AssertionError("OS unit never reached provable natural exit")


def test_real_central_recheck_os_cas_then_actual_pt_export(tmp_path):
    ctx = _environment(tmp_path)
    try:
        grant = _fresh_launch(ctx)
        started = ctx["bridge"].start(
            handle_id=ctx["handle"], task_attempt=3,
            central_launch_envelope=grant,
            trusted_fixture=ctx["fixture"],
        )
        assert started["unit_name"] == "changlian-os-" + ctx["handle"] + ".service"
        assert started["os_executor_connected"] is True
        assert started["production_launch_allowed"] is False
        assert started["result_publish_allowed"] is False
        assert started["trusted_stop_receipt_available"] is False
        original = ctx["journal"].verified_pt_identity(ctx["handle"], 3)
        assert original["invocation_id"] == started["invocation_id"]
        assert original["main_pid"] == started["main_pid"]
        assert original["launch_grant_digest"] == started["launch_grant_digest"]
        with closing(ctx["root"]._connect()) as db:
            row = db.execute(
                """SELECT state,event_seq FROM execution_intents
                   WHERE handle_id=?""", (ctx["handle"],),
            ).fetchone()
            assert tuple(row) == ("RUNNING", 3)
            assert db.execute(
                "SELECT count(*) FROM pt_export_unit_identities",
            ).fetchone()[0] == 1
        with pytest.raises(GrantRejected, match="HOLD"):
            ctx["bridge"].start(
                handle_id=ctx["handle"], task_attempt=3,
                central_launch_envelope=grant,
                trusted_fixture=ctx["fixture"],
            )
        with pytest.raises(GrantRejected, match="CPU_PT_HANDLE_PROFILE_MISMATCH_HOLD"):
            ctx["root"].record_cpu_identity(
                ctx["handle"], 3,
                invocation_id=started["invocation_id"],
                control_group=started["control_group"],
                main_pid=started["main_pid"],
            )
        proof = _evidence(ctx, started)
        path = Path("/run/changlian-pt-output-" + ctx["handle"]) / "source.onnx"
        data = path.read_bytes()
        assert hashlib.sha256(data).hexdigest() == proof["onnx_sha256"]
        assert len(data) == proof["onnx_size_bytes"]
        onnx.checker.check_model(onnx.load_from_string(data))
        assert proof["max_abs_error"] < 0.001
        assert _exit(ctx, started)["exit_code"] == 0
        restarted = PtExportJournal(ExecutionJournal(
            ctx["root"].path,
            test_only_unprivileged=True,
        ))
        assert restarted.verified_pt_identity(ctx["handle"], 3) == original
        print("CENTRAL_CAS_REAL_PT_EXPORT_PROOF", proof, flush=True)
    finally:
        _cleanup(ctx["fixture"], ctx["handle"])


@pytest.mark.parametrize("fault", ["forged-signature", "wrong-input-size", "lease-revoked"])
def test_failed_central_or_fixed_contract_never_starts_systemd(tmp_path, fault):
    ctx = _environment(tmp_path, input_size=640 if fault == "wrong-input-size" else 32)
    try:
        if fault == "lease-revoked":
            with closing(ctx["repo"]._connect()) as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute(
                    "UPDATE tasks SET lease_token='rotated' WHERE task_id=?",
                    (_TASK,),
                )
                db.commit()
            with pytest.raises(GrantRejected, match="HOLD"):
                _fresh_launch(ctx)
        else:
            grant = _fresh_launch(ctx)
            if fault == "forged-signature":
                grant = {
                    **grant, "claims": {
                        **grant["claims"], "source_sha256": "0" * 64,
                    },
                }
            with pytest.raises(GrantRejected, match="HOLD"):
                ctx["bridge"].start(
                    handle_id=ctx["handle"], task_attempt=3,
                    central_launch_envelope=grant,
                    trusted_fixture=ctx["fixture"],
                )
        assert ctx["fixture"].root.exists()
        assert not (ctx["fixture"].root / ".launch-consumed").exists()
        assert not Path(
            "/run/changlian-os-pt-pilot-" + ctx["handle"]
        ).exists()
        with closing(ctx["root"]._connect()) as db:
            assert db.execute(
                "SELECT state FROM execution_intents WHERE handle_id=?",
                (ctx["handle"],),
            ).fetchone()[0] == "PREPARED"
            assert db.execute(
                "SELECT count(*) FROM pt_export_unit_identities",
            ).fetchone()[0] == 0
    finally:
        _cleanup(ctx["fixture"], ctx["handle"])


def test_crash_after_cas_is_unknown_and_does_not_spawn_twice(tmp_path, monkeypatch):
    ctx = _environment(tmp_path)
    try:
        grant = _fresh_launch(ctx)
        invoked = []
        def failed_start(_staged):
            invoked.append(True)
            raise GrantRejected("PT_CPU_INJECTED_OS_FAILURE_HOLD")
        monkeypatch.setattr(ctx["pilot"], "launch", failed_start)
        with pytest.raises(GrantRejected, match="INJECTED_OS_FAILURE"):
            ctx["bridge"].start(
                handle_id=ctx["handle"], task_attempt=3,
                central_launch_envelope=grant,
                trusted_fixture=ctx["fixture"],
            )
        assert invoked == [True]
        with closing(ctx["root"]._connect()) as db:
            assert db.execute(
                "SELECT state FROM execution_intents WHERE handle_id=?",
                (ctx["handle"],),
            ).fetchone()[0] == "STARTING"
            assert db.execute("SELECT count(*) FROM pt_export_claims").fetchone()[0] == 1
            assert db.execute(
                "SELECT count(*) FROM pt_export_unit_identities",
            ).fetchone()[0] == 0
        with pytest.raises(GrantRejected, match="HOLD"):
            ctx["bridge"].start(
                handle_id=ctx["handle"], task_attempt=3,
                central_launch_envelope=grant,
                trusted_fixture=ctx["fixture"],
            )
        assert invoked == [True]
    finally:
        _cleanup(ctx["fixture"], ctx["handle"])



def test_real_code_pinned_official_yolo11n_central_cas_pt_to_onnx(tmp_path):
    """Real downloaded *and code-pinned* official PT, never an arbitrary file."""
    import os
    path = os.environ.get("CHANGLIAN_CI_PINNED_OFFICIAL_YOLO11N")
    assert path, "CI requires a verified local official source"
    downloaded = Path(path)
    ctx = _environment(tmp_path, official_path=downloaded)
    try:
        assert ctx["fixture"].source_name == "yolo11n.pt"
        assert ctx["fixture"].origin == "ultralytics-assets-v8.4.0-pinned-sha256"
        fresh = _fresh_launch(ctx)
        started = ctx["bridge"].start(
            handle_id=ctx["handle"], task_attempt=3,
            central_launch_envelope=fresh,
            trusted_fixture=ctx["fixture"],
        )
        os_identity = ctx["journal"].verified_pt_identity(ctx["handle"], 3)
        assert os_identity["unit_name"] == started["unit_name"]
        assert os_identity["invocation_id"] == started["invocation_id"]
        assert os_identity["main_pid"] == started["main_pid"]
        assert started["production_launch_allowed"] is False
        assert started["result_publish_allowed"] is False
        proof = _evidence(ctx, started)
        assert proof["source_sha256"] == ctx["fixture"].source_sha256
        assert proof["max_abs_error"] < .001
        target = Path("/run/changlian-pt-output-" + ctx["handle"]) / "source.onnx"
        assert target.is_file()
        assert hashlib.sha256(target.read_bytes()).hexdigest() == proof["onnx_sha256"]
        onnx.checker.check_model(onnx.load(str(target)))
        assert _exit(ctx, started)["exit_code"] == 0
        with pytest.raises(GrantRejected, match="HOLD"):
            ctx["bridge"].start(
                handle_id=ctx["handle"], task_attempt=3,
                central_launch_envelope=fresh,
                trusted_fixture=ctx["fixture"],
            )
        print("OFFICIAL_PINNED_YOLO_PT_ONNX_EVIDENCE", proof, flush=True)
    finally:
        _cleanup(ctx["fixture"], ctx["handle"])


def test_official_pinned_download_is_never_authorized_after_mutation(tmp_path):
    import os
    from platform_core.mother_model_assets import _OFFICIAL_YOLO11_DETECT
    source = Path(os.environ["CHANGLIAN_CI_PINNED_OFFICIAL_YOLO11N"])
    local = tmp_path / "yolo11n.pt"
    shutil.copyfile(source, local)
    original = local.stat().st_size
    with local.open("r+b") as out:
        out.seek(17)
        out.write(b"tamper")
    assert local.stat().st_size == original
    pilot = IsolatedPtExportCpuPilot(isolated_ci_only=True)
    size, sha = _OFFICIAL_YOLO11_DETECT["yolo11n.pt"]
    with pytest.raises(GrantRejected, match="HOLD"):
        pilot.stage_pinned_official_checkpoint(
            local, source_name="yolo11n.pt", source_sha256=sha,
            source_size_bytes=size,
        )
    symlink = tmp_path / "linked"
    symlink.mkdir()
    linked = symlink / "yolo11n.pt"
    linked.symlink_to(source)
    with pytest.raises(GrantRejected, match="HOLD"):
        pilot.stage_pinned_official_checkpoint(
            linked, source_name="yolo11n.pt", source_sha256=sha,
            source_size_bytes=size,
        )

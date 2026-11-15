"""P0-01C-2A/2B portable contracts ONLY; no real cgroup test here."""
from pathlib import Path
import sys

# tools/poc is deliberately not imported by production runtime.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "poc"))
import linux_cgroup_probe as probe
import linux_cgroup_poc as poc


def test_cgroup2_mount_parsing():
    raw = (
        "31 20 0:27 / /tmp/a\\040b rw - ext4 /dev/vda rw\n"
        "32 20 0:30 / /sys/fs/cgroup rw - cgroup2 cgroup rw\n"
    )
    assert probe.cgroup2_mount(raw) == "/sys/fs/cgroup"
    assert probe.cgroup2_mount("32 20 0:30 / /sys/fs/cgroup rw - cgroup cgroup rw") is None


def test_unified_path_rejects_parent_traversal():
    assert probe.unified_path("0::/user.slice/user-1000.slice/session-2.scope") == (
        "/user.slice/user-1000.slice/session-2.scope"
    )
    assert probe.unified_path("1:cpuset:/") is None
    assert probe.unified_path("0::/../../oops") is None


def test_populated_is_never_inferred_from_missing_cgroup(tmp_path):
    assert poc.cg_populated(str(tmp_path), "/no-such-unit") is None
    assert poc.cg_populated(str(tmp_path), "/../unit") is None
    target = tmp_path / "safe.service"
    target.mkdir()
    (target / "cgroup.events").write_text("populated 1\nfrozen 0\n", encoding="utf-8")
    assert poc.cg_populated(str(tmp_path), "/safe.service") == 1
    (target / "cgroup.events").write_text("populated 0\n", encoding="utf-8")
    assert poc.cg_populated(str(tmp_path), "/safe.service") == 0
    (target / "cgroup.events").write_text("populated 9\n", encoding="utf-8")
    assert poc.cg_populated(str(tmp_path), "/safe.service") is None


def test_cgroup_path_must_match_exact_boundary(monkeypatch):
    monkeypatch.setattr(poc.Path, "read_text", lambda self, **kwargs: "0::/test/a.service/child\n")
    assert poc.process_in_cgroup(111, "/test/a.service") is True
    assert poc.process_in_cgroup(111, "/test/a.serv") is False
    assert poc.process_in_cgroup(111, "/") is False


def test_default_cli_is_inert_and_never_claims_stop_proof(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["linux_cgroup_poc.py"])
    monkeypatch.setattr(poc, "run_poc", lambda: (_ for _ in ()).throw(AssertionError("must not run")))
    assert poc.main() == 2
    out = capsys.readouterr().out
    assert "NOT_EXECUTED" in out and '"stop_proof_verified": false' in out


def test_blocked_environment_cannot_attempt_systemd_start(monkeypatch):
    monkeypatch.setattr(poc, "inspect", lambda: {
        "eligible_for_poc": False, "blockers": ["USER_MANAGER_UNREACHABLE"]
    })
    monkeypatch.setattr(poc.subprocess, "Popen",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("unexpected spawn")))
    result, code = poc.run_poc()
    assert code == 2
    assert result["outcome"] == "BLOCKED_ENVIRONMENT"
    assert result["stop_proof_verified"] is False
    assert result["central_recovery_allowed"] is False


def test_internal_launcher_rejects_uncommitted_unit_before_systemd(monkeypatch, tmp_path):
    monkeypatch.setattr(poc, "inspect", lambda: (_ for _ in ()).throw(AssertionError("must not inspect")))
    monkeypatch.setattr(poc, "command", lambda *a, **kw:
                        (_ for _ in ()).throw(AssertionError("must not call systemd")))
    assert poc._start_service("other.service", tmp_path) == 4


def test_direct_payload_invocation_rejected_without_manifest(monkeypatch, tmp_path):
    monkeypatch.setattr(poc.subprocess, "Popen", lambda *a, **k:
                        (_ for _ in ()).throw(AssertionError("must not spawn")))
    assert poc._payload(tmp_path) == 4


def test_stop_requires_same_unit_id_group_and_invocation():
    expected = {"Id": "clpoc-aaa.service", "ControlGroup": "/user.slice/a.service",
                "InvocationID": "123456"}
    assert poc.same_unit_instance(dict(expected), expected) is True
    for field in expected:
        changed = dict(expected)
        changed[field] = "other"
        assert poc.same_unit_instance(changed, expected) is False
        missing = dict(expected)
        missing.pop(field)
        assert poc.same_unit_instance(missing, expected) is False


def test_process_identity_stop_check_is_unknown_on_reused_pid(monkeypatch):
    # state=R, starttime field22 = suffix field index19.
    fields = ["R"] + ["0"] * 18 + ["12"]
    monkeypatch.setattr(poc.Path, "read_text", lambda self, **kw: "999 (worker) " + " ".join(fields))
    assert poc.process_executing_by_identity(999, 12) is True
    assert poc.process_executing_by_identity(999, 13) is None
    fields[0] = "Z"
    assert poc.process_executing_by_identity(999, 12) is False


def test_process_identity_stop_check_denied_is_unknown(monkeypatch):
    def unreadable(self, **kwargs):
        raise PermissionError("no access")
    monkeypatch.setattr(poc.Path, "read_text", unreadable)
    assert poc.process_executing_by_identity(999, 12) is None


def test_process_identity_stop_check_missing_is_not_alive(monkeypatch):
    def missing(self, **kwargs):
        raise FileNotFoundError("gone")
    monkeypatch.setattr(poc.Path, "read_text", missing)
    assert poc.process_executing_by_identity(999, 12) is False


def test_original_cgroup_pinned_handle_reads_actual_events():
    from io import StringIO
    handle = StringIO("populated 1\nfrozen 0\n")
    assert poc.cg_populated_from_pinned_handle(handle) == 1
    handle.seek(0)
    handle.truncate(0)
    handle.write("populated 0\nfrozen 0\n")
    assert poc.cg_populated_from_pinned_handle(handle) == 0
    handle.close()
    assert poc.cg_populated_from_pinned_handle(handle) is None


def test_cgroup_pinned_handle_never_infers_missing_or_corrupt_state():
    from io import StringIO
    for data in ("", "frozen 0\n", "populated unknown\n", "populated 9\n"):
        assert poc.cg_populated_from_pinned_handle(StringIO(data)) is None


def test_cgroup_event_fd_never_infers_missing_as_empty(tmp_path):
    import os
    path = tmp_path / "events"
    path.write_text("populated 1\nfrozen 0\n", encoding="ascii")
    with path.open("rb", buffering=0) as handle:
        fd = handle.fileno()
        assert poc.read_cgroup_events_fd(fd) == 1
        path.write_text("populated 0\nfrozen 0\n", encoding="ascii")
        assert poc.read_cgroup_events_fd(fd) == 0
        path.write_text("populated lost\n", encoding="ascii")
        assert poc.read_cgroup_events_fd(fd) is None
    # Calling handle.fileno() after close raises ValueError in Python itself.
    # Preserve the integer descriptor to exercise our actual fail-closed read.
    assert poc.read_cgroup_events_fd(fd) is None


def test_cgroup_zero_before_arm_does_not_count_as_stop_proof(tmp_path):
    path = tmp_path / "events"
    path.write_text("populated 0\n", encoding="ascii")
    with path.open("rb", buffering=0) as handle:
        observer = poc.CgroupEventObserver(handle.fileno())
        observer._sample("before_stop")
        assert observer.observed_empty is False
        assert observer.arm_stop() is False
        assert observer.observed_empty is False
        assert observer.evidence()[-1]["after_stop_armed"] is False
        observer.close()


def test_cgroup_zero_observed_after_live_arm_is_only_local_evidence(tmp_path):
    path = tmp_path / "events"
    path.write_text("populated 1\n", encoding="ascii")
    with path.open("rb", buffering=0) as handle:
        observer = poc.CgroupEventObserver(handle.fileno())
        assert observer.arm_stop() is True
        assert observer.observed_empty is False
        path.write_text("populated 0\n", encoding="ascii")
        observer._sample("after_stop_armed")
        assert observer.observed_empty is True
        assert observer.evidence()[-1]["after_stop_armed"] is True
        observer.close()


def test_cgroup_observer_post_arm_unreadable_must_hold(tmp_path):
    path = tmp_path / "events"
    path.write_text("populated 1\n", encoding="ascii")
    with path.open("rb", buffering=0) as handle:
        observer = poc.CgroupEventObserver(handle.fileno())
        observer.arm_stop()
        assert observer.observed_empty is False
        observer._sample("first")
        path.write_text("populated unexpected\n", encoding="ascii")
        observer._sample("unreadable")
        assert observer.observed_empty is False
        assert observer.evidence()[-1]["populated"] is None
        observer.close()


def test_cgroup_observer_not_started_when_initial_state_unknown(tmp_path, monkeypatch):
    path = tmp_path / "events"
    path.write_text("populated 9\n", encoding="ascii")
    with path.open("rb", buffering=0) as handle:
        observer = poc.CgroupEventObserver(handle.fileno())
        monkeypatch.setattr(observer._thread, "start",
                            lambda: (_ for _ in ()).throw(AssertionError("must not start")))
        assert observer.start() is False
        assert observer.observed_empty is False
        observer.close()


def test_nested_cpu_child_script_is_valid_python_and_starts_a_new_session():
    source = poc.nested_child_script()
    compile(source, "<isolated-cpu-descendant>", "exec")
    assert "start_new_session=True" in source
    assert "grandchild.json" in source
    assert "leaf.wait()" in source


def test_three_process_tree_requires_lineage_sessions_ticks_and_cgroup(monkeypatch):
    ids = {
        "parent_pid": 100, "parent_ticks": 11,
        "child_pid": 200, "child_ticks": 22,
        "grandchild_pid": 300, "grandchild_ticks": 33,
    }
    parents = {200: 100, 300: 200}
    sessions = {200: 200, 300: 300}
    ticks = {100: 11, 200: 22, 300: 33}
    membership = {100: True, 200: True, 300: True}
    monkeypatch.setattr(poc, "proc_parent_pid", lambda pid: parents[pid])
    monkeypatch.setattr(poc.os, "getsid", lambda pid: sessions[pid])
    monkeypatch.setattr(poc, "proc_start_ticks", lambda pid: ticks[pid])
    monkeypatch.setattr(poc, "process_in_cgroup",
                        lambda pid, group: group == "/test.service" and membership[pid])
    assert poc.descendant_tree_bound(100, ids, "/test.service") is True
    assert poc.descendant_tree_bound(100, ids, "/other.service") is False
    parents[300] = 999
    assert poc.descendant_tree_bound(100, ids, "/test.service") is False
    parents[300] = 200
    sessions[300] = 200
    assert poc.descendant_tree_bound(100, ids, "/test.service") is False
    sessions[300] = 300
    ticks[300] = 44
    assert poc.descendant_tree_bound(100, ids, "/test.service") is False
    ticks[300] = 33
    membership[300] = False
    assert poc.descendant_tree_bound(100, ids, "/test.service") is False


def test_three_process_tree_rejects_duplicate_pid_and_missing_generation(monkeypatch):
    ids = {"parent_pid": 100, "parent_ticks": 1,
           "child_pid": 200, "child_ticks": 2,
           "grandchild_pid": 200, "grandchild_ticks": 3}
    assert poc.descendant_tree_bound(100, ids, "/test.service") is False
    ids["grandchild_pid"] = 300
    ids.pop("grandchild_ticks")
    assert poc.descendant_tree_bound(100, ids, "/test.service") is False


def test_cgroup_event_repopulation_invalidates_earlier_empty_signal(tmp_path):
    path = tmp_path / "events"
    path.write_text("populated 1\n", encoding="ascii")
    with path.open("rb", buffering=0) as handle:
        observer = poc.CgroupEventObserver(handle.fileno())
        assert observer.arm_stop() is True
        path.write_text("populated 0\n", encoding="ascii")
        observer._sample("stopped")
        assert observer.observed_empty is True
        path.write_text("populated 1\n", encoding="ascii")
        observer._sample("repopulated")
        assert observer.observed_empty is False
        assert observer.evidence()[-1]["populated"] == 1
        observer.close()


def test_proc_parent_pid_uses_parent_field_not_process_group(monkeypatch):
    monkeypatch.setattr(poc.Path, "read_text",
                        lambda self, **kw: "321 (cpu worker) R 123 456 789 0 0 0")
    assert poc.proc_parent_pid(321) == 123

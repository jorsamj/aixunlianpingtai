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

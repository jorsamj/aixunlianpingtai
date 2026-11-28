"""Test-only root-supervisor trust boundary contract; no users/systemd started."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parent))
import linux_supervisor_privilege_probe as p


def test_cli_inert_without_two_opt_in_flags(monkeypatch,capsys):
    monkeypatch.setattr(sys,"argv",["probe"])
    monkeypatch.setattr(p,"_run_trial",lambda: (_ for _ in ()).throw(
        AssertionError("probe must remain inert")))
    assert p.main()==2
    assert "INERT_OPT_IN_REQUIRED" in capsys.readouterr().out


def test_non_disposable_host_denied_before_creating_accounts(monkeypatch):
    monkeypatch.setattr(p,"_only_disposable_host",lambda:False)
    monkeypatch.setattr(p,"_run",lambda *_a,**_kw: (_ for _ in ()).throw(
        AssertionError("must not issue OS commands")))
    result,code=p._run_trial()
    assert code==2
    assert result["production_recovery_allowed"] is False
    assert result["privilege_boundary_verified"] is False


def test_secret_mode_root_only_and_ed25519_signature_roundtrip(tmp_path):
    key,secret=p._write_secret(tmp_path/"root-private")
    assert os.stat(secret).st_mode & 0o777 == 0o600
    assert os.stat(secret.parent).st_mode & 0o777 == 0o700
    payload={"challenge_id":"abc","task_id":"synthetic","execution_generation":3}
    signed=p._payload_signature(payload,key)
    check=p._public_verifier(key)
    assert check(signed)
    signed["payload"]["execution_generation"]=4
    assert check(signed) is False


def test_other_signer_is_rejected(tmp_path):
    signer_a,_=p._write_secret(tmp_path/"key_a")
    signer_b,_=p._write_secret(tmp_path/"key_b")
    message=p._payload_signature({"nonce":"one-time"},signer_a)
    assert p._public_verifier(signer_a)(message)
    assert not p._public_verifier(signer_b)(message)
    message["signature"]="not-hex"
    assert not p._public_verifier(signer_a)(message)


@pytest.mark.parametrize("field",[
    "Id","ControlGroup","InvocationID","User"
])
def test_systemd_unit_identity_reuse_fails_closed(field):
    original={"Id":"clpoc-"+"a"*24+".service",
              "ControlGroup":"/system.slice/clpoc-"+"a"*24+".service",
              "InvocationID":"f"*32,
              "User":"isolated-workload"}
    assert p._loaded_same_unit(dict(original),original)
    changed=dict(original)
    changed[field]="replaced"
    assert not p._loaded_same_unit(changed,original)
    changed.pop(field)
    assert not p._loaded_same_unit(changed,original)


def test_systemd_missing_identity_never_matches():
    assert not p._loaded_same_unit({}, {})
    assert not p._loaded_same_unit({"Id":"x"},{"Id":"x","User":"worker"})


def test_main_with_flags_denies_non_host(monkeypatch,capsys):
    monkeypatch.setattr(sys,"argv",["probe","--run","--github-ephemeral-only"])
    monkeypatch.setattr(p,"_only_disposable_host",lambda:False)
    assert p.main()==2
    result=json.loads(capsys.readouterr().out)
    assert result["outcome"]=="DISPOSABLE_GITHUB_HOST_REQUIRED_HOLD"
    assert result["production_recovery_allowed"] is False


def test_workload_attempts_real_ancestor_cgroup_migration_and_key_read():
    # Unit fixture deliberately performs the dangerous movement attempt ONLY
    # inside the disposable GitHub VM. Here we verify the code has both checks.
    assert "ancestor.open('w')" in p.WORKLOAD_CODE
    assert "key.read_bytes()" in p.WORKLOAD_CODE
    assert "start_new_session=True" in p.WORKLOAD_CODE


def test_agent_checks_all_root_control_paths():
    assert "systemctl" in p.AGENT_CODE
    assert "'--system'" in p.AGENT_CODE
    assert "'sudo'" in p.AGENT_CODE
    assert "os.kill(pid,0)" in p.AGENT_CODE
    assert "key.read_bytes()" in p.AGENT_CODE

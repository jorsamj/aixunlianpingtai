"""P0-01C-3B-3 pure Unix peercred admission contract; no root/systemd."""
import json
import os
from pathlib import Path
import socket
import sys
import time

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parent))
import linux_supervisor_ipc_probe as ipc


def fixture():
    unit="clpoc-"+"a"*24+".service"
    scope={
        "task_id":"poc-task-"+"b"*24,
        "execution_generation":3,
        "unit":unit,
        "boot_id":"01234567-89ab-cdef-0123-456789abcdef",
        "invocation_id":"d"*32,
        "challenge_id":"c"*32,
        "nonce":"fresh-"+"e"*32,
    }
    return ipc.AdmissionGate(1001,scope,100_000_000,
                             ttl_ns=1_000_000_000), {"action":"request_stop_admission",**scope}


def test_registered_agent_may_request_admission_once_only():
    gate,request=fixture()
    accepted=gate.check(request,1001,101_000_000)
    assert accepted=={"ok":True,"reason":"ADMISSION_CHECK_ONLY_NO_STOP_PROOF"}
    assert gate.consumed is True
    assert gate.check(request,1001,101_000_001)=={
        "ok":False,"reason":"CHALLENGE_ALREADY_CONSUMED"}


@pytest.mark.parametrize("actor",[1002,0,-1,True,None,"1001"])
def test_kernel_peer_credentials_must_match_exact_uid(actor):
    gate,request=fixture()
    assert gate.check(request,actor,101_000_000)=={
        "ok":False,"reason":"PEER_UID_NOT_AUTHORIZED"}
    assert gate.consumed is False


@pytest.mark.parametrize("modification",[
    {"task_id":"poc-task-"+"f"*24},
    {"execution_generation":4},
    {"execution_generation":True},
    {"execution_generation":3.0},
    {"execution_generation":"3"},
    {"execution_generation":0},
    {"unit":"clpoc-"+"f"*24+".service"},
    {"boot_id":"ffffffff-ffff-ffff-ffff-ffffffffffff"},
    {"invocation_id":"e"*32},
    {"challenge_id":"0"*32},
    {"nonce":"previous-generation"},
])
def test_scope_mismatch_or_incorrect_generation_must_hold(modification):
    gate,request=fixture()
    assert gate.check({**request,**modification},1001,101_000_000)["ok"] is False
    assert gate.consumed is False


@pytest.mark.parametrize("input_payload",[
    {},None,1,[],["request_stop_admission"],
    {"action":"request_stop_admission"},
    {"action":"request_stop_admission","unit":"any"},
])
def test_missing_or_invalid_shape_must_hold(input_payload):
    gate,_=fixture()
    assert gate.check(input_payload,1001,101_000_000)["ok"] is False
    assert gate.consumed is False


def test_extra_field_cannot_request_arbitrary_command_or_uid_override():
    gate,request=fixture()
    assert gate.check({**request,"shell":"/bin/sh"},1001,101_000_000)=={
        "ok":False,"reason":"REQUEST_SHAPE_INVALID"}
    assert gate.check({**request,"peer_uid":1001},1002,101_000_000)["ok"] is False
    assert gate.consumed is False


@pytest.mark.parametrize("action",["stop_any_unit","kill_pid","sign_receipt","exec",""])
def test_no_shell_or_stop_api_exposed(action):
    gate,request=fixture()
    assert gate.check({**request,"action":action},1001,101_000_000)=={
        "ok":False,"reason":"METHOD_NOT_ALLOWED"}
    assert gate.consumed is False


@pytest.mark.parametrize("clock",[-1,0,99_999_999,1_100_000_000,
                                     1_100_000_001,True,None])
def test_expired_clock_replay_and_type_confusion_denied(clock):
    gate,request=fixture()
    assert gate.check(request,1001,clock)["ok"] is False
    assert gate.consumed is False


def test_socket_real_kernel_so_peercred_current_uid_only(tmp_path,monkeypatch):
    if not hasattr(socket,"SO_PEERCRED") or os.name!="posix":
        pytest.skip("Linux SO_PEERCRED only")
    gate,request=fixture()
    gate.agent_uid=os.getuid()
    gate.issued_ns=time.monotonic_ns()
    # Test runs without elevated privileges. Root ownership is validated
    # separately on GitHub-hosted VM, not simulated here.
    monkeypatch.setattr(ipc.os,"chown",lambda *_args:None)
    endpoint=tmp_path/"root-admission.sock"
    server=ipc.RootAdmissionSocket(endpoint,os.getgid(),gate)
    assert server.start()
    try:
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as sock:
            sock.settimeout(3)
            sock.connect(str(endpoint))
            sock.sendall(json.dumps(request).encode())
            sock.shutdown(socket.SHUT_WR)
            reply=json.loads(sock.recv(4096))
        assert reply=={"ok":True,"reason":"ADMISSION_CHECK_ONLY_NO_STOP_PROOF"}
        assert gate.consumed
    finally:
        server.close()


def test_client_and_unbound_cpu_script_compile():
    compile(ipc.CLIENT,"<agent-client>","exec")
    compile(ipc.UNBOUND_CPU,"<unbound-cpu>","exec")
    assert "socket.SO_PEERCRED" in open(ipc.__file__,encoding="utf-8").read()
    assert "time.sleep(23)" in ipc.UNBOUND_CPU


def test_inert_without_both_cli_flags(monkeypatch,capsys):
    monkeypatch.setattr(sys,"argv",["ipc-probe"])
    monkeypatch.setattr(ipc,"_run_trial",lambda: (_ for _ in ()).throw(
        AssertionError("must not spawn")))
    assert ipc.main()==2
    assert "INERT_OPT_IN_REQUIRED" in capsys.readouterr().out


def test_refuses_non_disposable_host_before_root_operations(monkeypatch):
    monkeypatch.setattr(ipc.prior,"_only_disposable_host",lambda:False)
    monkeypatch.setattr(ipc.prior,"_run",lambda *_args,**_kw: (_ for _ in ()).throw(
        AssertionError("must not create users or processes")))
    outcome,code=ipc._run_trial()
    assert code==2
    assert outcome["production_recovery_allowed"] is False
    assert outcome["real_stop_proof_implemented"] is False
    assert outcome["outcome"]=="GITHUB_EPHEMERAL_UBUNTU_ONLY_HOLD"

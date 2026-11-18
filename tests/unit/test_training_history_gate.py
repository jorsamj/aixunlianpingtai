import json
import threading
import time

import pytest
from platform_core.training_history_gate import request_history_gate, service_history_gate

B = dict(task_id="task", attempt=2, snapshot_id="snapshot", payload_ref="payload/ref")


@pytest.mark.parametrize("allowed", [True, False])
def test_thread_handshake_and_duplicate(tmp_path, allowed):
    calls = []
    outcomes = []
    def worker():
        try:
            outcomes.append(request_history_gate(tmp_path, **B, timeout=2))
        except Exception as error:
            outcomes.append(error)
    thread = threading.Thread(target=worker)
    thread.start()
    deadline = time.monotonic() + 2
    while not (tmp_path / "request.json").exists() and time.monotonic() < deadline:
        time.sleep(.005)
    def check():
        calls.append(1)
        return dict(B, allowed=allowed)
    response = service_history_gate(tmp_path, **B, check_callback=check)
    assert response["allowed"] is allowed
    assert service_history_gate(tmp_path, **B, check_callback=check) == response
    thread.join(3)
    assert not thread.is_alive()
    assert calls == [1]
    assert len(outcomes) == 1
    assert isinstance(outcomes[0], dict if allowed else ValueError)


def test_wrong_binding_rejected(tmp_path):
    (tmp_path / "request.json").write_text(json.dumps(dict(B, attempt=3, nonce="a" * 32, timestamp=time.time())))
    with pytest.raises(ValueError, match="binding"):
        service_history_gate(tmp_path, **B, check_callback=lambda: pytest.fail("called"))


def test_timeout_fails_closed(tmp_path):
    with pytest.raises(TimeoutError):
        request_history_gate(tmp_path, **B, timeout=.03)


@pytest.mark.parametrize("raw", ["[]", "{" , "x" * 8193])
def test_malformed_request_rejected(tmp_path, raw):
    (tmp_path / "request.json").write_text(raw)
    with pytest.raises(ValueError):
        service_history_gate(tmp_path, **B, check_callback=lambda: pytest.fail("called"))


@pytest.mark.parametrize("offset", [-61, 6])
def test_stale_or_future_request_rejected(tmp_path, offset):
    (tmp_path / "request.json").write_text(json.dumps(dict(B, nonce="a" * 32, timestamp=time.time()+offset)))
    with pytest.raises(ValueError, match="expired"):
        service_history_gate(tmp_path, **B, check_callback=lambda: pytest.fail("called"))


def test_completed_request_does_not_expire_monitor_or_authorize_replay(tmp_path,monkeypatch):
    import platform_core.training_history_gate as gate
    from types import SimpleNamespace
    monkeypatch.setattr(gate.time,'time',lambda:1000)
    (tmp_path/'request.json').write_text(json.dumps(dict(B,nonce='a'*32,timestamp=1000)))
    response=service_history_gate(tmp_path,**B,check_callback=lambda:dict(B,allowed=True))
    monkeypatch.setattr(gate.time,'time',lambda:1090)
    assert service_history_gate(tmp_path,**B,check_callback=lambda:pytest.fail('re-authorized'))==response
    # Even a forced nonce collision cannot make the consumer accept an expired
    # response: skipping completed monitor work does not confer fresh authority.
    monkeypatch.setattr(gate,'uuid4',lambda:SimpleNamespace(hex='a'*32))
    with pytest.raises(ValueError,match='expired'):
        request_history_gate(tmp_path,**B,timeout=.1)

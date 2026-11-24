"""Real ``node_agent.py`` restart boundary (cross-platform fail-closed variant).

The production Agent entrypoint is started as a real OS child process against a
staged runtime root.  Once the training worker identity is durable, the Agent is
stopped with an ordinary process termination request and a *new* real Agent
process is started against the same state directory.

Windows: the restarted Agent must fail closed (no Job Object descendant stop
proof) — no new claim, identity retained, heartbeat error published.
POSIX: the first Agent performs its ordinary graceful shutdown, but the durable
dual-slot intent still requires central reconciliation, so the restarted Agent
must not advertise capabilities or claim new work.

The scenario itself lives in ``_real_agent_crash_recovery_support`` so the
POSIX-only full-chain file can run the same cross-platform contract.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_support():
    """Load the sibling harness by path (tests are not a Python package)."""
    name = "real_agent_crash_recovery_e2e_support"
    cached = sys.modules.get(name)
    if cached is not None:
        return cached
    path = Path(__file__).with_name("_real_agent_crash_recovery_support.py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


support = _load_support()


def test_real_agent_restart_is_fail_closed_without_stop_proof(tmp_path):
    support.run_restart_fail_closed_scenario(tmp_path)

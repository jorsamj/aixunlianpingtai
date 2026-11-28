"""P0-01C-3B-4: guarantees dummy DAC experiment cannot be mistaken for GPU."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gpu_device_acl_shadow_probe as probe


def test_dac_test_script_valid_python():
    compile(probe._READ_ATTEMPT, "<dummy-file-read-test>", "exec")


def test_inert_by_default_without_flags(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["gpu-shadow"])
    monkeypatch.setattr(probe, "run_shadow_probe",
                        lambda: (_ for _ in ()).throw(
                            AssertionError("MUST_NOT_TOUCH_HOST")))
    assert probe.main() == 2
    assert "INERT_OPT_IN_REQUIRED" in capsys.readouterr().out


def test_only_disposable_vm_can_create_users_or_files(monkeypatch):
    monkeypatch.setattr(probe.prior, "_only_disposable_host", lambda: False)
    monkeypatch.setattr(probe.prior, "_run",
                        lambda *args, **kwargs: (_ for _ in ()).throw(
                            AssertionError("NO_OS_COMMANDS_ALLOWED")))
    result, code = probe.run_shadow_probe()
    assert code == 2
    assert result["outcome"] == "GITHUB_EPHEMERAL_ROOT_PRECONDITION_HOLD"
    assert result["actual_cuda_or_gpu_device_tested"] is False
    assert result["production_recovery_allowed"] is False


def test_shadow_probe_always_declares_not_real_gpu(monkeypatch):
    monkeypatch.setattr(probe.prior, "_only_disposable_host", lambda: False)
    out, _ = probe.run_shadow_probe()
    assert out["actual_cuda_or_gpu_device_tested"] is False
    assert out["actual_ascend_or_rockchip_device_tested"] is False
    assert out["production_gpu_isolation_verified"] is False


def test_no_real_gpu_device_or_systemd_unit_used():
    source = Path(probe.__file__).read_text(encoding="utf-8")
    assert "os.mknod(" not in source
    assert "systemd-run" not in source
    assert "nvidia-smi" not in source
    assert "import torch" not in source
    assert "FAKE_FILE_DAC_COUNTEREXAMPLE_PASS_REAL_GPU_NOT_VERIFIED" in source

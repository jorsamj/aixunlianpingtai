from pathlib import Path
import sys

import pytest

import launcher


def test_torch_runtime_probe_accepts_usable_cuda_pair_with_different_versions(monkeypatch):
    """A working CUDA runtime is usable even when it is not the pinned release pair."""
    monkeypatch.setattr(
        launcher,
        "run_check",
        lambda *args, **kwargs: (
            True,
            'TORCH_PROBE_JSON:{"torch_version":"2.8.0+cu128","torchvision_version":"0.23.0+cu128",'
            '"cuda_available":true,"cuda_version":"12.8"}',
            "",
        ),
    )

    probe = launcher.torch_runtime_probe(Path("python"))

    assert probe == {
        "usable": True,
        "pinned_pair": False,
        "torch_version": "2.8.0+cu128",
        "torchvision_version": "0.23.0+cu128",
        "cuda_available": True,
        "cuda_version": "12.8",
        "error": "",
    }


def test_torch_runtime_probe_finds_prefixed_json_between_subprocess_noise(monkeypatch):
    monkeypatch.setattr(
        launcher,
        "run_check",
        lambda *args, **kwargs: (
            True,
            "torch startup diagnostic\n"
            "TORCH_PROBE_JSON:{\"torch_version\":\"2.12.1\",\"torchvision_version\":\"0.27.1\","
            "\"cuda_available\":false,\"cuda_version\":null}\n"
            "trailing warning",
            "",
        ),
    )

    probe = launcher.torch_runtime_probe(Path("python"))

    assert probe == {
        "usable": True,
        "pinned_pair": True,
        "torch_version": "2.12.1",
        "torchvision_version": "0.27.1",
        "cuda_available": False,
        "cuda_version": "",
        "error": "",
    }


def test_torch_runtime_probe_does_not_accept_unprefixed_json(monkeypatch):
    monkeypatch.setattr(
        launcher,
        "run_check",
        lambda *args, **kwargs: (
            True,
            '{"torch_version":"2.12.1","torchvision_version":"0.27.1",'
            '"cuda_available":false,"cuda_version":null}',
            "",
        ),
    )

    probe = launcher.torch_runtime_probe(Path("python"))

    assert probe["usable"] is False
    assert probe["cuda_available"] is False
    assert "无法解析 PyTorch runtime probe JSON" in probe["error"]


@pytest.mark.parametrize(
    "payload",
    [
        '{"torch_version":"2.12.1","torchvision_version":"0.27.1","cuda_available":"false","cuda_version":null}',
        "[]",
        '{"torch_version":"","torchvision_version":"0.27.1","cuda_available":false,"cuda_version":null}',
        '{"torch_version":"2.12.1","torchvision_version":"0.27.1","cuda_available":false,"cuda_version":128}',
    ],
)
def test_torch_runtime_probe_rejects_invalid_runtime_schema(monkeypatch, payload):
    monkeypatch.setattr(
        launcher,
        "run_check",
        lambda *args, **kwargs: (True, f"TORCH_PROBE_JSON:{payload}", ""),
    )

    probe = launcher.torch_runtime_probe(Path("python"))

    assert probe["usable"] is False
    assert probe["cuda_available"] is False
    assert "无法解析 PyTorch runtime probe JSON" in probe["error"]


def test_torch_runtime_probe_uses_the_target_python_subprocess(tmp_path, monkeypatch):
    (tmp_path / "torch.py").write_text(
        """__version__ = '2.12.1+cu128'
class _Cuda:
    @staticmethod
    def is_available():
        return True
cuda = _Cuda()
class _Version:
    cuda = '12.8'
version = _Version()
""",
        encoding="utf-8",
    )
    torchvision = tmp_path / "torchvision"
    torchvision.mkdir()
    (torchvision / "__init__.py").write_text(
        "__version__ = '0.27.1+cu128'\n", encoding="utf-8"
    )
    (torchvision / "ops.py").write_text(
        "def nms(*args, **kwargs):\n    return None\n", encoding="utf-8"
    )
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))

    probe = launcher.torch_runtime_probe(Path(sys.executable))

    assert probe == {
        "usable": True,
        "pinned_pair": True,
        "torch_version": "2.12.1+cu128",
        "torchvision_version": "0.27.1+cu128",
        "cuda_available": True,
        "cuda_version": "12.8",
        "error": "",
    }


def test_torch_runtime_probe_reports_a_missing_nms_from_the_target_python(tmp_path, monkeypatch):
    (tmp_path / "torch.py").write_text(
        """__version__ = '2.12.1+cu128'
class _Cuda:
    @staticmethod
    def is_available():
        return True
cuda = _Cuda()
class _Version:
    cuda = '12.8'
version = _Version()
""",
        encoding="utf-8",
    )
    torchvision = tmp_path / "torchvision"
    torchvision.mkdir()
    (torchvision / "__init__.py").write_text(
        "__version__ = '0.27.1+cu128'\n", encoding="utf-8"
    )
    (torchvision / "ops.py").write_text(
        "def another_op():\n    return None\n", encoding="utf-8"
    )
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))

    probe = launcher.torch_runtime_probe(Path(sys.executable))

    assert probe["usable"] is False
    assert "cannot import name 'nms'" in probe["error"]


def test_torch_runtime_probe_reports_the_actual_import_failure(monkeypatch):
    monkeypatch.setattr(
        launcher,
    "run_check",
        lambda *args, **kwargs: (False, "partial stdout", "torchvision nms import failed"),
    )

    probe = launcher.torch_runtime_probe(Path("python"))

    assert probe["usable"] is False
    assert probe["cuda_available"] is False
    assert probe["error"] == "torchvision nms import failed"


@pytest.mark.parametrize(
    ("usable", "pinned_pair", "expected"),
    [(True, True, True), (False, True, False), (True, False, False)],
)
def test_torch_pair_ready_remains_pinned_compatibility_wrapper(
    monkeypatch, usable, pinned_pair, expected
):
    monkeypatch.setattr(
        launcher,
        "torch_runtime_probe",
        lambda py: {
            "usable": usable,
            "pinned_pair": pinned_pair,
            "torch_version": "2.12.1+cu128",
            "torchvision_version": "0.27.1+cu128",
        },
    )

    assert launcher._torch_pair_ready(Path("python")) is expected


def test_torch_pair_ready_logs_versions_when_the_pinned_pair_is_usable(monkeypatch):
    messages = []
    monkeypatch.setattr(
        launcher,
        "torch_runtime_probe",
        lambda py: {
            "usable": True,
            "pinned_pair": True,
            "torch_version": "2.12.1+cu128",
            "torchvision_version": "0.27.1+cu128",
        },
    )
    monkeypatch.setattr(launcher, "say", messages.append)

    assert launcher._torch_pair_ready(Path("python")) is True
    assert messages == ["      PyTorch 已可用，跳过重复下载：2.12.1+cu128 0.27.1+cu128"]


@pytest.mark.parametrize("output", ["", "not JSON"])
def test_torch_runtime_probe_reports_malformed_json(monkeypatch, output):
    monkeypatch.setattr(
        launcher,
        "run_check",
        lambda *args, **kwargs: (True, f"TORCH_PROBE_JSON:{output}", ""),
    )

    probe = launcher.torch_runtime_probe(Path("python"))

    assert probe["usable"] is False
    assert probe["cuda_available"] is False
    assert "无法解析 PyTorch runtime probe JSON" in probe["error"]


def test_windows_cpu_install_route_keeps_pinned_packages_and_cpu_index(monkeypatch):
    """Keep the pre-existing Windows recovery route while Task 2 owns platform policy."""
    commands = []
    monkeypatch.setattr(launcher.sys, "platform", "win32")
    monkeypatch.setattr(launcher, "_torch_pair_ready", lambda py: False)
    monkeypatch.setattr(
        launcher,
        "_run_install",
        lambda command, label: commands.append((command, label)) or False,
    )

    with pytest.raises(RuntimeError, match="PyTorch CPU"):
        launcher.install_known_good_torch(Path("python"))

    assert commands
    first_command, first_label = commands[0]
    assert first_label == "PyTorch 官方 CPU 源"
    assert f"torch=={launcher.TORCH_VERSION}" in first_command
    assert f"torchvision=={launcher.TORCHVISION_VERSION}" in first_command
    assert ["--index-url", launcher.TORCH_CPU_INDEX] == first_command[-2:]

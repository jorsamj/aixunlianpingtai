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


def _probe(*, usable, pinned_pair, cuda_available=False, cuda_version=""):
    return {
        "usable": usable,
        "pinned_pair": pinned_pair,
        "torch_version": "2.8.0+cu128" if cuda_available else "2.8.0",
        "torchvision_version": "0.23.0+cu128" if cuda_available else "0.23.0",
        "cuda_available": cuda_available,
        "cuda_version": cuda_version,
        "error": "torch import failed" if not usable else "",
    }


def test_linux_reuses_a_usable_unpinned_cuda_runtime_without_installing(monkeypatch):
    commands = []
    messages = []
    monkeypatch.setattr(launcher.sys, "platform", "linux")
    monkeypatch.setattr(
        launcher,
        "torch_runtime_probe",
        lambda py: _probe(usable=True, pinned_pair=False, cuda_available=True, cuda_version="12.8"),
    )
    monkeypatch.setattr(launcher, "_run_install", lambda *args: commands.append(args) or True)
    monkeypatch.setattr(launcher, "say", messages.append)

    launcher.install_known_good_torch(Path("python"))

    assert commands == []
    assert any("2.8.0+cu128" in message and "12.8" in message for message in messages)


def test_linux_reuses_a_usable_cpu_runtime_without_replacing_it(monkeypatch):
    commands = []
    monkeypatch.setattr(launcher.sys, "platform", "linux")
    monkeypatch.setattr(
        launcher,
        "torch_runtime_probe",
        lambda py: _probe(usable=True, pinned_pair=False),
    )
    monkeypatch.setattr(launcher, "_run_install", lambda *args: commands.append(args) or True)

    launcher.install_known_good_torch(Path("python"))

    assert commands == []


def test_linux_reuses_a_usable_cpu_runtime_when_cuda_version_is_none(monkeypatch):
    commands = []
    monkeypatch.setattr(launcher.sys, "platform", "linux")
    monkeypatch.setattr(
        launcher,
        "torch_runtime_probe",
        lambda py: _probe(usable=True, pinned_pair=False, cuda_version=None),
    )
    monkeypatch.setattr(launcher, "_run_install", lambda *args: commands.append(args) or True)

    launcher.install_known_good_torch(Path("python"))

    assert commands == []


def test_linux_rejects_an_unusable_runtime_without_cpu_install_commands(monkeypatch):
    commands = []
    monkeypatch.setattr(launcher.sys, "platform", "linux")
    monkeypatch.setattr(
        launcher,
        "torch_runtime_probe",
        lambda py: _probe(usable=False, pinned_pair=False),
    )
    monkeypatch.setattr(launcher, "_run_install", lambda *args: commands.append(args) or True)

    with pytest.raises(RuntimeError, match="NVIDIA Linux"):
        launcher.install_known_good_torch(Path("python"))

    assert commands == []
    assert all(launcher.TORCH_CPU_INDEX not in command for command in commands)


def test_linux_rejects_an_incomplete_runtime_probe_without_installing(monkeypatch):
    commands = []
    monkeypatch.setattr(launcher.sys, "platform", "linux")
    monkeypatch.setattr(launcher, "torch_runtime_probe", lambda py: {})
    monkeypatch.setattr(launcher, "_run_install", lambda *args: commands.append(args) or True)

    with pytest.raises(RuntimeError, match="NVIDIA Linux"):
        launcher.install_known_good_torch(Path("python"))

    assert commands == []


def test_linux_rejects_a_usable_probe_missing_runtime_versions(monkeypatch):
    commands = []
    monkeypatch.setattr(launcher.sys, "platform", "linux")
    monkeypatch.setattr(
        launcher,
        "torch_runtime_probe",
        lambda py: {"usable": True, "pinned_pair": False},
    )
    monkeypatch.setattr(launcher, "_run_install", lambda *args: commands.append(args) or True)

    with pytest.raises(RuntimeError, match="NVIDIA Linux"):
        launcher.install_known_good_torch(Path("python"))

    assert commands == []


def test_windows_reuses_a_usable_pinned_runtime_without_installing(monkeypatch):
    commands = []
    monkeypatch.setattr(launcher.sys, "platform", "win32")
    monkeypatch.setattr(
        launcher,
        "torch_runtime_probe",
        lambda py: _probe(usable=True, pinned_pair=True),
    )
    monkeypatch.setattr(launcher, "_run_install", lambda *args: commands.append(args) or True)

    launcher.install_known_good_torch(Path("python"))

    assert commands == []


def test_windows_retries_cpu_index_until_post_install_probe_is_usable_and_pinned(monkeypatch):
    commands = []
    probes = iter(
        [
            _probe(usable=True, pinned_pair=False),
            _probe(usable=True, pinned_pair=False),
            _probe(usable=True, pinned_pair=True),
        ]
    )
    monkeypatch.setattr(launcher.sys, "platform", "win32")
    monkeypatch.setattr(launcher, "torch_runtime_probe", lambda py: next(probes))
    monkeypatch.setattr(
        launcher,
        "_run_install",
        lambda command, label: commands.append((command, label)) or True,
    )

    launcher.install_known_good_torch(Path("python"))

    assert len(commands) == 2
    first_command, first_label = commands[0]
    assert first_label == "PyTorch 官方 CPU 源"
    assert f"torch=={launcher.TORCH_VERSION}" in first_command
    assert f"torchvision=={launcher.TORCHVISION_VERSION}" in first_command
    assert ["--index-url", launcher.TORCH_CPU_INDEX] == first_command[-2:]
    assert launcher.TORCH_CPU_INDEX in commands[1][0]


def test_windows_accepts_a_ready_post_install_probe_after_a_failed_install_command(monkeypatch):
    commands = []
    probes = iter(
        [
            _probe(usable=False, pinned_pair=False),
            _probe(usable=True, pinned_pair=True),
        ]
    )
    monkeypatch.setattr(launcher.sys, "platform", "win32")
    monkeypatch.setattr(launcher, "torch_runtime_probe", lambda py: next(probes))
    monkeypatch.setattr(
        launcher,
        "_run_install",
        lambda command, label: commands.append((command, label)) or False,
    )

    launcher.install_known_good_torch(Path("python"))

    assert len(commands) == 1


def test_windows_raises_when_no_install_attempt_produces_a_usable_pinned_runtime(monkeypatch):
    commands = []
    probes = iter(
        [
            _probe(usable=False, pinned_pair=False),
            _probe(usable=True, pinned_pair=False),
            _probe(usable=False, pinned_pair=False),
        ]
    )
    monkeypatch.setattr(launcher.sys, "platform", "win32")
    monkeypatch.setattr(launcher, "torch_runtime_probe", lambda py: next(probes))
    monkeypatch.setattr(
        launcher,
        "_run_install",
        lambda command, label: commands.append((command, label)) or True,
    )

    with pytest.raises(RuntimeError, match="PyTorch CPU"):
        launcher.install_known_good_torch(Path("python"))

    assert len(commands) == 2


def test_windows_reports_the_last_post_install_probe_error_after_failed_attempts(monkeypatch):
    commands = []
    probe_calls = []
    initial_probe = _probe(usable=False, pinned_pair=False)
    first_post_install_probe = _probe(usable=False, pinned_pair=False)
    last_post_install_probe = _probe(usable=False, pinned_pair=False)
    last_post_install_probe["error"] = "last probe diagnostic"
    probes = iter([initial_probe, first_post_install_probe, last_post_install_probe])

    def probe(py):
        probe_calls.append(py)
        return next(probes)

    monkeypatch.setattr(launcher.sys, "platform", "win32")
    monkeypatch.setattr(launcher, "torch_runtime_probe", probe)
    monkeypatch.setattr(
        launcher,
        "_run_install",
        lambda command, label: commands.append((command, label)) or False,
    )

    with pytest.raises(RuntimeError, match="安装或安装后校验失败.*last probe diagnostic"):
        launcher.install_known_good_torch(Path("python"))

    assert len(commands) == 2
    assert len(probe_calls) == 3


def test_windows_retries_after_an_incomplete_post_install_probe(monkeypatch):
    commands = []
    probes = iter(
        [
            _probe(usable=False, pinned_pair=False),
            {},
            {"usable": False},
        ]
    )
    monkeypatch.setattr(launcher.sys, "platform", "win32")
    monkeypatch.setattr(launcher, "torch_runtime_probe", lambda py: next(probes))
    monkeypatch.setattr(
        launcher,
        "_run_install",
        lambda command, label: commands.append((command, label)) or True,
    )

    with pytest.raises(RuntimeError, match="PyTorch CPU"):
        launcher.install_known_good_torch(Path("python"))

    assert len(commands) == 2

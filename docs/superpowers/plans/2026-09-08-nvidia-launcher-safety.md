# NVIDIA Launcher Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent the launcher from replacing a working NVIDIA Linux CUDA Torch environment with CPU wheels while preserving the verified Windows CPU bootstrap.

**Architecture:** Separate runtime usability probing from the Windows pinned-version policy. Reuse any working Linux Torch/TorchVision pair, require CUDA availability for the NVIDIA preservation branch, and prohibit the CPU wheel index on non-Windows hosts.

**Tech Stack:** Python subprocess probes, JSON, pathlib, pytest monkeypatch, existing launcher bootstrap.

---

## File map

- Modify `launcher.py`: structured Torch probe and platform-specific installation decision.
- Create `tests/unit/test_launcher_torch_policy.py`: Linux CUDA preservation, Linux missing-runtime block, Windows CPU compatibility.
- Keep `requirements.txt` unchanged in this plan; launcher controls whether pinned CPU wheels are installed.

### Task 1: Probe Torch capability without requiring pinned versions

**Files:**
- Modify: `launcher.py`
- Create: `tests/unit/test_launcher_torch_policy.py`

- [ ] **Step 1: Write failing probe-policy tests**

```python
from pathlib import Path

import launcher


def test_linux_cuda_runtime_is_reused_even_when_version_differs(monkeypatch):
    installs = []
    monkeypatch.setattr(launcher.sys, "platform", "linux")
    monkeypatch.setattr(launcher, "torch_runtime_probe", lambda _py: {
        "usable": True,
        "torch_version": "2.6.0+cu124",
        "torchvision_version": "0.21.0+cu124",
        "cuda_available": True,
        "cuda_version": "12.4",
    })
    monkeypatch.setattr(launcher, "_run_install", lambda command, label: installs.append((command, label)))
    launcher.install_known_good_torch(Path("python"))
    assert installs == []


def test_linux_never_uses_cpu_wheel_index(monkeypatch):
    monkeypatch.setattr(launcher.sys, "platform", "linux")
    monkeypatch.setattr(launcher, "torch_runtime_probe", lambda _py: {
        "usable": False, "cuda_available": False, "error": "torch missing",
    })
    calls = []
    monkeypatch.setattr(launcher, "_run_install", lambda command, label: calls.append(command))
    with pytest.raises(RuntimeError, match="NVIDIA Linux"):
        launcher.install_known_good_torch(Path("python"))
    assert calls == []


def test_windows_cpu_keeps_pinned_install_route(monkeypatch):
    monkeypatch.setattr(launcher.sys, "platform", "win32")
    probes = iter([
        {"usable": False, "cuda_available": False, "error": "missing"},
        {"usable": True, "pinned_pair": True, "cuda_available": False},
    ])
    monkeypatch.setattr(launcher, "torch_runtime_probe", lambda _py: next(probes))
    calls = []
    monkeypatch.setattr(launcher, "_run_install", lambda command, label: calls.append(command) or True)
    launcher.install_known_good_torch(Path("python"))
    assert any(launcher.TORCH_CPU_INDEX in command for command in calls)
```

- [ ] **Step 2: Run and verify the probe API is absent**

Run: `python -m pytest tests/unit/test_launcher_torch_policy.py -q`

Expected: FAIL with `AttributeError: module 'launcher' has no attribute 'torch_runtime_probe'`.

- [ ] **Step 3: Implement a structured subprocess probe**

```python
def torch_runtime_probe(py: Path) -> dict:
    code = (
        "import json, torch, torchvision; "
        "from torchvision.ops import nms; "
        "print(json.dumps({"
        "'torch_version': torch.__version__, "
        "'torchvision_version': torchvision.__version__, "
        "'cuda_available': bool(torch.cuda.is_available()), "
        "'cuda_version': torch.version.cuda"
        "}))"
    )
    ok, out, error = run_check(py, "PyTorch", code, timeout=60)
    if not ok:
        return {"usable": False, "cuda_available": False, "error": error or out}
    try:
        payload = json.loads(out.splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        return {"usable": False, "cuda_available": False, "error": str(exc)}
    torch_version = str(payload.get("torch_version") or "")
    vision_version = str(payload.get("torchvision_version") or "")
    return {
        **payload,
        "usable": True,
        "pinned_pair": (
            torch_version.split("+")[0] == TORCH_VERSION
            and vision_version.split("+")[0] == TORCHVISION_VERSION
        ),
    }
```

Add `import json` to `launcher.py`. Keep `_torch_pair_ready()` as a thin compatibility wrapper returning `probe["usable"] and probe["pinned_pair"]` for existing callers/tests.

- [ ] **Step 4: Run the focused probe tests**

Run: `python -m pytest tests/unit/test_launcher_torch_policy.py -q`

Expected: Windows policy may still fail until Task 2; structured probe assertions PASS.

- [ ] **Step 5: Commit**

```bash
git add launcher.py tests/unit/test_launcher_torch_policy.py
git commit -m "test: define cross-platform torch bootstrap policy"
```

### Task 2: Enforce platform-specific installation decisions

**Files:**
- Modify: `launcher.py`
- Modify: `tests/unit/test_launcher_torch_policy.py`

- [ ] **Step 1: Add a failing Linux usable-CPU preservation test**

```python
def test_linux_usable_torch_is_not_replaced_by_cpu_wheels(monkeypatch):
    monkeypatch.setattr(launcher.sys, "platform", "linux")
    monkeypatch.setattr(launcher, "torch_runtime_probe", lambda _py: {
        "usable": True, "pinned_pair": False,
        "torch_version": "2.6.0", "torchvision_version": "0.21.0",
        "cuda_available": False, "cuda_version": None,
    })
    calls = []
    monkeypatch.setattr(launcher, "_run_install", lambda command, label: calls.append(command))
    launcher.install_known_good_torch(Path("python"))
    assert calls == []
```

- [ ] **Step 2: Run and observe the old CPU reinstall decision**

Run: `python -m pytest tests/unit/test_launcher_torch_policy.py -q`

Expected: FAIL until `install_known_good_torch()` uses the structured probe.

- [ ] **Step 3: Implement the decision table**

```python
def install_known_good_torch(py: Path):
    probe = torch_runtime_probe(py)
    if sys.platform != "win32":
        if probe.get("usable"):
            cuda = probe.get("cuda_version") or "CPU"
            say(
                "      Linux 现有 PyTorch 可用，保持原环境："
                f"torch {probe.get('torch_version')} / CUDA {cuda}"
            )
            return
        raise RuntimeError(
            "NVIDIA Linux 环境未检测到可用 PyTorch/TorchVision；启动器不会安装 CPU Torch "
            "或修改 CUDA/Driver。请在服务器环境中安装与 CUDA 匹配的 PyTorch 后重试。"
        )

    if probe.get("usable") and probe.get("pinned_pair"):
        say("      Windows PyTorch CPU 组合已可用，跳过重复下载。")
        return

    say(f"      安装稳定 PyTorch CPU 组合：torch {TORCH_VERSION} + torchvision {TORCHVISION_VERSION}")
    base = _pip_common(py) + ["--upgrade", "--force-reinstall"]
    packages = [f"torch=={TORCH_VERSION}", f"torchvision=={TORCHVISION_VERSION}"]
    attempts = [
        ("PyTorch 官方 CPU 源", base + packages + ["--index-url", TORCH_CPU_INDEX]),
        ("PyTorch 官方 CPU 源（TLS 兼容模式）", base + packages + [
            "--index-url", TORCH_CPU_INDEX,
            "--trusted-host", "download.pytorch.org",
            "--trusted-host", "download-r2.pytorch.org",
        ]),
    ]
    for label, command in attempts:
        if _run_install(command, label):
            installed = torch_runtime_probe(py)
            if installed.get("usable") and installed.get("pinned_pair"):
                return
    raise RuntimeError(
        "PyTorch CPU 组件下载失败。请检查代理/防火墙是否拦截 download.pytorch.org，"
        "或稍后重新运行 start.bat。"
    )
```

- [ ] **Step 4: Run all launcher tests**

Run: `python -m pytest tests/unit/test_launcher_torch_policy.py tests/unit/test_launcher_workers.py -q`

Expected: all tests PASS, and every Linux test records zero install commands.

- [ ] **Step 5: Commit**

```bash
git add launcher.py tests/unit/test_launcher_torch_policy.py
git commit -m "fix: preserve linux cuda torch environments"
```

### Task 3: Verify launcher safety in full regression

**Files:**
- Modify: `docs/codex-handoff.md`

- [ ] **Step 1: Run syntax and focused unit checks**

Run: `python -m py_compile launcher.py`

Run: `python -m pytest tests/unit/test_launcher_torch_policy.py tests/unit/test_launcher_workers.py -q`

Expected: compile succeeds and all launcher tests PASS.

- [ ] **Step 2: Run the full backend suite**

Run: `python -m pytest -q`

Expected: exact pass/fail/skip totals are recorded; no failure is accepted as unrelated without root-cause evidence.

- [ ] **Step 3: Record the validated boundary**

Update `docs/codex-handoff.md` with:

- Windows CPU bootstrap regression result;
- subprocess-policy tests proving Linux never invokes the CPU index;
- whether a real Ubuntu/A800 host was used;
- if no real NVIDIA host was available, the explicit label `真实 NVIDIA CUDA 启动：未验证`.

- [ ] **Step 4: Commit the evidence note**

```bash
git add docs/codex-handoff.md
git commit -m "docs: record nvidia launcher safety evidence"
```


from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TRAINING_TASKS = ROOT / "platform_core" / "training_tasks.py"
ISOLATION_TEST = ROOT / "tests" / "unit" / "test_training_bundle_isolation.py"
WORKFLOW = ROOT / ".github" / "workflows" / "training-input-integrity.yml"
HANDOFF = ROOT / "docs" / "CODEX_HANDOFF_2026-09-16_DISCOVERY_TRAINING_INPUT_INTEGRATION.md"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def patch_training_tasks() -> None:
    text = TRAINING_TASKS.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "import yaml\nfrom PIL import Image, ImageFile, ImageOps, UnidentifiedImageError\n",
        "import psutil\nimport yaml\nfrom PIL import Image, ImageFile, ImageOps, UnidentifiedImageError\n",
        "training_tasks psutil import",
    )
    old = '''def _process_is_running(process_id: int) -> bool:\n    if process_id <= 0:\n        return False\n    try:\n        os.kill(process_id, 0)\n    except ProcessLookupError:\n        return False\n    except (PermissionError, OSError):\n        return True\n    return True\n'''
    new = '''def _process_is_running(process_id: int) -> bool:\n    if process_id <= 0:\n        return False\n    # POSIX commonly uses os.kill(pid, 0) as a non-signalling existence probe,\n    # but that contract is unsafe on Windows: signal value 0 is CTRL_C_EVENT\n    # there. Use psutil's cross-platform, non-signalling PID probe instead. A\n    # reused PID intentionally counts as live so orphan cleanup remains\n    # conservative and never deletes a temporary copy owned by another process.\n    return bool(psutil.pid_exists(int(process_id)))\n'''
    text = replace_once(text, old, new, "training_tasks process probe")
    TRAINING_TASKS.write_text(text, encoding="utf-8")


def patch_test() -> None:
    text = ISOLATION_TEST.read_text(encoding="utf-8")
    anchor = '''def test_cleanup_requires_work_boundary_and_keeps_live_owner_copy(tmp_path: Path):\n'''
    guard = '''def test_process_liveness_probe_never_sends_os_signal(monkeypatch: pytest.MonkeyPatch):\n    observed: list[int] = []\n\n    monkeypatch.setattr(\n        training_tasks.psutil,\n        "pid_exists",\n        lambda process_id: observed.append(int(process_id)) or True,\n    )\n    monkeypatch.setattr(\n        training_tasks.os,\n        "kill",\n        lambda *_args, **_kwargs: (_ for _ in ()).throw(\n            AssertionError("process liveness probe must never signal a process")\n        ),\n    )\n\n    assert training_tasks._process_is_running(43210) is True\n    assert observed == [43210]\n    assert training_tasks._process_is_running(0) is False\n    assert observed == [43210]\n\n\n'''
    text = replace_once(text, anchor, guard + anchor, "non-signalling regression guard")
    ISOLATION_TEST.write_text(text, encoding="utf-8")


def patch_workflow() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    text = text.replace(" --disable-plugin-autoload", "")
    text = text.replace(" --basetemp=.pytest-unit-tmp", "")
    text = text.replace(" --basetemp=.pytest-integration-tmp", "")
    if "--disable-plugin-autoload" in text or "--basetemp=" in text:
        raise RuntimeError("diagnostic pytest flags still present")
    WORKFLOW.write_text(text, encoding="utf-8")


def patch_handoff() -> None:
    text = HANDOFF.read_text(encoding="utf-8")
    appendix = '''\n## Windows PID-probe defect found during cross-platform acceptance\n\nThe new Windows training-input gate exposed a real platform bug rather than a test-only\nproblem. `training_tasks._process_is_running()` used the POSIX idiom\n`os.kill(pid, 0)`. On Windows, Python defines signal value `0` as `CTRL_C_EVENT`; it is\ntherefore not a safe, non-signalling PID-existence probe. The diagnostic parent process\nreceived `KeyboardInterrupt` while a child test exercised orphan-copy cleanup, proving\nthe production code path could emit a console control event on Windows.\n\nThe implementation now uses `psutil.pid_exists()` for a cross-platform, non-signalling\nprobe. A permanent unit guard replaces `os.kill` with a function that raises if called\nand verifies the liveness path uses only the psutil probe. The temporary diagnostic\nworkflow/helper used to isolate this issue must be removed after the permanent Windows\nand Ubuntu gates are green.\n'''
    if "## Windows PID-probe defect found during cross-platform acceptance" not in text:
        text += appendix
    HANDOFF.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    patch_training_tasks()
    patch_test()
    patch_workflow()
    patch_handoff()

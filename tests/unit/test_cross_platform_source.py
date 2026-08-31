import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCES = [
    *sorted((ROOT / "platform_core").rglob("*.py")),
    ROOT / "task_worker.py",
    ROOT / "train_worker.py",
    ROOT / "paddle_worker.py",
    ROOT / "remote_train_server.py",
]


def test_worker_business_sources_have_no_windows_only_execution():
    violations = []
    patterns = {
        "shell=True": re.compile(r"shell\s*=\s*True"),
        "drive-qualified literal": re.compile(r"(?i)(?:r|u|f|rf|fr)?['\"][a-z]:\\"),
        "Windows command": re.compile(r"(?i)['\"](?:cmd(?:\.exe)?|powershell(?:\.exe)?|pwsh(?:\.exe)?)['\"]"),
    }
    for path in SOURCES:
        source = path.read_text(encoding="utf-8")
        for label, pattern in patterns.items():
            if pattern.search(source):
                violations.append(f"{path.relative_to(ROOT)}: {label}")
    assert violations == []


def test_linux_remote_launcher_starts_worker_and_api_from_environment():
    source = (ROOT / "start_remote_server.sh").read_text(encoding="utf-8")
    assert "task_worker.py" in source
    assert "remote_train_server:app" in source
    assert "MC_REMOTE_DATA_DIR" in source
    assert "C:\\" not in source and "D:\\" not in source

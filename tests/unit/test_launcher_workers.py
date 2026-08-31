from pathlib import Path

import launcher


def test_launcher_starts_api_and_worker_with_same_data_root(monkeypatch, tmp_path):
    calls = []

    class FakeProcess:
        def __init__(self, command):
            self.command = command

    def fake_popen(command, **options):
        calls.append((command, options))
        return FakeProcess(command)

    data_dir = tmp_path / "shared data"
    monkeypatch.setenv("MC_TRAIN_DATA_DIR", str(data_dir))
    monkeypatch.setattr(launcher.subprocess, "Popen", fake_popen)
    worker, api = launcher.start_service_processes(Path("python"), {"PYTHONUTF8": "1"})

    assert len(calls) == 2
    worker_command, worker_options = calls[0]
    api_command, api_options = calls[1]
    assert worker_command[1:3] == ["task_worker.py", "--data-dir"]
    assert Path(worker_command[3]) == data_dir.resolve()
    assert api_command[1:4] == ["-m", "uvicorn", "app:app"]
    assert worker_options["shell"] is False
    assert api_options["shell"] is False
    assert worker.command == worker_command
    assert api.command == api_command

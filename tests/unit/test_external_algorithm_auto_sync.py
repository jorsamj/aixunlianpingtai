from pathlib import Path

from platform_core.external_algorithm_auto_sync import ExternalAlgorithmAutoSyncReporter


class _Repository:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)


class _Service:
    def __init__(self, root: Path):
        self.repository = _Repository(root)
        self.due = True
        self.calls = []

    def auto_sync_due(self):
        return self.due

    def sync(self, *, project_id, algorithms_path, sync_type):
        self.calls.append((project_id, Path(algorithms_path), sync_type))
        if project_id == "broken":
            raise RuntimeError("provider failure")
        return {"ok": True}


class _InlineThread:
    def __init__(self, *, target, name, daemon):
        self.target = target
        self.name = name
        self.daemon = daemon
        self._alive = False

    def is_alive(self):
        return self._alive

    def start(self):
        self._alive = True
        try:
            self.target()
        finally:
            self._alive = False


class _DeferredThread:
    def __init__(self, *, target, name, daemon):
        self.target = target
        self.name = name
        self.daemon = daemon
        self.started = False

    def is_alive(self):
        return False

    def start(self):
        self.started = True


def _project(data_dir: Path, project_id: str):
    root = data_dir / "projects" / project_id
    root.mkdir(parents=True, exist_ok=True)
    (root / "meta.json").write_text("{}", encoding="utf-8")
    return root


def test_auto_sync_reporter_runs_all_real_projects_without_web_app(tmp_path: Path):
    good = _project(tmp_path, "good")
    _project(tmp_path, "broken")
    (tmp_path / "projects.json").write_text(
        '[{"id":"good"},{"id":"broken"},{"id":"missing"}]',
        encoding="utf-8",
    )
    service = _Service(tmp_path / "integration" / "external_algorithm_platform")
    reporter = ExternalAlgorithmAutoSyncReporter(
        tmp_path,
        lambda: object(),
        service=service,
        thread_factory=_InlineThread,
    )

    result = reporter.run_once()

    assert result == {"attempted": True, "synced": 1, "failed": 1}
    assert service.calls == [
        ("good", good / "algorithms.json", "auto"),
        ("broken", tmp_path / "projects" / "broken" / "algorithms.json", "auto"),
    ]


def test_auto_sync_reporter_uses_worker_heartbeat_trigger_without_periodic_timer(tmp_path: Path):
    _project(tmp_path, "project-1")
    (tmp_path / "projects.json").write_text('[{"id":"project-1"}]', encoding="utf-8")
    service = _Service(tmp_path / "integration" / "external_algorithm_platform")
    reporter = ExternalAlgorithmAutoSyncReporter(
        tmp_path,
        lambda: object(),
        service=service,
        thread_factory=_InlineThread,
    )

    assert reporter.report() is True
    assert service.calls[0][0] == "project-1"
    service.due = False
    assert reporter.report() is False


def test_auto_sync_reporter_reserves_starting_slot_before_thread_is_alive(tmp_path: Path):
    _project(tmp_path, "project-1")
    (tmp_path / "projects.json").write_text('[{"id":"project-1"}]', encoding="utf-8")
    service = _Service(tmp_path / "integration" / "external_algorithm_platform")
    created = []

    def thread_factory(**kwargs):
        thread = _DeferredThread(**kwargs)
        created.append(thread)
        return thread

    reporter = ExternalAlgorithmAutoSyncReporter(
        tmp_path,
        lambda: object(),
        service=service,
        thread_factory=thread_factory,
    )

    assert reporter.report() is True
    assert created[0].started is True
    assert reporter.report() is False
    assert len(created) == 1

    created[0].target()
    assert service.calls[0][0] == "project-1"
    assert reporter._thread is None


def test_task_worker_owns_auto_sync_hook_only_on_background_storage_role():
    source = (Path(__file__).resolve().parents[2] / "task_worker.py").read_text(encoding="utf-8")
    assert "ExternalAlgorithmAutoSyncReporter" in source
    assert 'if "storage" in set(instance_roles):' in source
    assert "instance_lease.add_renew_hook(external_sync_reporter.report)" in source
    assert "external-algorithm-platform-auto-sync" not in source

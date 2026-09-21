from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Callable

from filelock import FileLock, Timeout


class ExternalAlgorithmAutoSyncReporter:
    """Trigger ChangLian master-data sync from the existing background Worker heartbeat.

    The heartbeat hook itself must stay fast. Remote provider I/O therefore runs
    in a guarded one-shot daemon thread; there is no independent timer. The
    service-level auto_sync_due() remains the authoritative >=60 second cadence.
    """

    def __init__(
        self,
        data_dir: str | Path,
        secret_store_factory: Callable[[], Any],
        *,
        service: Any | None = None,
        thread_factory: Callable[..., Any] = threading.Thread,
    ) -> None:
        self.data_dir = Path(data_dir).expanduser().resolve()
        if service is None:
            # Late import keeps importing task_worker independent from FastAPI/app
            # startup while still reusing the canonical provider service contract.
            from .external_algorithm_platform import ExternalAlgorithmPlatformService

            service = ExternalAlgorithmPlatformService(
                data_dir=self.data_dir,
                secret_store_factory=secret_store_factory,
            )
        self.service = service
        self.thread_factory = thread_factory
        self._thread_guard = threading.Lock()
        self._thread: Any | None = None
        lock_root = Path(self.service.repository.root)
        lock_root.mkdir(parents=True, exist_ok=True)
        self._sync_lock = FileLock(str(lock_root / ".auto-sync-worker.lock"), timeout=0)

    def _project_ids(self) -> list[str]:
        path = self.data_dir / "projects.json"
        if not path.is_file():
            return []
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(rows, list):
            return []
        result: list[str] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            project_id = str(row.get("id") or "").strip()
            if project_id and (self.data_dir / "projects" / project_id / "meta.json").is_file():
                result.append(project_id)
        return result

    def run_once(self) -> dict[str, int | bool]:
        if not self.service.auto_sync_due():
            return {"attempted": False, "synced": 0, "failed": 0}
        try:
            with self._sync_lock.acquire(timeout=0):
                if not self.service.auto_sync_due():
                    return {"attempted": False, "synced": 0, "failed": 0}
                synced = 0
                failed = 0
                for project_id in self._project_ids():
                    try:
                        self.service.sync(
                            project_id=project_id,
                            algorithms_path=self.data_dir / "projects" / project_id / "algorithms.json",
                            sync_type="auto",
                        )
                        synced += 1
                    except Exception:
                        # sync() persists provider failure evidence. One project
                        # must not prevent the remaining projects from syncing.
                        failed += 1
                return {"attempted": True, "synced": synced, "failed": failed}
        except Timeout:
            return {"attempted": False, "synced": 0, "failed": 0}

    def _run_background(self) -> None:
        try:
            self.run_once()
        finally:
            with self._thread_guard:
                self._thread = None

    def report(self) -> bool:
        """Fast Worker-heartbeat hook; returns True only when a run was started."""
        if not self.service.auto_sync_due():
            return False

        with self._thread_guard:
            # Register the one-shot before start() so concurrent heartbeats cannot
            # create a second sync while the thread is still in its starting window.
            # start() must run outside this non-reentrant guard because test/runtime
            # thread factories may execute the target synchronously.
            if self._thread is not None:
                return False
            thread = self.thread_factory(
                target=self._run_background,
                name="external-algorithm-platform-auto-sync",
                daemon=True,
            )
            self._thread = thread

        try:
            thread.start()
        except Exception:
            with self._thread_guard:
                if self._thread is thread:
                    self._thread = None
            raise
        return True


__all__ = ["ExternalAlgorithmAutoSyncReporter"]

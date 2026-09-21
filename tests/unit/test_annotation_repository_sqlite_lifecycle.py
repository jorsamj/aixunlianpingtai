import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import platform_core.annotation_repository as annotation_repository_module
from platform_core.annotation_repository import AnnotationRepository


def test_ready_annotation_repository_bypasses_init_lock(tmp_path, monkeypatch):
    project = tmp_path / "project"
    AnnotationRepository(project)

    class ForbiddenInitLock:
        def __init__(self, *args, **kwargs):
            raise AssertionError("ready annotation repository must bypass init FileLock")

    monkeypatch.setattr(annotation_repository_module, "FileLock", ForbiddenInitLock)

    reopened = AnnotationRepository(project)
    with reopened._connect() as database:
        assert str(database.execute("PRAGMA journal_mode").fetchone()[0]).lower() == "wal"


def test_annotation_regular_connection_does_not_negotiate_wal(tmp_path, monkeypatch):
    repository = AnnotationRepository(tmp_path / "project")
    real_connect = sqlite3.connect

    class GuardedConnection:
        def __init__(self, connection):
            self.connection = connection

        @property
        def row_factory(self):
            return self.connection.row_factory

        @row_factory.setter
        def row_factory(self, value):
            self.connection.row_factory = value

        def execute(self, sql, *args, **kwargs):
            if "journal_mode" in str(sql).lower():
                raise AssertionError(
                    "ordinary AnnotationRepository._connect() must not touch journal_mode"
                )
            return self.connection.execute(sql, *args, **kwargs)

        def __getattr__(self, name):
            return getattr(self.connection, name)

    monkeypatch.setattr(
        annotation_repository_module.sqlite3,
        "connect",
        lambda *args, **kwargs: GuardedConnection(real_connect(*args, **kwargs)),
    )

    connection = repository._connect()
    try:
        assert int(connection.execute("PRAGMA busy_timeout").fetchone()[0]) == 30000
    finally:
        connection.close()


def test_concurrent_annotation_repository_initialization_has_one_schema_owner(tmp_path):
    project = tmp_path / "project"
    barrier = Barrier(8)

    def open_repository(index):
        barrier.wait(timeout=3)
        repository = AnnotationRepository(project)
        repository.upsert(
            f"image-{index}",
            [],
            "unannotated",
            project_material=False,
        )
        return repository.exists(f"image-{index}")

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(open_repository, index) for index in range(8)]
        assert all(future.result(timeout=10) for future in futures)

    repository = AnnotationRepository(project)
    assert repository.summary()["total"] == 8

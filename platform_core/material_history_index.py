"""Rebuildable, conservative history-reference index for material impact previews.

The index is a derived read model, never a source of deletion authorization.
The source signature checks repository SQLite/WAL, artifact file metadata,
snapshot trees and algorithm history before and after each cold scan.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path

from filelock import FileLock, Timeout as FileLockTimeout

_SCHEMA = """
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE references_by_image (image_id TEXT PRIMARY KEY, reasons_json TEXT NOT NULL);
"""
_VERSION = "material-history-v1"


def _source_signature(project_id, project_path, repository, artifacts):
    """Metadata invalidation includes only registered task owners.

    DELETE_INDEX previews create unregistered plan artifacts; they cannot
    invalidate the history index on every request.
    """
    digest = hashlib.sha256()
    with closing(sqlite3.connect(f"file:{Path(repository.path)}?mode=ro", uri=True)) as db:
        task_ids = [str(row[0]) for row in db.execute(
            "SELECT task_id FROM tasks WHERE project_id=? ORDER BY task_id", (str(project_id),)
        )]
    roots = [Path(project_path) / "snapshots"]
    roots.extend(Path(artifacts.root) / task_id for task_id in task_ids)
    files = [
        Path(repository.path), Path(str(repository.path) + "-wal"),
        Path(project_path) / "algorithms.json",
        Path(project_path) / "algorithms.sqlite3",
        Path(project_path) / "algorithms.sqlite3-wal",
    ]

    def record(path):
        path = Path(path)
        try:
            stat = path.lstat()
            values = (str(path), stat.st_mode, stat.st_size, stat.st_mtime_ns,
                      stat.st_ctime_ns, stat.st_ino)
        except FileNotFoundError:
            values = (str(path), "missing")
        digest.update(repr(values).encode("utf-8", errors="surrogateescape"))
        digest.update(b"\n")

    for path in files:
        record(path)
    for root in roots:
        record(root)
        if not root.is_dir():
            continue

        def fail(error):
            raise error

        for directory, dirs, names in os.walk(root, followlinks=False, onerror=fail):
            dirs.sort()
            names.sort()
            for name in dirs:
                record(Path(directory) / name)
            for name in names:
                record(Path(directory) / name)
    return digest.hexdigest()


def _read_index(path, signature, wanted):
    if not path.is_file():
        return None
    try:
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as db:
            row = db.execute("SELECT value FROM metadata WHERE key='signature'").fetchone()
            schema = db.execute("SELECT value FROM metadata WHERE key='schema'").fetchone()
            if not row or row[0] != signature or not schema or schema[0] != _VERSION:
                return None
            if wanted is None:
                result = db.execute("SELECT image_id,reasons_json FROM references_by_image")
                return {str(i): json.loads(payload) for i, payload in result}
            output = {}
            ids = sorted(set(map(str, wanted)))
            for start in range(0, len(ids), 300):
                batch = ids[start:start+300]
                if not batch:
                    continue
                query = ",".join("?" for _ in batch)
                for i, payload in db.execute(
                    f"SELECT image_id,reasons_json FROM references_by_image WHERE image_id IN ({query})",
                    batch,
                ):
                    output[str(i)] = json.loads(payload)
            return output
    except (sqlite3.Error, ValueError, TypeError, OSError):
        return None


def _write_index(path, signature, references):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with closing(sqlite3.connect(temporary)) as db:
            db.executescript(_SCHEMA)
            db.executemany(
                "INSERT INTO metadata VALUES (?,?)",
                (("schema", _VERSION), ("signature", signature)),
            )
            db.executemany(
                "INSERT INTO references_by_image VALUES (?,?)",
                ((str(image_id), json.dumps(reasons, ensure_ascii=False, sort_keys=True))
                 for image_id, reasons in references.items()),
            )
            db.commit()
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def query_material_history(project_id, project_path, repository, artifacts, scanner,
                           *, reference_image_ids=None):
    """Single-flight cold scans with read-only per-image lookup on a valid index.

    A changed source during the scan fails closed and never publishes partial
    history. The caller can report UNAVAILABLE instead of manufacturing zero.
    """
    if not isinstance(getattr(repository, "path", None), (str, Path)) or not isinstance(
        getattr(artifacts, "root", None), (str, Path)
    ):
        return scanner(project_id, project_path, repository, artifacts, with_reasons=True)
    index = Path(project_path) / "material-history-reference-index.sqlite3"
    try:
        with FileLock(str(index) + ".lock", timeout=25):
            before = _source_signature(project_id, project_path, repository, artifacts)
            cached = _read_index(index, before, reference_image_ids)
            if cached is not None:
                # Mutation between the signature and retrieval invalidates reuse.
                if before == _source_signature(project_id, project_path, repository, artifacts):
                    return cached
            scanned = scanner(project_id, project_path, repository, artifacts, with_reasons=True)
            after = _source_signature(project_id, project_path, repository, artifacts)
            if before != after:
                raise ValueError("historical material evidence changed during scan")
            _write_index(index, before, scanned)
            if reference_image_ids is None:
                return scanned
            wanted = set(map(str, reference_image_ids))
            return {image_id: evidence for image_id, evidence in scanned.items() if image_id in wanted}
    except FileLockTimeout as error:
        raise ValueError("material history scan is busy; please retry") from error

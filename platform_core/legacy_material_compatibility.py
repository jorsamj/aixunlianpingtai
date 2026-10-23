"""Explicit, temporary metadata repair over existing Material/Annotation owners.

Read-only discovery never constructs a repository or cache. JSON-only, remote,
unknown schemas and ambiguous identities are report-only; no original/GT moves.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
from contextlib import closing, ExitStack
from pathlib import Path

from .annotation_repository import AnnotationRepository
from .material_repository import MaterialRepository, material_annotation_lifecycle_fence, normalize_material
from .storage.local import LocalStorageProvider
from .storage.manager import StorageManager
from .storage.source_repository import storage_source_lifecycle_fence
from .training_bundle_cache import _is_link_like


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _stamp(path):
    if _is_link_like(path):
        raise ValueError("unsafe metadata/source link")
    try:
        info = path.stat()
        return [info.st_ino, info.st_size, info.st_mtime_ns]
    except FileNotFoundError:
        return None


def _readonly(path):
    if _stamp(path) is None:
        raise ValueError("existing repository is required")
    wal = Path(str(path) + "-wal")
    _stamp(wal)
    _stamp(Path(str(path) + "-shm"))
    # Without WAL, immutable avoids SQLite creating SHM/WAL on a read-only scan.
    # A live WAL is readable only with existing SHM; never create sidecars here.
    if wal.exists() and not Path(str(path) + "-shm").is_file():
        raise ValueError("unsupported WAL without existing shared memory")
    suffix = "?mode=ro" + ("&immutable=1" if not wal.exists() else "")
    connection = sqlite3.connect(path.resolve().as_uri() + suffix, uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


class LegacyMaterialCompatibilityService:
    def __init__(self, data_dir, project_id, *, enabled=True):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", str(project_id)):
            raise ValueError("invalid project_id")
        self.data_dir = Path(data_dir).resolve()
        self.project_id = str(project_id)
        self.project = self.data_dir / "projects" / self.project_id
        self.enabled = enabled
        for path in (self.data_dir / "projects", self.project):
            if _is_link_like(path):
                raise ValueError("unsafe project path")
        if not self.project.is_dir():
            raise KeyError(project_id)

    def _enabled(self):
        if not self.enabled:
            raise RuntimeError("LEGACY_COMPATIBILITY_DISABLED")

    def _legacy(self):
        path = self.project / "images.json"
        if _stamp(path) is None:
            return []
        if path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("unsupported legacy JSON size; existing owner migration required")
        value = json.loads(path.read_text(encoding="utf-8"))
        rows = value.get("items") if isinstance(value, dict) else value
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError("unsupported legacy material JSON")
        return rows

    def _rows(self, ids=None, *, cursor="", limit=50):
        path = self.project / "materials.sqlite3"
        if not path.is_file():
            rows = sorted(self._legacy(), key=lambda row: str(row.get("id") or ""))
            selected = [row for row in rows if (str(row.get("id")) in ids if ids is not None
                                                else str(row.get("id") or "") > cursor)]
            return [(row, json.dumps(row, sort_keys=True)) for row in selected[:limit]], "legacy_json", None
        with closing(_readonly(path)) as db:
            if db.execute("PRAGMA user_version").fetchone()[0] != 5:
                raise ValueError("unsupported material schema; no implicit migration")
            revision = int(db.execute("SELECT value FROM material_meta WHERE key='revision'").fetchone()[0])
            if ids is None:
                rows = db.execute("SELECT * FROM materials WHERE id>? ORDER BY id LIMIT ?",
                                  (cursor, limit)).fetchall()
            else:
                rows = db.execute("SELECT * FROM materials WHERE id IN (" +
                    ",".join("?" for _ in ids) + ") ORDER BY id", ids).fetchall()
            result = []
            for row in rows:
                payload = json.loads(row["payload_json"])
                if not isinstance(payload, dict) or payload.get("id") != row["id"]:
                    raise ValueError("material row identity conflict")
                normalized = normalize_material(payload)
                fields = ("storage_source_id", "storage_type", "object_key", "content_sha256", "size_bytes", "etag")
                conflicts = ["indexed/material payload mismatch"] if any(row[field] != normalized[field] for field in fields) else []
                aliases = db.execute("SELECT COUNT(*) FROM materials WHERE storage_source_id=? AND object_key=?",
                                     (row["storage_source_id"], row["object_key"])).fetchone()[0]
                if aliases != 1:
                    conflicts.append("shared object reference requires explicit identity review")
                if conflicts:
                    payload = {**payload, "_compatibility_conflicts": conflicts}
                result.append((payload, row["payload_json"]))
            return result, "sqlite", revision

    def _annotation(self, image_id):
        image_id = AnnotationRepository._id(image_id)
        if _is_link_like(self.project / "annotations") or _is_link_like(self.project / "annotations" / f"{image_id}.json"):
            raise ValueError("unsafe legacy annotation reference")
        # Reuse original decoding/fallback without __init__ schema/migration writes.
        owner = object.__new__(AnnotationRepository)
        owner.project_path = self.project
        owner.path = self.project / "annotations.sqlite3"
        if owner.path.is_file():
            owner._connect = lambda: _readonly(owner.path)
            return owner.get(image_id)
        return owner._legacy_record(image_id)

    def _source(self, row):
        normalized = normalize_material(row)
        if normalized["storage_source_id"] != "default_local" or normalized["storage_type"] != "local":
            raise ValueError("unsupported external storage; explicit provider verification required")
        sources = self.data_dir / "storage" / "storage_sources.sqlite3"
        if _is_link_like(sources.parent):
            raise ValueError("unsafe storage source directory")
        if sources.is_file():
            with closing(_readonly(sources)) as db:
                configured = db.execute("SELECT type,config_json,enabled FROM storage_sources WHERE id='default_local'").fetchone()
                if configured is None or configured["type"] != "local" or not configured["enabled"]:
                    raise ValueError("unsupported default source configuration")
                root = json.loads(configured["config_json"]).get("root")
                if root:
                    configured_root = Path(root)
                    if not configured_root.is_absolute():
                        configured_root = self.data_dir / configured_root
                    if configured_root.resolve() != self.project.resolve():
                        raise ValueError("unsupported configured default source root")
        key = normalized["object_key"]
        if not key.startswith("uploads/"):
            raise ValueError("unsupported original location")
        current = self.project
        for part in Path(key).parts:
            current = current / part
            if _is_link_like(current):
                raise ValueError("unsafe original path")
        if not current.is_file():
            raise ValueError("original is missing")
        # This original manager method uses only the normalized mapping and the
        # already-created provider, so it cannot initialize sources/cache/owners.
        manager = object.__new__(StorageManager)
        manager._providers = {"default_local": LocalStorageProvider("default_local", self.project)}
        return normalized, current, manager

    def _inspect(self, row, owner, legacy_rows=None):
        image_id = str(row.get("id") or "")
        item = {"image_id": image_id, "status": "unsupported", "issues": [],
                "candidate": False, "material_owner": owner, "material": row}
        try:
            if row.get("_compatibility_conflicts"):
                item.update(status="conflict", issues=row["_compatibility_conflicts"])
                return item
            annotation = self._annotation(image_id)
            item["ground_truth"] = annotation
            normalized, path, manager = self._source(row)
            legacy = [entry for entry in legacy_rows or [] if str(entry.get("id") or "") == image_id]
            item["legacy_json_evidence"] = legacy
            if owner == "sqlite" and legacy:
                if len(legacy) != 1:
                    item.update(status="conflict", issues=["ambiguous legacy JSON image identity"])
                    return item
                previous = normalize_material(legacy[0])
                if any(previous[field] != normalized[field] for field in ("storage_source_id", "object_key")):
                    item.update(status="conflict", issues=["legacy JSON and SQLite original references differ"])
                    return item
                if (previous.get("content_sha256") and normalized.get("content_sha256")
                        and previous["content_sha256"] != normalized["content_sha256"]):
                    item.update(status="conflict", issues=["legacy JSON and SQLite content identities differ"])
                    return item
            item["original"] = {"object_key": normalized["object_key"], "path": str(path), "stat": _stamp(path)}
            item["thumbnails"] = [{"field": field, "reference": row[field], "status": "report_only"}
                                  for field in ("thumbnail", "thumbnail_path", "thumbnail_ref") if row.get(field)]
            item["thumbnail_status"] = "references_reported_only" if item["thumbnails"] else "unknown_no_reference"
            missing = [field for field, absent in (("content_sha256", not row.get("content_sha256")),
                                                   ("size_bytes", not row.get("size_bytes"))) if absent]
            if not missing:
                item["status"] = "normal"
                return item
            if row.get("source_available") is False:
                raise ValueError("source marked unavailable")
            before = _stamp(path)
            digest = hashlib.sha256()
            size = 0
            with manager.open_reader(normalized) as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
                    size += len(chunk)
            if before != _stamp(path) or size <= 0 or size != before[1]:
                raise ValueError("source changed during inspection")
            actual_sha = digest.hexdigest()
            if any(entry.get("content_sha256") and entry["content_sha256"] != actual_sha for entry in legacy):
                item.update(status="conflict", issues=["legacy JSON content differs from actual source"])
                return item
            if ((row.get("content_sha256") and row["content_sha256"] != actual_sha)
                    or (row.get("size_bytes") and int(row["size_bytes"]) != size)):
                item.update(status="conflict", issues=["existing metadata differs from actual source"])
                return item
            if not row.get("width") or not row.get("height"):
                raise ValueError("unsupported missing dimensions; explicit image verification required")
            item["proposed"] = {"content_sha256": actual_sha, "size_bytes": size,
                                "etag": str(row.get("etag") or ""),
                                "width": row["width"], "height": row["height"]}
            item["issues"] = ["missing " + field for field in missing]
            if owner != "sqlite":
                item["issues"].append("JSON-only repair unsupported; original owner migration required")
            else:
                item.update(status="candidate", candidate=True)
        except Exception as error:
            item["issues"].append(str(error))
        return item

    def _catalog(self):
        result = {}
        for name in ("materials.sqlite3", "materials.sqlite3-wal", "annotations.sqlite3",
                     "annotations.sqlite3-wal", "images.json"):
            result[name] = _stamp(self.project / name)
        source = self.data_dir / "storage" / "storage_sources.sqlite3"
        result["storage_sources"] = _stamp(source)
        result["storage_sources_wal"] = _stamp(Path(str(source) + "-wal"))
        return result

    def preview(self, image_ids):
        self._enabled()
        ids = sorted(set(str(value) for value in image_ids))
        if not ids or len(ids) > 50 or any(not re.fullmatch(r"[A-Za-z0-9_.-]+", value) for value in ids):
            raise ValueError("preview requires 1..50 valid image_ids")
        before = self._catalog()
        rows, owner, revision = self._rows(ids, limit=50)
        legacy_rows = self._legacy()
        items = [self._inspect(row, owner, legacy_rows) for row, raw in rows]
        if {item["image_id"] for item in items} != set(ids):
            raise ValueError("unknown image_ids")
        after = self._catalog()
        if before != after:
            raise RuntimeError("LEGACY_COMPATIBILITY_STALE")
        evidence = {"catalog": after, "revision": revision, "rows": rows, "items": items}
        return {"image_ids": ids, "items": items, "fingerprint": _digest(evidence),
                "needs_migration": any(item["candidate"] for item in items),
                "safety": "metadata only; originals and formal GT remain untouched",
                "repositories": {"material_owner": owner, "legacy_json": after.get("images.json"),
                                 "annotations_sqlite": after.get("annotations.sqlite3")},
                "_revision": revision, "_payloads": {row["id"]: raw for row, raw in rows}}

    def scan(self, *, limit=50, cursor=None):
        self._enabled()
        limit = max(1, min(50, int(limit)))
        cursor = str(cursor or "")
        rows, owner, revision = self._rows(cursor=cursor, limit=limit + 1)
        more = len(rows) > limit
        rows = rows[:limit]
        legacy_rows = self._legacy()
        items = [self._inspect(row, owner, legacy_rows) for row, raw in rows]
        return {"items": items, "next_cursor": str(rows[-1][0]["id"]) if more else None,
                "needs_migration": any(item["candidate"] for item in items), "material_owner": owner}

    def _backup_path(self, task_id):
        folder = self.project / ".legacy-material-compatibility"
        if _is_link_like(folder):
            raise ValueError("unsafe backup directory")
        path = folder / (task_id + ".json")
        if _is_link_like(path):
            raise ValueError("unsafe backup path")
        return path

    def _write_backup(self, path, value):
        path.parent.mkdir(exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".backup-", suffix=".tmp")
        temporary = Path(temporary)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(value, stream, sort_keys=True, ensure_ascii=False, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            if json.loads(temporary.read_text(encoding="utf-8")) != value:
                raise RuntimeError("backup verification failed")
            os.replace(temporary, path)
            if os.name != "nt":
                descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
        finally:
            temporary.unlink(missing_ok=True)

    def apply(self, image_ids, *, expected_fingerprint, task_id, confirmed=False):
        self._enabled()
        if confirmed is not True or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", str(task_id)):
            raise ValueError("explicit confirmation and valid task_id are required")
        ids = sorted(set(str(value) for value in image_ids))
        path = self._backup_path(task_id)
        with ExitStack() as stack:
            sources = self.data_dir / "storage" / "storage_sources.sqlite3"
            if sources.is_file():
                stack.enter_context(storage_source_lifecycle_fence(sources))
            stack.enter_context(material_annotation_lifecycle_fence(self.project))
            backup = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
            if backup:
                backup_checksum = backup.get("backup_digest")
                if backup_checksum != _digest({key: value for key, value in backup.items() if key != "backup_digest"}):
                    raise RuntimeError("LEGACY_COMPATIBILITY_BACKUP_INVALID")
            if backup and (backup.get("fingerprint") != expected_fingerprint or backup.get("image_ids") != ids):
                raise RuntimeError("LEGACY_COMPATIBILITY_TASK_CONFLICT")
            if backup:
                with closing(_readonly(self.project / "materials.sqlite3")) as db:
                    audited = {row[0] for row in db.execute(
                        "SELECT image_id FROM material_storage_audit WHERE task_id=? AND action='METADATA_COMPLETED'", (task_id,))}
                if audited == set(ids):
                    return {"status": "already_applied", "task_id": task_id, "image_ids": ids,
                            "backup_ref": str(path.relative_to(self.project)).replace("\\", "/")}
                if audited:
                    raise RuntimeError("LEGACY_COMPATIBILITY_AUDIT_CONFLICT")
            preview = self.preview(ids)
            if preview["fingerprint"] != expected_fingerprint:
                raise RuntimeError("LEGACY_COMPATIBILITY_STALE")
            if not all(item["candidate"] for item in preview["items"]):
                raise ValueError("only proven SQLite metadata candidates can be applied")
            if backup is None:
                self._write_backup(path, {**preview, "backup_digest": _digest(preview)})
            # Full preview is rederived after durable backup; original image and
            # annotation changes cannot sneak through this preparation interval.
            checked = self.preview(ids)
            if checked["fingerprint"] != expected_fingerprint:
                raise RuntimeError("LEGACY_COMPATIBILITY_STALE")
            owner = object.__new__(MaterialRepository)
            owner.project_path = self.project
            owner.path = self.project / "materials.sqlite3"
            changes = [{"object_key": item["original"]["object_key"],
                        "old_sha256": item["material"].get("content_sha256", ""),
                        "category": "METADATA_COMPLETED", **item["proposed"]} for item in checked["items"]]
            count = owner.reconcile_storage_batch(task_id, "default_local", changes,
                expected_revision=checked["_revision"], expected_payloads=checked["_payloads"])
            if count != len(ids):
                raise RuntimeError("LEGACY_COMPATIBILITY_APPLY_COUNT_MISMATCH")
            return {"status": "applied", "task_id": task_id, "image_ids": ids,
                    "updated": count, "backup_ref": str(path.relative_to(self.project)).replace("\\", "/")}

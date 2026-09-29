"""Primary annotation storage; legacy JSON is read only until an explicit update."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock


STATES = {"unannotated", "annotated", "confirmed_empty"}
_SCHEMA_VERSION = 2
_INIT_LOCK_TIMEOUT = 30


def _normalize_scope(values) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    return sorted({str(value).strip() for value in values if str(value).strip()})


def _active_project_labels(project_path: Path) -> list[str]:
    """Return the concrete active label codes known when an empty GT is confirmed.

    Older call sites did not pass ``annotation_scope`` explicitly. Persisting the
    active label set is safer than storing a timeless ``*`` because projects can
    gain unrelated labels later. ``*`` remains only as a compatibility fallback
    when a legacy project has no readable label catalog.
    """
    path = project_path / "meta.json"
    if not path.is_file():
        return []
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    labels = list(meta.get("labels") or [])
    metadata = list(meta.get("label_meta") or [])
    active = []
    for index, value in enumerate(labels):
        code = str(value or "").strip()
        if not code:
            continue
        info = metadata[index] if index < len(metadata) and isinstance(metadata[index], dict) else {}
        if str(info.get("status") or "active").strip().lower() in {"disabled", "inactive"}:
            continue
        active.append(code)
    return _normalize_scope(active)


class AnnotationConflictError(RuntimeError):
    def __init__(self, image_id: str, expected_version: int, actual_version: int):
        self.image_id = str(image_id)
        self.expected_version = int(expected_version)
        self.actual_version = int(actual_version)
        super().__init__(
            f"annotation {self.image_id} changed concurrently: "
            f"expected version {self.expected_version}, actual {self.actual_version}"
        )


class AnnotationRepository:
    def __init__(self, project_path: str | Path):
        self.project_path = Path(project_path)
        self.project_path.mkdir(parents=True, exist_ok=True)
        self.path = self.project_path / "annotations.sqlite3"
        self._initialize()

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=30000")
        return db

    def _read_schema_version_fast(self) -> int | None:
        if not self.path.is_file():
            return None
        try:
            with closing(
                sqlite3.connect(self.path, timeout=0.25, isolation_level=None)
            ) as db:
                db.execute("PRAGMA busy_timeout=250")
                return int(db.execute("PRAGMA user_version").fetchone()[0])
        except sqlite3.Error:
            return None

    def _reference_index_ready_fast(self) -> bool:
        if not self.path.is_file():
            return False
        try:
            with closing(
                sqlite3.connect(self.path, timeout=0.25, isolation_level=None)
            ) as db:
                db.execute("PRAGMA busy_timeout=250")
                return db.execute(
                    "SELECT 1 FROM annotation_meta "
                    "WHERE key='index_rebuilt_at' LIMIT 1"
                ).fetchone() is not None
        except sqlite3.Error:
            return False

    def _initialize(self) -> None:
        if (
            self._read_schema_version_fast() == _SCHEMA_VERSION
            and self._reference_index_ready_fast()
        ):
            return
        lock = FileLock(
            str(self.path.resolve()) + ".init.lock",
            timeout=_INIT_LOCK_TIMEOUT,
        )
        rebuild_references = False
        with lock:
            with closing(self._connect()) as db:
                version = int(db.execute("PRAGMA user_version").fetchone()[0])
                if version == _SCHEMA_VERSION:
                    ready = db.execute(
                        "SELECT 1 FROM annotation_meta "
                        "WHERE key='index_rebuilt_at' LIMIT 1"
                    ).fetchone()
                    if ready is not None:
                        return
                    # Rebuild through a fresh writer connection. Closing this
                    # schema probe first avoids retaining a stale read snapshot
                    # while the derived index is reconciled.
                    db.close()
                    self.rebuild_reference_index()
                    return
                if version > _SCHEMA_VERSION:
                    raise RuntimeError(
                        f"annotation repository schema {version} is newer than supported {_SCHEMA_VERSION}"
                    )
                mode = str(db.execute("PRAGMA journal_mode").fetchone()[0]).lower()
                if mode != "wal":
                    mode = str(db.execute("PRAGMA journal_mode=WAL").fetchone()[0]).lower()
                if mode != "wal":
                    raise RuntimeError(
                        f"annotation repository requires WAL mode, got {mode}"
                    )
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS annotations (
                        image_id TEXT PRIMARY KEY,
                        annotation_state TEXT NOT NULL CHECK(annotation_state IN
                            ('unannotated','annotated','confirmed_empty')),
                        version INTEGER NOT NULL, content_digest TEXT NOT NULL,
                        boxes_json TEXT NOT NULL,
                        scope_json TEXT NOT NULL DEFAULT '[]',
                        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS ix_annotations_state ON annotations(annotation_state, image_id);
                    CREATE INDEX IF NOT EXISTS ix_annotations_updated ON annotations(updated_at);
                    CREATE TABLE IF NOT EXISTS annotation_delete_backup (
                        token TEXT NOT NULL, image_id TEXT NOT NULL,
                        annotation_state TEXT NOT NULL, version INTEGER NOT NULL,
                        content_digest TEXT NOT NULL, boxes_json TEXT NOT NULL,
                        scope_json TEXT NOT NULL, created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY(token, image_id)
                    );
                    CREATE INDEX IF NOT EXISTS ix_annotation_delete_backup_token
                        ON annotation_delete_backup(token, image_id);
                    CREATE TABLE IF NOT EXISTS annotation_label_references (
                        image_id TEXT NOT NULL,
                        label_code TEXT NOT NULL,
                        box_count INTEGER NOT NULL DEFAULT 0,
                        scope_ref INTEGER NOT NULL DEFAULT 0,
                        annotation_state TEXT NOT NULL,
                        source_kind TEXT NOT NULL CHECK(source_kind IN ('sqlite','legacy')),
                        PRIMARY KEY(image_id, label_code)
                    );
                    CREATE INDEX IF NOT EXISTS ix_annotation_label_references_code
                        ON annotation_label_references(label_code, image_id);
                    CREATE TABLE IF NOT EXISTS annotation_meta (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );
                    INSERT OR IGNORE INTO annotation_meta(key, value)
                        VALUES ('revision', '0');
                    CREATE TRIGGER IF NOT EXISTS annotation_refs_after_insert
                    AFTER INSERT ON annotations BEGIN
                        DELETE FROM annotation_label_references
                         WHERE image_id = NEW.image_id;
                        INSERT INTO annotation_label_references
                            (image_id, label_code, box_count, scope_ref,
                             annotation_state, source_kind)
                        SELECT NEW.image_id,
                               COALESCE(
                                   NULLIF(TRIM(CAST(json_extract(value, '$.label') AS TEXT)), ''),
                                   NULLIF(TRIM(CAST(json_extract(value, '$.code') AS TEXT)), '')
                               ),
                               COUNT(*), 0, NEW.annotation_state, 'sqlite'
                          FROM json_each(NEW.boxes_json)
                         WHERE COALESCE(
                                   NULLIF(TRIM(CAST(json_extract(value, '$.label') AS TEXT)), ''),
                                   NULLIF(TRIM(CAST(json_extract(value, '$.code') AS TEXT)), '')
                               ) IS NOT NULL
                         GROUP BY COALESCE(
                                   NULLIF(TRIM(CAST(json_extract(value, '$.label') AS TEXT)), ''),
                                   NULLIF(TRIM(CAST(json_extract(value, '$.code') AS TEXT)), '')
                               );
                        INSERT INTO annotation_label_references
                            (image_id, label_code, box_count, scope_ref,
                             annotation_state, source_kind)
                        SELECT NEW.image_id, TRIM(CAST(value AS TEXT)), 0, 1,
                               NEW.annotation_state, 'sqlite'
                          FROM json_each(NEW.scope_json)
                         WHERE TRIM(CAST(value AS TEXT)) <> ''
                        ON CONFLICT(image_id, label_code) DO UPDATE SET
                            scope_ref=1,
                            annotation_state=excluded.annotation_state,
                            source_kind='sqlite';
                        UPDATE annotation_meta
                           SET value = CAST(value AS INTEGER) + 1
                         WHERE key = 'revision';
                    END;
                    CREATE TRIGGER IF NOT EXISTS annotation_refs_after_update
                    AFTER UPDATE OF annotation_state, boxes_json, scope_json ON annotations BEGIN
                        DELETE FROM annotation_label_references
                         WHERE image_id = NEW.image_id;
                        INSERT INTO annotation_label_references
                            (image_id, label_code, box_count, scope_ref,
                             annotation_state, source_kind)
                        SELECT NEW.image_id,
                               COALESCE(
                                   NULLIF(TRIM(CAST(json_extract(value, '$.label') AS TEXT)), ''),
                                   NULLIF(TRIM(CAST(json_extract(value, '$.code') AS TEXT)), '')
                               ),
                               COUNT(*), 0, NEW.annotation_state, 'sqlite'
                          FROM json_each(NEW.boxes_json)
                         WHERE COALESCE(
                                   NULLIF(TRIM(CAST(json_extract(value, '$.label') AS TEXT)), ''),
                                   NULLIF(TRIM(CAST(json_extract(value, '$.code') AS TEXT)), '')
                               ) IS NOT NULL
                         GROUP BY COALESCE(
                                   NULLIF(TRIM(CAST(json_extract(value, '$.label') AS TEXT)), ''),
                                   NULLIF(TRIM(CAST(json_extract(value, '$.code') AS TEXT)), '')
                               );
                        INSERT INTO annotation_label_references
                            (image_id, label_code, box_count, scope_ref,
                             annotation_state, source_kind)
                        SELECT NEW.image_id, TRIM(CAST(value AS TEXT)), 0, 1,
                               NEW.annotation_state, 'sqlite'
                          FROM json_each(NEW.scope_json)
                         WHERE TRIM(CAST(value AS TEXT)) <> ''
                        ON CONFLICT(image_id, label_code) DO UPDATE SET
                            scope_ref=1,
                            annotation_state=excluded.annotation_state,
                            source_kind='sqlite';
                        UPDATE annotation_meta
                           SET value = CAST(value AS INTEGER) + 1
                         WHERE key = 'revision';
                    END;
                    CREATE TRIGGER IF NOT EXISTS annotation_refs_after_delete
                    AFTER DELETE ON annotations BEGIN
                        DELETE FROM annotation_label_references
                         WHERE image_id = OLD.image_id;
                        UPDATE annotation_meta
                           SET value = CAST(value AS INTEGER) + 1
                         WHERE key = 'revision';
                    END;
                """)
                columns = {
                    str(row[1])
                    for row in db.execute("PRAGMA table_info(annotations)").fetchall()
                }
                if "scope_json" not in columns:
                    db.execute(
                        "ALTER TABLE annotations "
                        "ADD COLUMN scope_json TEXT NOT NULL DEFAULT '[]'"
                    )
                rebuild_references = version < 2
                db.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")
                db.commit()
        if rebuild_references:
            self.rebuild_reference_index()

    @staticmethod
    def _id(image_id):
        image_id = str(image_id)
        if not image_id or any(c in image_id for c in '/\\:') or image_id in {'.', '..'}:
            raise ValueError("invalid annotation image_id")
        return image_id

    def _default_negative_scope(self) -> list[str]:
        return _active_project_labels(self.project_path) or ["*"]

    def _decode_persisted_row(self, row):
        result = dict(row)
        result['boxes'] = json.loads(result.pop('boxes_json'))
        result['annotation_scope'] = _normalize_scope(
            json.loads(result.pop('scope_json', '[]') or '[]')
        )
        if result['annotation_state'] == 'annotated' and not result['annotation_scope']:
            result['annotation_scope'] = _normalize_scope(
                box.get('label') or box.get('code') for box in result['boxes']
            )
        if result['annotation_state'] == 'confirmed_empty' and not result['annotation_scope']:
            result['annotation_scope'] = self._default_negative_scope()
        return result

    def _legacy_record(self, image_id: str) -> dict:
        path = self.project_path / "annotations" / f"{image_id}.json"
        legacy = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        boxes = legacy.get("boxes") or []
        state = legacy.get("annotation_state") or (
            "annotated" if boxes else "unannotated"
        )
        scope = _normalize_scope(legacy.get("annotation_scope"))
        if state == "annotated" and not scope:
            scope = _normalize_scope(
                box.get("label") or box.get("code") for box in boxes
            )
        if state == "confirmed_empty" and not scope:
            scope = self._default_negative_scope()
        return {
            **legacy,
            "image_id": image_id,
            "boxes": boxes,
            "annotation_state": state,
            "annotation_scope": scope,
            "version": 0,
        }

    def get(self, image_id):
        image_id = self._id(image_id)
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT * FROM annotations WHERE image_id=?",
                (image_id,),
            ).fetchone()
        if row:
            return self._decode_persisted_row(row)
        return self._legacy_record(image_id)

    def get_many(self, image_ids):
        ids = list(dict.fromkeys(self._id(value) for value in image_ids))
        if len(ids) > 500:
            raise ValueError("annotation batch lookup is limited to 500 image ids")
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        with closing(self._connect()) as db:
            rows = db.execute(
                f"SELECT * FROM annotations WHERE image_id IN ({placeholders})",
                ids,
            ).fetchall()
        result = {
            str(row["image_id"]): self._decode_persisted_row(row)
            for row in rows
        }
        for image_id in ids:
            if image_id not in result:
                # The batch query already proved this ID is absent from SQLite.
                # Go straight to legacy JSON fallback instead of opening another
                # connection and repeating the same SELECT once per missing ID.
                result[image_id] = self._legacy_record(image_id)
        return result

    def _content_payload(self, boxes, annotation_state=None, annotation_scope=None):
        boxes = [dict(box) for box in (boxes or [])]
        state = annotation_state or ('annotated' if boxes else 'confirmed_empty')
        if state not in STATES or bool(boxes) != (state == 'annotated'):
            raise ValueError('annotation state does not agree with boxes')
        scope = _normalize_scope(annotation_scope)
        if state == 'annotated' and not scope:
            scope = _normalize_scope(
                box.get('label') or box.get('code') for box in boxes
            )
        if state == 'confirmed_empty' and not scope:
            scope = self._default_negative_scope()
        if state == 'unannotated':
            scope = []
        boxes_payload = json.dumps(
            boxes, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
            allow_nan=False,
        )
        scope_payload = json.dumps(
            scope, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
        )
        digest_payload = json.dumps(
            {
                'annotation_state': state,
                'annotation_scope': scope,
                'boxes': json.loads(boxes_payload),
            },
            ensure_ascii=False, sort_keys=True, separators=(',', ':'),
            allow_nan=False,
        )
        return {
            'boxes': boxes,
            'annotation_state': state,
            'annotation_scope': scope,
            'boxes_payload': boxes_payload,
            'scope_payload': scope_payload,
            'content_digest': hashlib.sha256(
                digest_payload.encode('utf-8')
            ).hexdigest(),
        }

    def record_digest(self, record) -> str:
        prepared = self._content_payload(
            record.get('boxes') or [],
            record.get('annotation_state'),
            record.get('annotation_scope'),
        )
        return prepared['content_digest']

    def plan_label_remap(
        self, record, *, source_label: str | None = None,
        source_labels=None, target_label: str, target_class_id: int,
    ) -> dict:
        sources = list(dict.fromkeys(
            str(value).strip()
            for value in (
                source_labels
                if source_labels is not None
                else [source_label]
            )
            if str(value or '').strip()
        ))
        target = str(target_label or '').strip()
        if not sources or not target or target in sources:
            raise ValueError('source and target labels are required and must differ')
        source_set = set(sources)
        boxes, changed = [], 0
        for raw in record.get('boxes') or []:
            box = dict(raw)
            label = str(box.get('label') or box.get('code') or '').strip()
            if label in source_set:
                box['label'] = target
                if 'code' in box:
                    box['code'] = target
                box['class_id'] = int(target_class_id)
                box['canonical_label_id'] = target
                box['canonical_project_class_id'] = int(target_class_id)
                changed += 1
            boxes.append(box)
        original_scope = _normalize_scope(record.get('annotation_scope'))
        scope = [
            target if str(value).strip() in source_set else str(value).strip()
            for value in (record.get('annotation_scope') or [])
            if str(value).strip()
        ]
        prepared = self._content_payload(
            boxes,
            record.get('annotation_state'),
            scope,
        )
        return {
            **prepared,
            'changed_boxes': changed,
            # Preserve the public metric's historical meaning: it counts
            # confirmed-empty negative-scope changes. Annotated scopes are
            # still remapped and indexed, but are not added to this counter.
            'changed_scope': int(
                str(record.get('annotation_state') or '') == 'confirmed_empty'
                and prepared['annotation_scope'] != original_scope
            ),
        }

    @staticmethod
    def _reference_rows(record: dict, source_kind: str) -> list[tuple]:
        counts: dict[str, int] = {}
        for box in record.get('boxes') or []:
            code = str(box.get('label') or box.get('code') or '').strip()
            if code:
                counts[code] = counts.get(code, 0) + 1
        scopes = set(_normalize_scope(record.get('annotation_scope')))
        return [
            (
                str(record.get('image_id') or ''),
                code,
                int(counts.get(code) or 0),
                int(code in scopes),
                str(record.get('annotation_state') or 'unannotated'),
                source_kind,
            )
            for code in sorted(set(counts) | scopes)
            if code
        ]

    def rebuild_reference_index(self) -> dict[str, int]:
        """Reconcile the derived lookup index from AnnotationRepository truth.

        SQLite rows shadow same-named legacy JSON records. The index is a query
        accelerator only; callers must continue to read annotations for writes.
        """
        legacy_dir = self.project_path / 'annotations'
        with closing(self._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                db.execute('DELETE FROM annotation_label_references')
                rows = db.execute('SELECT * FROM annotations ORDER BY image_id').fetchall()
                persisted_ids = {str(row['image_id']) for row in rows}
                reference_rows = []
                for row in rows:
                    reference_rows.extend(
                        self._reference_rows(self._decode_persisted_row(row), 'sqlite')
                    )
                legacy_count = 0
                if legacy_dir.is_dir():
                    for path in sorted(legacy_dir.glob('*.json')):
                        image_id = path.stem
                        if image_id in persisted_ids:
                            continue
                        record = self._legacy_record(image_id)
                        reference_rows.extend(self._reference_rows(record, 'legacy'))
                        legacy_count += 1
                db.executemany(
                    'INSERT INTO annotation_label_references '
                    '(image_id,label_code,box_count,scope_ref,annotation_state,source_kind) '
                    'VALUES (?,?,?,?,?,?)',
                    reference_rows,
                )
                db.execute(
                    "INSERT OR REPLACE INTO annotation_meta(key,value) VALUES ('index_rebuilt_at',?)",
                    (datetime.now(timezone.utc).isoformat(),),
                )
                db.execute('COMMIT')
            except Exception:
                db.execute('ROLLBACK')
                raise
        return {
            'sqlite_records': len(persisted_ids),
            'legacy_records': legacy_count,
            'reference_rows': len(reference_rows),
        }

    def current_revision(self) -> int:
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT value FROM annotation_meta WHERE key='revision'"
            ).fetchone()
        return int(row[0]) if row is not None else 0

    def repository_fingerprint(self) -> str:
        with closing(self._connect()) as db:
            row = db.execute(
                'SELECT COUNT(*), COALESCE(MAX(updated_at), \'\') FROM annotations'
            ).fetchone()
        legacy_dir = self.project_path / 'annotations'
        legacy_count = 0
        legacy_latest = 0
        if legacy_dir.is_dir():
            for path in legacy_dir.glob('*.json'):
                try:
                    stat = path.stat()
                except OSError:
                    continue
                legacy_count += 1
                legacy_latest = max(legacy_latest, int(stat.st_mtime_ns))
        payload = json.dumps(
            {
                'revision': self.current_revision(),
                'sqlite_count': int(row[0] or 0),
                'sqlite_latest': str(row[1] or ''),
                'legacy_count': legacy_count,
                'legacy_latest': legacy_latest,
            },
            sort_keys=True,
            separators=(',', ':'),
        )
        return hashlib.sha256(payload.encode('utf-8')).hexdigest()

    def iter_records(self, batch_size: int = 500):
        """Yield all current GT records, with SQLite shadowing legacy JSON."""
        size = max(1, min(5000, int(batch_size)))
        cursor = ''
        persisted_ids: set[str] = set()
        while True:
            with closing(self._connect()) as db:
                rows = db.execute(
                    'SELECT * FROM annotations WHERE image_id>? '
                    'ORDER BY image_id LIMIT ?',
                    (cursor, size),
                ).fetchall()
            if not rows:
                break
            for row in rows:
                image_id = str(row['image_id'])
                persisted_ids.add(image_id)
                yield self._decode_persisted_row(row)
            cursor = str(rows[-1]['image_id'])
        legacy_dir = self.project_path / 'annotations'
        if legacy_dir.is_dir():
            for path in sorted(legacy_dir.glob('*.json')):
                if path.stem not in persisted_ids:
                    yield self._legacy_record(path.stem)

    def label_reference_preview(self, label_codes) -> dict[str, int]:
        codes = list(dict.fromkeys(
            str(code).strip() for code in (label_codes or ())
            if str(code).strip() and str(code).strip() != '*'
        ))
        if not codes:
            return {
                'positive_images': 0,
                'scope_images': 0,
                'affected_images': 0,
                'boxes': 0,
            }
        if len(codes) > 100:
            raise ValueError('annotation label reference preview is limited to 100 labels')
        placeholders = ','.join('?' for _ in codes)
        with closing(self._connect()) as db:
            row = db.execute(
                f'SELECT '
                f'COUNT(DISTINCT CASE WHEN box_count>0 THEN image_id END), '
                f'COUNT(DISTINCT CASE WHEN scope_ref=1 THEN image_id END), '
                f'COUNT(DISTINCT image_id), COALESCE(SUM(box_count),0) '
                f'FROM annotation_label_references '
                f'WHERE label_code IN ({placeholders})',
                codes,
            ).fetchone()
        return {
            'positive_images': int(row[0] or 0),
            'scope_images': int(row[1] or 0),
            'affected_images': int(row[2] or 0),
            'boxes': int(row[3] or 0),
        }

    def reference_image_ids(self, label_codes) -> list[str]:
        codes = list(dict.fromkeys(
            str(code).strip() for code in (label_codes or ())
            if str(code).strip() and str(code).strip() != '*'
        ))
        if not codes:
            return []
        if len(codes) > 100:
            raise ValueError('annotation label reference lookup is limited to 100 labels')
        placeholders = ','.join('?' for _ in codes)
        with closing(self._connect()) as db:
            rows = db.execute(
                f'SELECT DISTINCT image_id FROM annotation_label_references '
                f'WHERE label_code IN ({placeholders}) ORDER BY image_id',
                codes,
            ).fetchall()
        return [str(row[0]) for row in rows]

    def remap_labels_if_digests(
        self, requests, *, source_label: str | None = None,
        source_labels=None, target_label: str,
        target_class_id: int, project_material: bool = True,
    ) -> list[dict]:
        requests = [dict(item) for item in requests or []]
        if len(requests) > 500:
            raise ValueError('annotation remap batch is limited to 500 image ids')
        if not requests:
            return []
        ids = [self._id(item.get('image_id')) for item in requests]
        if len(set(ids)) != len(ids):
            raise ValueError('annotation remap image ids must be unique')
        preloaded = self.get_many(ids)
        results, projections = [], {}
        now = datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                for request, image_id in zip(requests, ids):
                    row = db.execute(
                        'SELECT * FROM annotations WHERE image_id=?',
                        (image_id,),
                    ).fetchone()
                    current = (
                        self._decode_persisted_row(row)
                        if row is not None else preloaded[image_id]
                    )
                    current_digest = self.record_digest(current)
                    expected = str(request.get('expected_digest') or '')
                    if not expected or current_digest != expected:
                        results.append({
                            'image_id': image_id,
                            'status': 'stale',
                            'current_digest': current_digest,
                        })
                        continue
                    planned = self.plan_label_remap(
                        current,
                        source_label=source_label,
                        source_labels=source_labels,
                        target_label=target_label,
                        target_class_id=target_class_id,
                    )
                    changed_content = planned['content_digest'] != current_digest
                    if changed_content:
                        if row is not None:
                            changed = db.execute(
                                """UPDATE annotations SET
                                   annotation_state=?, version=version+1,
                                   content_digest=?, boxes_json=?, scope_json=?,
                                   updated_at=?
                                   WHERE image_id=? AND content_digest=?""",
                                (
                                    planned['annotation_state'],
                                    planned['content_digest'],
                                    planned['boxes_payload'],
                                    planned['scope_payload'],
                                    now,
                                    image_id,
                                    current_digest,
                                ),
                            ).rowcount
                            if changed != 1:
                                results.append({
                                    'image_id': image_id,
                                    'status': 'stale',
                                    'current_digest': current_digest,
                                })
                                continue
                        else:
                            db.execute(
                                """INSERT INTO annotations
                                   (image_id, annotation_state, version,
                                    content_digest, boxes_json, scope_json,
                                    created_at, updated_at)
                                   VALUES (?, ?, 1, ?, ?, ?, ?, ?)""",
                                (
                                    image_id,
                                    planned['annotation_state'],
                                    planned['content_digest'],
                                    planned['boxes_payload'],
                                    planned['scope_payload'],
                                    now,
                                    now,
                                ),
                            )
                    label_counts = {}
                    for box in planned['boxes']:
                        code = str(
                            box.get('label') or box.get('code') or ''
                        ).strip()
                        if code:
                            label_counts[code] = label_counts.get(code, 0) + 1
                    projections[image_id] = {
                        'annotation_state': planned['annotation_state'],
                        'annotation_scope': planned['annotation_scope'],
                        'annotation_hash': planned['content_digest'],
                        'annotated': planned['annotation_state'] in {
                            'annotated', 'confirmed_empty',
                        },
                        'box_count': len(planned['boxes']),
                        'labels': sorted(label_counts),
                        'label_counts': label_counts,
                    }
                    results.append({
                        'image_id': image_id,
                        'status': 'applied' if changed_content else 'unchanged',
                        'changed_boxes': int(planned['changed_boxes']),
                        'changed_scope': int(planned.get('changed_scope') or 0),
                        'content_digest': planned['content_digest'],
                    })
                db.execute('COMMIT')
            except Exception:
                db.execute('ROLLBACK')
                raise
        if project_material and projections and (
            (self.project_path / 'materials.sqlite3').exists()
            or (self.project_path / 'images.json').exists()
        ):
            from .material_repository import MaterialRepository
            MaterialRepository(self.project_path).patch(projections)
        return results

    def summary(self):
        """Count persisted states; legacy JSON remains a per-image lazy fallback."""
        with closing(self._connect()) as db:
            rows = db.execute(
                'SELECT annotation_state, COUNT(*) AS total '
                'FROM annotations GROUP BY annotation_state'
            ).fetchall()
        counts = {state: 0 for state in STATES}
        counts.update({row['annotation_state']: int(row['total']) for row in rows})
        return {**counts, 'total': sum(counts.values())}

    def upsert_many(
        self, rows, *, project_material: bool = True, return_rows: bool = False,
    ):
        written = []
        persisted_rows = []
        projections = {}
        with closing(self._connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            for row in rows:
                image_id = self._id(row['image_id'])
                expected_version = row.get('expected_version')
                if expected_version is not None:
                    expected_version = int(expected_version)
                    if expected_version < 0:
                        raise ValueError('expected annotation version must be >= 0')
                    current = db.execute(
                        "SELECT version FROM annotations WHERE image_id=?",
                        (image_id,),
                    ).fetchone()
                    actual_version = int(current['version']) if current is not None else 0
                    if actual_version != expected_version:
                        raise AnnotationConflictError(
                            image_id, expected_version, actual_version
                        )
                boxes = list(row.get('boxes') or [])
                state = row.get('annotation_state') or ('annotated' if boxes else 'confirmed_empty')
                if state not in STATES or bool(boxes) != (state == 'annotated'):
                    raise ValueError('annotation state does not agree with boxes')
                scope = _normalize_scope(row.get('annotation_scope'))
                if state == 'annotated' and not scope:
                    scope = _normalize_scope(
                        box.get('label') or box.get('code') for box in boxes
                    )
                if state == 'confirmed_empty' and not scope:
                    scope = self._default_negative_scope()
                if state == 'unannotated':
                    scope = []
                boxes_payload = json.dumps(
                    boxes,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(',', ':'),
                    allow_nan=False,
                )
                scope_payload = json.dumps(
                    scope,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(',', ':'),
                )
                digest_payload = json.dumps(
                    {
                        'annotation_state': state,
                        'annotation_scope': scope,
                        'boxes': json.loads(boxes_payload),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(',', ':'),
                    allow_nan=False,
                )
                digest = hashlib.sha256(digest_payload.encode('utf-8')).hexdigest()
                now = datetime.now(timezone.utc).isoformat()
                db.execute(
                    """INSERT INTO annotations
                       (image_id, annotation_state, version, content_digest,
                        boxes_json, scope_json, created_at, updated_at)
                       VALUES (?, ?, 1, ?, ?, ?, ?, ?)
                       ON CONFLICT(image_id) DO UPDATE SET
                           annotation_state=excluded.annotation_state,
                           version=annotations.version+1,
                           content_digest=excluded.content_digest,
                           boxes_json=excluded.boxes_json,
                           scope_json=excluded.scope_json,
                           updated_at=excluded.updated_at
                       WHERE annotations.content_digest != excluded.content_digest""",
                    (
                        image_id,
                        state,
                        digest,
                        boxes_payload,
                        scope_payload,
                        now,
                        now,
                    ),
                )
                if return_rows:
                    persisted = db.execute(
                        "SELECT * FROM annotations WHERE image_id=?", (image_id,)
                    ).fetchone()
                    if persisted is None:
                        raise RuntimeError("annotation upsert did not persist a row")
                    persisted_rows.append(self._decode_persisted_row(persisted))
                projections[image_id] = {
                    'annotation_state': state,
                    'annotation_scope': scope,
                    'annotation_hash': digest,
                    'annotated': state in {'annotated', 'confirmed_empty'},
                    'box_count': len(boxes),
                    'labels': sorted({
                        str(box.get('label') or box.get('code') or '').strip()
                        for box in boxes
                        if str(box.get('label') or box.get('code') or '').strip()
                    }),
                }
                written.append(image_id)
        if project_material and projections and (
            (self.project_path / 'materials.sqlite3').exists()
            or (self.project_path / 'images.json').exists()
        ):
            # Keep searchable material metadata as a projection only. Annotation
            # Repository remains the ground-truth authority.
            from .material_repository import MaterialRepository
            MaterialRepository(self.project_path).patch(projections)
        return persisted_rows if return_rows else written

    def upsert(
        self, image_id, boxes, annotation_state=None, annotation_scope=None,
        *, project_material: bool = True, expected_version=None,
    ):
        persisted = self.upsert_many([{
            'image_id': image_id,
            'boxes': boxes,
            'annotation_state': annotation_state,
            'annotation_scope': annotation_scope,
            'expected_version': expected_version,
        }], project_material=project_material, return_rows=True)
        if not persisted:
            raise RuntimeError("annotation upsert did not return a persisted row")
        return persisted[0]

    def exists(self, image_id) -> bool:
        image_id = self._id(image_id)
        with closing(self._connect()) as db:
            return db.execute(
                "SELECT 1 FROM annotations WHERE image_id=?", (image_id,)
            ).fetchone() is not None

    @staticmethod
    def _delete_token(token) -> str:
        token = str(token or "").strip()
        if (
            not token
            or len(token) > 128
            or any(character in token for character in "/\\:\x00")
            or token in {".", ".."}
        ):
            raise ValueError("invalid annotation delete token")
        return token

    def delete_backup_count(self, token) -> int:
        token = self._delete_token(token)
        with closing(self._connect()) as db:
            return int(db.execute(
                "SELECT COUNT(*) FROM annotation_delete_backup WHERE token=?",
                (token,),
            ).fetchone()[0])

    def prepare_delete(self, token, image_ids) -> int:
        """Persist an idempotent SQLite backup before dataset deletion can remove GT."""
        token = self._delete_token(token)
        ids = list(dict.fromkeys(self._id(value) for value in image_ids))
        if not ids:
            return 0
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                db.executemany(
                    """INSERT OR IGNORE INTO annotation_delete_backup
                       (token, image_id, annotation_state, version, content_digest,
                        boxes_json, scope_json, created_at, updated_at)
                       SELECT ?, image_id, annotation_state, version, content_digest,
                              boxes_json, scope_json, created_at, updated_at
                       FROM annotations WHERE image_id=?""",
                    ((token, image_id) for image_id in ids),
                )
                count = int(db.execute(
                    "SELECT COUNT(*) FROM annotation_delete_backup WHERE token=?",
                    (token,),
                ).fetchone()[0])
                db.execute("COMMIT")
                return count
            except Exception:
                db.execute("ROLLBACK")
                raise

    def finalize_delete(self, token) -> int:
        """Delete matching annotation truth and remain idempotent after a crash.

        A recovery run may arrive after the annotation rows were already deleted
        but before the journal/backup cleanup completed. Missing rows are therefore
        treated as already finalized. A newer row with a different digest still
        fails closed and is never removed.
        """
        token = self._delete_token(token)
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                conflict = db.execute(
                    """SELECT annotations.image_id
                       FROM annotations
                       JOIN annotation_delete_backup backup
                         ON backup.image_id=annotations.image_id
                       WHERE backup.token=?
                         AND backup.content_digest<>annotations.content_digest
                       LIMIT 1""",
                    (token,),
                ).fetchone()
                if conflict is not None:
                    raise RuntimeError(
                        "annotation changed during dataset deletion; refusing stale delete"
                    )
                cursor = db.execute(
                    """DELETE FROM annotations
                       WHERE EXISTS (
                         SELECT 1 FROM annotation_delete_backup backup
                         WHERE backup.token=?
                           AND backup.image_id=annotations.image_id
                           AND backup.content_digest=annotations.content_digest
                       )""",
                    (token,),
                )
                deleted = max(0, int(cursor.rowcount))
                db.execute("COMMIT")
                return deleted
            except Exception:
                db.execute("ROLLBACK")
                raise

    def restore_delete(self, token) -> int:
        """Restore missing GT from backup without overwriting a newer concurrent annotation."""
        token = self._delete_token(token)
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                rows = db.execute(
                    """SELECT image_id, annotation_state, version, content_digest,
                              boxes_json, scope_json, created_at, updated_at
                       FROM annotation_delete_backup WHERE token=? ORDER BY image_id""",
                    (token,),
                ).fetchall()
                db.executemany(
                    """INSERT OR IGNORE INTO annotations
                       (image_id, annotation_state, version, content_digest, boxes_json,
                        scope_json, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (tuple(row) for row in rows),
                )
                db.execute(
                    "DELETE FROM annotation_delete_backup WHERE token=?", (token,)
                )
                db.execute("COMMIT")
                return len(rows)
            except Exception:
                db.execute("ROLLBACK")
                raise

    def complete_delete(self, token) -> int:
        token = self._delete_token(token)
        with closing(self._connect()) as db, db:
            cursor = db.execute(
                "DELETE FROM annotation_delete_backup WHERE token=?", (token,)
            )
            return max(0, int(cursor.rowcount))

    def remove(self, image_ids):
        with closing(self._connect()) as db, db:
            db.executemany(
                'DELETE FROM annotations WHERE image_id=?',
                ((self._id(i),) for i in image_ids),
            )

"""Primary annotation storage; legacy JSON is read only until an explicit update."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


STATES = {"unannotated", "annotated", "confirmed_empty"}


def _normalize_scope(values) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    return sorted({str(value).strip() for value in values if str(value).strip()})


class AnnotationRepository:
    def __init__(self, project_path: str | Path):
        self.project_path = Path(project_path)
        self.project_path.mkdir(parents=True, exist_ok=True)
        self.path = self.project_path / "annotations.sqlite3"
        with closing(self._connect()) as db:
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
                db.commit()

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        return db

    @staticmethod
    def _id(image_id):
        image_id = str(image_id)
        if not image_id or any(c in image_id for c in '/\\:') or image_id in {'.', '..'}:
            raise ValueError("invalid annotation image_id")
        return image_id

    def get(self, image_id):
        image_id = self._id(image_id)
        with closing(self._connect()) as db:
            row = db.execute("SELECT * FROM annotations WHERE image_id=?", (image_id,)).fetchone()
        if row:
            result = dict(row)
            result['boxes'] = json.loads(result.pop('boxes_json'))
            result['annotation_scope'] = _normalize_scope(
                json.loads(result.pop('scope_json', '[]') or '[]')
            )
            return result
        path = self.project_path / 'annotations' / f'{image_id}.json'
        legacy = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
        boxes = legacy.get('boxes') or []
        state = legacy.get('annotation_state') or ('annotated' if boxes else 'unannotated')
        scope = _normalize_scope(legacy.get('annotation_scope'))
        if state == 'annotated' and not scope:
            scope = _normalize_scope(box.get('label') or box.get('code') for box in boxes)
        if state == 'confirmed_empty' and not scope:
            scope = ['*']
        return {
            **legacy,
            'image_id': image_id,
            'boxes': boxes,
            'annotation_state': state,
            'annotation_scope': scope,
            'version': 0,
        }

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

    def upsert_many(self, rows):
        written = []
        projections = {}
        with closing(self._connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            for row in rows:
                image_id = self._id(row['image_id'])
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
                    # Explicit confirmed-empty means the reviewer/importer verified
                    # the image against the full active label set at that point.
                    # '*' keeps this legacy/global scope distinguishable from
                    # unannotated while allowing future partial scopes by code.
                    scope = ['*']
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
        if projections and (
            (self.project_path / 'materials.sqlite3').exists()
            or (self.project_path / 'images.json').exists()
        ):
            # Keep searchable material metadata as a projection only. Annotation
            # Repository remains the ground-truth authority.
            from .material_repository import MaterialRepository
            MaterialRepository(self.project_path).patch(projections)
        return written

    def upsert(self, image_id, boxes, annotation_state=None, annotation_scope=None):
        self.upsert_many([{
            'image_id': image_id,
            'boxes': boxes,
            'annotation_state': annotation_state,
            'annotation_scope': annotation_scope,
        }])
        return self.get(image_id)

    def remove(self, image_ids):
        with closing(self._connect()) as db, db:
            db.executemany(
                'DELETE FROM annotations WHERE image_id=?',
                ((self._id(i),) for i in image_ids),
            )

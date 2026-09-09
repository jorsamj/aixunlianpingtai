"""Primary annotation storage; legacy JSON is read only until an explicit update."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


STATES = {"unannotated", "annotated", "confirmed_empty"}


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
                    boxes_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_annotations_state ON annotations(annotation_state, image_id);
                CREATE INDEX IF NOT EXISTS ix_annotations_updated ON annotations(updated_at);
            """)

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
            return result
        path = self.project_path / 'annotations' / f'{image_id}.json'
        legacy = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
        boxes = legacy.get('boxes') or []
        state = legacy.get('annotation_state') or ('annotated' if boxes else 'unannotated')
        return {**legacy, 'image_id': image_id, 'boxes': boxes, 'annotation_state': state, 'version': 0}

    def upsert_many(self, rows):
        written = []
        with closing(self._connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            for row in rows:
                image_id = self._id(row['image_id'])
                boxes = list(row.get('boxes') or [])
                state = row.get('annotation_state') or ('annotated' if boxes else 'confirmed_empty')
                if state not in STATES or bool(boxes) != (state == 'annotated'):
                    raise ValueError('annotation state does not agree with boxes')
                payload = json.dumps(boxes, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
                digest = hashlib.sha256((state + '\n' + payload).encode('utf-8')).hexdigest()
                now = datetime.now(timezone.utc).isoformat()
                db.execute("""INSERT INTO annotations VALUES (?, ?, 1, ?, ?, ?, ?)
                    ON CONFLICT(image_id) DO UPDATE SET annotation_state=excluded.annotation_state,
                    version=annotations.version+1, content_digest=excluded.content_digest,
                    boxes_json=excluded.boxes_json, updated_at=excluded.updated_at
                    WHERE annotations.content_digest != excluded.content_digest""",
                    (image_id, state, digest, payload, now, now))
                written.append(image_id)
        return written

    def upsert(self, image_id, boxes, annotation_state=None):
        self.upsert_many([{'image_id': image_id, 'boxes': boxes, 'annotation_state': annotation_state}])
        return self.get(image_id)

    def remove(self, image_ids):
        with closing(self._connect()) as db, db:
            db.executemany('DELETE FROM annotations WHERE image_id=?', ((self._id(i),) for i in image_ids))

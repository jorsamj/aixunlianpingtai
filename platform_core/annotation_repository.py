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
                CREATE TABLE IF NOT EXISTS annotation_remap_audit (
                    task_id TEXT NOT NULL, image_id TEXT NOT NULL,
                    changed_boxes INTEGER NOT NULL, updated_at TEXT NOT NULL,
                    PRIMARY KEY(task_id, image_id)
                );
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

    def summary(self):
        """Count persisted states; legacy JSON remains a per-image lazy fallback."""
        with closing(self._connect()) as db:
            rows = db.execute('SELECT annotation_state, COUNT(*) AS total FROM annotations GROUP BY annotation_state').fetchall()
        counts = {state: 0 for state in STATES}
        counts.update({row['annotation_state']: int(row['total']) for row in rows})
        return {**counts, 'total': sum(counts.values())}

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

    def remap_imported_class(self, rows):
        """Idempotently replace boxes owned by one import/external class.

        New imports carry explicit provenance. Older 42.25 imports are matched by
        their deterministic ``<image_id>-<source line>`` box IDs and old stable
        label ID, so unrelated/manual boxes are never selected by label alone.
        """
        operations = list(rows)
        if len(operations) > 500:
            raise ValueError('annotation remap batch is limited to 500 images')
        results = []
        with closing(self._connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            for operation in operations:
                image_id = self._id(operation['image_id'])
                saved = db.execute('SELECT * FROM annotations WHERE image_id=?', (image_id,)).fetchone()
                if saved:
                    current = dict(saved)
                    boxes = list(json.loads(current['boxes_json']))
                    old_state = current['annotation_state']
                else:
                    legacy_path = self.project_path / 'annotations' / f'{image_id}.json'
                    legacy = json.loads(legacy_path.read_text(encoding='utf-8')) if legacy_path.is_file() else {}
                    boxes = list(legacy.get('boxes') or [])
                    old_state = legacy.get('annotation_state') or ('annotated' if boxes else 'unannotated')
                remap_task_id = str(operation['remap_task_id'])
                replay = db.execute(
                    'SELECT changed_boxes FROM annotation_remap_audit WHERE task_id=? AND image_id=?',
                    (remap_task_id, image_id)).fetchone()
                if replay is not None:
                    results.append({'image_id': image_id, 'boxes': boxes,
                                    'annotation_state': old_state,
                                    'changed_boxes': int(replay['changed_boxes'])})
                    continue
                import_id = str(operation['import_id'])
                external_class_id = int(operation['external_class_id'])
                old_label_id = operation.get('old_target_label_id')
                target = operation.get('target_label')
                sources = {f"{image_id}-{int(box['line_number'])}": box
                           for box in operation.get('source_boxes') or []}
                found: set[str] = set()
                rewritten = []
                changed_boxes = 0
                for box in boxes:
                    box_id = str(box.get('id') or '')
                    provenance = box.get('provenance') if isinstance(box.get('provenance'), dict) else {}
                    explicit = (str(provenance.get('import_id') or '') == import_id
                                and str(provenance.get('external_class_id', '')) == str(external_class_id))
                    legacy_match = (box_id in sources and old_label_id is not None
                                    and str(box.get('label_id') or '') == str(old_label_id))
                    if not explicit and not legacy_match:
                        rewritten.append(box)
                        continue
                    found.add(box_id)
                    if target is None:
                        changed_boxes += 1
                        continue
                    source = sources.get(box_id)
                    updated = dict(box)
                    if source is not None:
                        width, height = float(operation['width']), float(operation['height'])
                        updated.update(
                            x1=max(0.0, (source['cx'] - source['w'] / 2) * width),
                            y1=max(0.0, (source['cy'] - source['h'] / 2) * height),
                            x2=min(width, (source['cx'] + source['w'] / 2) * width),
                            y2=min(height, (source['cy'] + source['h'] / 2) * height),
                        )
                    updated.update(label_id=str(target['label_id']), label=str(target['code']),
                                   class_id=int(target['class_id']), provenance={
                                       'source': 'external_import', 'import_id': import_id,
                                       'external_class_id': external_class_id,
                                       'external_label': str(operation.get('external_label') or ''),
                                   })
                    if updated != box:
                        changed_boxes += 1
                    rewritten.append(updated)
                if target is not None:
                    width, height = float(operation['width']), float(operation['height'])
                    for box_id, source in sources.items():
                        if box_id in found:
                            continue
                        changed_boxes += 1
                        rewritten.append({
                            'id': box_id, 'label_id': str(target['label_id']),
                            'label': str(target['code']), 'class_id': int(target['class_id']),
                            'x1': max(0.0, (source['cx'] - source['w'] / 2) * width),
                            'y1': max(0.0, (source['cy'] - source['h'] / 2) * height),
                            'x2': min(width, (source['cx'] + source['w'] / 2) * width),
                            'y2': min(height, (source['cy'] + source['h'] / 2) * height),
                            'provenance': {'source': 'external_import', 'import_id': import_id,
                                           'external_class_id': external_class_id,
                                           'external_label': str(operation.get('external_label') or '')},
                        })
                new_state = 'annotated' if rewritten else (
                    'confirmed_empty' if old_state == 'confirmed_empty' else 'unannotated')
                payload = json.dumps(rewritten, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False)
                digest = hashlib.sha256((new_state + '\n' + payload).encode('utf-8')).hexdigest()
                now = datetime.now(timezone.utc).isoformat()
                db.execute("""INSERT INTO annotations VALUES (?, ?, 1, ?, ?, ?, ?)
                    ON CONFLICT(image_id) DO UPDATE SET annotation_state=excluded.annotation_state,
                    version=annotations.version+1,content_digest=excluded.content_digest,
                    boxes_json=excluded.boxes_json,updated_at=excluded.updated_at
                    WHERE annotations.content_digest != excluded.content_digest""",
                    (image_id, new_state, digest, payload, now, now))
                db.execute('INSERT INTO annotation_remap_audit VALUES(?,?,?,?)',
                           (remap_task_id, image_id, changed_boxes, now))
                results.append({'image_id': image_id, 'boxes': rewritten,
                                'annotation_state': new_state, 'changed_boxes': changed_boxes})
        return results

    def remove(self, image_ids):
        with closing(self._connect()) as db, db:
            db.executemany('DELETE FROM annotations WHERE image_id=?', ((self._id(i),) for i in image_ids))

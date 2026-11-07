"""Durable, bounded human review plans for training GT scope gaps.

The plan is a frozen *review request*, never permission to infer missing GT.
Actual writes still pass through the existing formal annotation CAS/evidence API.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TrainingScopeReviewPlans:
    def __init__(self, project_path: Path):
        root = Path(project_path).resolve()
        self.path = root / "training_scope_review_plans.sqlite3"
        self.lock = FileLock(str(root / ".training_scope_review_plans.lock"), timeout=15)

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=30000")
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS plans (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                request_json TEXT NOT NULL,
                contract_codes_json TEXT NOT NULL,
                material_revision INTEGER NOT NULL,
                annotation_revision INTEGER NOT NULL,
                selected_count INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS items (
                plan_id TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                image_id TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pending','succeeded','blocked','failed')),
                codes_json TEXT NOT NULL,
                expected_version INTEGER,
                content_sha256 TEXT NOT NULL,
                message TEXT NOT NULL DEFAULT '',
                PRIMARY KEY(plan_id, image_id),
                UNIQUE(plan_id, ordinal),
                FOREIGN KEY(plan_id) REFERENCES plans(id)
            );
            CREATE INDEX IF NOT EXISTS idx_scope_review_items_status
                ON items(plan_id,status,ordinal);
        """)
        return db

    def create(self, *, project_id, actor_id, request, contract_codes, material_revision,
               annotation_revision, items):
        task_id = uuid.uuid4().hex
        timestamp = _now()
        with self.lock, closing(self._connect()) as db:
            with db:
                db.execute("INSERT INTO plans VALUES (?,?,?,?,?,?,?,?,?,?)", (
                    task_id, str(project_id), str(actor_id), timestamp, timestamp,
                    json.dumps(request, ensure_ascii=False, sort_keys=True),
                    json.dumps(sorted(contract_codes)), int(material_revision),
                    int(annotation_revision), len(items)))
                db.executemany("INSERT INTO items VALUES (?,?,?,?,?,?,?,?)", [
                    (task_id, index, item['image_id'], item['status'],
                     json.dumps(sorted(item.get('reviewed_label_codes') or [])),
                     item.get('expected_version'), item.get('source_content_sha256') or '',
                     item.get('message') or '') for index, item in enumerate(items)
                ])
        return self.read(task_id, project_id=project_id, actor_id=actor_id)

    @staticmethod
    def _owned(db, task_id, project_id, actor_id):
        row = db.execute("SELECT * FROM plans WHERE id=? AND project_id=? AND actor_id=?",
                         (str(task_id), str(project_id), str(actor_id))).fetchone()
        if row is None:
            raise LookupError("review plan not found for the authenticated reviewer")
        return dict(row)

    @staticmethod
    def _summary(db, plan):
        counts = {row['status']: row['n'] for row in db.execute(
            "SELECT status,count(*) n FROM items WHERE plan_id=? GROUP BY status", (plan['id'],))}
        samples = [dict(row) for row in db.execute(
            "SELECT image_id,status,codes_json,message FROM items WHERE plan_id=? "
            "AND status IN ('blocked','failed') ORDER BY ordinal LIMIT 15", (plan['id'],))]
        return {
            'task_id':plan['id'], 'project_id':plan['project_id'], 'actor_id':plan['actor_id'],
            'created_at':plan['created_at'], 'updated_at':plan['updated_at'],
            'material_revision':plan['material_revision'], 'annotation_revision':plan['annotation_revision'],
            'selected_count':plan['selected_count'],
            'pending':counts.get('pending', 0), 'succeeded':counts.get('succeeded', 0),
            'failed':counts.get('failed', 0), 'blocked':counts.get('blocked', 0),
            'done':not counts.get('pending', 0),
            'effective_label_codes':json.loads(plan['contract_codes_json']),
            'problems':[{'image_id':row['image_id'], 'status':row['status'],
                'reviewed_label_codes':json.loads(row['codes_json']), 'message':row['message']}
                for row in samples],
        }

    def read(self, task_id, *, project_id, actor_id):
        with closing(self._connect()) as db:
            plan = self._owned(db, task_id, project_id, actor_id)
            return self._summary(db, plan)

    def metadata(self, task_id, *, project_id, actor_id):
        with closing(self._connect()) as db:
            return self._owned(db, task_id, project_id, actor_id)

    def results(self, task_id, *, project_id, actor_id, state='problems', cursor=0, limit=50):
        if state not in {'problems','pending','succeeded','failed','blocked','all'}:
            raise ValueError('invalid review result state')
        if cursor < 0 or not 1 <= limit <= 100:
            raise ValueError('invalid review result page bounds')
        with closing(self._connect()) as db:
            self._owned(db, task_id, project_id, actor_id)
            clause = ("status IN ('blocked','failed')" if state=='problems'
                else '1=1' if state=='all' else 'status=?')
            params = [task_id] if state in {'problems','all'} else [task_id,state]
            count = db.execute(f'SELECT count(*) FROM items WHERE plan_id=? AND {clause}',params).fetchone()[0]
            rows = [dict(row) for row in db.execute(
                f'SELECT image_id,status,codes_json,message FROM items WHERE plan_id=? AND {clause} '
                'ORDER BY ordinal LIMIT ? OFFSET ?',(*params,limit,cursor))]
            return {'task_id':task_id,'state':state,'total':count,'cursor':cursor,
                'next_cursor':str(cursor+len(rows)) if cursor+len(rows)<count else None,
                'items':[{'image_id':row['image_id'],'status':row['status'],
                    'reviewed_label_codes':json.loads(row['codes_json']), 'message':row['message']} for row in rows]}

    def execute(self, task_id, *, project_id, actor_id, limit, reviewer):
        """One serial, at-most-50-item step. A crashed step is safely retryable.

        `reviewer` does the canonical GT/source/CAS check and idempotent write.
        A global annotation revision cannot be reused after our own first write;
        each frozen image version and content hash is checked individually.
        """
        with self.lock, closing(self._connect()) as db:
            plan = self._owned(db, task_id, project_id, actor_id)
            pending = [dict(row) for row in db.execute(
                "SELECT * FROM items WHERE plan_id=? AND status='pending' ORDER BY ordinal LIMIT ?",
                (task_id, limit))]
            for row in pending:
                item = {
                    'image_id':row['image_id'],
                    'reviewed_label_codes':json.loads(row['codes_json']),
                    'expected_version':row['expected_version'],
                    'source_content_sha256':row['content_sha256'],
                }
                try:
                    reviewer(plan, item)
                    status, message = 'succeeded', ''
                except Exception as error:
                    if not hasattr(error, 'status_code') and not isinstance(error, ValueError):
                        raise
                    status, message = 'failed', str(getattr(error, 'detail', str(error)))[:500]
                with db:
                    db.execute("UPDATE items SET status=?,message=? WHERE plan_id=? AND image_id=? AND status='pending'",
                               (status, message, task_id, row['image_id']))
                    db.execute("UPDATE plans SET updated_at=? WHERE id=?", (_now(),task_id))
            return {**self._summary(db, plan), 'step_processed':len(pending)}

from __future__ import annotations

import json
import sqlite3
import time
import hashlib
from contextlib import closing, contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from .task_runtime import ArtifactStore


def cross_label_overlaps(boxes: list[dict[str, Any]], *, limit: int = 12) -> list[dict[str, Any]]:
    """Return bounded, reviewable evidence of ambiguous cross-label boxes.

    A different class on the same physical target is not a safe automatic
    training label. The caller must hold the image for a human decision.
    """
    conflicts = []
    for index, left in enumerate(boxes):
        for other_index in range(index + 1, len(boxes)):
            right = boxes[other_index]
            if str(left.get("label") or "") == str(right.get("label") or ""):
                continue
            try:
                x1, y1 = max(float(left["x1"]), float(right["x1"])), max(float(left["y1"]), float(right["y1"]))
                x2, y2 = min(float(left["x2"]), float(right["x2"])), min(float(left["y2"]), float(right["y2"]))
                intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
                a = (float(left["x2"]) - float(left["x1"])) * (float(left["y2"]) - float(left["y1"]))
                b = (float(right["x2"]) - float(right["x1"])) * (float(right["y2"]) - float(right["y1"]))
                iou = intersection / (a + b - intersection) if a > 0 and b > 0 and intersection > 0 else 0.0
            except (KeyError, TypeError, ValueError, OverflowError, ZeroDivisionError):
                continue  # Existing provider and draft geometry validation handle invalid boxes.
            if iou <= 0.5:
                continue
            conflicts.append({
                "labels": [str(left.get("label") or "")[:80], str(right.get("label") or "")[:80]],
                "box_indices": [index, other_index],
                "iou": round(iou, 4),
                "boxes": [{key: box.get(key) for key in ("label", "x1", "y1", "x2", "y2")}
                          for box in (left, right)],
            })
            if len(conflicts) >= limit:
                return conflicts
    return conflicts


@dataclass(frozen=True)
class CandidateDecision:
    image_id: str
    accepted: bool
    boxes: list[dict[str, Any]] | None = None
    # Explicit human-reviewed canonical labels for THIS image. None preserves
    # legacy task-wide review behavior; never infer this field from AI output.
    review_scope: list[str] | None = None


@dataclass(frozen=True)
class CandidatePage:
    items: list[dict[str, Any]]
    next_cursor: str | None
    total: int


class CandidateStore:
    """Indexed candidates with bounded reads and atomic migration of legacy pages."""
    def __init__(self, artifacts: ArtifactStore, *, task_id: str, page_size: int = 50):
        if not 1 <= int(page_size) <= 200:
            raise ValueError("page_size must be between 1 and 200")
        self.artifacts, self.task_id, self.page_size = artifacts, str(task_id), int(page_size)
        self.path = artifacts.artifact_path(self.task_id, "candidates/items.sqlite3")

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS candidates (
                ordinal INTEGER PRIMARY KEY, image_id TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL, accepted INTEGER, boxes_count INTEGER NOT NULL, item_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_candidates_review ON candidates(status,accepted);
            CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS commits(image_id TEXT PRIMARY KEY, summary_json TEXT NOT NULL);
        """)
        db.execute("BEGIN IMMEDIATE")
        columns = {row[1] for row in db.execute("PRAGMA table_info(candidates)")}
        for name, definition in (("review_state", "TEXT NOT NULL DEFAULT 'active'"),
                                 ("draft_revision", "INTEGER NOT NULL DEFAULT 0"),
                                 ("draft_json", "TEXT"), ("review_operation_id", "TEXT")):
            if name not in columns:
                db.execute(f"ALTER TABLE candidates ADD COLUMN {name} {definition}")
        db.executescript("""
            CREATE INDEX IF NOT EXISTS ix_candidates_state ON candidates(review_state,status,boxes_count);
            CREATE TABLE IF NOT EXISTS review_transfer_receipts (
                operation_id TEXT NOT NULL,image_id TEXT NOT NULL,status TEXT NOT NULL,
                receipt_json TEXT NOT NULL,PRIMARY KEY(operation_id,image_id)
            );
            CREATE INDEX IF NOT EXISTS ix_review_transfer_status ON review_transfer_receipts(operation_id,status,image_id);
            CREATE TABLE IF NOT EXISTS review_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, image_id TEXT NOT NULL,
                operation_id TEXT NOT NULL, kind TEXT NOT NULL, event_json TEXT NOT NULL,
                UNIQUE(image_id,operation_id,kind)
            );
        """)
        db.execute("INSERT OR IGNORE INTO metadata(key,value) VALUES ('review_revision','0')")
        db.commit()
        return db

    def initialize(
        self,
        *,
        labels: list[str],
        total_images: int,
        commit_guard: Callable[[], Any] | None = None,
    ) -> None:
        """Reset a new candidate store, fencing the SQLite commit when requested."""
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute("DELETE FROM candidates")
                db.execute("DELETE FROM commits")
                db.execute("DELETE FROM review_events")
                db.execute("DELETE FROM metadata WHERE key='generation_scope_sha256'")
                db.execute("INSERT OR REPLACE INTO metadata VALUES ('initialized','1')")
                if commit_guard is not None:
                    commit_guard()
                db.commit()
            except Exception:
                db.rollback()
                raise
        self.artifacts.atomic_write_json(self.task_id, "candidates/manifest.json", {
            "schema_version": 2, "labels": list(labels), "total_images": max(0, int(total_images)),
            "page_size": self.page_size, "database_ref": "candidates/items.sqlite3",
        })

    def _ready(self, *, commit_guard: Callable[[], Any] | None = None):
        manifest = self.artifacts.read_json(self.task_id, "candidates/manifest.json", default=None)
        if not isinstance(manifest, dict):
            raise FileNotFoundError("annotation candidate manifest does not exist")
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                if db.execute("SELECT 1 FROM metadata WHERE key='initialized'").fetchone():
                    db.rollback()
                    return
                for number in range(len(manifest.get("pages") or [])):
                    for item in self.artifacts.read_json(self.task_id, self._page_ref(number), default=[]):
                        self._put(db, item, normalize=False)
                db.execute("INSERT INTO metadata VALUES ('initialized','1')")
                if commit_guard is not None:
                    commit_guard()
                db.commit()
            except Exception:
                db.rollback()
                raise

    @staticmethod
    def _bump_revision(db):
        db.execute("UPDATE metadata SET value=CAST(value AS INTEGER)+1 WHERE key='review_revision'")

    @staticmethod
    def _put(db, item, *, normalize=True):
        item = dict(item)
        image_id = str(item.get("image_id") or "")
        if not image_id:
            raise ValueError("candidate image_id is required")
        if normalize:
            existing = db.execute("SELECT draft_revision,review_state FROM candidates WHERE image_id=?", (image_id,)).fetchone()
            if existing and (existing['draft_revision'] or existing['review_state'] != 'active'):
                return  # A generation retry must never erase human work or transfer evidence.
        item["image_id"] = image_id
        item["boxes"] = [dict(box) for box in item.get("boxes") or []]
        accepted = None if normalize else item.get("accepted")
        item["accepted"] = accepted
        db.execute("""INSERT INTO candidates(image_id,status,accepted,boxes_count,item_json) VALUES (?,?,?,?,?)
            ON CONFLICT(image_id) DO UPDATE SET status=excluded.status,accepted=excluded.accepted,
                boxes_count=excluded.boxes_count,item_json=excluded.item_json""",
            (image_id, str(item.get("status") or "failed"), accepted, len(item["boxes"]), json.dumps(item, ensure_ascii=False)))
        if not normalize:
            existing_draft=db.execute('SELECT draft_json FROM candidates WHERE image_id=?',(image_id,)).fetchone()
            if existing_draft and existing_draft[0]:
                draft=json.loads(existing_draft[0]);draft['boxes']=item['boxes']
                db.execute('UPDATE candidates SET draft_json=? WHERE image_id=?',(json.dumps(draft,ensure_ascii=False),image_id))
        CandidateStore._bump_revision(db)

    def _append_items_transaction(
        self,
        db,
        items: Iterable[dict[str, Any]],
        *,
        commit_guard: Callable[[], Any] | None = None,
    ) -> None:
        db.execute("BEGIN IMMEDIATE")
        try:
            for item in items:
                self._put(db, item)
            if commit_guard is not None:
                commit_guard()
            db.commit()
        except Exception:
            db.rollback()
            raise

    def append_items(
        self,
        items: Iterable[dict[str, Any]],
        *,
        commit_guard: Callable[[], Any] | None = None,
    ) -> None:
        """Append/update candidates and optionally prove task ownership before commit.

        Candidate rows live in their own SQLite file, so obtaining the fenced
        artifact path alone is not enough to fence a later SQLite commit. The
        production AI annotation handler supplies a WorkerContext-backed guard
        so stale/late model output cannot commit after losing its lease.
        """
        self._ready(commit_guard=commit_guard)
        with closing(self._connect()) as db:
            self._append_items_transaction(
                db,
                items,
                commit_guard=commit_guard,
            )

    @contextmanager
    def write_session(
        self,
        *,
        commit_guard: Callable[[], Any] | None = None,
    ):
        """Reuse one connection while keeping every append independently durable.

        AI generation must keep per-image recovery truth so an already-billed
        provider call is not repeated after a crash. The session therefore
        reuses only connection/schema setup; each append still executes its own
        BEGIN IMMEDIATE, fencing guard, and COMMIT.
        """
        self._ready(commit_guard=commit_guard)
        with closing(self._connect()) as db:
            def append(items: Iterable[dict[str, Any]]) -> None:
                self._append_items_transaction(
                    db,
                    items,
                    commit_guard=commit_guard,
                )

            yield append

    def generation_state(
        self,
        image_ids: Iterable[str],
        *,
        commit_guard: Callable[[], Any] | None = None,
    ) -> dict[str, Any]:
        """Recover unordered generation commits from the existing candidate store.

        done_ids contains success/empty, including reviewed or transferred rows;
        failed_ids alone may be retried. next_index is the contiguous *persisted*
        prefix (including failures), never the number of completed futures.
        Read only indexed scalar columns in bounded pages under one snapshot.
        Freeze ordered input on first validation; legacy stores are validated
        against the caller's immutable task input before recording its digest.
        No candidate or formal annotation is modified by recovery.
        """
        expected = [str(value) for value in image_ids]
        scope = set(expected)
        if any(not value.strip() for value in expected):
            raise ValueError("annotation generation input contains invalid image id")
        if len(scope) != len(expected):
            raise ValueError("annotation generation input contains duplicate image ids")
        digest = hashlib.sha256()
        for image_id in expected:
            encoded = image_id.encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
        scope_hash = digest.hexdigest()
        self._ready(commit_guard=commit_guard)
        done, failed = set(), set()
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                frozen = db.execute(
                    "SELECT value FROM metadata WHERE key='generation_scope_sha256'"
                ).fetchone()
                if frozen is not None and frozen[0] != scope_hash:
                    raise ValueError("annotation generation scope differs from immutable task input")
                after_ordinal = 0
                while True:
                    rows = db.execute(
                        "SELECT ordinal,image_id,status FROM candidates "
                        "WHERE ordinal>? ORDER BY ordinal LIMIT 500", (after_ordinal,),
                    ).fetchall()
                    if not rows:
                        break
                    for row in rows:
                        image_id, status = str(row["image_id"]), str(row["status"])
                        if image_id not in scope:
                            raise ValueError("annotation candidate is outside immutable task input")
                        if image_id in done or image_id in failed:
                            raise ValueError("annotation candidate recovery contains duplicate image ids")
                        if status in {"success", "empty"}:
                            done.add(image_id)
                        elif status == "failed":
                            failed.add(image_id)
                        else:
                            raise ValueError(f"annotation candidate has invalid generation status: {status}")
                    after_ordinal = int(rows[-1]["ordinal"])
                    if len(rows) < 500:
                        break
                if frozen is None:
                    db.execute("INSERT INTO metadata VALUES ('generation_scope_sha256',?)", (scope_hash,))
                    if commit_guard is not None:
                        commit_guard()
                db.commit()
            except Exception:
                db.rollback()
                raise
        next_index = 0
        while next_index < len(expected) and (expected[next_index] in done or expected[next_index] in failed):
            next_index += 1
        return dict(done_ids=done, failed_ids=failed, succeeded=len(done),
                    failed=len(failed), total=len(done) + len(failed), next_index=next_index)

    def generation_prefix(
        self,
        image_ids: Iterable[str],
        *,
        commit_guard: Callable[[], Any] | None = None,
    ) -> dict[str, int]:
        """Return the durable contiguous generation prefix in request order.

        Candidate SQLite is stronger recovery evidence than worker.json for the
        crash window where a candidate transaction committed but the following
        checkpoint write did not. Generation is sequential, therefore stored
        rows must form an exact prefix of the immutable request image order.
        A guard also fences the rare legacy-page migration performed by _ready().
        """
        expected = [str(value) for value in image_ids]
        self._ready(commit_guard=commit_guard)
        succeeded = 0
        failed = 0
        next_index = 0
        after_ordinal = 0
        with closing(self._connect()) as db:
            stored_total = int(
                db.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
            )
            if stored_total > len(expected):
                raise ValueError(
                    "annotation candidate store contains more rows than task input"
                )
            while next_index < stored_total:
                rows = db.execute(
                    "SELECT ordinal,image_id,status FROM candidates "
                    "WHERE ordinal>? ORDER BY ordinal LIMIT 500",
                    (after_ordinal,),
                ).fetchall()
                if not rows:
                    raise ValueError(
                        "annotation candidate recovery rows changed during validation"
                    )
                for row in rows:
                    image_id = str(row["image_id"])
                    if image_id != expected[next_index]:
                        raise ValueError(
                            "annotation candidate recovery order does not match immutable task input"
                        )
                    status = str(row["status"])
                    if status == "failed":
                        failed += 1
                    elif status in {"success", "empty"}:
                        succeeded += 1
                    else:
                        raise ValueError(
                            f"annotation candidate has invalid generation status: {status}"
                        )
                    next_index += 1
                after_ordinal = int(rows[-1]["ordinal"])
        return {
            "next_index": next_index,
            "succeeded": succeeded,
            "failed": failed,
        }

    @staticmethod
    def _decode(row):
        item = json.loads(row["item_json"])
        item["accepted"] = None if row["accepted"] is None else bool(row["accepted"])
        item.setdefault("original_boxes", item.get("boxes") or [])
        if "draft_revision" in row.keys():
            item["draft_revision"] = int(row["draft_revision"])
            item["review_state"] = row["review_state"]
            item["review_operation_id"] = row["review_operation_id"]
            if row["draft_json"]:
                draft = json.loads(row["draft_json"])
                item["boxes"] = draft["boxes"]
                item["draft"] = draft
        return item

    def get(self, image_id):
        self._ready()
        with closing(self._connect()) as db:
            row = db.execute("SELECT * FROM candidates WHERE image_id=?", (str(image_id),)).fetchone()
        return self._decode(row) if row else None

    def get_many(self, image_ids) -> dict[str, dict]:
        ids = list(dict.fromkeys(str(value) for value in image_ids or [] if str(value)))
        if not ids:
            return {}
        if len(ids) > 200:
            raise ValueError("candidate batch lookup is limited to 200 image ids")
        self._ready()
        placeholders = ",".join("?" for _ in ids)
        with closing(self._connect()) as db:
            rows = db.execute(
                f"SELECT * FROM candidates WHERE image_id IN ({placeholders})",
                ids,
            ).fetchall()
        return {str(row["image_id"]): self._decode(row) for row in rows}

    def read_page(self, *, cursor: str | None, limit: int = 50, filter: str = 'all') -> CandidatePage:
        self._ready()
        try:
            offset = max(0, int(cursor or 0))
        except ValueError as error:
            raise ValueError("candidate cursor must be numeric") from error
        with closing(self._connect()) as db:
            where = self._filter_sql(filter)
            total = db.execute(f"SELECT COUNT(*) FROM candidates WHERE {where}").fetchone()[0]
            rows = db.execute(f"SELECT * FROM candidates WHERE {where} ORDER BY ordinal LIMIT ? OFFSET ?",
                              (max(1, min(200, int(limit))), offset)).fetchall()
        following = offset + len(rows)
        return CandidatePage([self._decode(row) for row in rows], str(following) if following < total else None, total)

    def iter_items(self):
        self._ready()
        ordinal = 0
        with closing(self._connect()) as db:
            while True:
                rows = db.execute(
                    "SELECT * FROM candidates WHERE ordinal>? ORDER BY ordinal LIMIT 200",
                    (ordinal,),
                ).fetchall()
                if not rows:
                    return
                for row in rows:
                    yield self._decode(row)
                ordinal = int(rows[-1]["ordinal"])
                if len(rows) < 200:
                    return

    def iter_accepted_items(self, *, include_committed=False):
        """Stream only accepted review rows in bounded ordinal pages."""
        self._ready()
        ordinal = 0
        with closing(self._connect()) as db:
            while True:
                rows = db.execute(
                    "SELECT * FROM candidates WHERE ordinal>? AND accepted=1 "
                    "AND status IN ('success','empty') AND review_state='active' "
                    + ("" if include_committed else "AND image_id NOT IN (SELECT image_id FROM commits) ") + "ORDER BY ordinal LIMIT 200",
                    (ordinal,),
                ).fetchall()
                if not rows:
                    return
                for row in rows:
                    yield self._decode(row)
                ordinal = int(rows[-1]["ordinal"])
                if len(rows) < 200:
                    return

    def get_commit_summaries(self, image_ids) -> dict[str, dict[str, Any]]:
        ids = list(dict.fromkeys(str(value) for value in image_ids or [] if str(value)))
        if len(ids) > 200:
            raise ValueError("candidate commit batch lookup is limited to 200 image ids")
        if not ids:
            return {}
        self._ready()
        placeholders = ",".join("?" for _ in ids)
        with closing(self._connect()) as db:
            rows = db.execute(
                f"SELECT image_id,summary_json FROM commits WHERE image_id IN ({placeholders})",
                ids,
            ).fetchall()
        return {
            str(row["image_id"]): json.loads(row["summary_json"])
            for row in rows
        }

    def read_commit_page(self, *, cursor: str | None = None, limit: int = 50) -> CandidatePage:
        """Page the task's historical journal by indexed image ID; never load it all."""
        count = int(limit)
        if not 1 <= count <= 100:
            raise ValueError("commit audit page size must be between 1 and 100")
        if cursor is not None and len(str(cursor)) > 200:
            raise ValueError("commit audit cursor is too long")
        self._ready()
        with closing(self._connect()) as db:
            total = int(db.execute("SELECT COUNT(*) FROM commits").fetchone()[0])
            rows = db.execute(
                "SELECT image_id,summary_json FROM commits WHERE image_id>? "
                "ORDER BY image_id LIMIT ?",
                (str(cursor or ""), count + 1),
            ).fetchall()
        selected = rows[:count]
        return CandidatePage(
            [dict(json.loads(row["summary_json"]), image_id=str(row["image_id"])) for row in selected],
            str(selected[-1]["image_id"]) if len(rows) > count else None,
            total,
        )

    def record_commit_summaries(
        self,
        summaries: Iterable[dict[str, Any]],
        *,
        commit_guard: Callable[[], Any] | None = None,
    ) -> None:
        rows = [dict(summary) for summary in summaries or []]
        if len(rows) > 200:
            raise ValueError("candidate commit journal batch is limited to 200 image ids")
        if not rows:
            return
        image_ids = [str(row.get("image_id") or "") for row in rows]
        if any(not image_id for image_id in image_ids) or len(set(image_ids)) != len(image_ids):
            raise ValueError("candidate commit journal image ids must be present and unique")
        self._ready(commit_guard=commit_guard)
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                db.executemany(
                    "INSERT OR REPLACE INTO commits(image_id,summary_json) VALUES (?,?)",
                    (
                        (str(row["image_id"]), json.dumps(row, ensure_ascii=False))
                        for row in rows
                    ),
                )
                if commit_guard is not None:
                    commit_guard()
                self._bump_revision(db)
                db.commit()
            except Exception:
                db.rollback()
                raise

    def apply_decisions(
        self,
        decisions: Iterable[CandidateDecision],
        *,
        allowed_statuses: Iterable[str] | None = None,
    ) -> None:
        """Apply review decisions with bounded candidate reads in one transaction.

        Review payloads can span many paginated candidate pages. Keep SQLite
        lookups bounded to 200 ids instead of issuing one SELECT per image.
        When allowed_statuses is provided, missing/failed candidates fail closed
        before the transaction commits so the API cannot partially apply an
        invalid review batch.
        """
        pending = list(decisions)
        allowed = (
            {str(value) for value in allowed_statuses}
            if allowed_statuses is not None
            else None
        )
        self._ready()
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                for offset in range(0, len(pending), 200):
                    batch = pending[offset:offset + 200]
                    image_ids = list(dict.fromkeys(str(item.image_id) for item in batch))
                    if not image_ids:
                        continue
                    placeholders = ",".join("?" for _ in image_ids)
                    rows = db.execute(
                        f"SELECT * FROM candidates WHERE image_id IN ({placeholders})",
                        image_ids,
                    ).fetchall()
                    items = {
                        str(row["image_id"]): self._decode(row)
                        for row in rows
                    }
                    if allowed is not None:
                        invalid = [
                            image_id
                            for image_id in image_ids
                            if image_id not in items
                            or str(items[image_id].get("status") or "") not in allowed
                        ]
                        if invalid:
                            raise ValueError(
                                "candidate decisions contain missing or unavailable review items"
                            )
                    for decision in batch:
                        image_id = str(decision.image_id)
                        item = items.get(image_id)
                        if item is None:
                            continue
                        if (item.get("review_state", "active") != "active"
                                or db.execute("SELECT 1 FROM commits WHERE image_id=?", (image_id,)).fetchone()):
                            raise ValueError("candidate is unavailable for review")
                        item = dict(item)
                        if decision.accepted and item.get("manual_review_required"):
                            if not int(item.get("draft_revision") or 0) and decision.boxes is None:
                                raise ValueError("跨标签重叠框尚未人工消歧，请先编辑并保存候选框")
                            if cross_label_overlaps(decision.boxes if decision.boxes is not None else item.get("boxes") or []):
                                raise ValueError("跨标签目标框仍显著重叠，请删除或修改冲突框后再采用")
                        item["accepted"] = bool(decision.accepted)
                        if decision.boxes is not None:
                            item["boxes"] = decision.boxes
                        # A new decision replaces, never inherits, previously
                        # attested scope. Rejection cannot attest any scope.
                        item.pop("review_scope", None)
                        if decision.review_scope is not None:
                            scope = decision.review_scope
                            if (not decision.accepted or not isinstance(scope, list)
                                    or not 1 <= len(scope) <= 128
                                    or any(not isinstance(code, str) or not code.strip()
                                           or code != code.strip() for code in scope)
                                    or len(set(scope)) != len(scope)):
                                raise ValueError("candidate per-image review scope is invalid")
                            item["review_scope"] = list(scope)
                        self._put(db, item, normalize=False)
                        items[image_id] = item
                db.commit()
            except Exception:
                db.rollback()
                raise

    def decide_unmentioned(self, accepted, *, exclude=()):
        self._ready()
        with closing(self._connect()) as db, db:
            db.execute("CREATE TEMP TABLE excluded(image_id TEXT PRIMARY KEY)")
            db.executemany("INSERT OR IGNORE INTO excluded VALUES (?)", ((str(value),) for value in exclude))
            db.execute("UPDATE candidates SET accepted=? WHERE status IN ('success','empty') "
                       "AND accepted IS NULL AND review_state='active' "
                       "AND (NOT ? OR COALESCE(json_extract(item_json,'$.manual_review_required'),0)=0 OR draft_revision>0) "
                       "AND image_id NOT IN (SELECT image_id FROM commits) "
                       "AND image_id NOT IN (SELECT image_id FROM excluded)", (bool(accepted), bool(accepted)))
            self._bump_revision(db)

    def remap_labels(self, mapping: dict[str, str], label_ids: dict[str, int]) -> None:
        normalized = {
            str(source): str(target)
            for source, target in dict(mapping or {}).items()
            if str(source) and str(target)
        }
        unknown_targets = sorted(set(normalized.values()) - set(label_ids))
        if unknown_targets:
            raise ValueError("annotation label mapping targets are unavailable: " + ", ".join(unknown_targets))
        # Even an identity/no-op mapping must revalidate candidate labels against
        # the current active project catalog. A label may have been disabled or
        # its class_id may have changed after human confirmation but before the
        # durable review commit is claimed by a Worker.
        self._ready()
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                after_ordinal = 0
                while True:
                    rows = db.execute(
                        "SELECT * FROM candidates "
                        "WHERE status IN ('success','empty') AND ordinal>? AND review_state='active' AND (accepted IS NULL OR accepted=1) "
                        "ORDER BY ordinal LIMIT 200",
                        (after_ordinal,),
                    ).fetchall()
                    if not rows:
                        break
                    for row in rows:
                        item = self._decode(row)
                        changed = False
                        boxes = []
                        for box in item.get("boxes") or []:
                            current = dict(box)
                            source = str(current.get("label") or "").strip()
                            if not source:
                                raise ValueError("annotation candidate label is required")
                            if source not in normalized and source not in label_ids:
                                raise ValueError(
                                    f"annotation candidate label is unavailable: {source}"
                                )
                            target = normalized.get(source, source)
                            target_id = int(label_ids[target])
                            try:
                                current_id = int(current.get("class_id"))
                            except (TypeError, ValueError, OverflowError):
                                current_id = None
                            if source != target or current_id != target_id:
                                current["label"] = target
                                current["class_id"] = target_id
                                changed = True
                            boxes.append(current)
                        if changed:
                            item["boxes"] = boxes
                            self._put(db, item, normalize=False)
                    after_ordinal = int(rows[-1]["ordinal"])
                    if len(rows) < 200:
                        break
                db.commit()
            except Exception:
                db.rollback()
                raise

    def label_summary(self) -> list[dict[str, Any]]:
        """SQL aggregation avoids decoding every image on first-page entry."""
        self._ready()
        with closing(self._connect()) as db:
            rows=db.execute("""SELECT json_extract(b.value,'$.label') AS label,
                COUNT(*) AS boxes,COUNT(DISTINCT c.image_id) AS images
                FROM candidates c JOIN json_each(COALESCE(c.draft_json,c.item_json),'$.boxes') b
                WHERE c.status IN ('success','empty') AND c.review_state='active'
                AND (c.accepted IS NULL OR c.accepted=1)
                AND COALESCE(json_extract(b.value,'$.label'),'')<>''
                GROUP BY label ORDER BY boxes DESC,label""").fetchall()
            return [dict(row) for row in rows]

    def summary(self) -> dict[str, int]:
        self._ready()
        summary = {key: 0 for key in ("total", "success", "empty", "failed", "accepted", "rejected", "unreviewed", "boxes")}
        with closing(self._connect()) as db:
            for row in db.execute("SELECT status,accepted,COUNT(*) AS n,SUM(boxes_count) AS boxes FROM candidates GROUP BY status,accepted"):
                count = row["n"]
                summary["total"] += count
                summary["boxes"] += row["boxes"]
                if row["status"] in {"success", "empty", "failed"}:
                    summary[row["status"]] += count
                # Failed provider generations have no human decision to make.
                if row["status"] in {"success", "empty"}:
                    summary["unreviewed" if row["accepted"] is None else "accepted" if row["accepted"] else "rejected"] += count
        return summary

    def statistics(self) -> dict[str, int]:
        """Exact per-task stage counts, including only durably journaled GT commits.

        The commit journal is written after the formal AnnotationRepository batch.
        It means 'committed by this task', not that the GT remains unchanged today.
        """
        summary = self.summary()
        with closing(self._connect()) as db:
            summary["gt_committed"] = int(db.execute("SELECT COUNT(*) FROM commits").fetchone()[0])
        return summary

    def failure_codes(self, *, limit: int = 5) -> list[dict[str, Any]]:
        """Bounded failure-code histogram, no user/model response text."""
        self._ready()
        with closing(self._connect()) as db:
            rows = db.execute(
                """SELECT COALESCE(NULLIF(json_extract(item_json, '$.error_code'), ''),
                           'UNKNOWN_FAILURE') AS code, COUNT(*) AS n
                   FROM candidates WHERE status='failed'
                   GROUP BY code ORDER BY n DESC, code LIMIT ?""",
                (max(1, min(int(limit), 20)),),
            ).fetchall()
        return [{"code": str(row["code"])[:100], "count": int(row["n"])} for row in rows]

    def all_items(self):
        """Compatibility only; production consumers must use iter_items."""
        return list(self.iter_items())

    def reject_all_reviewable(self) -> None:
        self.decide_unmentioned(False)

    @staticmethod
    def _page_ref(page_number: int) -> str:
        return f"candidates/page-{page_number:06d}.json"
    @staticmethod
    def _filter_sql(filter):
        active = "review_state='active'"
        options = {
            'all': '1=1', 'with_boxes': f"{active} AND status='success' AND boxes_count>0",
            'clean_boxes': f"{active} AND status='success' AND boxes_count>0 AND COALESCE(json_extract(item_json,'$.manual_review_required'),0)=0",
            'ambiguous': f"{active} AND status='success' AND COALESCE(json_extract(item_json,'$.manual_review_required'),0)=1 AND image_id NOT IN (SELECT image_id FROM commits)",
            'empty': f"{active} AND status IN ('success','empty') AND boxes_count=0",
            'zero': f"{active} AND status IN ('success','empty') AND boxes_count=0",
            'rejected': f"{active} AND accepted=0",
            'low': f"{active} AND EXISTS (SELECT 1 FROM json_each(candidates.item_json,'$.boxes') b WHERE json_extract(b.value,'$.confidence')<0.6)",
            'hard': f"{active} AND COALESCE(json_array_length(json_extract(item_json,'$.hard_sample_signals')),0)>0",
            'failed': "status='failed'", 'edited': 'draft_revision>0',
            'transferred': "review_state='transferred'", 'blocked': "review_state='blocked'",
            'unreviewed': f"{active} AND status IN ('success','empty') AND accepted IS NULL AND image_id NOT IN (SELECT image_id FROM commits)",
            'remaining': f"{active} AND status IN ('success','empty') AND (accepted IS NULL OR accepted=1) AND image_id NOT IN (SELECT image_id FROM commits)",
        }
        if filter not in options:
            raise ValueError('unknown candidate filter')
        return options[filter]

    def review_revision(self):
        self._ready()
        with closing(self._connect()) as db:
            return int(db.execute("SELECT value FROM metadata WHERE key='review_revision'").fetchone()[0])

    def iter_selected_ids(self, filter='all'):
        self._ready()
        where = self._filter_sql(filter)
        with closing(self._connect()) as db:
            ordinal = 0
            while True:
                rows = db.execute(f'SELECT ordinal,image_id FROM candidates WHERE ordinal>? AND ({where}) ORDER BY ordinal LIMIT 200', (ordinal,)).fetchall()
                if not rows:
                    break
                for row in rows:
                    yield str(row['image_id'])
                ordinal = rows[-1]['ordinal']

    def review_counts(self):
        self._ready()
        with closing(self._connect()) as db:
            result = {key: int(db.execute(f'SELECT COUNT(*) FROM candidates WHERE {self._filter_sql(value)}').fetchone()[0])
                      for key, value in [('total','all'),('with_boxes','with_boxes'),('clean_boxes','clean_boxes'),('ambiguous','ambiguous'),('zero','zero'),('failed','failed'),('edited','edited'),('transferred','transferred'),('blocked','blocked'),('remaining_reviewable','remaining'),('unreviewed_reviewable','unreviewed')]}
            result['revision'] = int(db.execute("SELECT value FROM metadata WHERE key='review_revision'").fetchone()[0])
            return result

    def save_draft(self, image_id, boxes, *, expected_revision, actor, request_id):
        """Persist a task-local review revision, never write formal annotations.

        Geometry, source hash and permission checks belong to the API holding
        the existing task review lock. This layer enforces atomic CAS and replay.
        """
        if not isinstance(boxes, list) or len(boxes)>300 or any(not isinstance(box, dict) for box in boxes):
            raise ValueError('invalid candidate draft boxes')
        if not actor or not request_id or len(str(request_id))>200:
            raise ValueError('draft actor and request_id required')
        encoded = json.dumps(boxes, ensure_ascii=False, allow_nan=False, sort_keys=True)
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        self._ready()
        with closing(self._connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute("SELECT event_json FROM review_events WHERE image_id=? AND operation_id=? AND kind='draft'",(str(image_id),str(request_id))).fetchone()
            if prior:
                event = json.loads(prior[0])
                if event['digest'] != digest or event['actor'] != actor:
                    raise ValueError('request_id reused with different draft')
                return event['result']
            row = db.execute('SELECT * FROM candidates WHERE image_id=?',(str(image_id),)).fetchone()
            if (not row or row['status'] not in {'success','empty'} or row['review_state'] != 'active'
                    or db.execute('SELECT 1 FROM commits WHERE image_id=?',(str(image_id),)).fetchone()):
                raise ValueError('candidate unavailable for draft')
            if row['draft_revision'] != expected_revision:
                raise ValueError('candidate draft revision conflict')
            original = json.loads(row['item_json'])
            if original.get('manual_review_required') and cross_label_overlaps(boxes):
                raise ValueError('跨标签目标框仍显著重叠，请删除或修改冲突框再保存')
            result = dict(image_id=str(image_id),revision=int(expected_revision)+1,boxes=json.loads(encoded),saved_at=time.time(),actor=str(actor))
            db.execute('UPDATE candidates SET draft_revision=?,draft_json=?,boxes_count=? WHERE image_id=?',
                       (result['revision'],json.dumps(result,ensure_ascii=False),len(boxes),str(image_id)))
            db.execute("INSERT INTO review_events(image_id,operation_id,kind,event_json) VALUES (?,?,'draft',?)",(str(image_id),str(request_id),json.dumps(dict(digest=digest,actor=actor,result=result),ensure_ascii=False)))
            self._bump_revision(db)
            return result

    def set_review_exclusion(self, image_id, state, *, operation_id, actor, expected_revision=None, details=None, transfer_receipt=None):
        """Journal cross-store transfer state under the existing task lock.

        pending_transfer blocks acceptance BEFORE pool write, transferred follows
        its durable receipt; active is explicit pre-finalization undo.
        """
        receipt_rows=[] if transfer_receipt is None else [self._transfer_receipt_row(operation_id,image_id,transfer_receipt)]
        if state not in {'active','pending_transfer','transferred','blocked'}:
            raise ValueError('invalid candidate review state')
        if not operation_id or not actor:
            raise ValueError('operation and actor required')
        self._ready()
        with closing(self._connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM candidates WHERE image_id=?',(str(image_id),)).fetchone()
            if not row or row['status'] not in {'success','empty'}:
                raise ValueError('candidate unavailable for transfer')
            if row['review_state'] != 'active' and row['review_operation_id'] != str(operation_id):
                raise ValueError('candidate belongs to another transfer operation')
            if state != 'active' and db.execute("SELECT 1 FROM review_events WHERE image_id=? AND operation_id=? AND kind='active'", (str(image_id),str(operation_id))).fetchone():
                raise ValueError('transfer operation already undone')
            prior=db.execute('SELECT event_json FROM review_events WHERE image_id=? AND operation_id=? AND kind=?',(str(image_id),str(operation_id),state)).fetchone()
            if prior:
                event=json.loads(prior[0])
                if event['actor'] != actor or event['details'] != (details or {}):
                    raise ValueError('operation reused with different transfer')
                if row['review_state'] == state:
                    self._write_transfer_receipt_rows(db,receipt_rows)
                    return event
            if db.execute('SELECT 1 FROM commits WHERE image_id=?',(str(image_id),)).fetchone():
                raise ValueError('candidate already finalized')
            if expected_revision is not None and row['draft_revision'] != expected_revision:
                raise ValueError('candidate draft revision conflict')
            event=dict(image_id=str(image_id),state=state,operation_id=str(operation_id),actor=str(actor),created_at=time.time(),details=details or {})
            db.execute('UPDATE candidates SET review_state=?,review_operation_id=? WHERE image_id=?',(state,str(operation_id),str(image_id)))
            kind = state if prior is None else f"{state}:retry:{db.execute('SELECT COALESCE(MAX(id),0)+1 FROM review_events').fetchone()[0]}"
            db.execute('INSERT INTO review_events(image_id,operation_id,kind,event_json) VALUES (?,?,?,?)',(str(image_id),str(operation_id),kind,json.dumps(event,ensure_ascii=False)))
            self._bump_revision(db)
            self._write_transfer_receipt_rows(db,receipt_rows)
            return event

    @staticmethod
    def _transfer_receipt_row(operation_id,image_id,receipt):
        status=receipt.get('status')
        if status not in {'pending','failed','transferred','undone'}:
            raise ValueError('invalid transfer receipt status')
        return (str(operation_id),str(image_id),status,json.dumps(receipt,ensure_ascii=False,allow_nan=False))

    @staticmethod
    def _write_transfer_receipt_rows(db,rows,*,preserve_existing=False):
        conflict='DO NOTHING' if preserve_existing else 'DO UPDATE SET status=excluded.status,receipt_json=excluded.receipt_json'
        db.executemany('INSERT INTO review_transfer_receipts VALUES (?,?,?,?) ON CONFLICT(operation_id,image_id) '+conflict,rows)

    def write_transfer_receipts(self, operation_id, receipts, *, preserve_existing=False):
        """Bounded outbox progress in the existing candidate database, never GT."""
        if not operation_id or not isinstance(receipts,dict) or len(receipts)>200:
            raise ValueError('transfer receipt batch must contain at most 200 images')
        rows=[self._transfer_receipt_row(operation_id,image_id,receipt) for image_id,receipt in receipts.items()]
        self._ready()
        with closing(self._connect()) as db,db:
            db.execute('BEGIN IMMEDIATE')
            self._write_transfer_receipt_rows(db,rows,preserve_existing=preserve_existing)

    def read_transfer_receipts(self, operation_id, *, image_ids=None, status=None, offset=0, limit=200):
        self._ready()
        where=['operation_id=?'];values=[str(operation_id)]
        if image_ids is not None:
            ids=list(dict.fromkeys(map(str,image_ids)))
            if len(ids)>200:raise ValueError('transfer receipt lookup is limited to 200 ids')
            if not ids:return {}
            where.append('image_id IN ('+','.join('?' for _ in ids)+')');values.extend(ids)
        if status is not None:
            where.append('status=?');values.append(str(status))
        with closing(self._connect()) as db:
            rows=db.execute('SELECT image_id,receipt_json FROM review_transfer_receipts WHERE '+' AND '.join(where)+' ORDER BY image_id LIMIT ? OFFSET ?',(*values,max(1,min(200,int(limit))),max(0,int(offset)))).fetchall()
            return {str(row['image_id']):{**json.loads(row['receipt_json']), 'image_id':str(row['image_id'])} for row in rows}

    def transfer_receipt_statuses(self, operation_id):
        self._ready()
        with closing(self._connect()) as db:
            return {str(row['image_id']):str(row['status']) for row in db.execute('SELECT image_id,status FROM review_transfer_receipts WHERE operation_id=?',(str(operation_id),))}

    def transfer_receipt_counts(self, operation_id):
        self._ready()
        with closing(self._connect()) as db:
            counts={str(row['status']):int(row['n']) for row in db.execute('SELECT status,COUNT(*) n FROM review_transfer_receipts WHERE operation_id=? GROUP BY status',(str(operation_id),))}
            return {**counts,'total':sum(counts.values())}

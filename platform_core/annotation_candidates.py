from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from .task_runtime import ArtifactStore


@dataclass(frozen=True)
class CandidateDecision:
    image_id: str
    accepted: bool
    boxes: list[dict[str, Any]] | None = None


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
    def _put(db, item, *, normalize=True):
        item = dict(item)
        image_id = str(item.get("image_id") or "")
        if not image_id:
            raise ValueError("candidate image_id is required")
        item["image_id"] = image_id
        item["boxes"] = [dict(box) for box in item.get("boxes") or []]
        accepted = None if normalize else item.get("accepted")
        item["accepted"] = accepted
        db.execute("""INSERT INTO candidates(image_id,status,accepted,boxes_count,item_json) VALUES (?,?,?,?,?)
            ON CONFLICT(image_id) DO UPDATE SET status=excluded.status,accepted=excluded.accepted,
                boxes_count=excluded.boxes_count,item_json=excluded.item_json""",
            (image_id, str(item.get("status") or "failed"), accepted, len(item["boxes"]), json.dumps(item, ensure_ascii=False)))

    def append_items(
        self,
        items: Iterable[dict[str, Any]],
        *,
        commit_guard: Callable[[], Any] | None = None,
    ) -> None:
        """Append/update candidates and optionally prove task ownership before commit.

        Candidate rows live in their own SQLite file, so obtaining the fenced
        artifact path alone is not enough to fence a later SQLite commit.  The
        production AI annotation handler supplies a WorkerContext-backed guard
        so a stale execution cannot commit model output after losing its lease.
        """
        self._ready(commit_guard=commit_guard)
        with closing(self._connect()) as db:
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
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT image_id,status FROM candidates ORDER BY ordinal"
            ).fetchall()
        if len(rows) > len(expected):
            raise ValueError("annotation candidate store contains more rows than task input")
        succeeded = 0
        failed = 0
        for index, row in enumerate(rows):
            image_id = str(row["image_id"])
            if image_id != expected[index]:
                raise ValueError(
                    "annotation candidate recovery order does not match immutable task input"
                )
            status = str(row["status"])
            if status == "failed":
                failed += 1
            elif status in {"success", "empty"}:
                succeeded += 1
            else:
                raise ValueError(f"annotation candidate has invalid generation status: {status}")
        return {
            "next_index": len(rows),
            "succeeded": succeeded,
            "failed": failed,
        }

    @staticmethod
    def _decode(row):
        item = json.loads(row["item_json"])
        item["accepted"] = None if row["accepted"] is None else bool(row["accepted"])
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

    def read_page(self, *, cursor: str | None, limit: int = 50) -> CandidatePage:
        self._ready()
        try:
            offset = max(0, int(cursor or 0))
        except ValueError as error:
            raise ValueError("candidate cursor must be numeric") from error
        with closing(self._connect()) as db:
            total = db.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
            rows = db.execute("SELECT * FROM candidates ORDER BY ordinal LIMIT ? OFFSET ?",
                              (max(1, min(200, int(limit))), offset)).fetchall()
        following = offset + len(rows)
        return CandidatePage([self._decode(row) for row in rows], str(following) if following < total else None, total)

    def iter_items(self):
        self._ready()
        ordinal = 0
        while True:
            with closing(self._connect()) as db:
                rows = db.execute("SELECT * FROM candidates WHERE ordinal>? ORDER BY ordinal LIMIT 200", (ordinal,)).fetchall()
            if not rows:
                return
            for row in rows:
                yield self._decode(row)
            ordinal = rows[-1]["ordinal"]

    def iter_accepted_items(self):
        """Stream only accepted review rows in bounded ordinal pages."""
        self._ready()
        ordinal = 0
        while True:
            with closing(self._connect()) as db:
                rows = db.execute(
                    "SELECT * FROM candidates WHERE ordinal>? AND accepted=1 "
                    "AND status IN ('success','empty') ORDER BY ordinal LIMIT 200",
                    (ordinal,),
                ).fetchall()
            if not rows:
                return
            for row in rows:
                yield self._decode(row)
            ordinal = rows[-1]["ordinal"]

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
                        item = dict(item)
                        item["accepted"] = bool(decision.accepted)
                        if decision.boxes is not None:
                            item["boxes"] = decision.boxes
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
                       "AND image_id NOT IN (SELECT image_id FROM excluded)", (bool(accepted),))

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
                        "WHERE status IN ('success','empty') AND ordinal>? "
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
        summary: dict[str, dict[str, Any]] = {}
        for item in self.iter_items():
            if item.get("status") not in {"success", "empty"}:
                continue
            seen = set()
            for box in item.get("boxes") or []:
                label = str(box.get("label") or "").strip()
                if not label:
                    continue
                row = summary.setdefault(label, {"label": label, "boxes": 0, "images": 0})
                row["boxes"] += 1
                if label not in seen:
                    row["images"] += 1
                    seen.add(label)
        return sorted(summary.values(), key=lambda row: (-int(row["boxes"]), str(row["label"])))

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

    def all_items(self):
        """Compatibility only; production consumers must use iter_items."""
        return list(self.iter_items())

    def reject_all_reviewable(self) -> None:
        self.decide_unmentioned(False)

    @staticmethod
    def _page_ref(page_number: int) -> str:
        return f"candidates/page-{page_number:06d}.json"

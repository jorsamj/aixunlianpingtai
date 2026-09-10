from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from typing import Any, Iterable

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

    def initialize(self, *, labels: list[str], total_images: int) -> None:
        with closing(self._connect()) as db, db:
            db.execute("DELETE FROM candidates")
            db.execute("DELETE FROM commits")
            db.execute("INSERT OR REPLACE INTO metadata VALUES ('initialized','1')")
        self.artifacts.atomic_write_json(self.task_id, "candidates/manifest.json", {
            "schema_version": 2, "labels": list(labels), "total_images": max(0, int(total_images)),
            "page_size": self.page_size, "database_ref": "candidates/items.sqlite3",
        })

    def _ready(self):
        manifest = self.artifacts.read_json(self.task_id, "candidates/manifest.json", default=None)
        if not isinstance(manifest, dict):
            raise FileNotFoundError("annotation candidate manifest does not exist")
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM metadata WHERE key='initialized'").fetchone():
                return
            for number in range(len(manifest.get("pages") or [])):
                for item in self.artifacts.read_json(self.task_id, self._page_ref(number), default=[]):
                    self._put(db, item, normalize=False)
            db.execute("INSERT INTO metadata VALUES ('initialized','1')")

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

    def append_items(self, items: Iterable[dict[str, Any]]) -> None:
        self._ready()
        with closing(self._connect()) as db, db:
            for item in items:
                self._put(db, item)

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

    def apply_decisions(self, decisions: Iterable[CandidateDecision]) -> None:
        self._ready()
        with closing(self._connect()) as db, db:
            for decision in decisions:
                row = db.execute("SELECT * FROM candidates WHERE image_id=?", (str(decision.image_id),)).fetchone()
                if not row:
                    continue
                item = self._decode(row)
                item["accepted"] = bool(decision.accepted)
                if decision.boxes is not None:
                    item["boxes"] = decision.boxes
                self._put(db, item, normalize=False)

    def decide_unmentioned(self, accepted, *, exclude=()):
        self._ready()
        with closing(self._connect()) as db, db:
            db.execute("CREATE TEMP TABLE excluded(image_id TEXT PRIMARY KEY)")
            db.executemany("INSERT OR IGNORE INTO excluded VALUES (?)", ((str(value),) for value in exclude))
            db.execute("UPDATE candidates SET accepted=? WHERE status IN ('success','empty') "
                       "AND image_id NOT IN (SELECT image_id FROM excluded)", (bool(accepted),))

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
                # Failed generation has no human decision to make.
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

"""Bounded, durable candidate storage for one material-import task artifact.

Scan input owns candidate metadata; confirmation and indexing own lifecycle
fields. No manifest or complete selection is retained in Python or JSON.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Iterable, Iterator, Mapping

from .errors import redact_storage_error


_SCHEMA = """
CREATE TABLE IF NOT EXISTS candidates (
    import_id TEXT NOT NULL DEFAULT '',
    preview_id TEXT NOT NULL DEFAULT '',
    object_key TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    storage_source_id TEXT NOT NULL,
    storage_type TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    etag TEXT NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    status TEXT NOT NULL,
    error TEXT NOT NULL,
    duplicate INTEGER NOT NULL DEFAULT 0 CHECK (duplicate IN (0, 1)),
    selected INTEGER NOT NULL DEFAULT 0 CHECK (selected IN (0, 1)),
    indexed INTEGER NOT NULL DEFAULT 0 CHECK (indexed IN (0, 1)),
    image_id TEXT,
    indexed_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_candidates_status ON candidates(status, object_key);
CREATE INDEX IF NOT EXISTS ix_candidates_selection ON candidates(selected, indexed, object_key);
CREATE INDEX IF NOT EXISTS ix_candidates_hash ON candidates(content_sha256);
CREATE TABLE IF NOT EXISTS meta (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    digest TEXT NOT NULL,
    selected_count INTEGER NOT NULL,
    confirmed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dataset_objects (
    object_key TEXT PRIMARY KEY, size_bytes INTEGER NOT NULL, etag TEXT NOT NULL,
    sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dataset_manifest (
    object_key TEXT PRIMARY KEY, split TEXT NOT NULL, label_key TEXT,
    annotation_status TEXT NOT NULL DEFAULT 'unannotated',
    box_count INTEGER NOT NULL DEFAULT 0, yaml_key TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS candidate_annotations (
    object_key TEXT NOT NULL REFERENCES dataset_manifest(object_key),
    line_number INTEGER NOT NULL, class_id INTEGER NOT NULL,
    cx REAL NOT NULL, cy REAL NOT NULL, w REAL NOT NULL, h REAL NOT NULL,
    clipped INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (object_key, line_number)
);
CREATE INDEX IF NOT EXISTS ix_candidate_annotations_class ON candidate_annotations(class_id, object_key, line_number);
CREATE TABLE IF NOT EXISTS label_mapping (
    class_id INTEGER PRIMARY KEY, name TEXT NOT NULL, target_label_id TEXT,
    import_id TEXT NOT NULL DEFAULT '', action TEXT, target_label_code TEXT
);
CREATE TABLE IF NOT EXISTS annotation_issues (
    object_key TEXT NOT NULL, line_number INTEGER NOT NULL,
    code TEXT NOT NULL, severity TEXT NOT NULL,
    PRIMARY KEY (object_key, line_number, code)
);
CREATE INDEX IF NOT EXISTS ix_annotation_issues_code ON annotation_issues(code);
CREATE TABLE IF NOT EXISTS confirmation_details (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1), payload TEXT NOT NULL,
    import_id TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS indexing_outcomes (
    object_key TEXT PRIMARY KEY, image_id TEXT NOT NULL, existing_material INTEGER NOT NULL,
    annotations_written INTEGER NOT NULL DEFAULT 0, boxes_imported INTEGER NOT NULL DEFAULT 0,
    boxes_skipped INTEGER NOT NULL DEFAULT 0, negative_samples INTEGER NOT NULL DEFAULT 0
);
"""
_SCAN_FIELDS = (
    "import_id", "preview_id", "object_key", "filename", "storage_source_id", "storage_type", "content_sha256",
    "size_bytes", "etag", "width", "height", "status", "error", "duplicate",
)
# Include provider credential names and their SDK/header aliases. Keep this
# explicit so ordinary diagnostics such as endpoint and bucket stay readable.
_CREDENTIAL_NAMES = (
    "access_key", "access_key_id", "access_key_secret", "secret", "secret_key",
    "secret_access_key", "api_key", "x_api_key", "token", "password",
    "security_token", "session_token", "access_token", "bearer_token",
    "aws_access_key_id", "aws_secret_access_key", "aws_session_token", "client_secret",
)
_CREDENTIAL = re.compile(r"""
    (?P<prefix>
        (?<![\w-])["']?
        (?:""" + "|".join(name.replace("_", "[_-]?") for name in _CREDENTIAL_NAMES) + r""")
        ["']?\s*[:=]\s*
    )
    (?P<value>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s,;}\]]+)
""", re.IGNORECASE | re.VERBOSE)
_ABSOLUTE_PATH = re.compile(r"(?<!\w)(?:[A-Za-z]:[\\/]|\\\\|/)[^\s\"'<>]*")
_HTTP_URL = re.compile(
    r"(?<!\w)https?://(?:\[[0-9a-f:.]+\]|[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?)"
    r"(?::[0-9]{1,5})?(?:[/?#][^\s\"'<>]*)?",
    re.IGNORECASE,
)


def _text(value: object) -> str:
    # Never stringify mappings, arbitrary provider objects, or nested secrets.
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    return ""


def _key(value: object) -> str:
    key = _text(value)
    if not key.strip():
        raise ValueError("object_key must be a nonempty scalar")
    return key


def _nonnegative_int(value: object) -> int:
    try:
        number = int(value) if isinstance(value, (str, int, float)) else 0
        return max(0, min(number, 2**63 - 1))
    except (ValueError, TypeError, OverflowError):
        return 0


def _redact_error(value: object) -> str:
    def replace_credential(match: re.Match) -> str:
        credential = match["value"]
        quote = credential[0] if credential[0] in {"'", '"'} else ""
        return match["prefix"] + quote + "[REDACTED]" + quote

    # Consume quoted values in full before the shared redactor truncates text or
    # handles unquoted values. This also preserves spaces within credentials.
    error = _CREDENTIAL.sub(replace_credential, _text(value))
    error = redact_storage_error(error)
    # Redact only non-URL spans. No placeholder can collide with hostile error
    # text, and a colon before a local path does not exempt it from redaction.
    parts = []
    after = 0
    for match in _HTTP_URL.finditer(error):
        parts.append(_ABSOLUTE_PATH.sub("[REDACTED PATH]", error[after:match.start()]))
        parts.append(match[0])
        after = match.end()
    parts.append(_ABSOLUTE_PATH.sub("[REDACTED PATH]", error[after:]))
    return "".join(parts)


def normalize_candidate(row: Mapping[str, object]) -> dict[str, object]:
    """Whitelist scan fields, normalize scalars, and scrub diagnostic secrets.

    object_key is a provider-relative identifier and is preserved verbatim.
    Provider configuration (including absolute roots) is never serialized.
    Selection, IDs and index timestamps cannot be injected by scan input.
    """
    key = _key(row.get("object_key"))
    storage_type = _text(row.get("storage_type")).strip().lower()
    filename = _text(row.get("filename"))
    if storage_type == "local":
        for field, value in (("object_key", key), ("filename", filename)):
            if PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute():
                raise ValueError(f"local {field} must be a relative path")
    error = _redact_error(row.get("error"))
    duplicate = _text(row.get("duplicate")).strip().lower() in {"1", "true", "yes"}
    return {
        "object_key": key,
        "filename": filename or key.replace("\\", "/").rsplit("/", 1)[-1],
        "storage_source_id": _text(row.get("storage_source_id")),
        "storage_type": storage_type,
        "content_sha256": _text(row.get("content_sha256")).strip().lower(),
        "size_bytes": _nonnegative_int(row.get("size_bytes")),
        "etag": _text(row.get("etag")),
        "width": _nonnegative_int(row.get("width")),
        "height": _nonnegative_int(row.get("height")),
        "status": _text(row.get("status")).strip().upper() or "IMPORTABLE",
        "error": error,
        "duplicate": int(duplicate),
    }


def _limit(value: int, maximum: int = 5000) -> int:
    return max(1, min(int(value), maximum))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Confirmation:
    digest: str
    selected_count: int
    confirmed_at: str


class ImportCandidateStore:
    def __init__(self, path: str | Path, import_id: str = "") -> None:
        self.path = Path(path)
        self.import_id = _text(import_id).strip()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            connection.executescript(_SCHEMA)
            self._migrate(connection)
            if self.import_id:
                connection.execute("UPDATE candidates SET import_id=? WHERE import_id=''", (self.import_id,))
                for row in connection.execute("SELECT object_key FROM candidates WHERE preview_id='' ").fetchall():
                    connection.execute("UPDATE candidates SET preview_id=? WHERE object_key=?", (
                        uuid.uuid5(uuid.NAMESPACE_URL, f'{self.import_id}:{row[0]}').hex, row[0]))
                connection.execute("UPDATE label_mapping SET import_id=? WHERE import_id=''", (self.import_id,))
                connection.execute("UPDATE confirmation_details SET import_id=? WHERE import_id=''", (self.import_id,))
            connection.commit()

    @staticmethod
    def _migrate(connection: sqlite3.Connection) -> None:
        additions = {
            "candidates": {"import_id": "TEXT NOT NULL DEFAULT ''",
                           "preview_id": "TEXT NOT NULL DEFAULT ''"},
            "label_mapping": {
                "import_id": "TEXT NOT NULL DEFAULT ''", "action": "TEXT",
                "target_label_code": "TEXT",
            },
            "confirmation_details": {"import_id": "TEXT NOT NULL DEFAULT ''"},
        }
        for table, columns in additions.items():
            existing = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
            for name, definition in columns.items():
                if name not in existing:
                    connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS ix_candidate_annotations_class "
            "ON candidate_annotations(class_id, object_key, line_number)"
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA temp_store=FILE")
            return connection
        except BaseException:
            connection.close()
            raise

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                yield connection

    def upsert_many(self, rows: Iterable[Mapping[str, object]]) -> int:
        """Insert scan metadata once per key, streaming the input in one transaction."""
        fields = ",".join(_SCAN_FIELDS)
        placeholders = ",".join("?" for _ in _SCAN_FIELDS)

        def values():
            for row in rows:
                normalized = normalize_candidate(row)
                normalized["import_id"] = self.import_id
                normalized["preview_id"] = uuid.uuid5(
                    uuid.NAMESPACE_URL, f'{self.import_id}:{normalized["object_key"]}'
                ).hex
                yield tuple(normalized[field] for field in _SCAN_FIELDS)

        with self._transaction() as connection:
            before = connection.total_changes
            connection.executemany(
                f"INSERT OR IGNORE INTO candidates ({fields}) VALUES ({placeholders})", values()
            )
            return connection.total_changes - before

    def counts(self) -> dict[str, int]:
        with closing(self._connect()) as connection:
            return {row[0]: row[1] for row in connection.execute(
                "SELECT status, COUNT(*) FROM candidates GROUP BY status"
            )}

    def inventory_many(self, rows: Iterable[Mapping[str, object]]) -> None:
        with self._transaction() as connection:
            connection.executemany(
                "INSERT OR REPLACE INTO dataset_objects VALUES (?, ?, ?, ?)",
                ((_key(row.get("object_key")), _nonnegative_int(row.get("size_bytes")),
                  _text(row.get("etag")), _text(row.get("sha256"))) for row in rows),
            )

    def manifest_many(self, rows: Iterable[Mapping[str, object]]) -> None:
        with self._transaction() as connection:
            connection.executemany(
                "INSERT OR IGNORE INTO dataset_manifest (object_key, split, yaml_key) VALUES (?, ?, ?)",
                ((_key(row.get("object_key")), _text(row.get("split")),
                  _key(row.get("yaml_key"))) for row in rows),
            )

    def annotation_batch(self, images: Iterable[Mapping[str, object]],
                         boxes: Iterable[Mapping[str, object]],
                         issues: Iterable[Mapping[str, object]]) -> None:
        """Append bounded annotation chunks; callers reset once before rescanning."""
        with self._transaction() as connection:
            connection.executemany(
                "UPDATE dataset_manifest SET label_key=?, annotation_status=?, box_count=? WHERE object_key=?",
                ((row.get("label_key"), row["annotation_status"], row["box_count"],
                  row["object_key"]) for row in images),
            )
            connection.executemany(
                "INSERT OR REPLACE INTO candidate_annotations VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ((row["object_key"], row["line_number"], row["class_id"], row["cx"],
                  row["cy"], row["w"], row["h"], int(row.get("clipped", False))) for row in boxes),
            )
            connection.executemany(
                "INSERT OR IGNORE INTO annotation_issues VALUES (?, ?, ?, ?)",
                ((row["object_key"], row["line_number"], row["code"], row["severity"]) for row in issues),
            )

    def set_label_mapping(self, names: Mapping[int, str]) -> None:
        with self._transaction() as connection:
            connection.executemany(
                "INSERT INTO label_mapping (class_id, name, import_id) VALUES (?, ?, ?) "
                "ON CONFLICT(class_id) DO UPDATE SET name=excluded.name,import_id=excluded.import_id",
                ((class_id, name, self.import_id) for class_id, name in names.items()),
            )

    def annotations_for_keys(self, keys: Iterable[str]) -> dict[str, dict]:
        """Read one caller-bounded image batch, including its persisted boxes."""
        keys = list(keys)
        if len(keys) > 500:
            raise ValueError("annotation lookup is limited to 500 image keys")
        if not keys:
            return {}
        placeholders = ",".join("?" for _ in keys)
        with closing(self._connect()) as connection:
            result = {row["object_key"]: {**dict(row), "boxes": []} for row in connection.execute(
                f"SELECT * FROM dataset_manifest WHERE object_key IN ({placeholders})", keys)}
            for row in connection.execute(
                f"SELECT * FROM candidate_annotations WHERE object_key IN ({placeholders}) ORDER BY object_key, line_number", keys
            ):
                result[row["object_key"]]["boxes"].append(dict(row))
            return result

    def quality_summary(self, example_limit: int = 20) -> dict:
        with closing(self._connect()) as connection:
            return {
                "images": connection.execute("SELECT COUNT(*) FROM dataset_manifest").fetchone()[0],
                "boxes": connection.execute("SELECT COUNT(*) FROM candidate_annotations").fetchone()[0],
                "classes": connection.execute("SELECT COUNT(*) FROM label_mapping").fetchone()[0],
                "annotation_status": dict(connection.execute(
                    "SELECT annotation_status, COUNT(*) FROM dataset_manifest GROUP BY annotation_status")),
                "issues": dict(connection.execute("SELECT code, COUNT(*) FROM annotation_issues GROUP BY code")),
                "examples": [dict(row) for row in connection.execute(
                    "SELECT * FROM annotation_issues ORDER BY object_key, line_number, code LIMIT ?",
                    (_limit(example_limit, 100),))],
            }

    def iter_status(self, status: str, batch_size: int = 500) -> Iterator[dict]:
        """Yield individual rows in key order, reading at most one bounded page."""
        limit = _limit(batch_size)
        after = None
        while True:
            with closing(self._connect()) as connection:
                if after is None:
                    rows = connection.execute(
                        "SELECT * FROM candidates WHERE status=? ORDER BY object_key LIMIT ?",
                        (status, limit),
                    ).fetchall()
                else:
                    rows = connection.execute(
                        "SELECT * FROM candidates WHERE status=? AND object_key>? ORDER BY object_key LIMIT ?",
                        (status, after, limit),
                    ).fetchall()
            if not rows:
                return
            after = rows[-1]["object_key"]
            yield from (dict(row) for row in rows)

    def failure_page(self, limit: int = 200) -> list[dict]:
        with closing(self._connect()) as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM candidates WHERE status='FAILED' ORDER BY object_key LIMIT ?",
                (_limit(limit, 500),),
            )]

    def find_content_hashes(self, hashes: Iterable[object]) -> set[str]:
        """Lookup in chunks of at most 500 bound parameters; only matches accumulate."""
        found: set[str] = set()
        chunk: set[str] = set()
        with closing(self._connect()) as connection:
            def lookup():
                placeholders = ",".join("?" for _ in chunk)
                found.update(row[0] for row in connection.execute(
                    f"SELECT DISTINCT content_sha256 FROM candidates WHERE content_sha256 IN ({placeholders})",
                    tuple(chunk),
                ))
                chunk.clear()

            for value in hashes:
                value = _text(value).strip().lower()
                if value and value not in found:
                    chunk.add(value)
                if len(chunk) == 500:
                    lookup()
            if chunk:
                lookup()
        return found

    def confirm(self, selected_keys: Iterable[object], *, details: dict | None = None) -> Confirmation:
        """Atomically freeze a valid selection; identical retries return its original record."""
        with self._transaction() as connection:
            connection.execute("CREATE TEMP TABLE selection (object_key TEXT PRIMARY KEY)")
            connection.executemany(
                "INSERT OR IGNORE INTO selection VALUES (?)", ((_key(key),) for key in selected_keys)
            )
            digest = hashlib.sha256()
            count = 0
            for row in connection.execute("SELECT object_key FROM selection ORDER BY object_key"):
                encoded = row[0].encode("utf-8")
                digest.update(len(encoded).to_bytes(8, "big"))
                digest.update(encoded)
                count += 1
            value = digest.hexdigest()
            previous = connection.execute("SELECT digest, selected_count, confirmed_at FROM meta WHERE singleton=1").fetchone()
            saved = connection.execute("SELECT payload FROM confirmation_details WHERE singleton=1").fetchone()
            if saved and json.loads(saved[0]) != details:
                raise ValueError("conflicting import mapping or quality confirmation")
            if previous is not None:
                if previous["digest"] != value:
                    raise ValueError("conflicting import selection confirmation")
                return Confirmation(**dict(previous))
            invalid = connection.execute(
                "SELECT 1 FROM selection s LEFT JOIN candidates c ON c.object_key=s.object_key "
                "WHERE c.object_key IS NULL OR c.status != 'IMPORTABLE' LIMIT 1"
            ).fetchone()
            if invalid:
                raise ValueError("selection contains unknown or non-IMPORTABLE object_key")
            connection.execute("UPDATE candidates SET selected=0 WHERE selected=1")
            connection.execute("UPDATE candidates SET selected=1 WHERE object_key IN (SELECT object_key FROM selection)")
            confirmed = Confirmation(value, count, _now())
            connection.execute("INSERT INTO meta VALUES (1, ?, ?, ?)",
                               (confirmed.digest, confirmed.selected_count, confirmed.confirmed_at))
            if details is not None:
                connection.execute(
                    "INSERT INTO confirmation_details(singleton,payload,import_id) VALUES(1,?,?)",
                    (json.dumps(details, sort_keys=True), self.import_id),
                )
            return confirmed

    def selection_facts(self, keys=None):
        """Validate a caller selection in SQLite and hash its image/annotation contents."""
        with closing(self._connect()) as db:
            db.execute("CREATE TEMP TABLE wanted(object_key TEXT PRIMARY KEY)")
            if keys is None:
                db.execute("INSERT INTO wanted SELECT object_key FROM candidates WHERE status='IMPORTABLE'")
            else:
                db.executemany("INSERT OR IGNORE INTO wanted VALUES(?)", ((_key(key),) for key in keys))
            if db.execute("SELECT 1 FROM wanted w LEFT JOIN candidates c USING(object_key) "
                          "WHERE c.object_key IS NULL OR c.status!='IMPORTABLE' LIMIT 1").fetchone():
                raise ValueError("selection contains unknown or non-IMPORTABLE object_key")
            digest = hashlib.sha256()
            for query in (
                "SELECT c.object_key,c.content_sha256,c.width,c.height,m.annotation_status,m.label_key "
                "FROM candidates c JOIN wanted w USING(object_key) LEFT JOIN dataset_manifest m USING(object_key) ORDER BY c.object_key",
                "SELECT a.* FROM candidate_annotations a JOIN wanted w USING(object_key) ORDER BY a.object_key,a.line_number",
                "SELECT class_id,name,import_id FROM label_mapping ORDER BY class_id",
            ):
                for row in db.execute(query):
                    digest.update(json.dumps(tuple(row), ensure_ascii=False, separators=(',', ':')).encode('utf-8') + b'\n')
            classes = [dict(row) for row in db.execute(
                "SELECT l.class_id,l.name FROM label_mapping l "
                "LEFT JOIN candidate_annotations a ON a.class_id=l.class_id "
                "LEFT JOIN wanted w ON w.object_key=a.object_key "
                "WHERE (?='' OR l.import_id=?) GROUP BY l.class_id,l.name ORDER BY l.class_id",
                (self.import_id, self.import_id))]
            return {'content_digest': digest.hexdigest(), 'classes': classes}

    def external_classes(self):
        with closing(self._connect()) as db:
            return [dict(row) for row in db.execute(
                "SELECT l.import_id,l.class_id,l.name,COUNT(DISTINCT c.object_key) image_count,"
                "COUNT(c.object_key) box_count,l.action,l.target_label_id,l.target_label_code FROM label_mapping l "
                "LEFT JOIN candidate_annotations a ON a.class_id=l.class_id "
                "LEFT JOIN candidates c ON c.object_key=a.object_key AND c.status='IMPORTABLE' "
                "AND c.import_id=l.import_id "
                "WHERE (?='' OR l.import_id=?) "
                "GROUP BY l.import_id,l.class_id,l.name,l.action,l.target_label_id,l.target_label_code "
                "ORDER BY l.class_id LIMIT 10000", (self.import_id, self.import_id))]

    def save_label_decisions(self, decisions: Mapping[str, Mapping[str, object]]) -> None:
        with self._transaction() as db:
            for external_id, decision in decisions.items():
                updated = db.execute(
                    "UPDATE label_mapping SET action=?,target_label_id=?,target_label_code=? "
                    "WHERE class_id=? AND (?='' OR import_id=?)",
                    (decision.get("action"), decision.get("target_label_id"),
                     decision.get("target_label_code"), int(external_id),
                     self.import_id, self.import_id),
                ).rowcount
                if updated != 1:
                    raise ValueError(f"unknown external class {external_id}")

    def class_samples(self, class_id: int, *, page: int = 0, limit: int = 6) -> dict:
        """Return a small deterministic spread without loading all matching rows."""
        page = max(0, int(page))
        limit = _limit(limit, 12)
        with closing(self._connect()) as db:
            total = db.execute(
                "SELECT COUNT(DISTINCT a.object_key) FROM candidate_annotations a "
                "JOIN candidates c USING(object_key) WHERE a.class_id=? AND c.status='IMPORTABLE' "
                "AND (?='' OR c.import_id=?)", (int(class_id), self.import_id, self.import_id),
            ).fetchone()[0]
            if not total:
                return {"items": [], "page": page, "limit": limit, "total": 0}
            window = min(limit, total)
            shift = (page * window) % total
            offsets = sorted({(shift + ((i * total) // window)) % total for i in range(window)})
            items = []
            for offset in offsets:
                row = db.execute(
                    "SELECT c.preview_id,c.filename,c.width,c.height,c.storage_source_id,c.object_key "
                    "FROM candidate_annotations a JOIN candidates c USING(object_key) "
                    "WHERE a.class_id=? AND c.status='IMPORTABLE' AND (?='' OR c.import_id=?) "
                    "GROUP BY c.object_key ORDER BY c.object_key LIMIT 1 OFFSET ?",
                    (int(class_id), self.import_id, self.import_id, offset),
                ).fetchone()
                if row:
                    item = dict(row)
                    item["boxes"] = [dict(box) for box in db.execute(
                        "SELECT line_number,cx,cy,w,h,clipped FROM candidate_annotations "
                        "WHERE class_id=? AND object_key=? ORDER BY line_number LIMIT 100",
                        (int(class_id), row["object_key"]),
                    )]
                    items.append(item)
            return {"items": items, "page": page, "limit": limit, "total": total}

    def candidate_by_preview_id(self, preview_id: str) -> dict | None:
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT object_key,storage_source_id,storage_type,filename FROM candidates "
                "WHERE preview_id=? AND status='IMPORTABLE' AND (?='' OR import_id=?) LIMIT 1",
                (_text(preview_id), self.import_id, self.import_id),
            ).fetchone()
            return dict(row) if row else None

    def bind_index_batch(self, rows):
        """Freeze resolved image IDs and new/existing provenance before material writes."""
        with self._transaction() as db:
            for row in rows:
                db.execute("INSERT OR IGNORE INTO indexing_outcomes(object_key,image_id,existing_material) VALUES(?,?,?)",
                           (row['object_key'], row['image_id'], int(row.get('existing_material', False))))
                saved = db.execute("SELECT image_id,existing_material FROM indexing_outcomes WHERE object_key=?", (row['object_key'],)).fetchone()
                row['image_id'], row['existing_material'] = saved
                db.execute("UPDATE candidates SET image_id=? WHERE object_key=? AND indexed=0", (row['image_id'], row['object_key']))

    def record_annotation_outcomes(self, rows):
        with self._transaction() as db:
            db.executemany("UPDATE indexing_outcomes SET annotations_written=?,boxes_imported=?,boxes_skipped=?,negative_samples=? WHERE object_key=?",
                ((r.get('annotations_written', 0), r.get('boxes_imported', 0), r.get('boxes_skipped', 0), r.get('negative_samples', 0), r['object_key']) for r in rows))

    def indexing_counts(self):
        with closing(self._connect()) as db:
            row = db.execute("SELECT COALESCE(SUM(o.annotations_written),0),COALESCE(SUM(o.boxes_imported),0),"
                "COALESCE(SUM(o.boxes_skipped),0),COALESCE(SUM(o.negative_samples),0),"
                "COALESCE(SUM(o.existing_material),0),COALESCE(SUM(1-o.existing_material),0) "
                "FROM indexing_outcomes o JOIN candidates c USING(object_key) WHERE c.indexed=1").fetchone()
            return dict(zip(('annotations_written','boxes_imported','boxes_skipped','negative_samples',
                             'existing_materials_updated','new_materials_indexed'), row))

    def skipped_boxes_for_keys(self, keys):
        keys = list(keys)
        if not keys:
            return {}
        with closing(self._connect()) as db:
            return dict(db.execute("SELECT object_key,COUNT(DISTINCT line_number) FROM annotation_issues "
                "WHERE severity='error' AND line_number>0 AND object_key IN (" + ','.join('?' for _ in keys) + ") GROUP BY object_key", keys))

    def assign_image_ids(self, task_id: str, batch_size: int = 500) -> int:
        """Persist UUID5 IDs in bounded transactions; return the number newly assigned."""
        if not _text(task_id).strip():
            raise ValueError("task_id is required")
        namespace = uuid.uuid5(uuid.NAMESPACE_URL, str(task_id))
        limit = _limit(batch_size)
        assigned = 0
        after = None
        while True:
            with self._transaction() as connection:
                keyset = "" if after is None else " AND object_key>?"
                parameters = (limit,) if after is None else (after, limit)
                rows = connection.execute(
                    "SELECT object_key FROM candidates WHERE selected=1 AND indexed=0 "
                    "AND (image_id IS NULL OR image_id='')" + keyset + " ORDER BY object_key LIMIT ?",
                    parameters,
                ).fetchall()
                if not rows:
                    return assigned
                connection.executemany(
                    "UPDATE candidates SET image_id=? WHERE object_key=?",
                    ((uuid.uuid5(namespace, row[0]).hex, row[0]) for row in rows),
                )
                assigned += len(rows)
                after = rows[-1][0]

    def pending_index_batch(self, limit: int = 500) -> list[dict]:
        """Return at most 5000 selected, unindexed rows (IDs may still be unassigned)."""
        with closing(self._connect()) as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM candidates WHERE selected=1 AND indexed=0 ORDER BY object_key LIMIT ?",
                (_limit(limit),),
            )]

    def mark_indexed(self, rows: Iterable[Mapping[str, object]]) -> int:
        """Mark mappings containing object_key; other input fields cannot alter persisted IDs.

        Unknown, unselected or unassigned keys fail the entire batch. Repeated
        acknowledgements preserve indexed_at and return zero new transitions.
        """
        changed = 0
        with self._transaction() as connection:
            timestamp = _now()
            for row in rows:
                key = _key(row.get("object_key"))
                persisted = connection.execute(
                    "SELECT selected, image_id FROM candidates WHERE object_key=?", (key,)
                ).fetchone()
                if persisted is None or not persisted["selected"] or not persisted["image_id"]:
                    raise ValueError("indexed object_key must exist, be selected and have an assigned image_id")
                changed += connection.execute(
                    "UPDATE candidates SET indexed=1, indexed_at=? WHERE object_key=? AND indexed=0",
                    (timestamp, key),
                ).rowcount
        return changed


class RescanCandidateStore(ImportCandidateStore):
    """A task-owned inventory, baseline and immutable reconciliation decision."""

    def __init__(self, path):
        super().__init__(path)
        with self._transaction() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS rescan_baseline (
                    image_id TEXT PRIMARY KEY, object_key TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_rescan_baseline_key ON rescan_baseline(object_key);
                CREATE TABLE IF NOT EXISTS rescan_objects (
                    object_key TEXT PRIMARY KEY, category TEXT NOT NULL,
                    payload TEXT NOT NULL, applied INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS ix_rescan_category ON rescan_objects(category,applied,object_key);
                CREATE TABLE IF NOT EXISTS rescan_meta (key TEXT PRIMARY KEY, payload TEXT NOT NULL);
            """)

    def meta(self, key):
        with closing(self._connect()) as db:
            row = db.execute("SELECT payload FROM rescan_meta WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else None

    def set_meta(self, key, value):
        with self._transaction() as db:
            db.execute("INSERT OR REPLACE INTO rescan_meta VALUES(?,?)", (key, json.dumps(value)))

    def baseline_batch(self, rows):
        with self._transaction() as db:
            db.executemany("INSERT OR REPLACE INTO rescan_baseline VALUES(?,?,?)",
                           ((r['id'], r['object_key'], json.dumps(r)) for r in rows))

    def baseline_for_keys(self, keys):
        keys = list(keys)
        if len(keys) > 500:
            raise ValueError('rescan lookup is limited to 500 keys')
        if not keys:
            return {}
        with closing(self._connect()) as db:
            result = {}
            for row in db.execute('SELECT object_key,payload FROM rescan_baseline WHERE object_key IN ('
                                  + ','.join('?' for _ in keys) + ') ORDER BY image_id', keys):
                result.setdefault(row[0], json.loads(row[1]))
            return result

    def restart_inventory(self):
        # Interrupted listings must restart: providers need not return sorted keys.
        with self._transaction() as db:
            db.execute('DELETE FROM rescan_objects')
            db.execute('DELETE FROM candidates')

    def object_batch(self, rows):
        with self._transaction() as db:
            db.executemany('INSERT OR REPLACE INTO rescan_objects(object_key,category,payload) VALUES(?,?,?)',
                           ((r['object_key'], r['category'], json.dumps(r)) for r in rows))

    def finish_inventory(self):
        with self._transaction() as db:
            db.execute("INSERT OR IGNORE INTO rescan_objects(object_key,category,payload) "
                       "SELECT b.object_key,'MISSING',b.payload FROM rescan_baseline b "
                       "WHERE NOT EXISTS(SELECT 1 FROM rescan_objects o WHERE o.object_key=b.object_key)")
            db.execute("INSERT OR REPLACE INTO rescan_meta VALUES('scan_complete','true')")

    def summary(self):
        with closing(self._connect()) as db:
            counts = dict(db.execute('SELECT category,COUNT(*) FROM rescan_objects GROUP BY category'))
            examples = {category: [r[0] for r in db.execute(
                'SELECT object_key FROM rescan_objects WHERE category=? ORDER BY object_key LIMIT 20', (category,))]
                for category in ('NEW', 'MISSING', 'CHANGED', 'UNCHANGED', 'INVALID', 'SKIPPED')}
            return {'counts': counts, 'examples': examples,
                    'applied': db.execute('SELECT COUNT(*) FROM rescan_objects WHERE applied=1').fetchone()[0]}

    def confirm_policy(self, policy):
        with self._transaction() as db:
            previous = db.execute("SELECT payload FROM rescan_meta WHERE key='policy'").fetchone()
            if previous and json.loads(previous[0]) != policy:
                raise ValueError('rescan policy is already confirmed; create a new rescan to change it')
            if not db.execute("SELECT 1 FROM rescan_meta WHERE key='scan_complete'").fetchone():
                raise ValueError('rescan is incomplete')
            db.execute("INSERT OR IGNORE INTO rescan_meta VALUES('policy',?)", (json.dumps(policy, sort_keys=True),))

    def pending_objects(self, categories, limit=500):
        with closing(self._connect()) as db:
            return [dict(json.loads(r['payload']), category=r['category']) for r in db.execute(
                'SELECT payload,category FROM rescan_objects WHERE applied=0 AND category IN ('
                + ','.join('?' for _ in categories) + ') ORDER BY object_key LIMIT ?',
                (*categories, min(500, max(1, int(limit)))))] if categories else []

    def mark_applied(self, rows):
        with self._transaction() as db:
            db.executemany('UPDATE rescan_objects SET applied=1 WHERE object_key=?',
                           ((r['object_key'],) for r in rows))

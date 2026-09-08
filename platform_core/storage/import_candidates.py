"""Bounded, durable candidate storage for one material-import task artifact.

Scan input owns candidate metadata; confirmation and indexing own lifecycle
fields. No manifest or complete selection is retained in Python or JSON.
"""
from __future__ import annotations

import hashlib
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
"""
_SCAN_FIELDS = (
    "object_key", "filename", "storage_source_id", "storage_type", "content_sha256",
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
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            connection.executescript(_SCHEMA)

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

    def confirm(self, selected_keys: Iterable[object]) -> Confirmation:
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
            return confirmed

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

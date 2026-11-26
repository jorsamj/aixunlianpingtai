"""Provider-neutral history-reference evidence for the SQLite-attach readers.

Three read projections used to open ``algorithms.sqlite3`` directly with SQL
ATTACH: the material-history signature, the training-usage freshness proof and
the conversion-catalog reference check.  After a cutover those reads would
return stale rows, so they were first made fail-closed.  This module closes the
other half of U1: the same *business* evidence is now served by whichever
provider is authoritative, with an equivalent contract and bounded reads.

Contract parity with the SQLite projection:

* ``revision``      - the durable algorithm revision token (or ``None`` when the
  catalog is not initialized yet; never "0 versions").
* ``has_versions``  - a bounded existence probe; ``None`` means this provider
  cannot prove the project has no version history.
* payload pages     - keyset pages (``id > after``) of the non-structural
  ``payload``/``payload_json`` object, exactly what the reference matcher used.

A provider/connection failure is *not* "no history" and *not* "no reference":
it raises, so callers can report "unable to verify" instead of authorizing a
delete or claiming a fresh dataset.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

from .algorithm_repository import (
    AlgorithmRepositoryError,
    AlgorithmRepository,
    open_algorithm_repository,
)

#: One page is bounded so a large project never becomes a single huge read.
MAX_HISTORY_PAYLOAD_PAGE = 200
#: Hard cap on scanned records per project; exceeding it fails closed.
MAX_HISTORY_PAYLOAD_RECORDS = 5000

KIND_ALGORITHM = "ALGORITHM"
KIND_VERSION = "VERSION"


def open_history_repository(
    json_path: str | Path, **kwargs: object
) -> AlgorithmRepository:
    """Open the authoritative provider for read-only history evidence.

    The provider rules are the ordinary algorithm-domain rules: SQLite refuses a
    catalog another provider owns, and PostgreSQL requires a DSN plus an
    admission record.  A configuration failure raises instead of falling back.
    """
    return open_algorithm_repository(json_path, **kwargs)  # type: ignore[arg-type]


def revision_token(repository: AlgorithmRepository) -> tuple[str, str | None]:
    """Derived-read signature component: which provider, which revision."""
    return (str(repository.provider_name), repository.history_revision())


def iter_history_payloads(
    repository: AlgorithmRepository,
    *,
    page_size: int = MAX_HISTORY_PAYLOAD_PAGE,
    max_records: int = MAX_HISTORY_PAYLOAD_RECORDS,
) -> Iterator[tuple[str, str, dict]]:
    """Yield ``(kind, record_id, payload)`` over bounded keyset pages.

    The scan is deterministic (ordered by id) and capped; a project whose
    history exceeds the cap raises instead of silently checking a prefix.
    """
    page = int(page_size)
    if not 1 <= page <= 500:
        raise ValueError("history payload page size must be 1..500")
    limit = int(max_records)
    if limit <= 0:
        raise ValueError("history payload record cap must be positive")
    examined = 0
    for kind, fetch in (
        (KIND_ALGORITHM, repository.history_algorithm_payloads),
        (KIND_VERSION, repository.history_version_payloads),
    ):
        after: str | None = None
        while True:
            rows = fetch(after=after, limit=page)
            for record_id, payload in rows:
                examined += 1
                if examined > limit:
                    raise AlgorithmRepositoryError(
                        "ALGORITHM_HISTORY_EVIDENCE_UNBOUNDED",
                        "algorithm history exceeds the bounded reference scan",
                        detail=f"limit={limit} provider={repository.provider_name}",
                    )
                yield kind, str(record_id), payload
            if len(rows) < page:
                break
            after = str(rows[-1][0])

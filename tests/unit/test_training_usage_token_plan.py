"""Dense historical usage must resolve exact relation tokens via the existing index."""
import json
import sqlite3
import statistics
import time

from platform_core.training_material_usage import TrainingMaterialUsage


def test_dense_token_lookup_preserves_project_scope_and_uses_exact_index(tmp_path):
    path = tmp_path / "tasks.sqlite3"
    index = TrainingMaterialUsage(path)
    with sqlite3.connect(path) as database:
        index._schema(database)
        usage_rows = []
        token_rows = []
        for project in ("selected", "unrelated"):
            for number in range(3200):
                identity = f"image-{number}"
                task_id = f"{project}-task-{number}"
                tokens = [("image_id", identity), ("content_sha256", f"digest-{number}")]
                usage_rows.append((project, "algorithm", task_id, "snapshot", identity, "train",
                                   json.dumps(tokens), "", 2, 0))
                token_rows.extend((project, kind, value, task_id, identity, "train") for kind, value in tokens)
        database.executemany("INSERT INTO training_material_usage VALUES(?,?,?,?,?,?,?,?,?,?)", usage_rows)
        database.executemany("INSERT INTO training_usage_tokens VALUES(?,?,?,?,?,?)", token_rows)
        database.commit()

    # One query spans the batch boundary; a matching image and SHA must not
    # duplicate the stored record, and another project's matches must not leak.
    images = [
        {"id": f"image-{number}", "content_sha256": f"digest-{number}"}
        for number in range(125, 325)
    ]
    result = index._query_candidates("selected", "algorithm", images)
    assert len(result["records"]) == 200
    assert {row["task_id"] for row in result["records"]} == {
        f"selected-task-{number}" for number in range(125, 325)
    }
    assert result["revision"] != "unknown"

    sql = index._token_lookup_sql(2)
    with sqlite3.connect(path) as database:
        detail = " ".join(str(row[3]) for row in database.execute(
            "EXPLAIN QUERY PLAN " + sql,
            ("image_id", "image-125", "content_sha256", "digest-125", "selected"),
        ))
    assert "token_kind=? AND token_value=?" in detail
    assert "SCAN t" not in detail

    # Same dense fixture, same 200 requested tokens and returned records. The
    # timing is diagnostic only (never a flaky CI pass/fail threshold).
    requested = [(kind, value) for number in range(125, 225)
                 for kind, value in (("image_id", f"image-{number}"),
                                     ("content_sha256", f"digest-{number}"))]
    old_predicate = " OR ".join("(t.token_kind=? AND t.token_value=?)" for _ in requested)
    old_sql = (
        "SELECT DISTINCT u.* FROM training_usage_tokens t "
        "JOIN training_material_usage u ON u.task_id=t.task_id "
        "AND u.image_id=t.image_id AND u.role=t.role "
        "WHERE t.project_id=? AND (" + old_predicate + ")"
    )
    new_sql = index._token_lookup_sql(len(requested))
    old_params = ["selected", *(item for token in requested for item in token)]
    new_params = [*(item for token in requested for item in token), "selected"]
    durations = {"old": [], "indexed": []}
    with sqlite3.connect(path) as database:
        for _ in range(3):
            for name, statement, values in (("old", old_sql, old_params),
                                            ("indexed", new_sql, new_params)):
                began = time.perf_counter()
                result_ids = {row[2] for row in database.execute(statement, values)}
                durations[name].append((time.perf_counter() - began) * 1000)
                assert result_ids == {f"selected-task-{number}" for number in range(125, 225)}
    print("isolated_dense_usage_lookup_ms", {
        name: round(statistics.median(samples), 2) for name, samples in durations.items()
    })


def test_empty_token_query_is_a_read_only_noop(tmp_path):
    path = tmp_path / "tasks.sqlite3"
    sqlite3.connect(path).close()
    result = TrainingMaterialUsage(path)._query_candidates("p", "a", [])
    assert result["records"] == []

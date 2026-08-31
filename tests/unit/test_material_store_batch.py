from platform_core.material_store import MaterialStore
import subprocess
import sys
import time
from pathlib import Path


def test_upsert_many_commits_one_revision_and_is_idempotent(tmp_path):
    store = MaterialStore(tmp_path / "images.json")
    first = store.upsert_many(
        [
            {"id": "a", "filename": "a.jpg", "split": "unassigned"},
            {"id": "b", "filename": "b.jpg", "split": "unassigned"},
        ]
    )
    assert [row["id"] for row in first] == ["a", "b"]
    assert store.read().revision == 1

    store.upsert_many(
        [
            {"id": "a", "filename": "a-new.jpg"},
            {"id": "b", "filename": "b.jpg"},
        ]
    )
    snapshot = store.read()
    assert snapshot.revision == 2
    assert len(snapshot.rows) == 2
    assert next(row for row in snapshot.rows if row["id"] == "a")["filename"] == "a-new.jpg"


def test_two_processes_do_not_overwrite_each_others_material_batch(tmp_path):
    index = tmp_path / "images.json"
    gate = tmp_path / "go"
    root = Path(__file__).resolve().parents[2]
    processes = []
    for prefix in ("left", "right"):
        code = (
            "import time;from pathlib import Path;"
            "from platform_core.material_store import MaterialStore;"
            f"gate=Path({str(gate)!r});"
            "\nwhile not gate.exists(): time.sleep(.01)\n"
            f"store=MaterialStore(Path({str(index)!r}));"
            f"rows=[{{'id':f'{prefix}-{{i}}'}} for i in range(20)];"
            "\ndef apply(current):\n time.sleep(.25);current.extend(rows)\n"
            "store.mutate(apply)"
        )
        processes.append(
            subprocess.Popen(
                [sys.executable, "-c", code],
                cwd=root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        )
    time.sleep(0.1)
    gate.write_text("go", encoding="utf-8")
    for process in processes:
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, stderr or stdout
    rows = MaterialStore(index).read().rows
    assert len(rows) == 40
    assert len({row["id"] for row in rows}) == 40

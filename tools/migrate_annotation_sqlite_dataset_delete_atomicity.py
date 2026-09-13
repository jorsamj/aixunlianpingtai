from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


root = Path(__file__).resolve().parents[1]
repo_path = root / "platform_core" / "annotation_repository.py"
app_path = root / "app.py"
batching_test_path = root / "tests" / "api" / "test_material_batching.py"
atomicity_test_path = root / "tests" / "api" / "test_material_selection_atomicity.py"

repo = repo_path.read_text(encoding="utf-8")
repo = replace_once(
    repo,
    """                CREATE INDEX IF NOT EXISTS ix_annotations_state ON annotations(annotation_state, image_id);\n                CREATE INDEX IF NOT EXISTS ix_annotations_updated ON annotations(updated_at);\n""",
    """                CREATE INDEX IF NOT EXISTS ix_annotations_state ON annotations(annotation_state, image_id);\n                CREATE INDEX IF NOT EXISTS ix_annotations_updated ON annotations(updated_at);\n                CREATE TABLE IF NOT EXISTS annotation_delete_backup (\n                    token TEXT NOT NULL, image_id TEXT NOT NULL,\n                    annotation_state TEXT NOT NULL, version INTEGER NOT NULL,\n                    content_digest TEXT NOT NULL, boxes_json TEXT NOT NULL,\n                    scope_json TEXT NOT NULL, created_at TEXT NOT NULL,\n                    updated_at TEXT NOT NULL,\n                    PRIMARY KEY(token, image_id)\n                );\n                CREATE INDEX IF NOT EXISTS ix_annotation_delete_backup_token\n                    ON annotation_delete_backup(token, image_id);\n""",
    "annotation delete backup schema",
)

methods = '''    def exists(self, image_id) -> bool:\n        image_id = self._id(image_id)\n        with closing(self._connect()) as db:\n            return db.execute(\n                "SELECT 1 FROM annotations WHERE image_id=?", (image_id,)\n            ).fetchone() is not None\n\n    @staticmethod\n    def _delete_token(token) -> str:\n        token = str(token or "").strip()\n        if (\n            not token\n            or len(token) > 128\n            or any(character in token for character in "/\\\\:\\x00")\n            or token in {".", ".."}\n        ):\n            raise ValueError("invalid annotation delete token")\n        return token\n\n    def delete_backup_count(self, token) -> int:\n        token = self._delete_token(token)\n        with closing(self._connect()) as db:\n            return int(db.execute(\n                "SELECT COUNT(*) FROM annotation_delete_backup WHERE token=?",\n                (token,),\n            ).fetchone()[0])\n\n    def prepare_delete(self, token, image_ids) -> int:\n        """Persist an idempotent SQLite backup before dataset deletion can remove GT."""\n        token = self._delete_token(token)\n        ids = list(dict.fromkeys(self._id(value) for value in image_ids))\n        if not ids:\n            return 0\n        with closing(self._connect()) as db:\n            db.execute("BEGIN IMMEDIATE")\n            try:\n                db.executemany(\n                    """INSERT OR IGNORE INTO annotation_delete_backup\n                       (token, image_id, annotation_state, version, content_digest,\n                        boxes_json, scope_json, created_at, updated_at)\n                       SELECT ?, image_id, annotation_state, version, content_digest,\n                              boxes_json, scope_json, created_at, updated_at\n                       FROM annotations WHERE image_id=?""",\n                    ((token, image_id) for image_id in ids),\n                )\n                count = int(db.execute(\n                    "SELECT COUNT(*) FROM annotation_delete_backup WHERE token=?",\n                    (token,),\n                ).fetchone()[0])\n                db.execute("COMMIT")\n                return count\n            except Exception:\n                db.execute("ROLLBACK")\n                raise\n\n    def finalize_delete(self, token) -> int:\n        """Delete only annotation rows that still match the durable backup snapshot."""\n        token = self._delete_token(token)\n        with closing(self._connect()) as db:\n            db.execute("BEGIN IMMEDIATE")\n            try:\n                expected = int(db.execute(\n                    "SELECT COUNT(*) FROM annotation_delete_backup WHERE token=?",\n                    (token,),\n                ).fetchone()[0])\n                cursor = db.execute(\n                    """DELETE FROM annotations\n                       WHERE EXISTS (\n                         SELECT 1 FROM annotation_delete_backup backup\n                         WHERE backup.token=?\n                           AND backup.image_id=annotations.image_id\n                           AND backup.content_digest=annotations.content_digest\n                       )""",\n                    (token,),\n                )\n                deleted = max(0, int(cursor.rowcount))\n                if deleted != expected:\n                    raise RuntimeError(\n                        "annotation changed during dataset deletion; refusing stale delete"\n                    )\n                db.execute("COMMIT")\n                return deleted\n            except Exception:\n                db.execute("ROLLBACK")\n                raise\n\n    def restore_delete(self, token) -> int:\n        """Restore missing GT from backup without overwriting a newer concurrent annotation."""\n        token = self._delete_token(token)\n        with closing(self._connect()) as db:\n            db.execute("BEGIN IMMEDIATE")\n            try:\n                rows = db.execute(\n                    """SELECT image_id, annotation_state, version, content_digest,\n                              boxes_json, scope_json, created_at, updated_at\n                       FROM annotation_delete_backup WHERE token=? ORDER BY image_id""",\n                    (token,),\n                ).fetchall()\n                db.executemany(\n                    """INSERT OR IGNORE INTO annotations\n                       (image_id, annotation_state, version, content_digest, boxes_json,\n                        scope_json, created_at, updated_at)\n                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",\n                    (tuple(row) for row in rows),\n                )\n                db.execute(\n                    "DELETE FROM annotation_delete_backup WHERE token=?", (token,)\n                )\n                db.execute("COMMIT")\n                return len(rows)\n            except Exception:\n                db.execute("ROLLBACK")\n                raise\n\n    def complete_delete(self, token) -> int:\n        token = self._delete_token(token)\n        with closing(self._connect()) as db, db:\n            cursor = db.execute(\n                "DELETE FROM annotation_delete_backup WHERE token=?", (token,)\n            )\n            return max(0, int(cursor.rowcount))\n\n'''
repo = replace_once(
    repo,
    "    def remove(self, image_ids):\n",
    methods + "    def remove(self, image_ids):\n",
    "annotation delete repository methods",
)
repo_path.write_text(repo, encoding="utf-8")

app = app_path.read_text(encoding="utf-8")

app = replace_once(
    app,
    """    return errors\n\n\ndef _v50_end_image_batch(save: bool = True):\n""",
    """    image_ids = [\n        str(record.get("id") or "")\n        for record in records\n        if str(record.get("id") or "")\n    ]\n    if image_ids:\n        try:\n            AnnotationRepository(p).remove(image_ids)\n        except Exception as error:\n            errors.append(f"annotation sqlite cleanup: {error}")\n    return errors\n\n\ndef _v50_end_image_batch(save: bool = True):\n""",
    "buffered annotation sqlite cleanup",
)

app = replace_once(
    app,
    """def _v50_cleanup_dataset_delete_artifacts(journal: Dict[str, Any]):\n    project_id = str(journal.get("project_id") or "")\n    token = str(journal.get("token") or "")\n    staging_dir = _v50_dataset_delete_staging_dir(project_id, token)\n""",
    """def _v50_cleanup_dataset_delete_artifacts(journal: Dict[str, Any]):\n    project_id = str(journal.get("project_id") or "")\n    token = str(journal.get("token") or "")\n    # The SQLite backup is part of the deletion journal. Clear it before\n    # removing filesystem recovery evidence so a DB failure leaves the journal.\n    AnnotationRepository(project_dir(project_id)).complete_delete(token)\n    staging_dir = _v50_dataset_delete_staging_dir(project_id, token)\n""",
    "dataset delete backup cleanup",
)

app = replace_once(
    app,
    """        if dataset_present:\n            _v50_restore_dataset_delete_files(project_id, journal)\n            _v50_restore_dataset_delete_rows(project_id, journal)\n            journal["status"] = "recovered"\n        else:\n            _v50_finish_absent_dataset_deletion(project_id, journal)\n            journal["status"] = "deletion_finished"\n""",
    """        annotation_repository = AnnotationRepository(project_dir(project_id))\n        if dataset_present:\n            _v50_restore_dataset_delete_files(project_id, journal)\n            _v50_restore_dataset_delete_rows(project_id, journal)\n            annotation_repository.restore_delete(token)\n            journal["status"] = "recovered"\n        else:\n            _v50_finish_absent_dataset_deletion(project_id, journal)\n            annotation_repository.finalize_delete(token)\n            journal["status"] = "deletion_finished"\n""",
    "dataset delete recovery annotation truth",
)

app = replace_once(
    app,
    """            journal["status"] = "claimed"\n            _v50_write_dataset_delete_journal(journal)\n\n        journal["status"] = "staging"\n""",
    """            journal["status"] = "claimed"\n            _v50_write_dataset_delete_journal(journal)\n            AnnotationRepository(project_dir(project_id)).prepare_delete(\n                claim_token,\n                [str(row.get("id")) for row in journal["claimed_rows"]],\n            )\n\n        journal["status"] = "staging"\n""",
    "dataset delete prepare annotation backup",
)

app = replace_once(
    app,
    """                with coordination_lock:\n                    _v50_restore_dataset_delete_rows(project_id, journal)\n                    journal["status"] = "rolled_back"\n""",
    """                with coordination_lock:\n                    _v50_restore_dataset_delete_rows(project_id, journal)\n                    AnnotationRepository(project_dir(project_id)).restore_delete(\n                        claim_token\n                    )\n                    journal["status"] = "rolled_back"\n""",
    "dataset delete rollback annotation truth",
)

app = replace_once(
    app,
    """            if len(finalized) != len(journal["claimed_rows"]):\n                raise RuntimeError("数据集删除锁定的素材数量已变化")\n            journal["status"] = "finalized"\n""",
    """            if len(finalized) != len(journal["claimed_rows"]):\n                raise RuntimeError("数据集删除锁定的素材数量已变化")\n            AnnotationRepository(project_dir(project_id)).finalize_delete(claim_token)\n            journal["status"] = "finalized"\n""",
    "dataset delete finalize annotation truth",
)

app_path.write_text(app, encoding="utf-8")

batching = batching_test_path.read_text(encoding="utf-8")
batching = replace_once(
    batching,
    """    project_path = app_module.project_dir(project_id)\n    upload_path = project_path / "uploads" / record["stored_name"]\n    annotation_path = project_path / "annotations" / f"{record['id']}.json"\n    assert upload_path.exists()\n    assert annotation_path.exists()\n""",
    """    project_path = app_module.project_dir(project_id)\n    upload_path = project_path / "uploads" / record["stored_name"]\n    annotation_repository = app_module.AnnotationRepository(project_path)\n    assert upload_path.exists()\n    assert annotation_repository.exists(record["id"])\n""",
    "batching test sqlite precondition",
)
batching = replace_once(
    batching,
    """    assert not upload_path.exists()\n    assert not annotation_path.exists()\n""",
    """    assert not upload_path.exists()\n    assert not annotation_repository.exists(record["id"])\n""",
    "batching test sqlite cleanup assertion",
)
batching = replace_once(
    batching,
    """    project_path = app_module.project_dir(project_id)\n    for record in (first, second):\n        assert not (project_path / "uploads" / record["stored_name"]).exists()\n        assert not (project_path / "annotations" / f"{record['id']}.json").exists()\n""",
    """    project_path = app_module.project_dir(project_id)\n    annotation_repository = app_module.AnnotationRepository(project_path)\n    for record in (first, second):\n        assert not (project_path / "uploads" / record["stored_name"]).exists()\n        assert not annotation_repository.exists(record["id"])\n""",
    "multi-dataset sqlite cleanup assertion",
)
batching_test_path.write_text(batching, encoding="utf-8")

atomicity = atomicity_test_path.read_text(encoding="utf-8")
atomicity = replace_once(
    atomicity,
    """    def fail_locked_file(source, destination):\n        if source.name == f"{locked['id']}.json":\n            raise PermissionError("simulated Windows file lock")\n        return original_stage(source, destination)\n""",
    """    def fail_locked_file(source, destination):\n        if source.name == locked["stored_name"]:\n            raise PermissionError("simulated Windows file lock")\n        return original_stage(source, destination)\n""",
    "file lock targets real image",
)
atomicity = replace_once(
    atomicity,
    """    assert (\n        app_module.project_dir(project_id) / "annotations" / f"{locked['id']}.json"\n    ).exists()\n""",
    """    annotation_repository = app_module.AnnotationRepository(\n        app_module.project_dir(project_id)\n    )\n    assert annotation_repository.exists(locked["id"])\n""",
    "file lock sqlite annotation assertion",
)
atomicity_test_path.write_text(atomicity, encoding="utf-8")

print("annotation SQLite dataset delete atomicity migration applied")

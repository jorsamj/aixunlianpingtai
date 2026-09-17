from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

# 1) Extend AlgorithmSqlStore with row-level transactional CRUD.
store_path = ROOT / 'platform_core' / 'algorithm_sql_store.py'
text = store_path.read_text(encoding='utf-8')
marker = '    def migration_status(self) -> dict[str, Any]:\n'
if marker not in text:
    raise SystemExit('migration_status marker not found')
methods = r'''    def read_one(self, algorithm_id: str) -> dict | None:
        self.ensure_ready()
        with self._connect() as conn:
            return self._read_one_conn(conn, str(algorithm_id))

    def create_algorithm(self, item: Mapping[str, Any]) -> dict:
        self.ensure_ready()
        value = dict(item)
        algorithm_id = str(value.get("id") or "").strip()
        name = str(value.get("name") or "").strip()
        if not algorithm_id or not name:
            raise PlatformError("ALGORITHM_ID_REQUIRED", "算法数据不完整", "创建算法需要稳定 ID 和名称。", "请刷新后重试。", 409)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                duplicate = conn.execute(
                    "SELECT id FROM algorithms WHERE project_id=? AND lower(trim(name))=lower(trim(?)) LIMIT 1",
                    (self.project_id, name),
                ).fetchone()
                if duplicate is not None:
                    raise PlatformError("ALGORITHM_NAME_EXISTS", "算法名称已存在", f"当前项目中已经存在名为“{name}”的算法。", "请使用不同名称，或编辑已有算法。", 409)
                sort_index = int(conn.execute(
                    "SELECT COALESCE(MIN(sort_index),0)-1 FROM algorithms WHERE project_id=?",
                    (self.project_id,),
                ).fetchone()[0])
                self._insert_algorithm_conn(conn, value, sort_index)
                self._replace_analyses_conn(conn, algorithm_id, value)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return value

    def patch_algorithm(self, algorithm_id: str, patch: Mapping[str, Any], *, replace_analyses: bool = False) -> dict:
        self.ensure_ready()
        algorithm_id = str(algorithm_id)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                existing = self._read_one_conn(conn, algorithm_id)
                if existing is None:
                    raise PlatformError("ALGORITHM_NOT_FOUND", "算法不存在", f"找不到算法 {algorithm_id}。", "请刷新算法列表后重试。", 404)
                merged = dict(existing)
                merged.update(dict(patch))
                proposed_name = str(merged.get("name") or "").strip()
                duplicate = conn.execute(
                    "SELECT id FROM algorithms WHERE project_id=? AND id<>? AND lower(trim(name))=lower(trim(?)) LIMIT 1",
                    (self.project_id, algorithm_id, proposed_name),
                ).fetchone()
                if duplicate is not None:
                    raise PlatformError("ALGORITHM_NAME_EXISTS", "算法名称已存在", f"算法名称“{proposed_name}”已被使用。", "请使用不同名称。", 409)
                self._update_algorithm_conn(conn, merged)
                if replace_analyses:
                    self._replace_analyses_conn(conn, algorithm_id, merged)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return merged

    def delete_algorithm(self, algorithm_id: str) -> None:
        self.ensure_ready()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                cursor = conn.execute("DELETE FROM algorithms WHERE project_id=? AND id=?", (self.project_id, str(algorithm_id)))
                if cursor.rowcount != 1:
                    raise PlatformError("ALGORITHM_NOT_FOUND", "算法不存在", f"找不到算法 {algorithm_id}。", "请刷新算法列表后重试。", 404)
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def attach_version(self, algorithm_id: str, version: Mapping[str, Any]) -> dict:
        self.ensure_ready()
        algorithm_id = str(algorithm_id)
        value = dict(version)
        version_id = str(value.get("id") or "").strip()
        if not version_id:
            raise PlatformError("ALGORITHM_VERSION_ID_REQUIRED", "算法版本缺少 ID", algorithm_id, "请重新归档训练版本。", 409)
        task_id = str(value.get("task_id") or value.get("job_id") or value.get("training_job_id") or "").strip()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                if conn.execute("SELECT 1 FROM algorithms WHERE project_id=? AND id=?", (self.project_id, algorithm_id)).fetchone() is None:
                    raise PlatformError("ALGORITHM_NOT_FOUND", "算法不存在", f"找不到算法 {algorithm_id}。", "请刷新算法列表后重试。", 404)
                if task_id:
                    duplicate = conn.execute(
                        "SELECT * FROM algorithm_versions WHERE algorithm_id=? AND training_job_id=? LIMIT 1",
                        (algorithm_id, task_id),
                    ).fetchone()
                    if duplicate is not None:
                        conn.rollback()
                        return self._version_from_row(duplicate)
                if conn.execute("SELECT 1 FROM algorithm_versions WHERE id=?", (version_id,)).fetchone() is not None:
                    raise PlatformError("ALGORITHM_VERSION_ID_DUPLICATED", "算法版本 ID 已存在", version_id, "请检查训练归档幂等状态。", 409)
                sort_index = int(conn.execute(
                    "SELECT COALESCE(MIN(sort_index),0)-1 FROM algorithm_versions WHERE algorithm_id=?",
                    (algorithm_id,),
                ).fetchone()[0])
                self._insert_version_conn(conn, algorithm_id, value, sort_index)
                updated_at = str(value.get("finished_at") or value.get("created_at") or "") or None
                conn.execute(
                    "UPDATE algorithms SET current_version_id=?, updated_at=COALESCE(?,updated_at) WHERE project_id=? AND id=?",
                    (version_id, updated_at, self.project_id, algorithm_id),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return value

    def patch_version(self, algorithm_id: str, version_id: str, patch: Mapping[str, Any], *, now: str) -> dict:
        self.ensure_ready()
        algorithm_id = str(algorithm_id)
        version_id = str(version_id)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute("SELECT * FROM algorithm_versions WHERE algorithm_id=? AND id=?", (algorithm_id, version_id)).fetchone()
                if row is None:
                    if conn.execute("SELECT 1 FROM algorithms WHERE project_id=? AND id=?", (self.project_id, algorithm_id)).fetchone() is None:
                        raise PlatformError("ALGORITHM_NOT_FOUND", "算法不存在", f"找不到算法 {algorithm_id}。", "请刷新算法列表后重试。", 404)
                    raise PlatformError("ALGORITHM_VERSION_NOT_FOUND", "算法版本不存在", f"找不到版本 {version_id}。", "请刷新版本列表后重试。", 404)
                value = self._version_from_row(row)
                value.update(dict(patch))
                value["updated_at"] = now
                self._update_version_conn(conn, algorithm_id, value, row["sort_index"])
                conn.execute("UPDATE algorithms SET updated_at=? WHERE project_id=? AND id=?", (now, self.project_id, algorithm_id))
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return value

    def rollback_version(
        self,
        algorithm_id: str,
        target_version_id: str,
        *,
        expected_current_version_id: str,
        operation: Mapping[str, Any],
        now: str,
        delete_current_version: bool,
    ) -> dict | None:
        self.ensure_ready()
        algorithm_id = str(algorithm_id)
        target_version_id = str(target_version_id)
        expected_current_version_id = str(expected_current_version_id)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                algorithm = self._read_one_conn(conn, algorithm_id)
                if algorithm is None:
                    raise PlatformError("ALGORITHM_NOT_FOUND", "算法不存在", f"找不到算法 {algorithm_id}。", "请刷新算法列表后重试。", 404)
                persisted_current = str(algorithm.get("current_version_id") or "")
                if persisted_current and persisted_current != expected_current_version_id:
                    raise PlatformError("ALGORITHM_VERSION_CONFLICT", "算法当前版本已经发生变化", f"请求基于 {expected_current_version_id}，当前实际版本为 {persisted_current}。", "请刷新算法版本列表后重新确认。", 409)
                target = conn.execute("SELECT 1 FROM algorithm_versions WHERE algorithm_id=? AND id=?", (algorithm_id, target_version_id)).fetchone()
                if target is None:
                    raise PlatformError("ALGORITHM_VERSION_NOT_FOUND", "算法版本不存在", f"找不到版本 {target_version_id}。", "请刷新版本列表后重试。", 404)
                current_row = conn.execute("SELECT * FROM algorithm_versions WHERE algorithm_id=? AND id=?", (algorithm_id, expected_current_version_id)).fetchone()
                if current_row is None:
                    raise PlatformError("ALGORITHM_VERSION_CONFLICT", "当前版本记录已发生变化", expected_current_version_id, "请刷新后重试。", 409)
                removed = self._version_from_row(current_row) if delete_current_version else None
                payload = self._json_object(conn.execute("SELECT payload_json FROM algorithms WHERE id=?", (algorithm_id,)).fetchone()[0])
                operations = list(payload.get("version_operations") or [])
                operations.append(dict(operation))
                payload["version_operations"] = operations
                conn.execute(
                    "UPDATE algorithms SET current_version_id=?, updated_at=?, payload_json=? WHERE project_id=? AND id=?",
                    (target_version_id, now, self._dumps(payload), self.project_id, algorithm_id),
                )
                if delete_current_version:
                    conn.execute("DELETE FROM algorithm_versions WHERE algorithm_id=? AND id=?", (algorithm_id, expected_current_version_id))
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return removed

    def delete_version_with_operation(
        self,
        algorithm_id: str,
        version_id: str,
        *,
        expected_current_version_id: str | None,
        operation: Mapping[str, Any],
        now: str,
    ) -> dict:
        self.ensure_ready()
        algorithm_id = str(algorithm_id)
        version_id = str(version_id)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute("SELECT * FROM algorithm_versions WHERE algorithm_id=? AND id=?", (algorithm_id, version_id)).fetchone()
                if row is None:
                    raise PlatformError("ALGORITHM_VERSION_NOT_FOUND", "算法版本不存在", f"找不到版本 {version_id}。", "请刷新版本列表后重试。", 404)
                current = conn.execute("SELECT current_version_id,payload_json FROM algorithms WHERE project_id=? AND id=?", (self.project_id, algorithm_id)).fetchone()
                if current is None:
                    raise PlatformError("ALGORITHM_NOT_FOUND", "算法不存在", f"找不到算法 {algorithm_id}。", "请刷新算法列表后重试。", 404)
                persisted_current = str(current["current_version_id"] or "")
                if persisted_current and expected_current_version_id is not None and persisted_current != str(expected_current_version_id):
                    raise PlatformError("ALGORITHM_VERSION_CONFLICT", "算法当前版本已经发生变化", f"请求基于 {expected_current_version_id}，当前实际版本为 {persisted_current}。", "请刷新后重试。", 409)
                if version_id == persisted_current:
                    raise PlatformError("ALGORITHM_CURRENT_VERSION_DELETE_FORBIDDEN", "不能直接删除当前版本", f"版本 {version_id} 当前正在作为算法默认版本。", "请先回退到另一个有效版本，再删除该版本。", 409)
                payload = self._json_object(current["payload_json"])
                operations = list(payload.get("version_operations") or [])
                operations.append(dict(operation))
                payload["version_operations"] = operations
                conn.execute("DELETE FROM algorithm_versions WHERE algorithm_id=? AND id=?", (algorithm_id, version_id))
                conn.execute("UPDATE algorithms SET updated_at=?, payload_json=? WHERE project_id=? AND id=?", (now, self._dumps(payload), self.project_id, algorithm_id))
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return self._version_from_row(row)

    def update_version_operation(self, algorithm_id: str, operation_id: str, patch: Mapping[str, Any]) -> None:
        self.ensure_ready()
        algorithm_id = str(algorithm_id)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute("SELECT payload_json FROM algorithms WHERE project_id=? AND id=?", (self.project_id, algorithm_id)).fetchone()
                if row is None:
                    raise PlatformError("ALGORITHM_CLEANUP_STATE_LOST", "清理状态无法保存", f"算法 {algorithm_id} 不存在。", "请检查版本操作审计。", 500)
                payload = self._json_object(row["payload_json"])
                operations = list(payload.get("version_operations") or [])
                operation = next((item for item in operations if str(item.get("id") or "") == str(operation_id)), None)
                if operation is None:
                    raise PlatformError("ALGORITHM_CLEANUP_STATE_LOST", "清理审计不存在", f"找不到操作记录 {operation_id}。", "请检查算法版本操作审计。", 500)
                operation.update(dict(patch))
                payload["version_operations"] = operations
                conn.execute("UPDATE algorithms SET payload_json=? WHERE project_id=? AND id=?", (self._dumps(payload), self.project_id, algorithm_id))
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def sync_external_algorithms(self, incoming: Mapping[str, Mapping[str, Any]], *, provider: str, synced_at: str) -> dict[str, int]:
        self.ensure_ready()
        provider = str(provider).upper()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                rows = conn.execute(
                    "SELECT id,external_product_id FROM algorithms WHERE project_id=? AND upper(COALESCE(source_type,''))='EXTERNAL' AND upper(COALESCE(provider_type,''))=?",
                    (self.project_id, provider),
                ).fetchall()
                existing = {str(row["external_product_id"] or ""): str(row["id"]) for row in rows if row["external_product_id"]}
                added = updated = unchanged = inactivated = 0
                for product_id, master_raw in incoming.items():
                    master = dict(master_raw)
                    algorithm_id = existing.get(str(product_id))
                    if not algorithm_id:
                        item = {**master, "current_version_id": None, "version_operations": [], "versions": [], "created_at": synced_at, "updated_at": synced_at}
                        sort_index = int(conn.execute("SELECT COALESCE(MIN(sort_index),0)-1 FROM algorithms WHERE project_id=?", (self.project_id,)).fetchone()[0])
                        self._insert_algorithm_conn(conn, item, sort_index)
                        self._replace_analyses_conn(conn, str(item["id"]), item)
                        added += 1
                        continue
                    current = self._read_one_conn(conn, algorithm_id)
                    if current is None:
                        continue
                    changed = any(current.get(key) != value for key, value in master.items())
                    merged = dict(current)
                    merged.update(master)
                    if changed:
                        merged["updated_at"] = synced_at
                        self._update_algorithm_conn(conn, merged)
                        self._replace_analyses_conn(conn, algorithm_id, merged)
                        updated += 1
                    else:
                        unchanged += 1
                incoming_ids = {str(key) for key in incoming}
                for row in rows:
                    pid = str(row["external_product_id"] or "")
                    if pid in incoming_ids:
                        continue
                    current = self._read_one_conn(conn, str(row["id"]))
                    if current is not None and current.get("external_active") is not False:
                        current["external_active"] = False
                        current["external_last_synced_at"] = synced_at
                        current["updated_at"] = synced_at
                        self._update_algorithm_conn(conn, current)
                        inactivated += 1
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return {"added": added, "updated": updated, "unchanged": unchanged, "inactivated": inactivated, "total": len(incoming)}

    def _read_one_conn(self, conn: sqlite3.Connection, algorithm_id: str) -> dict | None:
        row = conn.execute("SELECT * FROM algorithms WHERE project_id=? AND id=?", (self.project_id, str(algorithm_id))).fetchone()
        if row is None:
            return None
        item = self._json_object(row["payload_json"])
        item.update({"id": row["id"], "name": row["name"], "remark": row["remark"] or "", "industry": row["industry"] or "", "algorithm_type": row["algorithm_type"] or "", "current_version_id": row["current_version_id"], "created_at": row["created_at"], "updated_at": row["updated_at"]})
        self._overlay_optional(item, row, ("source_type", "provider_type", "external_product_id", "external_product_code", "external_category_id", "external_analysis_id", "external_active", "master_data_readonly", "external_last_synced_at"))
        versions = conn.execute("SELECT * FROM algorithm_versions WHERE algorithm_id=? ORDER BY sort_index ASC, id ASC", (row["id"],)).fetchall()
        item["versions"] = [self._version_from_row(v) for v in versions]
        analyses = conn.execute("SELECT * FROM algorithm_external_analyses WHERE algorithm_id=? ORDER BY sort_index ASC, external_analysis_id ASC", (row["id"],)).fetchall()
        if analyses:
            item["external_analyses"] = [self._analysis_from_row(a) for a in analyses]
            item["external_analysis_ids"] = [str(a["external_analysis_id"]) for a in analyses]
        item.setdefault("version_operations", [])
        return item

    def _algorithm_payload(self, item: Mapping[str, Any]) -> dict:
        payload = dict(item)
        payload.pop("versions", None)
        payload.pop("external_analyses", None)
        payload.pop("external_analysis_ids", None)
        for key in ("id", "name", "remark", "industry", "algorithm_type", "current_version_id", "source_type", "provider_type", "external_product_id", "external_product_code", "external_category_id", "external_analysis_id", "external_active", "master_data_readonly", "external_last_synced_at", "created_at", "updated_at"):
            payload.pop(key, None)
        return payload

    def _insert_algorithm_conn(self, conn: sqlite3.Connection, item: Mapping[str, Any], sort_index: int) -> None:
        conn.execute(
            """INSERT INTO algorithms (id,project_id,name,remark,industry,algorithm_type,current_version_id,source_type,provider_type,external_product_id,external_product_code,external_category_id,external_analysis_id,external_active,master_data_readonly,external_last_synced_at,created_at,updated_at,sort_index,payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (str(item.get("id")), self.project_id, str(item.get("name") or ""), str(item.get("remark") or ""), str(item.get("industry") or ""), str(item.get("algorithm_type") or ""), self._nullable_text(item.get("current_version_id")), self._nullable_text(item.get("source_type")), self._nullable_text(item.get("provider_type")), self._nullable_text(item.get("external_product_id")), self._nullable_text(item.get("external_product_code")), self._nullable_text(item.get("external_category_id")), self._nullable_text(item.get("external_analysis_id")), self._nullable_bool(item.get("external_active")), self._nullable_bool(item.get("master_data_readonly")), self._nullable_text(item.get("external_last_synced_at")), self._nullable_text(item.get("created_at")), self._nullable_text(item.get("updated_at")), int(sort_index), self._dumps(self._algorithm_payload(item))),
        )

    def _update_algorithm_conn(self, conn: sqlite3.Connection, item: Mapping[str, Any]) -> None:
        conn.execute(
            """UPDATE algorithms SET name=?,remark=?,industry=?,algorithm_type=?,current_version_id=?,source_type=?,provider_type=?,external_product_id=?,external_product_code=?,external_category_id=?,external_analysis_id=?,external_active=?,master_data_readonly=?,external_last_synced_at=?,created_at=?,updated_at=?,payload_json=? WHERE project_id=? AND id=?""",
            (str(item.get("name") or ""), str(item.get("remark") or ""), str(item.get("industry") or ""), str(item.get("algorithm_type") or ""), self._nullable_text(item.get("current_version_id")), self._nullable_text(item.get("source_type")), self._nullable_text(item.get("provider_type")), self._nullable_text(item.get("external_product_id")), self._nullable_text(item.get("external_product_code")), self._nullable_text(item.get("external_category_id")), self._nullable_text(item.get("external_analysis_id")), self._nullable_bool(item.get("external_active")), self._nullable_bool(item.get("master_data_readonly")), self._nullable_text(item.get("external_last_synced_at")), self._nullable_text(item.get("created_at")), self._nullable_text(item.get("updated_at")), self._dumps(self._algorithm_payload(item)), self.project_id, str(item.get("id"))),
        )

    def _insert_version_conn(self, conn: sqlite3.Connection, algorithm_id: str, version: Mapping[str, Any], sort_index: int) -> None:
        conn.execute(
            """INSERT INTO algorithm_versions (id,algorithm_id,version_name,version_no,training_job_id,framework,training_status,stored_path,model_name,artifact_verified,trainable,external_analysis_id,external_algo_version_id,external_publish_status,created_at,finished_at,sort_index,payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (str(version.get("id")), algorithm_id, self._nullable_text(version.get("version_name")), self._nullable_text(version.get("version_no")), self._nullable_text(version.get("task_id") or version.get("job_id") or version.get("training_job_id")), self._nullable_text(version.get("framework")), self._nullable_text(version.get("training_status") or version.get("status")), self._nullable_text(version.get("stored_path")), self._nullable_text(version.get("model_name")), self._nullable_bool(version.get("artifact_verified")), self._nullable_bool(version.get("trainable")), self._nullable_text(version.get("external_analysis_id")), self._nullable_text(version.get("external_algo_version_id")), self._nullable_text(version.get("external_publish_status")), self._nullable_text(version.get("created_at")), self._nullable_text(version.get("finished_at")), int(sort_index), self._dumps(dict(version))),
        )

    def _update_version_conn(self, conn: sqlite3.Connection, algorithm_id: str, version: Mapping[str, Any], sort_index: int) -> None:
        conn.execute("DELETE FROM algorithm_versions WHERE algorithm_id=? AND id=?", (algorithm_id, str(version.get("id"))))
        self._insert_version_conn(conn, algorithm_id, version, sort_index)

    def _replace_analyses_conn(self, conn: sqlite3.Connection, algorithm_id: str, item: Mapping[str, Any]) -> None:
        conn.execute("DELETE FROM algorithm_external_analyses WHERE algorithm_id=?", (algorithm_id,))
        analyses = [dict(a) for a in (item.get("external_analyses") or []) if isinstance(a, Mapping)]
        if not analyses:
            analyses = [{"analysis_id": str(value)} for value in (item.get("external_analysis_ids") or []) if str(value or "").strip()]
        default_analysis_id = str(item.get("external_analysis_id") or "")
        seen: set[str] = set()
        for index, analysis in enumerate(analyses):
            analysis_id = str(analysis.get("analysis_id") or analysis.get("analysisId") or "").strip()
            if not analysis_id or analysis_id in seen:
                continue
            seen.add(analysis_id)
            compute_platform_ids = analysis.get("compute_platform_ids") or analysis.get("computePlatformIds") or []
            conn.execute(
                """INSERT INTO algorithm_external_analyses (algorithm_id,external_analysis_id,analysis_name,analysis_type,is_default,active,compute_platform_ids_json,sort_index,payload_json) VALUES (?,?,?,?,?,?,?,?,?)""",
                (algorithm_id, analysis_id, self._nullable_text(analysis.get("analysis_name") or analysis.get("analysisName")), self._nullable_text(analysis.get("analysis_type") or analysis.get("analysisType")), 1 if analysis_id == default_analysis_id else 0, 0 if analysis.get("active") is False else 1, self._dumps(list(compute_platform_ids) if isinstance(compute_platform_ids, (list, tuple, set)) else []), index, self._dumps(analysis)),
            )

'''
text = text.replace(marker, methods + marker, 1)
store_path.write_text(text, encoding='utf-8')

# 2) Switch algorithms.py high-frequency mutations to SQL row-level methods.
alg_path = ROOT / 'platform_core' / 'algorithms.py'
text = alg_path.read_text(encoding='utf-8')

def replace_func(name: str, next_name: str, body: str):
    global text
    pattern = rf'def {name}\(.*?\n(?=def {next_name}\()'
    new_text, count = re.subn(pattern, body.rstrip() + '\n\n', text, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f'failed to replace {name}')
    text = new_text

replace_func('create_algorithm', 'update_algorithm', r'''def create_algorithm(
    path: Path,
    payload: Mapping[str, Any],
    now: str,
    algorithm_id: str | None = None,
) -> dict:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise PlatformError(code="ALGORITHM_NAME_REQUIRED", message="算法名称不能为空", detail="创建算法时必须填写名称。", solution="请输入一个能够区分业务用途的算法名称。")
    item = {
        "id": algorithm_id or uuid.uuid4().hex[:12],
        "name": name,
        "remark": str(payload.get("remark") or ""),
        "industry": str(payload.get("industry") or "").strip(),
        "algorithm_type": str(payload.get("algorithm_type") or "").strip(),
        "current_version_id": None,
        "version_operations": [],
        "versions": [],
        "created_at": now,
        "updated_at": now,
    }
    return AlgorithmSqlStore(Path(path)).create_algorithm(item)
''')
replace_func('update_algorithm', 'delete_algorithm', r'''def update_algorithm(path: Path, algorithm_id: str, payload: Mapping[str, Any], now: str) -> dict:
    store = AlgorithmSqlStore(Path(path))
    existing = store.read_one(str(algorithm_id))
    if existing is None:
        raise PlatformError("ALGORITHM_NOT_FOUND", "算法不存在", f"找不到算法 {algorithm_id}。", "请刷新算法列表后重试。", 404)
    patch = {
        "name": str(payload.get("name") or existing.get("name") or "").strip(),
        "remark": str(payload.get("remark") or ""),
        "industry": str(payload.get("industry") or "").strip(),
        "algorithm_type": str(payload.get("algorithm_type") or "").strip(),
        "updated_at": now,
    }
    if "current_version_id" not in existing:
        patch["current_version_id"] = resolve_current_version_id(existing)
    return store.patch_algorithm(str(algorithm_id), patch)
''')
replace_func('delete_algorithm', 'attach_version', r'''def delete_algorithm(path: Path, algorithm_id: str) -> None:
    AlgorithmSqlStore(Path(path)).delete_algorithm(str(algorithm_id))
''')
replace_func('attach_version', 'update_algorithm_version', r'''def attach_version(path: Path, algorithm_id: str, version: Mapping[str, Any]) -> dict:
    return AlgorithmSqlStore(Path(path)).attach_version(str(algorithm_id), version)
''')
replace_func('update_algorithm_version', 'rollback_algorithm_version', r'''def update_algorithm_version(
    path: Path,
    algorithm_id: str,
    version_id: str,
    patch: Mapping[str, Any],
    *,
    now: str,
) -> dict:
    protected = {"id", "version_id", "base_version_id", "parent_version_id"}
    values = {key: value for key, value in patch.items() if key not in protected}
    return AlgorithmSqlStore(Path(path)).patch_version(str(algorithm_id), str(version_id), values, now=now)
''')

# Replace rollback and delete-version as a pair using boundaries to preserve semantics + cleanup.
rollback_pattern = r'def rollback_algorithm_version\(.*?\n(?=def delete_algorithm_version\()'
rollback_body = r'''def rollback_algorithm_version(
    path: Path,
    algorithm_id: str,
    target_version_id: str,
    *,
    now: str,
    delete_current_version: bool = False,
    operator: str = "local_user",
    expected_current_version_id: str | None = None,
    dependency_check: Callable[[Mapping[str, Any], Mapping[str, Any]], Sequence[Mapping[str, Any]]] | None = None,
    cleanup: Callable[[Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]] | None = None,
) -> dict:
    operation_id = uuid.uuid4().hex[:12]
    store = AlgorithmSqlStore(Path(path))
    algorithm = store.read_one(str(algorithm_id))
    if algorithm is None:
        raise PlatformError("ALGORITHM_NOT_FOUND", "算法不存在", f"找不到算法 {algorithm_id}。", "请刷新算法列表后重试。", 404)
    versions = list(algorithm.get("versions") or [])
    current_id = resolve_current_version_id(algorithm)
    if not current_id:
        raise PlatformError("ALGORITHM_CURRENT_VERSION_MISSING", "算法没有可回退的当前版本", "当前算法没有成功且产物已校验的版本。", "请先完成一次有效训练。", 409)
    if expected_current_version_id is not None and str(expected_current_version_id) != current_id:
        raise PlatformError("ALGORITHM_VERSION_CONFLICT", "算法当前版本已经发生变化", f"请求基于 {expected_current_version_id}，当前实际版本为 {current_id}。", "请刷新算法版本列表后重新确认。", 409)
    if str(target_version_id) == current_id:
        raise PlatformError("ALGORITHM_VERSION_ALREADY_CURRENT", "目标版本已经是当前版本", f"版本 {target_version_id} 无需再次回退。", "请选择其他历史版本。", 409)
    target = next((row for row in versions if str(row.get("id") or "") == str(target_version_id)), None)
    if target is None:
        raise PlatformError("ALGORITHM_VERSION_NOT_FOUND", "算法版本不存在", f"找不到版本 {target_version_id}。", "请刷新版本列表后重试。", 404)
    target_framework = str(target.get("framework") or "ultralytics")
    choose_iteration_base([target], "", target_framework, strict_latest=True, artifact_validator=lambda candidate: candidate.is_file() and candidate.stat().st_size > 0)
    current = next(row for row in versions if str(row.get("id") or "") == current_id)
    if delete_current_version:
        dependencies = list((dependency_check or (lambda _algorithm, _version: []))(algorithm, current) or [])
        if dependencies:
            reasons = [str(item.get("reason") or item.get("id") or "存在活动引用") for item in dependencies]
            raise PlatformError("ALGORITHM_VERSION_IN_USE", "当前版本仍被活动业务引用，不能删除", "；".join(reasons), "请先结束相关任务或停止对应业务，再重新执行回退并删除。", 409)
    operation = {
        "id": operation_id,
        "algorithm_id": str(algorithm_id),
        "from_version_id": current_id,
        "to_version_id": str(target_version_id),
        "deleted_version_id": current_id if delete_current_version else None,
        "action": "rollback_and_delete" if delete_current_version else "rollback",
        "operator": str(operator or "local_user"),
        "created_at": now,
        "cleanup_status": "cleanup_pending" if delete_current_version else "not_required",
        "cleanup_targets": [],
        "cleanup_errors": [],
    }
    removed_version = store.rollback_version(str(algorithm_id), str(target_version_id), expected_current_version_id=current_id, operation=operation, now=now, delete_current_version=delete_current_version)
    cleanup_result: Mapping[str, Any] = {}
    cleanup_status = "not_required"
    if delete_current_version and removed_version is not None:
        try:
            cleanup_result = dict((cleanup or (lambda _algorithm, _version: {"status": "cleanup_pending"}))(dict(algorithm), removed_version) or {})
        except Exception as error:
            cleanup_result = {"status": "cleanup_failed", "targets": [], "errors": [str(error)]}
        cleanup_status = str(cleanup_result.get("status") or "cleanup_failed")
        if cleanup_status not in {"cleanup_completed", "cleanup_pending", "cleanup_failed"}:
            cleanup_status = "cleanup_failed"
        store.update_version_operation(str(algorithm_id), operation_id, {
            "cleanup_status": cleanup_status,
            "cleanup_targets": [str(item) for item in cleanup_result.get("targets") or []],
            "cleanup_errors": [str(item) for item in cleanup_result.get("errors") or []],
        })
    return {
        "algorithm_id": str(algorithm_id),
        "previous_current_version_id": current_id,
        "current_version_id": str(target_version_id),
        "deleted_version_id": current_id if delete_current_version else None,
        "action": "rollback_and_delete" if delete_current_version else "rollback",
        "operation_id": operation_id,
        "cleanup_status": cleanup_status,
        "cleanup_targets": [str(item) for item in cleanup_result.get("targets") or []],
        "cleanup_errors": [str(item) for item in cleanup_result.get("errors") or []],
    }
'''
text, count = re.subn(rollback_pattern, rollback_body + '\n\n', text, count=1, flags=re.S)
if count != 1:
    raise SystemExit('failed to replace rollback_algorithm_version')

delete_pattern = r'def delete_algorithm_version\(.*\Z'
delete_body = r'''def delete_algorithm_version(
    path: Path,
    algorithm_id: str,
    version_id: str,
    *,
    now: str,
    operator: str = "local_user",
    dependency_check: Callable[[Mapping[str, Any], Mapping[str, Any]], Sequence[Mapping[str, Any]]] | None = None,
    cleanup: Callable[[Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]] | None = None,
) -> dict:
    operation_id = uuid.uuid4().hex[:12]
    store = AlgorithmSqlStore(Path(path))
    algorithm = store.read_one(str(algorithm_id))
    if algorithm is None:
        raise PlatformError("ALGORITHM_NOT_FOUND", "算法不存在", f"找不到算法 {algorithm_id}。", "请刷新算法列表后重试。", 404)
    versions = list(algorithm.get("versions") or [])
    target = next((row for row in versions if str(row.get("id") or "") == str(version_id)), None)
    if target is None:
        raise PlatformError("ALGORITHM_VERSION_NOT_FOUND", "算法版本不存在", f"找不到版本 {version_id}。", "请刷新版本列表后重试。", 404)
    current_id = resolve_current_version_id(algorithm)
    if str(version_id) == str(current_id or ""):
        raise PlatformError("ALGORITHM_CURRENT_VERSION_DELETE_FORBIDDEN", "不能直接删除当前版本", f"版本 {version_id} 当前正在作为算法默认版本。", "请先回退到另一个有效版本，再删除该版本。", 409)
    dependencies = list((dependency_check or (lambda _algorithm, _version: []))(algorithm, target) or [])
    if dependencies:
        reasons = [str(item.get("reason") or item.get("id") or "存在活动引用") for item in dependencies]
        raise PlatformError("ALGORITHM_VERSION_IN_USE", "算法版本仍被活动业务引用，不能删除", "；".join(reasons), "请先结束相关任务或停止对应业务，再重新删除。", 409)
    operation = {
        "id": operation_id,
        "algorithm_id": str(algorithm_id),
        "from_version_id": current_id,
        "to_version_id": current_id,
        "deleted_version_id": str(version_id),
        "action": "delete_version",
        "operator": str(operator or "local_user"),
        "created_at": now,
        "cleanup_status": "cleanup_pending",
        "cleanup_targets": [],
        "cleanup_errors": [],
    }
    removed = store.delete_version_with_operation(str(algorithm_id), str(version_id), expected_current_version_id=current_id, operation=operation, now=now)
    try:
        cleanup_result = dict((cleanup or (lambda _algorithm, _version: {"status": "cleanup_pending"}))(dict(algorithm), dict(removed)) or {})
    except Exception as error:
        cleanup_result = {"status": "cleanup_failed", "targets": [], "errors": [str(error)]}
    status = str(cleanup_result.get("status") or "cleanup_failed")
    if status not in {"cleanup_completed", "cleanup_pending", "cleanup_failed"}:
        status = "cleanup_failed"
    store.update_version_operation(str(algorithm_id), operation_id, {
        "cleanup_status": status,
        "cleanup_targets": [str(item) for item in cleanup_result.get("targets") or []],
        "cleanup_errors": [str(item) for item in cleanup_result.get("errors") or []],
    })
    return {
        "algorithm_id": str(algorithm_id),
        "previous_current_version_id": current_id,
        "current_version_id": current_id,
        "deleted_version_id": str(version_id),
        "action": "delete_version",
        "operation_id": operation_id,
        "cleanup_status": status,
        "cleanup_targets": [str(item) for item in cleanup_result.get("targets") or []],
        "cleanup_errors": [str(item) for item in cleanup_result.get("errors") or []],
    }
'''
text, count = re.subn(delete_pattern, delete_body + '\n', text, count=1, flags=re.S)
if count != 1:
    raise SystemExit('failed to replace delete_algorithm_version')
alg_path.write_text(text, encoding='utf-8')

# 3) New Changlian sync uses a SQL transaction scoped to external master rows.
ext_path = ROOT / 'platform_core' / 'external_algorithm_platform.py'
text = ext_path.read_text(encoding='utf-8')
text = text.replace('from .algorithms import list_algorithms, save_algorithms\n', 'from .algorithm_sql_store import AlgorithmSqlStore\nfrom .algorithms import list_algorithms\n', 1)
old = re.search(r'    with lock:\n        algorithms = list_algorithms\(algorithms_path\).*?\n    return \{\n        "added": added,\n        "updated": updated,\n        "unchanged": unchanged,\n        "inactivated": inactivated,\n        "total": len\(incoming\),\n    \}', text, flags=re.S)
if old is None:
    raise SystemExit('external mirror persistence block not found')
replacement = '    return AlgorithmSqlStore(algorithms_path).sync_external_algorithms(incoming, provider=provider, synced_at=synced_at)'
text = text[:old.start()] + replacement + text[old.end():]
ext_path.write_text(text, encoding='utf-8')

# 4) Update tests to assert SQL runtime state rather than mutated legacy JSON.
test_alg = ROOT / 'tests' / 'unit' / 'test_algorithms.py'
text = test_alg.read_text(encoding='utf-8')
text = text.replace('stored = json.loads(path.read_text(encoding="utf-8"))[0]["versions"]', 'stored = algorithms_module.list_algorithms(path)[0]["versions"]')
text = text.replace('stored = json.loads(path.read_text(encoding="utf-8"))[0]', 'stored = algorithms_module.list_algorithms(path)[0]')
# Atomic failure tests should verify SQL too, while retaining the legacy JSON immutability check.
text = text.replace('assert json.loads(path.read_text(encoding="utf-8")) == original\n', 'assert json.loads(path.read_text(encoding="utf-8")) == original\n    assert algorithms_module.list_algorithms(path)[0]["current_version_id"] == original[0].get("current_version_id")\n', 2)
test_alg.write_text(text, encoding='utf-8')

# 5) Add cross-flow concurrency regression.
sql_test = ROOT / 'tests' / 'unit' / 'test_algorithm_sql_store.py'
text = sql_test.read_text(encoding='utf-8')
if 'test_external_sync_cannot_overwrite_concurrent_training_version' not in text:
    text += r'''


def test_external_sync_cannot_overwrite_concurrent_training_version(tmp_path: Path):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from platform_core.algorithms import attach_version, list_algorithms

    project = tmp_path / "projects" / "p1"
    project.mkdir(parents=True)
    json_path = project / "algorithms.json"
    json_path.write_text("[]", encoding="utf-8")
    mirror_products_to_algorithms(
        algorithms_path=json_path,
        products=[{"productId": "product-200", "productName": "并发算法", "categoryId": "cat"}],
        categories=[{"categoryId": "cat", "categoryName": "测试"}],
        analyses_by_product={"product-200": [{"analysisId": "analysis-1", "analysisName": "视觉"}]},
        synced_at="2026-09-17T10:00:00Z",
    )
    algorithm = next(row for row in list_algorithms(json_path) if row.get("external_product_id") == "product-200")
    barrier = threading.Barrier(2)

    def finish_training():
        barrier.wait(timeout=2)
        attach_version(json_path, algorithm["id"], {
            "id": "concurrent-v1", "task_id": "train-concurrent", "training_status": "SUCCEEDED",
            "artifact_verified": True, "trainable": True, "framework": "ultralytics",
            "finished_at": "2026-09-17T10:01:00Z", "stored_path": "/models/concurrent-v1/best.pt",
        })

    def sync_master():
        barrier.wait(timeout=2)
        mirror_products_to_algorithms(
            algorithms_path=json_path,
            products=[{"productId": "product-200", "productName": "并发算法（更新）", "categoryId": "cat"}],
            categories=[{"categoryId": "cat", "categoryName": "测试"}],
            analyses_by_product={"product-200": [{"analysisId": "analysis-1", "analysisName": "视觉"}]},
            synced_at="2026-09-17T10:01:00Z",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(finish_training), executor.submit(sync_master)]
        for future in futures:
            future.result(timeout=5)

    persisted = next(row for row in list_algorithms(json_path) if row["id"] == algorithm["id"])
    assert persisted["name"] == "并发算法（更新）"
    assert persisted["current_version_id"] == "concurrent-v1"
    assert [row["id"] for row in persisted["versions"]] == ["concurrent-v1"]
'''
sql_test.write_text(text, encoding='utf-8')

print('row-level SQL CRUD migration applied')

from pathlib import Path
import re


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, got {count}")
    return text.replace(old, new, 1)


def sub_once(text: str, pattern: str, replacement: str, label: str) -> str:
    text, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f"{label}: expected one regex match, got {count}")
    return text


# 1) Split modern material-batch preparation from queue publication so upload
# decisions can freeze a selection before publishing their own durable state.
path = Path("platform_core/material_batches.py")
text = path.read_text(encoding="utf-8")
pattern = r"def create_batch\(project_id, materials, repository, artifacts, payload\):.*?(?=\n\n_SCHEMA = )"
replacement = '''def prepare_batch(project_id, materials, artifacts, payload, *, task_id=None):
    """Freeze a batch selection durably without publishing executable queue truth yet."""
    operation, selection, options = parse_request(payload)
    if operation is BatchOperation.AI_ANNOTATE:
        from .annotation_runtime import prepare_request
        options = prepare_request(materials.project_path.parent.parent, project_id, options, runtime=False)
    if selection.repository_revision is None:
        raise BatchRequestError("BATCH_ESTIMATE_REQUIRED", "estimate and provide selection_spec.repository_revision first", 409)
    if operation is BatchOperation.DELETE_SOURCE and options.get("confirmation_token") != _confirmation_token(
        project_id, operation, selection, options,
    ):
        raise BatchRequestError("DELETE_SOURCE_CONFIRMATION_REQUIRED", "confirm source deletion using the estimate confirmation_token", 409)
    task_id = str(task_id or uuid.uuid4().hex)
    request_payload = {
        "operation": operation.value,
        "selection_spec": selection.as_dict(),
        "options": options,
    }
    selection_path = artifacts.artifact_path(task_id, SELECTION_REF)
    existing_request = artifacts.read_json(task_id, "request.json", default=None)
    if existing_request is not None:
        if existing_request != request_payload:
            raise BatchRequestError("BATCH_TASK_ID_CONFLICT", "task id is already prepared for a different material batch", 409)
        with closing(BatchSelection(selection_path)) as manifest:
            if not manifest.frozen():
                raise BatchRequestError("BATCH_SELECTION_NOT_FROZEN", "prepared batch selection is incomplete", 409)
        return TaskRecord.new(
            task_id, project_id, TaskKind.MATERIAL_BATCH, "request.json",
            f"materials:{project_id}", required_capabilities=("materials.batch",),
        )
    try:
        # Prepare the schema before taking the material lock. No task exists yet.
        with closing(BatchSelection(selection_path)):
            pass
        clauses, params = _predicate(materials, selection)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with closing(materials._connect()) as database:
            database.execute("ATTACH DATABASE ? AS batch_selection", (str(selection_path),))
            database.execute("PRAGMA batch_selection.synchronous=FULL")
            database.execute("BEGIN IMMEDIATE")
            if materials._revision(database) != selection.repository_revision:
                raise BatchRequestError("MATERIAL_REVISION_CHANGED", "material repository changed; re-estimate before confirming", 409)
            inserted = database.execute(
                "INSERT INTO batch_selection.selection(image_id) SELECT m.id FROM main.materials m" + where,
                params,
            ).rowcount
            if selection.scope is not SelectionScope.FILTERED and inserted != len(selection.image_ids):
                raise BatchRequestError("MATERIAL_SELECTION_CHANGED", "selected materials are missing; re-estimate before confirming", 409)
            database.executemany(
                "INSERT INTO batch_selection.meta(key,value) VALUES (?,?)",
                (("frozen", utc_now()), ("repository_revision", str(selection.repository_revision))),
            )
            database.commit()
        artifacts.atomic_write_json(task_id, "request.json", request_payload)
        with closing(BatchSelection(selection_path)) as manifest:
            artifacts.atomic_write_json(task_id, CHECKPOINT_REF, manifest.summary())
        return TaskRecord.new(
            task_id, project_id, TaskKind.MATERIAL_BATCH, "request.json",
            f"materials:{project_id}", required_capabilities=("materials.batch",),
        )
    except Exception as error:
        try:
            artifacts.atomic_write_json(task_id, "creation_failure.json", {
                "task_id": task_id, "status": "CREATION_FAILED", "error": redact_storage_error(error),
            })
        except Exception:
            pass
        if isinstance(error, BatchRequestError):
            raise
        raise BatchRequestError("BATCH_CREATION_FAILED", f"material batch creation failed: {redact_storage_error(error)}", 500) from error


def publish_prepared_batch(task, repository, artifacts):
    """Publish one previously frozen batch exactly once into TaskRepository."""
    existing = repository.get(task.task_id)
    if existing is not None:
        if existing.project_id != task.project_id or existing.kind is not TaskKind.MATERIAL_BATCH:
            raise BatchRequestError("BATCH_TASK_ID_CONFLICT", "task id is already owned by another durable task", 409)
        return existing
    request = artifacts.read_json(task.task_id, task.payload_ref, default=None)
    selection_path = artifacts.artifact_path(task.task_id, SELECTION_REF)
    if not isinstance(request, dict) or not selection_path.is_file():
        raise BatchRequestError("BATCH_NOT_PREPARED", "material batch artifacts are incomplete", 409)
    with closing(BatchSelection(selection_path)) as manifest:
        if not manifest.frozen():
            raise BatchRequestError("BATCH_SELECTION_NOT_FROZEN", "material batch selection is incomplete", 409)
    try:
        return repository.create(task, artifacts=artifacts)
    except Exception as error:
        if isinstance(error, BatchRequestError):
            raise
        raise BatchRequestError("BATCH_PUBLICATION_FAILED", f"material batch publication failed: {redact_storage_error(error)}", 500) from error


def create_batch(project_id, materials, repository, artifacts, payload):
    task = prepare_batch(project_id, materials, artifacts, payload)
    return publish_prepared_batch(task, repository, artifacts)
'''
text = sub_once(text, pattern, replacement, "material batch prepare/publish split")
path.write_text(text, encoding="utf-8")

# 2) Bridge active v47/v55 cleaning entry points onto the modern durable batch.
path = Path("app.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "from platform_core.video_tasks import SamplingMode, VideoSampleRequest\n",
    "from platform_core.video_tasks import SamplingMode, VideoSampleRequest\n"
    "from platform_core.material_batches import (\n"
    "    BatchOperation as MaterialBatchOperation,\n"
    "    SELECTION_REF as MATERIAL_BATCH_SELECTION_REF,\n"
    "    estimate_batch as estimate_material_batch,\n"
    "    prepare_batch as prepare_material_batch,\n"
    "    publish_prepared_batch as publish_prepared_material_batch,\n"
    "    public_batch as public_material_batch,\n"
    ")\n",
    "material batch compatibility imports",
)
text = replace_once(
    text,
    "def _v33_load_tasks(project_id: str, kind: str) -> List[Dict[str, Any]]:\n    with _v33_task_lock:\n        return read_json(_v33_tasks_file(project_id, kind), [])\n",
    "def _v33_load_tasks(project_id: str, kind: str) -> List[Dict[str, Any]]:\n"
    "    if kind == 'clean_tasks' and '_v47_list_durable_clean_tasks' in globals():\n"
    "        return _v47_list_durable_clean_tasks(project_id)\n"
    "    with _v33_task_lock:\n"
    "        return read_json(_v33_tasks_file(project_id, kind), [])\n",
    "clean task durable list bridge",
)

helpers = r'''
def _v47_material_batch_payload(project_id: str, payload: V47CleanReq) -> Dict[str, Any]:
    data = payload.model_dump() if hasattr(payload, 'model_dump') else payload.dict()
    image_ids = list(dict.fromkeys(str(x) for x in (data.pop('image_ids', None) or []) if str(x)))
    selection: Dict[str, Any]
    if image_ids:
        selection = {'scope': 'SELECTED', 'image_ids': image_ids}
    else:
        selection = {'scope': 'FILTERED', 'filters': {}}
    draft = {'operation': MaterialBatchOperation.CLEAN.value, 'selection_spec': selection, 'options': data}
    estimate = estimate_material_batch(project_id, material_store(project_id), draft)
    draft['selection_spec'] = estimate['selection_spec']
    return draft


def _v47_material_batch_request(task_id: str) -> Dict[str, Any]:
    return shared_task_artifacts().read_json(task_id, 'request.json', default={}) or {}


def _v47_clean_compat_task(task: TaskRecord) -> Dict[str, Any]:
    repository = shared_task_repository()
    artifacts = shared_task_artifacts()
    body = public_material_batch(task, artifacts, repository if repository.get(task.task_id) is not None else None)
    request = _v47_material_batch_request(task.task_id)
    options = dict(request.get('options') or {})
    selection = dict(request.get('selection_spec') or {})
    request_payload = {**options, 'image_ids': list(selection.get('image_ids') or [])}
    confirmed = artifacts.read_json(task.task_id, 'clean_confirmation.json', default=None)
    public_status = str(body.get('status') or task.status.value)
    if public_status in {'QUEUED', 'WAITING_RESOURCE'}:
        status = 'queued'
        status_text = '等待资源' if public_status == 'WAITING_RESOURCE' else '排队中'
    elif public_status == 'RUNNING':
        status, status_text = 'running', '清洗中'
    elif public_status == 'CANCEL_REQUESTED':
        status, status_text = 'running', '正在停止'
    elif public_status == 'CANCELLED':
        status, status_text = 'cancelled', '已停止'
    elif public_status == 'SUCCEEDED':
        status, status_text = ('done', '已确认') if confirmed else ('awaiting_confirmation', '待确认')
    elif public_status == 'PARTIAL_SUCCESS':
        status, status_text = 'failed', '部分失败，请重试'
    elif public_status in {'BLOCKED_BY_ENVIRONMENT', 'BLOCKED_BY_HARDWARE'}:
        status, status_text = 'failed', '运行环境不可用'
    else:
        status, status_text = 'failed', '失败'
    return {
        'id': task.task_id,
        'name': options.get('task_name') or '自动清洗任务',
        'status': status,
        'status_text': status_text,
        'stage': body.get('phase'),
        'progress': body.get('progress_percent') or 0,
        'processed_images': body.get('processed') or 0,
        'total_images': body.get('total') or 0,
        'flagged_images': body.get('flagged') or 0,
        'created_at': body.get('created_at'),
        'finished_at': body.get('finished_at'),
        'request_payload': request_payload,
        'resource_queue_position': body.get('resource_queue_position'),
        'resource_wait_reason': body.get('resource_wait_reason'),
        'worker_id': body.get('worker_id'),
        'lease_expires_at': body.get('lease_expires_at'),
        'durable_task_kind': TaskKind.MATERIAL_BATCH.value,
    }


def _v47_list_durable_clean_tasks(project_id: str) -> List[Dict[str, Any]]:
    repository = shared_task_repository()
    page = repository.list(project_id=project_id, kinds={TaskKind.MATERIAL_BATCH}, limit=100)
    rows = []
    for task in page.items:
        request = _v47_material_batch_request(task.task_id)
        if request.get('operation') == MaterialBatchOperation.CLEAN.value:
            rows.append(_v47_clean_compat_task(task))
    return rows


def _v62_prepare_clean_compat(project_id: str, payload: V47CleanReq, task_id: Optional[str] = None) -> Tuple[Dict[str, Any], bool]:
    get_project(project_id)
    requested_id = str(task_id or uuid.uuid4().hex[:12])
    existing = shared_task_repository().get(requested_id)
    if existing is not None:
        if existing.project_id != project_id or existing.kind is not TaskKind.MATERIAL_BATCH:
            raise ValueError('清洗任务 ID 已被其他任务占用')
        request = _v47_material_batch_request(requested_id)
        if request.get('operation') != MaterialBatchOperation.CLEAN.value:
            raise ValueError('清洗任务 ID 已被其他批处理占用')
        return _v47_clean_compat_task(existing), False
    batch_payload = _v47_material_batch_payload(project_id, payload)
    prepared = prepare_material_batch(
        project_id,
        material_store(project_id),
        shared_task_artifacts(),
        batch_payload,
        task_id=requested_id,
    )
    return _v47_clean_compat_task(prepared), True


def _v62_publish_clean_compat(project_id: str, task_id: str) -> Dict[str, Any]:
    repository = shared_task_repository()
    existing = repository.get(task_id)
    if existing is not None:
        return _v47_clean_compat_task(existing)
    request = _v47_material_batch_request(task_id)
    if request.get('operation') != MaterialBatchOperation.CLEAN.value:
        raise ValueError('清洗任务尚未准备完成')
    prepared = TaskRecord.new(
        task_id, project_id, TaskKind.MATERIAL_BATCH, 'request.json',
        f'materials:{project_id}', required_capabilities=('materials.batch',),
    )
    published = publish_prepared_material_batch(prepared, repository, shared_task_artifacts())
    return _v47_clean_compat_task(published)


def _v47_durable_clean_results(task_id: str) -> Dict[str, Any]:
    artifacts = shared_task_artifacts()
    path = artifacts.artifact_path(task_id, MATERIAL_BATCH_SELECTION_REF)
    if not path.is_file():
        return {'items': []}
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as database:
        if database.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='clean_results'").fetchone() is None:
            return {'items': []}
        rows = database.execute(
            'SELECT r.result_json,s.state,s.error FROM clean_results r '
            'JOIN selection s ON s.image_id=r.image_id ORDER BY r.image_id'
        ).fetchall()
    return {'items': [{**json.loads(row[0]), 'item_state': row[1], 'item_error': row[2]} for row in rows]}
'''
text = replace_once(text, "\n_V47_ACTIVE_CLEAN_WORKERS: set[Tuple[str, str]] = set()\n", "\n" + helpers + "\n_V47_ACTIVE_CLEAN_WORKERS: set[Tuple[str, str]] = set()\n", "durable cleaning compatibility helpers")

# Manual v47 compatibility endpoint now publishes a modern durable batch.
text = replace_once(
    text,
    "@app.post('/api/v47/projects/{project_id}/clean-tasks')\ndef v47_create_clean_task(project_id: str, payload: V47CleanReq):\n    return _v47_create_clean_task_record(project_id, payload)\n",
    "@app.post('/api/v47/projects/{project_id}/clean-tasks')\n"
    "def v47_create_clean_task(project_id: str, payload: V47CleanReq):\n"
    "    task, _ = _v62_prepare_clean_compat(project_id, payload)\n"
    "    return _v62_publish_clean_compat(project_id, str(task['id']))\n",
    "v47 durable create bridge",
)

# Upload-batch preparation/publication keeps the existing atomic ordering but
# no longer creates or starts the legacy daemon worker.
text = text.replace("_, prepared_created = _v47_prepare_clean_task_record(\n                    project_id,\n                    clean_request,\n                    task_id=clean_task_id,\n                )", "_, prepared_created = _v62_prepare_clean_compat(\n                    project_id,\n                    clean_request,\n                    task_id=clean_task_id,\n                )")
if "_, prepared_created = _v47_prepare_clean_task_record(" in text:
    raise SystemExit("v55 durable prepare replacement did not cover active call")
text = replace_once(
    text,
    "if clean_task_id:\n                _v47_start_clean_task_record(project_id, clean_task_id)",
    "if clean_task_id:\n                _v62_publish_clean_compat(project_id, clean_task_id)",
    "v55 durable publish bridge",
)

# Legacy list callers now subscribe to durable task projections. Stop is a real
# cancellation request against TaskRepository, not a stop_requested JSON flag.
text = replace_once(
    text,
    "@app.post('/api/v47/projects/{project_id}/clean-tasks/{task_id}/stop')\n"
    "def v47_stop_clean_task(project_id: str, task_id: str):\n"
    "    if not _v33_get_task(project_id, 'clean_tasks', task_id):\n"
    "        raise HTTPException(status_code=404, detail='清洗任务不存在')\n"
    "    _v33_update_task(project_id, 'clean_tasks', task_id, stop_requested=True, status_text='正在停止')\n"
    "    return {'ok': True}\n",
    "@app.post('/api/v47/projects/{project_id}/clean-tasks/{task_id}/stop')\n"
    "def v47_stop_clean_task(project_id: str, task_id: str):\n"
    "    task = shared_task_repository().get(task_id)\n"
    "    if task is None or task.project_id != project_id or task.kind is not TaskKind.MATERIAL_BATCH:\n"
    "        raise HTTPException(status_code=404, detail='清洗任务不存在')\n"
    "    shared_task_repository().request_cancel(task_id)\n"
    "    return {'ok': True}\n",
    "v47 durable cancel bridge",
)
text = replace_once(
    text,
    "    return {'task': task, 'result': read_json(_v47_file_for(project_id, 'clean_results', task_id), {'items': []})}\n",
    "    return {'task': task, 'result': _v47_durable_clean_results(task_id)}\n",
    "v47 durable result bridge",
)
text = replace_once(
    text,
    "    allowed = {str(x.get('image_id')) for x in read_json(_v47_file_for(project_id, 'clean_results', task_id), {'items': []}).get('items', [])}\n",
    "    allowed = {str(x.get('image_id')) for x in _v47_durable_clean_results(task_id).get('items', [])}\n",
    "v47 durable confirm result source",
)
text = replace_once(
    text,
    "    _v33_update_task(project_id, 'clean_tasks', task_id, status='done', status_text='已确认', deleted_images=deleted, delete_failures=len(failed_items), processed_confirmed=len(processed_ids), confirmed_at=now_iso(), finished_at=now_iso())\n"
    "    return {'ok': not failed_items, 'deleted': deleted, 'deleted_ids': deleted_ids, 'deleted_images': deleted_images, 'failed_items': failed_items, 'processed_ids': processed_ids}\n",
    "    shared_task_artifacts().atomic_write_json(task_id, 'clean_confirmation.json', {\n"
    "        'confirmed_at': now_iso(), 'deleted': deleted, 'deleted_ids': deleted_ids,\n"
    "        'delete_failures': len(failed_items), 'processed_ids': processed_ids,\n"
    "    })\n"
    "    return {'ok': not failed_items, 'deleted': deleted, 'deleted_ids': deleted_ids, 'deleted_images': deleted_images, 'failed_items': failed_items, 'processed_ids': processed_ids}\n",
    "v47 durable confirmation marker",
)

path.write_text(text, encoding="utf-8")

# 3) Make the new API behavior a permanent release contract.
path = Path(".github/workflows/v42.25-release-regression.yml")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "      - tests/api/test_durable_training_controls.py\n",
    "      - tests/api/test_durable_training_controls.py\n      - tests/api/test_clean_unified_execution_truth.py\n",
    "release path cleaning guard",
)
text = replace_once(
    text,
    "          tests/api/test_durable_training_controls.py\n",
    "          tests/api/test_durable_training_controls.py\n          tests/api/test_clean_unified_execution_truth.py\n",
    "release runtime cleaning guard",
)
text = replace_once(
    text,
    "# AI-annotation queue-display guard: polling rows must preserve durable resource_queue_position/resource_wait_reason instead of erasing runtimeText.\n",
    "# AI-annotation queue-display guard: polling rows must preserve durable resource_queue_position/resource_wait_reason instead of erasing runtimeText.\n# Cleaning execution guard: manual and upload-batch clean_task_id values must publish one MATERIAL_BATCH/CLEAN TaskRepository truth.\n",
    "release cleaning guard comment",
)
path.write_text(text, encoding="utf-8")

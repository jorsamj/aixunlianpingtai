from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding='utf-8')


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding='utf-8')


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f'{path}: expected one match, got {count}: {old[:100]!r}')
    write(path, text.replace(old, new, 1))


def replace_count(path: str, old: str, new: str, expected: int) -> None:
    text = read(path)
    count = text.count(old)
    if count != expected:
        raise RuntimeError(f'{path}: expected {expected} matches, got {count}: {old[:100]!r}')
    write(path, text.replace(old, new))


# Multipart repository must allow different parts to write concurrently.
replace_once(
    'platform_core/zip_multipart.py',
    '''    def write_part(self, upload_id: str, part_number: int, stream: BinaryIO) -> dict[str, Any]:\n        with self.lock:\n            meta = self._read(upload_id)\n            if meta.get('status') == 'completed':\n                return self._public(meta)\n            total_parts = int(meta['total_parts'])\n            number = int(part_number)\n            if number < 0 or number >= total_parts:\n                raise ValueError('multipart part number out of range')\n            expected = int(meta['part_size'])\n            if number == total_parts - 1:\n                expected = int(meta['file_size']) - int(meta['part_size']) * (total_parts - 1)\n            target = self._part_path(upload_id, number)\n            target.parent.mkdir(parents=True, exist_ok=True)\n            temporary = target.with_suffix('.tmp')\n            written = 0\n            digest = hashlib.sha256()\n            with temporary.open('wb') as output:\n                while True:\n                    chunk = stream.read(1024 * 1024)\n                    if not chunk:\n                        break\n                    output.write(chunk)\n                    digest.update(chunk)\n                    written += len(chunk)\n            if written != expected:\n                temporary.unlink(missing_ok=True)\n                raise ValueError(f'multipart part size mismatch: {written}/{expected}')\n            temporary.replace(target)\n            return {**self._public(meta), 'part_number': number, 'part_sha256': digest.hexdigest()}\n''',
    '''    def write_part(self, upload_id: str, part_number: int, stream: BinaryIO) -> dict[str, Any]:\n        # Different part numbers are independent and may be written in parallel.\n        # A per-part lock protects duplicate retries without serialising the whole upload.\n        meta = self._read(upload_id)\n        if meta.get('status') == 'completed':\n            return self._public(meta)\n        total_parts = int(meta['total_parts'])\n        number = int(part_number)\n        if number < 0 or number >= total_parts:\n            raise ValueError('multipart part number out of range')\n        expected = int(meta['part_size'])\n        if number == total_parts - 1:\n            expected = int(meta['file_size']) - int(meta['part_size']) * (total_parts - 1)\n        target = self._part_path(upload_id, number)\n        target.parent.mkdir(parents=True, exist_ok=True)\n        part_lock = FileLock(str(target) + '.lock', timeout=30)\n        with part_lock:\n            temporary = target.with_suffix('.tmp')\n            written = 0\n            digest = hashlib.sha256()\n            with temporary.open('wb') as output:\n                while True:\n                    chunk = stream.read(1024 * 1024)\n                    if not chunk:\n                        break\n                    output.write(chunk)\n                    digest.update(chunk)\n                    written += len(chunk)\n            if written != expected:\n                temporary.unlink(missing_ok=True)\n                raise ValueError(f'multipart part size mismatch: {written}/{expected}')\n            temporary.replace(target)\n        return {**self._public(meta), 'part_number': number, 'part_sha256': digest.hexdigest()}\n''',
)

# Backend wiring: multipart session endpoints + faster local I/O + more frequent truthful progress.
replace_once(
    'app.py',
    'from platform_core.storage.zip_import import (\n',
    'from platform_core.zip_multipart import ZipMultipartRepository\nfrom platform_core.storage.zip_import import (\n',
)
replace_once(
    'app.py',
    'class TrainReq(BaseModel):\n    @model_validator(mode="before")',
    'class TrainReq(BaseModel):\n    task_id: Optional[str] = None\n\n    @model_validator(mode="before")',
)

app = read('app.py')
start = app.find('@app.post("/api/v12/projects/{project_id}/train/start")')
if start < 0:
    raise RuntimeError('v12 train endpoint not found')
end = app.find('\n@app.', start + 10)
if end < 0:
    end = len(app)
section = app[start:end]
old_task = 'task_id = uuid.uuid4().hex[:12]'
if section.count(old_task) != 1:
    raise RuntimeError(f'v12 task id assignment expected once, got {section.count(old_task)}')
new_task = '''requested_task_id = str(payload.task_id or "").strip()\n    if requested_task_id and not re.fullmatch(r"train_[0-9a-f]{16,32}", requested_task_id):\n        raise HTTPException(status_code=422, detail="训练任务 ID 格式不正确")\n    task_id = requested_task_id or uuid.uuid4().hex[:12]\n    if requested_task_id:\n        existing_task = shared_task_repository().get(task_id)\n        if existing_task is not None:\n            if existing_task.project_id == project_id and existing_task.kind is TaskKind.TRAINING:\n                return JSONResponse(status_code=202, content={"ok": True, "task": _public_task(existing_task), "idempotent": True})\n            raise HTTPException(status_code=409, detail="训练任务 ID 已被占用")'''
section = section.replace(old_task, new_task, 1)
app = app[:start] + section + app[end:]
write('app.py', app)

multipart_code = r'''
class V19MultipartUploadReq(BaseModel):
    file_name: str
    file_size: int = Field(gt=0)
    fingerprint: str = ""
    part_size: int = 8 * 1024 * 1024


def _v19_multipart_repository(project_id: str) -> ZipMultipartRepository:
    return ZipMultipartRepository(project_dir(project_id))


@app.post("/api/v19/projects/{project_id}/datasets/{dataset_id}/import/uploads")
def v19_create_multipart_upload(project_id: str, dataset_id: str, payload: V19MultipartUploadReq):
    get_project(project_id)
    filename = safe_filename(payload.file_name or "dataset.zip")
    if Path(filename).suffix.lower() != ".zip":
        raise HTTPException(status_code=400, detail="文件类型不支持：请上传 .zip 压缩包。")
    repository = _v19_multipart_repository(project_id)
    try:
        session = repository.create_or_resume(
            dataset_id=dataset_id, file_name=filename, file_size=int(payload.file_size),
            fingerprint=str(payload.fingerprint or ""), part_size=int(payload.part_size or 0),
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    job_id = str(session["upload_id"])
    current = read_json(v19_job_file(project_id, job_id), {})
    if not isinstance(current, dict) or not current:
        current = {
            "id": job_id, "project_id": project_id, "dataset_id": dataset_id,
            "batch_id": job_id, "file_name": filename,
            "file_size_mb": round(int(payload.file_size) / 1024 / 1024, 2),
            "uploaded_bytes": int(session.get("received_bytes") or 0),
            "upload_progress": float(session.get("upload_progress") or 0),
            "status": "uploading", "stage": "正在上传 ZIP", "progress": 0,
            "message": "分片上传已创建，可断点续传",
            "upload_session_id": job_id, "total_parts": int(session.get("total_parts") or 0),
            "created_at": now_iso(), "updated_at": now_iso(),
        }
    else:
        current.update({
            "status": "uploading", "stage": "正在上传 ZIP",
            "uploaded_bytes": int(session.get("received_bytes") or 0),
            "upload_progress": float(session.get("upload_progress") or 0),
            "message": f"继续上传：已完成 {len(session.get('completed_parts') or [])}/{int(session.get('total_parts') or 0)} 个分片",
            "updated_at": now_iso(),
        })
    v19_write_job(project_id, current)
    return {"ok": True, **session, "job": v19_public_job(project_id, current, image_limit=0)}


@app.put("/api/v19/projects/{project_id}/import/uploads/{upload_id}/parts/{part_number}")
async def v19_upload_multipart_part(project_id: str, upload_id: str, part_number: int, request: Request):
    get_project(project_id)
    repository = _v19_multipart_repository(project_id)
    try:
        payload = await request.body()
        result = repository.write_part(upload_id, part_number, BytesIO(payload))
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="ZIP 上传会话不存在") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    job = read_json(v19_job_file(project_id, upload_id), {})
    if isinstance(job, dict) and job:
        completed = len(result.get("completed_parts") or [])
        total_parts = int(result.get("total_parts") or 0)
        job.update({
            "status": "uploading", "stage": "正在上传 ZIP",
            "uploaded_bytes": int(result.get("received_bytes") or 0),
            "upload_progress": float(result.get("upload_progress") or 0),
            "message": f"已完成 {completed}/{total_parts} 个分片",
            "updated_at": now_iso(),
        })
        v19_write_job(project_id, job)
    return {"ok": True, **result}


@app.post("/api/v19/projects/{project_id}/import/uploads/{upload_id}/complete")
def v19_complete_multipart_upload(project_id: str, upload_id: str):
    get_project(project_id)
    repository = _v19_multipart_repository(project_id)
    try:
        session = repository.get(upload_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="ZIP 上传会话不存在") from error
    job = read_json(v19_job_file(project_id, upload_id), {})
    if not isinstance(job, dict) or not job:
        raise HTTPException(status_code=404, detail="ZIP 导入任务不存在")
    jd = v19_job_dir(project_id, upload_id)
    jd.mkdir(parents=True, exist_ok=True)
    zip_path = jd / "source.zip"
    try:
        v19_update_job(project_id, upload_id, status="merging", stage="正在合并 ZIP 分片", progress=0,
                       upload_progress=100, message="文件上传完成，正在服务器合并分片")
        if not (str(session.get("status") or "") == "completed" and zip_path.is_file()):
            repository.assemble(upload_id, zip_path)
        v19_update_job(project_id, upload_id, status="validating", stage="正在校验 ZIP", progress=0,
                       upload_progress=100, uploaded_bytes=zip_path.stat().st_size,
                       message="分片合并完成，正在检查 ZIP 目录结构")
        scan_started = time.time()
        scan = v19_scan_zip(zip_path)
        scan_seconds = round(max(0.0, time.time() - scan_started), 2)
        if scan.get("image_count", 0) == 0:
            raise ValueError("ZIP 内容不匹配：压缩包内没有识别到支持的图片文件。")
        scan_images = list(scan.pop("images", []) or [])
        v19_write_scan_images(project_id, upload_id, scan_images)
        finished = {
            **job, **scan,
            "id": upload_id, "project_id": project_id,
            "dataset_id": job.get("dataset_id") or session.get("dataset_id") or "default",
            "batch_id": upload_id, "file_name": job.get("file_name") or session.get("file_name") or "dataset.zip",
            "file_size_mb": round(zip_path.stat().st_size / 1024 / 1024, 2),
            "uploaded_bytes": zip_path.stat().st_size, "upload_progress": 100,
            "scan_seconds": scan_seconds, "status": "selecting", "stage": "上传与校验完成", "progress": 0,
            "message": "上传与 ZIP 校验完成，等待开始后台导入",
            "scan_images_ref": "scan-images.json", "uploaded_at": now_iso(), "updated_at": now_iso(),
        }
        v19_write_job(project_id, finished)
        return v19_public_job(project_id, finished, image_limit=500)
    except zipfile.BadZipFile as error:
        v19_update_job(project_id, upload_id, status="failed", stage="ZIP 校验失败", progress=0,
                       upload_progress=100, error="压缩包已损坏、格式不正确或不是有效 ZIP。",
                       message="ZIP 校验失败", finished_at=now_iso())
        raise HTTPException(status_code=400, detail="ZIP 校验失败：压缩包已损坏、格式不正确或不是有效 ZIP。") from error
    except Exception as error:
        v19_update_job(project_id, upload_id, status="failed", stage="ZIP 处理失败", progress=0,
                       upload_progress=100, error=str(error), message=str(error), finished_at=now_iso())
        raise HTTPException(status_code=400, detail=f"ZIP 处理失败：{error}") from error


'''
marker = '@app.post("/api/v19/projects/{project_id}/datasets/{dataset_id}/import/jobs")\n'
app = read('app.py')
if app.count(marker) != 1:
    raise RuntimeError(f'v19 create route marker count {app.count(marker)}')
write('app.py', app.replace(marker, multipart_code + marker, 1))

replace_count('app.py', 'file.read(1024 * 1024)', 'file.read(8 * 1024 * 1024)', 1)
replace_count('app.py', "shutil.copyfileobj(src, out, length=1024*1024)", "shutil.copyfileobj(src, out, length=8*1024*1024)", 1)
replace_count(
    'app.py',
    "if progress_cb and (idx==1 or idx==total or idx%20==0):\n                progress_cb(idx,total,f'正在解压 {idx}/{total} 个文件')",
    "if progress_cb:\n                progress_cb(idx,total,f'正在解压 {idx}/{total} 个文件')",
    1,
)
replace_count(
    'app.py',
    "if progress_cb and (progress_done==1 or progress_done==total_expected or progress_done%20==0): progress_cb(progress_done,total_expected,",
    "if progress_cb: progress_cb(progress_done,total_expected,",
    3,
)
replace_once(
    'app.py',
    '''                def extract_progress(done,total,msg):\n                    frac=done/max(1,total); prog=8+frac*24\n                    elapsed=max(0.01,time.time()-processing_started)\n                    eta=max(0.0,elapsed/max(0.01,prog)*max(0.0,100-prog))\n                    v19_update_job(project_id, job_id, stage="正在解压数据集", progress=round(prog,1), processed=done, total_files=total, message=msg, processing_seconds=round(elapsed,1), eta_seconds=round(eta,1))\n''',
    '''                last_extract_emit = 0.0\n                def extract_progress(done,total,msg):\n                    nonlocal last_extract_emit\n                    tick = time.monotonic()\n                    if done != total and tick - last_extract_emit < 0.6:\n                        return\n                    last_extract_emit = tick\n                    frac=done/max(1,total); prog=8+frac*24\n                    elapsed=max(0.01,time.time()-processing_started)\n                    eta=max(0.0,elapsed/max(0.01,prog)*max(0.0,100-prog))\n                    v19_update_job(project_id, job_id, stage="正在解压数据集", progress=round(prog,1), processed=done, total_files=total, message=msg, processing_seconds=round(elapsed,1), eta_seconds=round(eta,1))\n''',
)
replace_once(
    'app.py',
    '''                def import_progress(done,total,msg):\n                    frac=done/max(1,total); prog=45+frac*50\n                    elapsed=max(0.01,time.time()-processing_started)\n                    eta=max(0.0,elapsed/max(0.01,prog)*max(0.0,100-prog))\n                    v19_update_job(project_id, job_id, stage=msg, progress=round(prog,1), processed=done, total_selected=total, message=msg, processing_seconds=round(elapsed,1), eta_seconds=round(eta,1))\n''',
    '''                last_import_emit = 0.0\n                def import_progress(done,total,msg):\n                    nonlocal last_import_emit\n                    tick = time.monotonic()\n                    if done != total and tick - last_import_emit < 0.6:\n                        return\n                    last_import_emit = tick\n                    frac=done/max(1,total); prog=45+frac*50\n                    elapsed=max(0.01,time.time()-processing_started)\n                    eta=max(0.0,elapsed/max(0.01,prog)*max(0.0,100-prog))\n                    v19_update_job(project_id, job_id, stage=msg, progress=round(prog,1), processed=done, total_selected=total, message=msg, processing_seconds=round(elapsed,1), eta_seconds=round(eta,1))\n''',
)

# Durable label conversion/indexing: smaller committed batches and explicit stages.
path = 'platform_core/storage/import_tasks.py'
text = read(path)
if 'INDEX_BATCH_SIZE = 50' not in text:
    match = re.search(r'(?m)^BATCH_SIZE\s*=\s*(\d+)\s*$', text)
    if not match:
        raise RuntimeError('BATCH_SIZE marker not found')
    text = text[:match.end()] + '\nINDEX_BATCH_SIZE = 50' + text[match.end():]
old = '            batch = store.pending_index_batch(BATCH_SIZE)\n            if not batch:\n                break\n'
new = '''            batch = store.pending_index_batch(INDEX_BATCH_SIZE)\n            if not batch:\n                break\n            batch_start = indexed_at_least + 1\n            batch_end = min(selected_count, indexed_at_least + len(batch))\n            context.repository.heartbeat(\n                context.task.task_id, context.lease.lease_token,\n                progress=(50.0 if selected_count <= 0 else min(98.0, 50.0 + 49.0 * indexed_at_least / selected_count)),\n                stage="mapping_labels",\n                current_item=f"正在转换标签：{batch_start} - {batch_end} / {selected_count}",\n            )\n'''
if text.count(old) != 1:
    raise RuntimeError(f'pending index batch marker count {text.count(old)}')
text = text.replace(old, new, 1)
old = '            materials.upsert_many(records)\n            if context.cancel_requested():\n                return TaskStatus.CANCELLED, None\n            annotations.upsert_many(annotation_rows)\n'
new = '''            materials.upsert_many(records)\n            context.repository.heartbeat(\n                context.task.task_id, context.lease.lease_token,\n                progress=(50.0 if selected_count <= 0 else min(98.5, 50.0 + 49.0 * (indexed_at_least + len(batch) * 0.55) / selected_count)),\n                stage="writing_annotations",\n                current_item=f"正在写入标签与标注：{batch_start} - {batch_end} / {selected_count}",\n            )\n            if context.cancel_requested():\n                return TaskStatus.CANCELLED, None\n            annotations.upsert_many(annotation_rows)\n'''
if text.count(old) != 1:
    raise RuntimeError(f'material upsert marker count {text.count(old)}')
text = text.replace(old, new, 1)
write(path, text)

# User-facing storage-import progress + global task list bridge.
replace_once(
    'static/modules/storage-import-progress.js',
    "const POLL_DELAY = 1200;\n",
    "const POLL_DELAY = 800;\nconst STAGE_LABELS = {MAPPING_LABELS:'正在转换标签', WRITING_ANNOTATIONS:'正在写入标注', INDEXING:'正在建立素材索引', FINALIZING:'正在整理结果', SCANNING:'正在扫描素材'};\n",
)
replace_once(
    'static/modules/storage-import-progress.js',
    "  const stage = (canonicalTaskPhase(task) || status || 'SCANNING').toUpperCase();\n",
    "  const stage = (canonicalTaskPhase(task) || status || 'SCANNING').toUpperCase();\n  const stageLabel = STAGE_LABELS[stage] || stage;\n",
)
replace_once(
    'static/modules/storage-import-progress.js',
    "  const parts = [stage];\n",
    "  const parts = [stageLabel];\n",
)
replace_once(
    'static/modules/storage-import-progress.js',
    '''  function render(task) {\n    currentTask = task || currentTask;\n    if (!currentTask) return;\n    const status = statusElement();\n    if (status) status.textContent = storageImportProgressText(currentTask);\n    if (typeof window.renderStorageImportTask61 === 'function') {\n      window.renderStorageImportTask61(currentTask);\n    }\n  }\n''',
    '''  function render(task) {\n    currentTask = task || currentTask;\n    if (!currentTask) return;\n    const status = statusElement();\n    if (status) status.textContent = storageImportProgressText(currentTask);\n    const s = state();\n    const taskId = String(currentTask.task_id || currentTask.id || trackedTaskId || '');\n    const projectId = String(s.project?.id || '');\n    const phase = (canonicalTaskPhase(currentTask) || '').toUpperCase();\n    const progress = taskProgress(currentTask).percent || 0;\n    if (taskId && projectId) {\n      window.UploadTaskCenterRuntime?.upsert?.({\n        id: `storage-import:${taskId}`, kind: 'storage-import',\n        title: ['MAPPING_LABELS','WRITING_ANNOTATIONS','INDEXING'].includes(phase) ? '标签转换 / 素材索引' : '素材导入',\n        status: canonicalTaskStatus(currentTask), progress, stage: STAGE_LABELS[phase] || phase || '素材导入',\n        detail: String(currentTask.current_item || currentTask.error || ''),\n        serverUrl: `/api/v62/projects/${encodeURIComponent(projectId)}/tasks/${encodeURIComponent(taskId)}`,\n      });\n    }\n    if (typeof window.renderStorageImportTask61 === 'function') {\n      window.renderStorageImportTask61(currentTask);\n    }\n  }\n''',
)

# Global task center installation before upload bootstraps execute.
replace_once(
    'static/main.mjs',
    "import {installStorageImportProgressRuntime, storageImportProgressText} from './modules/storage-import-progress.js?v=422520';\n",
    "import {installStorageImportProgressRuntime, storageImportProgressText} from './modules/storage-import-progress.js?v=422520';\nimport {installUploadTaskCenter} from './modules/upload-task-center.js?v=66001';\n",
)
replace_once(
    'static/main.mjs',
    "window.installServerMaterialImport61?.();\nconst storageImportProgressRuntime = installStorageImportProgressRuntime({pollRegistry, getState: () => state});\n",
    "window.installServerMaterialImport61?.();\nconst uploadTaskCenterRuntime = installUploadTaskCenter({getState: () => state, projectId: () => state.project?.id, notify});\nwindow.PlatformCore.runtime.uploadTaskCenterRuntime = uploadTaskCenterRuntime;\nconst storageImportProgressRuntime = installStorageImportProgressRuntime({pollRegistry, getState: () => state});\n",
)

# ZIP runtime: queue semantics, resumable multipart upload, and task-center bridge.
replace_once(
    'static/modules/zip-import-runtime.js',
    "export const ACTIVE_ZIP_STATUSES = new Set(['selecting','queued','waiting','running']);\n",
    "export const ACTIVE_ZIP_STATUSES = new Set(['uploading','merging','validating','selecting','queued','waiting','running']);\nexport const IMPORT_QUEUE_ZIP_STATUSES = new Set(['selecting','queued','waiting','running']);\n",
)
replace_once(
    'static/modules/zip-import-runtime.js',
    "export function zipQueueInfo(job,jobs) {\n  const active=activeZipJobs(jobs), index=active.findIndex(x=>String(x?.id||'')===String(job?.id||''));\n",
    "export function zipQueueInfo(job,jobs) {\n  const active=orderZipJobs(jobs).filter(row=>IMPORT_QUEUE_ZIP_STATUSES.has(status(row))), index=active.findIndex(x=>String(x?.id||'')===String(job?.id||''));\n",
)
replace_once(
    'static/modules/zip-import-runtime.js',
    "  if(s==='selecting'&&q.waits)",
    "  if(s==='uploading') return {status:s,progress:Number(job?.upload_progress||0),stage:'正在上传 ZIP',message:job?.message||'正在分片上传，可断点续传。',queue:q};\n  if(s==='merging') return {status:s,progress:100,stage:'正在合并 ZIP 分片',message:job?.message||'文件已上传，服务器正在合并分片。',queue:q};\n  if(s==='validating') return {status:s,progress:100,stage:'正在校验 ZIP',message:job?.message||'服务器正在校验压缩包目录结构。',queue:q};\n  if(s==='selecting'&&q.waits)",
)

zip = read('static/modules/zip-import-runtime.js')
insert_marker = '\nexport function installZipImportRuntime('
if zip.count(insert_marker) != 1:
    raise RuntimeError('zip install marker not unique')
multipart_js = r'''

export function zipPartPlan(fileSize, partSize, completedParts = []) {
  const size=Math.max(0,Number(fileSize)||0),part=Math.max(1,Number(partSize)||1),done=new Set((completedParts||[]).map(Number)),rows=[];
  for(let index=0,start=0;start<size;index+=1,start+=part){const end=Math.min(size,start+part);rows.push({index,start,end,size:end-start,completed:done.has(index)})}
  return rows;
}

async function createZipUploadSession(projectId,file,{fetchImpl=globalThis.fetch}={}) {
  const fingerprint=`${file.name}:${file.size}:${Number(file.lastModified||0)}`;
  return json(await fetchImpl(`/api/v19/projects/${encodeURIComponent(String(projectId))}/datasets/default/import/uploads`,{
    method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({file_name:file.name,file_size:file.size,fingerprint,part_size:8*1024*1024}),
  }));
}

function uploadZipPartXHR(projectId,uploadId,part,file,{onTransfer=()=>{},xhrFactory=()=>new XMLHttpRequest()}={}) {
  return new Promise((resolve,reject)=>{
    const xhr=xhrFactory();
    xhr.open('PUT',`/api/v19/projects/${encodeURIComponent(String(projectId))}/import/uploads/${encodeURIComponent(String(uploadId))}/parts/${part.index}`,true);
    xhr.setRequestHeader?.('Content-Type','application/octet-stream');
    xhr.upload.onprogress=e=>{if(e.lengthComputable)onTransfer({loaded:e.loaded,total:e.total,ratio:e.total?e.loaded/e.total:0})};
    xhr.onerror=()=>reject(new Error(`ZIP 分片 ${part.index+1} 网络连接中断`));
    xhr.onabort=()=>reject(new Error(`ZIP 分片 ${part.index+1} 已取消`));
    xhr.onload=()=>{let body={};try{body=JSON.parse(xhr.responseText||'{}')}catch(_){};if(xhr.status<200||xhr.status>=300)return reject(new Error(String(body?.detail||xhr.responseText||`HTTP ${xhr.status}`)));resolve(body)};
    xhr.send(file.slice(part.start,part.end));
  });
}

export async function uploadZipMultipartJob(projectId,file,{onTransfer=()=>{},onSession=()=>{},onPhase=()=>{},fetchImpl=globalThis.fetch,xhrFactory=()=>new XMLHttpRequest(),concurrency=4,retries=2}={}) {
  const session=await createZipUploadSession(projectId,file,{fetchImpl});
  const uploadId=String(session.upload_id||'');
  if(!uploadId)throw new Error('服务器未返回 ZIP 上传会话 ID');
  onSession(session);
  const plan=zipPartPlan(file.size,session.part_size,session.completed_parts);
  const pending=plan.filter(part=>!part.completed),inflight=new Map();
  let committed=plan.filter(part=>part.completed).reduce((sum,part)=>sum+part.size,0),cursor=0;
  const emit=()=>{const loaded=Math.min(file.size,committed+[...inflight.values()].reduce((sum,value)=>sum+value,0));onTransfer({loaded,total:file.size,ratio:file.size?loaded/file.size:0,completedParts:plan.length-pending.length+Math.min(cursor,pending.length),totalParts:plan.length})};
  emit();
  async function uploadOne(part){
    let attempt=0;
    while(true){
      try{
        const result=await uploadZipPartXHR(projectId,uploadId,part,file,{xhrFactory,onTransfer:p=>{inflight.set(part.index,Math.min(part.size,Number(p.loaded)||0));emit()}});
        inflight.delete(part.index);committed+=part.size;emit();return result;
      }catch(error){
        inflight.delete(part.index);emit();
        if(attempt>=retries)throw error;
        attempt+=1;await new Promise(resolve=>setTimeout(resolve,300*Math.pow(2,attempt-1)));
      }
    }
  }
  async function worker(){while(true){const index=cursor++;if(index>=pending.length)return;await uploadOne(pending[index])}}
  await Promise.all(Array.from({length:Math.max(1,Math.min(Number(concurrency)||1,4,pending.length||1))},()=>worker()));
  onPhase({stage:'正在合并与校验 ZIP',message:'所有分片上传完成，服务器正在合并并校验压缩包'});
  return json(await fetchImpl(`/api/v19/projects/${encodeURIComponent(String(projectId))}/import/uploads/${encodeURIComponent(uploadId)}/complete`,{method:'POST',credentials:'same-origin'}));
}
'''
zip = zip.replace(insert_marker, multipart_js + insert_marker, 1)
write('static/modules/zip-import-runtime.js', zip)
replace_once(
    'static/modules/zip-import-runtime.js',
    "  async function maybeStart(project){const active=activeZipJobs(jobs),next=active[0];if(!next||status(next)!=='selecting')return;",
    "  async function maybeStart(project){const next=orderZipJobs(jobs).find(row=>status(row)==='selecting'&&zipQueueInfo(row,jobs).canStart);if(!next)return;",
)
replace_once(
    'static/modules/zip-import-runtime.js',
    "  function render(){\n    const d=dock(),active=activeZipJobs(jobs);\n",
    "  function render(){\n    const d=dock(),active=activeZipJobs(jobs);\n    if(window.UploadTaskCenterRuntime)d.classList.add('hidden');\n",
)
replace_once(
    'static/modules/zip-import-runtime.js',
    "    if(uploading){d.classList.remove('hidden');",
    "    if(uploading){if(!window.UploadTaskCenterRuntime)d.classList.remove('hidden');",
)
replace_once(
    'static/modules/zip-import-runtime.js',
    "    if(!active.length)d.classList.add('hidden');else{const v=zipView(current,jobs);d.classList.remove('hidden');",
    "    if(!active.length)d.classList.add('hidden');else{const v=zipView(current,jobs);if(!window.UploadTaskCenterRuntime)d.classList.remove('hidden');",
)
replace_once(
    'static/modules/zip-import-runtime.js',
    "      let server=await listZipJobs(project,{fetchImpl});jobs=mergeJobs(server);await maybeStart(project);",
    "      let server=await listZipJobs(project,{fetchImpl});jobs=mergeJobs(server);for(const job of jobs){const v=zipView(job,jobs);window.UploadTaskCenterRuntime?.upsert?.({id:`zip:${job.id}`,kind:'zip',title:job.file_name||'ZIP 数据导入',status:String(job.status||'').toUpperCase(),progress:v.progress,stage:v.stage,detail:v.message,serverUrl:`/api/v19/projects/${encodeURIComponent(project)}/import/jobs/${encodeURIComponent(String(job.id))}`})}await maybeStart(project);",
)
replace_once(
    'static/modules/zip-import-runtime.js',
    "      const response=await uploadZipJob(project,file,{onTransfer:e=>{uploading={progress:Math.round(e.ratio*100),message:`${bytes(e.loaded)} / ${bytes(e.total)}`};render()}});uploading=null;",
    "      const response=await uploadZipMultipartJob(project,file,{fetchImpl,onSession:session=>{window.UploadTaskCenterRuntime?.upsert?.({id:`zip:${session.upload_id}`,kind:'zip',title:file.name,status:'UPLOADING',progress:Number(session.upload_progress||0),stage:'正在上传 ZIP',detail:`已完成 ${(session.completed_parts||[]).length}/${session.total_parts||0} 个分片`,serverUrl:`/api/v19/projects/${encodeURIComponent(project)}/import/jobs/${encodeURIComponent(String(session.upload_id))}`})},onTransfer:e=>{uploading={progress:Math.round(e.ratio*1000)/10,message:`${bytes(e.loaded)} / ${bytes(e.total)}`};window.UploadTaskCenterRuntime?.upsert?.({id:`zip:${String((knownJobs.size&&[...knownJobs.keys()][0])||'')}`,kind:'zip',title:file.name,status:'UPLOADING',progress:uploading.progress,stage:'正在上传 ZIP',detail:uploading.message});render()},onPhase:phase=>{uploading={progress:100,message:phase.message};render()}});uploading=null;",
)
# The transfer callback needs a stable session id rather than a guessed known job.
zip = read('static/modules/zip-import-runtime.js')
old = "    uploading={progress:0,message:'准备上传'};window.closeModal?.();open();render();\n    try{\n      const response=await uploadZipMultipartJob(project,file,{fetchImpl,onSession:session=>{window.UploadTaskCenterRuntime?.upsert?.({id:`zip:${session.upload_id}`"
new = "    let multipartTaskId='';uploading={progress:0,message:'准备上传'};window.closeModal?.();open();render();\n    try{\n      const response=await uploadZipMultipartJob(project,file,{fetchImpl,onSession:session=>{multipartTaskId=String(session.upload_id||'');window.UploadTaskCenterRuntime?.upsert?.({id:`zip:${session.upload_id}`"
if zip.count(old) != 1:
    raise RuntimeError('multipart task id insertion marker missing')
zip = zip.replace(old, new, 1)
zip = zip.replace("id:`zip:${String((knownJobs.size&&[...knownJobs.keys()][0])||'')}`", "id:`zip:${multipartTaskId}`", 1)
write('static/modules/zip-import-runtime.js', zip)

# Ordinary image uploads also appear in the global task list without changing their proven sequential contract.
replace_once(
    'static/modules/material-upload-runtime.js',
    "    const chunks = partitionMaterialFiles(rows, {maxFiles, maxBytes});\n    renderShell(rows.length, chunks.length);\n",
    "    const chunks = partitionMaterialFiles(rows, {maxFiles, maxBytes});\n    const uploadTaskId = `images:${Date.now()}:${Math.random().toString(16).slice(2,8)}`;\n    const chunkBytes = chunks.map(chunk => chunk.reduce((sum,file)=>sum+fileSize(file),0));\n    const totalBytes = Math.max(1, chunkBytes.reduce((sum,value)=>sum+value,0));\n    const bytesBefore = chunkBytes.map((_,index)=>chunkBytes.slice(0,index).reduce((sum,value)=>sum+value,0));\n    window.UploadTaskCenterRuntime?.upsert?.({id:uploadTaskId,kind:'browser-upload',title:`图片上传 · ${rows.length} 张`,status:'UPLOADING',progress:0,stage:'准备上传',detail:`${chunks.length} 个批次`});\n    renderShell(rows.length, chunks.length);\n",
)
replace_once(
    'static/modules/material-upload-runtime.js',
    "            const percent = Math.round((event.ratio || 0) * 100);\n            setText('up411TransferText', `当前批次传输 ${percent}% · ${formatBytes(event.loadedBytes)} / ${formatBytes(event.totalBytes)}`);\n",
    "            const percent = Math.round((event.ratio || 0) * 100);\n            const overallBytes = bytesBefore[event.chunkIndex] + chunkBytes[event.chunkIndex] * (event.ratio || 0);\n            window.UploadTaskCenterRuntime?.upsert?.({id:uploadTaskId,status:'UPLOADING',progress:overallBytes/totalBytes*100,stage:`上传第 ${event.chunkNumber}/${event.chunkCount} 批`,detail:`${formatBytes(overallBytes)} / ${formatBytes(totalBytes)}`});\n            setText('up411TransferText', `当前批次传输 ${percent}% · ${formatBytes(event.loadedBytes)} / ${formatBytes(event.totalBytes)}`);\n",
)
replace_once(
    'static/modules/material-upload-runtime.js',
    "      renderResult(aggregate, (performance.now() - started) / 1000);\n",
    "      window.UploadTaskCenterRuntime?.upsert?.({id:uploadTaskId,status:'SUCCEEDED',progress:100,stage:'上传完成',detail:`成功 ${aggregate.uploaded.length} · 失败 ${aggregate.failed.length}`});\n      renderResult(aggregate, (performance.now() - started) / 1000);\n",
)
replace_once(
    'static/modules/material-upload-runtime.js',
    "      setText('up411Text', '上传中断');\n      throw error;\n",
    "      window.UploadTaskCenterRuntime?.upsert?.({id:uploadTaskId,status:'FAILED',stage:'上传中断',detail:String(error?.message||error)});\n      setText('up411Text', '上传中断');\n      throw error;\n",
)

# Training dialog: explicit algorithm name and a stable planned task id before submit.
path = 'static/app.js'
text = read(path)
marker = "window.startAlgorithmTraining429=function(aid){const a=(state.algorithms||[]).find(x=>x.id===aid);if(!a)return toast('算法不存在');"
replacement = "window.startAlgorithmTraining429=function(aid){const a=(state.algorithms||[]).find(x=>x.id===aid);if(!a)return toast('算法不存在');const plannedTaskId='train_'+(globalThis.crypto?.randomUUID?.().replace(/-/g,'').slice(0,20)||Math.random().toString(16).slice(2,22));"
if text.count(marker) != 1:
    raise RuntimeError(f'training modal start marker count {text.count(marker)}')
text = text.replace(marker, replacement, 1)
old = '<div class="field"><label>关联算法</label><input class="input" value="${esc(a.name)}" readonly></div><div class="field"><label>任务优先级</label>'
new = '<div class="field"><label>算法名称</label><input class="input" value="${esc(a.name)}" readonly></div><div class="field"><label>本次训练任务 ID</label><input id="tr429TaskId" class="input" value="${esc(plannedTaskId)}" readonly></div><div class="field"><label>任务优先级</label>'
if text.count(old) != 1:
    raise RuntimeError(f'training identity fields marker count {text.count(old)}')
text = text.replace(old, new, 1)
write(path, text)

replace_once(
    'static/modules/training-submit.js',
    "      const externalAnalysisId = window.ExternalAlgorithmPlatformRuntime?.selectedAnalysisId?.(asset.id) || '';\n      if (externalAnalysisId) payload.external_analysis_id = externalAnalysisId;\n",
    "      const externalAnalysisId = window.ExternalAlgorithmPlatformRuntime?.selectedAnalysisId?.(asset.id) || '';\n      if (externalAnalysisId) payload.external_analysis_id = externalAnalysisId;\n      const plannedTaskId = String(document.getElementById('tr429TaskId')?.value || '').trim();\n      if (plannedTaskId) payload.task_id = plannedTaskId;\n",
)

# Focused frontend contracts added by this batch.
(ROOT / 'tests/frontend/zip-multipart-upload.test.mjs').write_text(r'''import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {zipPartPlan} from '../../static/modules/zip-import-runtime.js';

test('large ZIP is divided into deterministic resumable parts', () => {
  const parts = zipPartPlan(21, 8, [0,2]);
  assert.deepEqual(parts, [
    {index:0,start:0,end:8,size:8,completed:true},
    {index:1,start:8,end:16,size:8,completed:false},
    {index:2,start:16,end:21,size:5,completed:true},
  ]);
});

test('ZIP runtime uses multipart upload path and bounded parallelism', () => {
  const source = fs.readFileSync(new URL('../../static/modules/zip-import-runtime.js', import.meta.url), 'utf8');
  assert.match(source, /import\/uploads/);
  assert.match(source, /concurrency=4/);
  assert.match(source, /uploadZipMultipartJob\(project,file/);
  assert.match(source, /retries=2/);
});
''', encoding='utf-8')

(ROOT / 'tests/frontend/training-task-identity.test.mjs').write_text(r'''import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const appSource = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
const submitSource = fs.readFileSync(new URL('../../static/modules/training-submit.js', import.meta.url), 'utf8');

test('training modal shows algorithm name and planned task id', () => {
  assert.match(appSource, /<label>算法名称<\/label>/);
  assert.match(appSource, /id="tr429TaskId"/);
  assert.match(appSource, /plannedTaskId='train_'/);
});

test('training submit sends the planned task id through the canonical submit owner', () => {
  assert.match(submitSource, /getElementById\('tr429TaskId'\)/);
  assert.match(submitSource, /payload\.task_id = plannedTaskId/);
});
''', encoding='utf-8')

print('upload pipeline v2 patch applied')

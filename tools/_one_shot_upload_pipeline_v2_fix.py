from pathlib import Path

path = Path(__file__).resolve().parent / '_one_shot_upload_pipeline_v2.py'
text = path.read_text(encoding='utf-8')
old = '''app = read('app.py')
start = app.find('@app.post("/api/v12/projects/{project_id}/train/start")')
if start < 0:
    raise RuntimeError('v12 train endpoint not found')
end = app.find('\\n@app.', start + 10)
if end < 0:
    end = len(app)
section = app[start:end]
old_task = 'task_id = uuid.uuid4().hex[:12]'
if section.count(old_task) != 1:
    raise RuntimeError(f'v12 task id assignment expected once, got {section.count(old_task)}')
new_task = ''' + "'''requested_task_id = str(payload.task_id or \"\").strip()\\n    if requested_task_id and not re.fullmatch(r\"train_[0-9a-f]{16,32}\", requested_task_id):\\n        raise HTTPException(status_code=422, detail=\"训练任务 ID 格式不正确\")\\n    task_id = requested_task_id or uuid.uuid4().hex[:12]\\n    if requested_task_id:\\n        existing_task = shared_task_repository().get(task_id)\\n        if existing_task is not None:\\n            if existing_task.project_id == project_id and existing_task.kind is TaskKind.TRAINING:\\n                return JSONResponse(status_code=202, content={\"ok\": True, \"task\": _public_task(existing_task), \"idempotent\": True})\\n            raise HTTPException(status_code=409, detail=\"训练任务 ID 已被占用\")'''" + '''
section = section.replace(old_task, new_task, 1)
app = app[:start] + section + app[end:]
write('app.py', app)
'''
new = '''old_train_task = ''' + "'''    else:\\n        device = normalize_training_device(payload.device)\\n        resource_key = f\"training:{device}\"\\n    task_id = uuid.uuid4().hex[:12]\\n    request_payload = payload.model_dump(mode=\"json\", exclude_none=True)\\n'''" + '''
new_train_task = ''' + "'''    else:\\n        device = normalize_training_device(payload.device)\\n        resource_key = f\"training:{device}\"\\n    requested_task_id = str(payload.task_id or \"\").strip()\\n    if requested_task_id and not re.fullmatch(r\"train_[0-9a-f]{16,32}\", requested_task_id):\\n        raise HTTPException(status_code=422, detail=\"训练任务 ID 格式不正确\")\\n    task_id = requested_task_id or uuid.uuid4().hex[:12]\\n    if requested_task_id:\\n        existing_task = shared_task_repository().get(task_id)\\n        if existing_task is not None:\\n            if existing_task.project_id == project_id and existing_task.kind is TaskKind.TRAINING:\\n                return JSONResponse(status_code=202, content={\"ok\": True, \"task\": _public_task(existing_task), \"idempotent\": True})\\n            raise HTTPException(status_code=409, detail=\"训练任务 ID 已被占用\")\\n    request_payload = payload.model_dump(mode=\"json\", exclude_none=True)\\n'''" + '''
replace_once('app.py', old_train_task, new_train_task)
'''
if old not in text:
    raise SystemExit('old helper training patch block not found')
path.write_text(text.replace(old, new, 1), encoding='utf-8')
print('one-shot helper training patch scope corrected')

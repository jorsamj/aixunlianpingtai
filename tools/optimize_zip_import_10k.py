from pathlib import Path

APP = Path('app.py')
JS = Path('static/app.js')
INDEX = Path('static/index.html')
API_TEST = Path('tests/api/test_v19_import_scalability.py')
FRONT_TEST = Path('tests/frontend/zip-import-10k.test.mjs')

# ---------------- backend: split cold candidate manifest from hot runtime state ----------------
text = APP.read_text(encoding='utf-8')
old = '''def v19_job_file(project_id: str, job_id: str) -> Path:\n    return v19_job_dir(project_id, job_id) / "job.json"\n\n\ndef v19_normalize_zip_path(name: str) -> str:\n'''
new = '''def v19_job_file(project_id: str, job_id: str) -> Path:\n    return v19_job_dir(project_id, job_id) / "job.json"\n\n\ndef v19_scan_images_file(project_id: str, job_id: str) -> Path:\n    return v19_job_dir(project_id, job_id) / "scan-images.json"\n\n\ndef v19_write_scan_images(project_id: str, job_id: str, images: List[Dict[str, Any]]):\n    path = v19_scan_images_file(project_id, job_id)\n    path.parent.mkdir(parents=True, exist_ok=True)\n    write_json(path, list(images or []))\n\n\ndef v19_read_scan_images(project_id: str, job_id: str) -> List[Dict[str, Any]]:\n    path = v19_scan_images_file(project_id, job_id)\n    if path.is_file():\n        value = read_json(path, [])\n        return value if isinstance(value, list) else []\n    # Backward compatibility for historical jobs created before the manifest split.\n    legacy = read_json(v19_job_file(project_id, job_id), {})\n    value = legacy.get("images") if isinstance(legacy, dict) else []\n    return value if isinstance(value, list) else []\n\n\ndef v19_normalize_zip_path(name: str) -> str:\n'''
if text.count(old) != 1:
    raise SystemExit(f'v19 manifest helper anchor count={text.count(old)}')
text = text.replace(old, new, 1)

old = '''def v19_write_job(project_id: str, job: Dict[str, Any]):\n    job["updated_at"] = now_iso()\n    f = v19_job_file(project_id, job["id"])\n    f.parent.mkdir(parents=True, exist_ok=True)\n    write_json(f, job)\n\n\ndef v19_update_job(project_id: str, job_id: str, **kwargs):\n'''
new = '''def v19_write_job(project_id: str, job: Dict[str, Any]):\n    job["updated_at"] = now_iso()\n    f = v19_job_file(project_id, job["id"])\n    f.parent.mkdir(parents=True, exist_ok=True)\n    persisted = dict(job)\n    images = persisted.pop("images", None)\n    if isinstance(images, list):\n        v19_write_scan_images(project_id, str(job["id"]), images)\n        persisted["scan_images_ref"] = "scan-images.json"\n    write_json(f, persisted)\n\n\ndef v19_public_job(project_id: str, job: Dict[str, Any], image_limit: int = 0) -> Dict[str, Any]:\n    result = dict(job or {})\n    result.pop("images", None)\n    limit = max(0, min(500, int(image_limit or 0)))\n    if limit:\n        images = v19_read_scan_images(project_id, str(result.get("id") or ""))\n        result["images"] = images[:limit]\n        result["images_truncated"] = len(images) > limit\n    return result\n\n\ndef v19_update_job(project_id: str, job_id: str, **kwargs):\n'''
if text.count(old) != 1:
    raise SystemExit(f'v19 write anchor count={text.count(old)}')
text = text.replace(old, new, 1)

# Creation stores the 10k-scale candidate list once, then persists only compact task state.
old = '''    scan_seconds = round(max(0.0, time.time() - scan_started), 2)\n    if scan.get("image_count", 0) == 0:\n        shutil.rmtree(jd, ignore_errors=True)\n        raise HTTPException(status_code=400, detail="ZIP 内容不匹配：压缩包内没有识别到支持的图片文件。")\n    job = {\n'''
new = '''    scan_seconds = round(max(0.0, time.time() - scan_started), 2)\n    if scan.get("image_count", 0) == 0:\n        shutil.rmtree(jd, ignore_errors=True)\n        raise HTTPException(status_code=400, detail="ZIP 内容不匹配：压缩包内没有识别到支持的图片文件。")\n    scan_images = list(scan.pop("images", []) or [])\n    v19_write_scan_images(project_id, job_id, scan_images)\n    job = {\n'''
if text.count(old) != 1:
    raise SystemExit(f'v19 create scan anchor count={text.count(old)}')
text = text.replace(old, new, 1)

old = '''        "status": "selecting", "stage": "上传与校验完成", "progress": 0,\n        "message": "上传与ZIP校验完成，等待开始后台导入",\n        "created_at": now_iso(), "uploaded_at": now_iso(), "updated_at": now_iso(), **scan,\n    }\n    v19_write_job(project_id, job)\n    return job\n'''
new = '''        "status": "selecting", "stage": "上传与校验完成", "progress": 0,\n        "message": "上传与ZIP校验完成，等待开始后台导入",\n        "scan_images_ref": "scan-images.json",\n        "created_at": now_iso(), "uploaded_at": now_iso(), "updated_at": now_iso(), **scan,\n    }\n    v19_write_job(project_id, job)\n    return v19_public_job(project_id, job, image_limit=500)\n'''
if text.count(old) != 1:
    raise SystemExit(f'v19 create return anchor count={text.count(old)}')
text = text.replace(old, new, 1)

old = '''    if selected_paths:\n        allowed = {x.get("path") for x in job.get("images", [])}\n        selected_paths = [x for x in selected_paths if x in allowed]\n'''
new = '''    if selected_paths:\n        allowed = {x.get("path") for x in v19_read_scan_images(project_id, job_id)}\n        selected_paths = [x for x in selected_paths if x in allowed]\n'''
if text.count(old) != 1:
    raise SystemExit(f'v19 selected path anchor count={text.count(old)}')
text = text.replace(old, new, 1)

old = '''    th = threading.Thread(target=v19_import_worker, args=(project_id, job.get("dataset_id") or "default", job_id, selected_paths), daemon=True)\n    th.start()\n    return v19_read_job(project_id, job_id)\n'''
new = '''    th = threading.Thread(target=v19_import_worker, args=(project_id, job.get("dataset_id") or "default", job_id, selected_paths), daemon=True)\n    th.start()\n    return v19_public_job(project_id, v19_read_job(project_id, job_id))\n'''
if text.count(old) != 1:
    raise SystemExit(f'v19 start return anchor count={text.count(old)}')
text = text.replace(old, new, 1)

old = '''    for jf in d.glob("*/job.json"):\n        job = read_json(jf, {})\n        if job:\n            # 列表里最多返回前 300 个图片候选，避免巨大 JSON 卡页面；详情接口返回完整。\n            if isinstance(job.get("images"), list) and len(job["images"]) > 300:\n                job = {**job, "images": job["images"][:300], "images_truncated": True}\n            jobs.append(job)\n    jobs.sort(key=lambda x: x.get("created_at", ""), reverse=True)\n    return {"ok": True, "items": jobs}\n\n\n@app.get("/api/v19/projects/{project_id}/import/jobs/{job_id}")\ndef v19_get_import_job(project_id: str, job_id: str):\n    return v19_read_job(project_id, job_id)\n'''
new = '''    for jf in d.glob("*/job.json"):\n        job = read_json(jf, {})\n        if job:\n            # Selecting jobs keep a bounded preview for compatibility. Running/terminal polling stays O(1).\n            preview = 300 if job.get("status") == "selecting" else 0\n            jobs.append(v19_public_job(project_id, job, image_limit=preview))\n    jobs.sort(key=lambda x: x.get("created_at", ""), reverse=True)\n    return {"ok": True, "items": jobs}\n\n\n@app.get("/api/v19/projects/{project_id}/import/jobs/{job_id}")\ndef v19_get_import_job(project_id: str, job_id: str, include_images: bool = False, image_limit: int = 500):\n    job = v19_read_job(project_id, job_id)\n    return v19_public_job(project_id, job, image_limit=image_limit if include_images else 0)\n'''
if text.count(old) != 1:
    raise SystemExit(f'v19 list/detail anchor count={text.count(old)}')
text = text.replace(old, new, 1)
APP.write_text(text, encoding='utf-8')

# ---------------- frontend: final data-page ZIP owner uses v19, plus terminal scoped refresh ----------------
text = JS.read_text(encoding='utf-8')
needle = 'onclick="doImportData()"'
idx = text.rfind(needle)
if idx < 0:
    raise SystemExit('final v36 doImportData button not found')
# Ensure we are replacing the v36 final importData owner, not the historical v18 owner.
owner = text.rfind('window.importData=function(){', 0, idx)
if owner < 0 or 'showImportTabV36' not in text[owner:idx]:
    raise SystemExit('final v36 importData owner proof failed')
text = text[:idx] + 'onclick="doImportUploadV19()"' + text[idx + len(needle):]

old = '''function renderImportPicker(job){\n  const imgs=job.images||[];\n  const shown=imgs.slice(0,500);\n  const more=imgs.length>shown.length?`<div class="alert warn">当前只显示前 ${shown.length} 张，点击“解析全部”会解析压缩包内全部 ${imgs.length} 张图片。</div>`:'';\n'''
new = '''function renderImportPicker(job){\n  const imgs=job.images||[];\n  const shown=imgs.slice(0,500);\n  const total=Math.max(shown.length,Number(job.image_count||0));\n  const more=total>shown.length?`<div class="alert warn">当前只显示前 ${shown.length} 张，点击“解析全部”会解析压缩包内全部 ${total} 张图片。</div>`:'';\n'''
if text.count(old) != 1:
    raise SystemExit(f'import picker anchor count={text.count(old)}')
text = text.replace(old, new, 1)

old = '''function startImportPolling(){\n  ensureImportDock();\n  if(state.importPollTimer)return;\n  state.importPollTimer=setInterval(async()=>{\n    await loadImportJobs();\n    const hasRunning=(state.importJobs||[]).some(j=>j.status==='running');\n    if(!hasRunning && state.importPollTimer){clearInterval(state.importPollTimer);state.importPollTimer=null;}\n  },1200);\n}\n'''
new = '''function startImportPolling(seedJobId){\n  ensureImportDock();\n  if(state.importPollTimer)return;\n  const tracked=new Set((state.importJobs||[]).filter(j=>j.status==='running').map(j=>j.id));\n  if(seedJobId)tracked.add(seedJobId);\n  state.importPollTimer=setInterval(async()=>{\n    if(state.importPollBusy)return;\n    state.importPollBusy=true;\n    try{\n      await loadImportJobs();\n      const jobs=state.importJobs||[],byId=new Map(jobs.map(j=>[j.id,j]));\n      for(const id of [...tracked]){\n        const job=byId.get(id);\n        if(!job||!['done','failed'].includes(job.status))continue;\n        tracked.delete(id);\n        if(job.status==='done'){\n          window.completeZipImportReview412?.(id);\n          window.invalidateQuality411?.();\n          await window.refreshLabels414?.(false);\n          if(state.page==='数据集')await window.reloadMaterialPage61?.();\n          toast(`后台导入完成：${job.report?.imported_images||0} 张图片`);\n        }else toast(`后台导入失败：${job.error||job.message||'请查看任务记录'}`);\n      }\n      jobs.filter(j=>j.status==='running').forEach(j=>tracked.add(j.id));\n      const hasRunning=jobs.some(j=>j.status==='running');\n      if(!hasRunning&&state.importPollTimer){clearInterval(state.importPollTimer);state.importPollTimer=null;}\n    }finally{state.importPollBusy=false;}\n  },1200);\n}\n'''
if text.count(old) != 1:
    raise SystemExit(f'import polling anchor count={text.count(old)}')
text = text.replace(old, new, 1)

old = '''  if(r){toast('已缩放到后台解析，右下角可查看进度');closeModal();await loadImportJobs();startImportPolling();}\n};\n'''
new = '''  if(r){toast('已缩放到后台解析，右下角可查看进度');closeModal();await loadImportJobs();startImportPolling(job.id);}\n};\n'''
if text.count(old) != 1:
    raise SystemExit(f'import start polling seed anchor count={text.count(old)}')
text = text.replace(old, new, 1)
JS.write_text(text, encoding='utf-8')

# Cache bust classic app only; formal VERSION stays unchanged.
text = INDEX.read_text(encoding='utf-8')
old = '/static/app.js?v=42.25.94'
new = '/static/app.js?v=42.25.95'
if text.count(old) != 1:
    raise SystemExit(f'app cache anchor count={text.count(old)}')
INDEX.write_text(text.replace(old, new, 1), encoding='utf-8')

API_TEST.write_text(r'''import io
import json
import zipfile

import app as app_module


def _project(client):
    response = client.post('/api/projects', json={'name': 'zip-10k', 'description': '', 'labels': []})
    response.raise_for_status()
    return response.json()['id']


def _ten_thousand_member_zip():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_STORED) as archive:
        for index in range(10_000):
            archive.writestr(f'images/train/image_{index:05d}.jpg', b'x')
        archive.writestr('data.yaml', 'train: images/train\nnames: [object]\n')
    return buffer.getvalue()


def test_v19_10k_scan_keeps_candidate_manifest_out_of_hot_job_state(client):
    project_id = _project(client)
    response = client.post(
        f'/api/v19/projects/{project_id}/datasets/default/import/jobs',
        files={'file': ('ten-thousand.zip', _ten_thousand_member_zip(), 'application/zip')},
    )
    response.raise_for_status()
    body = response.json()
    assert body['image_count'] == 10_000
    assert len(body['images']) == 500
    assert body['images_truncated'] is True

    job_id = body['id']
    job_path = app_module.v19_job_file(project_id, job_id)
    persisted = json.loads(job_path.read_text(encoding='utf-8'))
    assert 'images' not in persisted
    assert persisted['scan_images_ref'] == 'scan-images.json'
    assert job_path.stat().st_size < 64 * 1024

    manifest = json.loads(app_module.v19_scan_images_file(project_id, job_id).read_text(encoding='utf-8'))
    assert len(manifest) == 10_000

    detail = client.get(f'/api/v19/projects/{project_id}/import/jobs/{job_id}')
    detail.raise_for_status()
    assert 'images' not in detail.json()

    preview = client.get(
        f'/api/v19/projects/{project_id}/import/jobs/{job_id}',
        params={'include_images': 'true', 'image_limit': 25},
    )
    preview.raise_for_status()
    assert len(preview.json()['images']) == 25
    assert preview.json()['images_truncated'] is True

    listing = client.get(f'/api/v19/projects/{project_id}/import/jobs')
    listing.raise_for_status()
    row = next(item for item in listing.json()['items'] if item['id'] == job_id)
    assert len(row['images']) == 300
    assert row['images_truncated'] is True

    # Hundreds of hot progress writes stay bounded because they no longer rewrite the 10k manifest.
    for index in range(500):
        app_module.v19_update_job(project_id, job_id, status='running', progress=index / 5, processed=index * 20)
    persisted = json.loads(job_path.read_text(encoding='utf-8'))
    assert 'images' not in persisted
    assert job_path.stat().st_size < 64 * 1024
    listing = client.get(f'/api/v19/projects/{project_id}/import/jobs')
    row = next(item for item in listing.json()['items'] if item['id'] == job_id)
    assert 'images' not in row
''', encoding='utf-8')

FRONT_TEST.write_text(r'''import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const app = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

function sliceBetween(startNeedle, endNeedle, from = 0) {
  const start = app.indexOf(startNeedle, from);
  assert.notEqual(start, -1, `missing ${startNeedle}`);
  const end = app.indexOf(endNeedle, start + startNeedle.length);
  assert.notEqual(end, -1, `missing ${endNeedle}`);
  return app.slice(start, end);
}

test('final v36 data import owner uses background v19 uploader, never synchronous v18 doImportData', () => {
  const start = app.lastIndexOf('window.importData=function(){');
  assert.ok(start >= 0);
  const end = app.indexOf('window.showImportTabV36=', start);
  assert.ok(end > start);
  const owner = app.slice(start, end);
  assert.match(owner, /onclick="doImportUploadV19\(\)"/);
  assert.doesNotMatch(owner, /onclick="doImportData\(\)"/);
});

test('background import polling performs one scoped terminal refresh without broad reload', () => {
  const owner = sliceBetween('function startImportPolling(seedJobId){', 'window.openImportDock=');
  assert.match(owner, /tracked=new Set/);
  assert.match(owner, /refreshLabels414\?\.\(false\)/);
  assert.match(owner, /state\.page==='数据集'/);
  assert.match(owner, /reloadMaterialPage61\?\.\(\)/);
  assert.doesNotMatch(owner, /loadRelated\(/);
  assert.doesNotMatch(owner, /reload\(/);
});

test('10k picker reports full image_count while rendering only bounded preview', () => {
  const owner = sliceBetween('function renderImportPicker(job){', 'window.toggleImportChecks=');
  assert.match(owner, /imgs\.slice\(0,500\)/);
  assert.match(owner, /Number\(job\.image_count\|\|0\)/);
  assert.match(owner, /全部 \$\{total\} 张图片/);
});
''', encoding='utf-8')

print('ZIP 10k import optimization applied')

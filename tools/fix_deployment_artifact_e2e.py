from pathlib import Path

APP = Path('static/app.js')
INDEX = Path('static/index.html')
API_TEST = Path('tests/api/test_deployment_artifact_visibility.py')
FRONTEND_TEST = Path('tests/frontend/deployment-artifact-refresh.test.mjs')
BROWSER_TEST = Path('tests/browser/deployment-artifact-visibility.spec.mjs')

source = APP.read_text(encoding='utf-8')

load_start = source.index('  async function loadDeployData(force=false){')
load_fetch = source.index('    const [rr,ss,jj,aa]=await Promise.all([', load_start)
load_prefix = source[load_start:load_fetch]
old_cached = """        if(cached){
          state.deployResources=cached.resources||[];state.deploySources=cached.sources||[];state.deployJobs=cached.jobs||[];state.deployArtifacts=cached.artifacts||[];state.deployLoaded=true;return;
        }
"""
new_cached = """        if(cached&&Date.now()-Number(cached.ts||0)<ttl){
          state.deployResources=cached.resources||[];state.deploySources=cached.sources||[];state.deployJobs=cached.jobs||[];state.deployArtifacts=cached.artifacts||[];state.deployLoaded=true;
          await refreshDeployArtifactsV39();
          return;
        }
"""
if old_cached not in load_prefix:
    raise SystemExit('deployment cache branch anchor missing')
load_prefix = load_prefix.replace(old_cached, new_cached, 1)
source = source[:load_start] + load_prefix + source[load_fetch:]

full_assign = "state.deployResources=rr?.items||[];state.deploySources=ss?.items||[];state.deployJobs=jj?.items||[];state.deployArtifacts=aa?.items||[];state.deployLoaded=true;"
full_assign_new = full_assign + "state.deployArtifactsRefreshedAt=Date.now();"
if source.count(full_assign) != 1:
    raise SystemExit(f'full deployment assignment anchor count={source.count(full_assign)}')
source = source.replace(full_assign, full_assign_new, 1)

load_owner = '  window.loadDeployData=loadDeployData;\n'
helper = """  window.loadDeployData=loadDeployData;

  async function refreshDeployArtifactsV39(){
    if(!pid())return false;
    const aa=await safe(api(`/api/v39/projects/${pid()}/deploy/artifacts`));
    if(!aa)return false;
    state.deployArtifacts=aa.items||[];
    state.deployArtifactsRefreshedAt=Date.now();
    const cacheKey=`cl_algo_deploy_cache_${pid()}`;
    try{localStorage.setItem(cacheKey,JSON.stringify({ts:Date.now(),resources:state.deployResources||[],sources:state.deploySources||[],jobs:state.deployJobs||[],artifacts:state.deployArtifacts||[]}))}catch(e){}
    return true;
  }
"""
if source.count(load_owner) != 1:
    raise SystemExit(f'loadDeployData owner anchor count={source.count(load_owner)}')
source = source.replace(load_owner, helper, 1)

poll_start = source.index('  async function pollDeployJobs(){')
poll_end = source.index('  window.renderDeployCenter=function(){', poll_start)
old_poll = source[poll_start:poll_end]
if 'refreshDeployArtifactsV39' in old_poll:
    raise SystemExit('poll already migrated')
new_poll = """  async function pollDeployJobs(){
    if(state.page!=='部署转换')return;
    const previous=new Map((state.deployJobs||[]).map(j=>[String(j.id),String(j.status||'')]));
    const r=await safe(api(`/api/v39/projects/${pid()}/deploy/jobs`));
    if(r){
      const next=r.items||[];
      const artifactChanged=next.some(j=>{
        const current=String(j.status||''),before=previous.get(String(j.id))||'';
        return ['done','blocked_by_hardware'].includes(current)&&!['done','blocked_by_hardware'].includes(before);
      });
      state.deployJobs=next;
      if(artifactChanged)await refreshDeployArtifactsV39();
      renderDeployJobsOnly();
    }
    if((state.deployJobs||[]).some(j=>['queued','running'].includes(j.status))){clearTimeout(window.__deployPollV39);window.__deployPollV39=setTimeout(pollDeployJobs,1800)}
  }
"""
source = source[:poll_start] + new_poll + source[poll_end:]

artifact_open = """  window.renderDeployArtifacts=function(){
    if(!state.deployLoaded){document.getElementById('view').innerHTML='<div class=\"loading\">正在读取部署产物...</div>';loadDeployData().then(renderDeployArtifacts);return}
"""
artifact_open_new = """  window.renderDeployArtifacts=function(){
    if(!state.deployLoaded){document.getElementById('view').innerHTML='<div class=\"loading\">正在读取部署产物...</div>';loadDeployData(true).then(renderDeployArtifacts);return}
    if(!state.deployArtifactsRefreshing&&Date.now()-Number(state.deployArtifactsRefreshedAt||0)>1000){
      state.deployArtifactsRefreshing=true;
      refreshDeployArtifactsV39().finally(()=>{state.deployArtifactsRefreshing=false;if(state.page==='部署产物')window.renderDeployArtifacts()});
    }
"""
if source.count(artifact_open) != 1:
    raise SystemExit(f'deploy artifact renderer anchor count={source.count(artifact_open)}')
source = source.replace(artifact_open, artifact_open_new, 1)

APP.write_text(source, encoding='utf-8')

index = INDEX.read_text(encoding='utf-8')
if '/static/app.js?v=42.25.93' not in index:
    raise SystemExit('expected app cache 42.25.93')
INDEX.write_text(index.replace('/static/app.js?v=42.25.93', '/static/app.js?v=42.25.94', 1), encoding='utf-8')

API_TEST.write_text(r'''import json
import uuid
from pathlib import Path

import app as platform_app


def test_completed_deployment_artifact_is_listed_downloadable_and_persistent(client, seeded_project):
    project_id, _image = seeded_project
    job_id = f"artifact-{uuid.uuid4().hex[:8]}"
    job_dir = platform_app.deploy_root(project_id) / "jobs" / job_id
    artifacts = job_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    model = artifacts / "model.onnx"
    model.write_bytes(b"real-conversion-output")
    manifest = artifacts / "manifest.json"
    manifest.write_text(json.dumps({"job_id": job_id, "outputs": [{"name": model.name}]}), encoding="utf-8")
    outputs = [
        {"name": model.name, "path": str(model), "rel": "artifacts/model.onnx", "size_mb": 0.001},
        {"name": manifest.name, "path": str(manifest), "rel": "artifacts/manifest.json", "size_mb": 0.001},
    ]
    (job_dir / "job.json").write_text(json.dumps({
        "id": job_id,
        "project_id": project_id,
        "status": "done",
        "target": "onnx",
        "source_name": "best.pt",
        "resource": {"name": "Ultralytics"},
        "params": {"precision": "fp16", "input_size": 640},
        "created_at": "2026-09-13 00:00:00",
        "finished_at": "2026-09-13 00:01:00",
        "outputs": outputs,
    }, ensure_ascii=False), encoding="utf-8")

    response = client.get(f"/api/v39/projects/{project_id}/deploy/artifacts")
    response.raise_for_status()
    items = response.json()["items"]
    item = next(row for row in items if row["job_id"] == job_id and row["name"] == "model.onnx")
    assert item["target"] == "onnx"
    assert item["source_name"] == "best.pt"
    assert item["download_url"]
    download = client.get(item["download_url"])
    assert download.status_code == 200
    assert download.content == b"real-conversion-output"

    # The listing is rebuilt from persisted job metadata + real files, so another API read
    # after in-memory state changes still returns the artifact.
    second = client.get(f"/api/v39/projects/{project_id}/deploy/artifacts")
    second.raise_for_status()
    assert any(row["job_id"] == job_id and row["name"] == "model.onnx" for row in second.json()["items"])


def test_failed_or_missing_deployment_outputs_are_not_exposed_as_artifacts(client, seeded_project):
    project_id, _image = seeded_project
    root = platform_app.deploy_root(project_id) / "jobs"

    failed_id = f"failed-{uuid.uuid4().hex[:8]}"
    failed_dir = root / failed_id
    failed_artifacts = failed_dir / "artifacts"
    failed_artifacts.mkdir(parents=True, exist_ok=True)
    fake = failed_artifacts / "fake.onnx"
    fake.write_bytes(b"must-not-be-listed")
    (failed_dir / "job.json").write_text(json.dumps({
        "id": failed_id, "status": "failed", "target": "onnx",
        "outputs": [{"name": fake.name, "path": str(fake), "rel": "artifacts/fake.onnx"}],
    }), encoding="utf-8")

    missing_id = f"missing-{uuid.uuid4().hex[:8]}"
    missing_dir = root / missing_id
    missing_dir.mkdir(parents=True, exist_ok=True)
    missing_path = missing_dir / "artifacts" / "gone.onnx"
    (missing_dir / "job.json").write_text(json.dumps({
        "id": missing_id, "status": "done", "target": "onnx",
        "outputs": [{"name": "gone.onnx", "path": str(missing_path), "rel": "artifacts/gone.onnx"}],
    }), encoding="utf-8")

    response = client.get(f"/api/v39/projects/{project_id}/deploy/artifacts")
    response.raise_for_status()
    ids = {row["job_id"] for row in response.json()["items"]}
    assert failed_id not in ids
    assert missing_id not in ids
''', encoding='utf-8')

FRONTEND_TEST.write_text(r'''import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const source=readFileSync(new URL('../../static/app.js',import.meta.url),'utf8');

function owner(startMarker,endMarker){
  const start=source.indexOf(startMarker);
  const end=source.indexOf(endMarker,start+startMarker.length);
  assert.ok(start>=0&&end>start,`missing owner ${startMarker}`);
  return source.slice(start,end);
}

test('deployment cache honors TTL and refreshes authoritative artifacts before reuse',()=>{
  const load=owner('  async function loadDeployData(force=false){','  window.loadDeployData=loadDeployData;');
  assert.match(load,/Date\.now\(\)-Number\(cached\.ts\|\|0\)<ttl/);
  assert.match(load,/await refreshDeployArtifactsV39\(\)/);
});

test('deployment polling refreshes artifacts when a conversion enters a successful terminal state',()=>{
  const poll=owner('  async function pollDeployJobs(){','  window.renderDeployCenter=function(){');
  assert.match(poll,/\['done','blocked_by_hardware'\]\.includes\(current\)/);
  assert.match(poll,/if\(artifactChanged\)await refreshDeployArtifactsV39\(\)/);
});

test('deployment artifact page revalidates server truth without manual refresh',()=>{
  const render=owner('  window.renderDeployArtifacts=function(){','  // Add deployment action to algorithm version management.');
  assert.match(render,/deployArtifactsRefreshedAt/);
  assert.match(render,/refreshDeployArtifactsV39\(\)/);
});
''', encoding='utf-8')

BROWSER_TEST.write_text(r'''import {test, expect} from '@playwright/test';


test('completed conversion becomes visible in deployment artifacts without manual refresh', async ({page, request}) => {
  const project = await (await request.post('/api/projects', {data: {
    name: `部署产物联动-${Date.now()}`,
    labels: [{code: 'fire', display_name: '明火'}]
  }})).json();

  const job = {
    id: 'deploy-artifact-job',
    source_name: 'best.pt',
    target: 'onnx',
    resource: {name: 'Ultralytics'},
    params: {precision: 'fp16', input_size: 640},
    status: 'running',
    stage: '导出 ONNX',
    progress: 42,
    created_at: '2026-09-13 00:00:00'
  };
  const artifact = {
    job_id: job.id,
    name: 'converted.onnx',
    source_name: 'best.pt',
    target: 'onnx',
    params: {precision: 'fp16', input_size: 640},
    size_mb: 1.25,
    created_at: '2026-09-13 00:01:00',
    download_url: '/download/converted.onnx'
  };

  let jobsCalls = 0;
  let artifactCalls = 0;
  await page.route(`**/api/v39/projects/${project.id}/deploy/jobs`, route => {
    jobsCalls += 1;
    route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({
      ok: true,
      items: [{...job, status: 'done', stage: '转换完成', progress: 100, finished_at: '2026-09-13 00:01:00'}]
    })});
  });
  await page.route(`**/api/v39/projects/${project.id}/deploy/artifacts`, route => {
    artifactCalls += 1;
    route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({
      ok: true,
      items: jobsCalls > 0 ? [artifact] : []
    })});
  });

  await page.addInitScript(({projectId, cachedJob}) => {
    localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({projectId, page: '工作台'}));
    localStorage.setItem(`cl_algo_deploy_cache_${projectId}`, JSON.stringify({
      ts: Date.now(), resources: [], sources: [], jobs: [cachedJob], artifacts: []
    }));
  }, {projectId: project.id, cachedJob: job});

  await page.goto('/');
  await page.evaluate(() => window.setPage('部署转换'));
  await expect.poll(() => jobsCalls, {timeout: 10_000}).toBeGreaterThan(0);
  await expect.poll(() => artifactCalls, {timeout: 10_000}).toBeGreaterThanOrEqual(2);

  await page.evaluate(() => window.setPage('部署产物'));
  await expect(page.getByText('converted.onnx', {exact: true})).toBeVisible();
  await expect(page.getByRole('link', {name: '下载'})).toHaveAttribute('href', '/download/converted.onnx');
});
''', encoding='utf-8')

print('deployment artifact E2E patch prepared')

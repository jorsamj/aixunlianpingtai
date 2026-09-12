from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'static/app.js'
INDEX = ROOT / 'static/index.html'
BROWSER = ROOT / 'tests/browser/algorithm-list-performance.spec.mjs'
UNIT = ROOT / 'tests/frontend/algorithm-version-publish-owner.test.mjs'

old = "window.saveAssign=async name=>{const m=state.assigningModel||{};await safe(api(`/api/v12/projects/${pid()}/algorithms/${$('#algoSel').value}/versions`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model_name:name,model_source:'project',version_name:$('#verName').value,remark:$('#verRemark').value,job_id:m.job_id||''})}));closeModal();await reload();toast('已发布为算法版本')};"
new = "window.saveAssign=async name=>{const m=state.assigningModel||{},aid=$('#algoSel').value;const r=await safe(api(`/api/v12/projects/${pid()}/algorithms/${aid}/versions`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model_name:name,model_source:'project',version_name:$('#verName').value,remark:$('#verRemark').value,job_id:m.job_id||''})}));if(!r?.version)return;const a=(state.algorithms||[]).find(x=>x.id===aid);if(a)a.versions=[r.version,...(a.versions||[]).filter(v=>v.id!==r.version.id)];state.pending=(state.pending||[]).filter(x=>x.name!==name&&(!r.version.model_key||x.model_key!==r.version.model_key));state.assigningModel=null;closeModal();render();toast('已发布为算法版本')};"

app = APP.read_text(encoding='utf-8')
if app.count(old) != 1:
    raise SystemExit(f'R20b expected exactly 1 live reload-backed publish owner, got {app.count(old)}')
app = app.replace(old, new, 1)
if old in app:
    raise SystemExit('R20b reload-backed publish owner survived')
if app.count(new) != 1:
    raise SystemExit(f'R20b final publish owner count={app.count(new)}')
APP.write_text(app, encoding='utf-8')

idx = INDEX.read_text(encoding='utf-8')
old_cache = '/static/app.js?v=42.25.77'
new_cache = '/static/app.js?v=42.25.78'
if idx.count(old_cache) != 1:
    raise SystemExit(f'R20b app cache anchor count={idx.count(old_cache)}')
INDEX.write_text(idx.replace(old_cache, new_cache, 1), encoding='utf-8')

b = BROWSER.read_text(encoding='utf-8')
anchor = "  await page.locator('#verName').fill('R20B-PUBLISH');\n  await page.locator('#verRemark').fill('发布行为基线');\n  await page.locator('#modalBody').getByRole('button', {name: '发布为算法版本'}).click();"
replacement = "  await page.locator('#verName').fill('R20B-PUBLISH');\n  await page.locator('#verRemark').fill('发布行为基线');\n  await expect.poll(async () => page.evaluate(() => !state.__extras412)).toBe(true);\n  const requests = [];\n  page.on('request', request => {\n    const url = new URL(request.url());\n    if (url.pathname.startsWith('/api/')) requests.push(`${request.method()} ${url.pathname}${url.search}`);\n  });\n  await page.locator('#modalBody').getByRole('button', {name: '发布为算法版本'}).click();"
if b.count(anchor) != 1:
    raise SystemExit(f'R20b browser click anchor count={b.count(anchor)}')
b = b.replace(anchor, replacement, 1)

anchor2 = "  expect(submittedBody).toMatchObject({\n    model_name: 'publish-r20b.pt',\n    model_source: 'project',\n    version_name: 'R20B-PUBLISH',\n    remark: '发布行为基线',\n    job_id: 'job-publish-r20b',\n  });\n  expect(pageErrors).toEqual([]);"
replacement2 = "  expect(submittedBody).toMatchObject({\n    model_name: 'publish-r20b.pt',\n    model_source: 'project',\n    version_name: 'R20B-PUBLISH',\n    remark: '发布行为基线',\n    job_id: 'job-publish-r20b',\n  });\n  await expect.poll(async () => page.evaluate(() => state.algorithms.find(x => x.id === 'algo-publish-r20b')?.versions?.[0]?.id || null)).toBe('version-publish-r20b');\n  await expect.poll(async () => page.evaluate(() => state.pending.some(x => x.name === 'publish-r20b.pt'))).toBe(false);\n  const publishRequest = `POST /api/v12/projects/${projectId}/algorithms/algo-publish-r20b/versions`;\n  expect(requests.filter(row => row === publishRequest)).toEqual([publishRequest]);\n  const forbiddenReloadRequests = requests.filter(row => {\n    const path = row.slice(row.indexOf(' ') + 1).split('?')[0];\n    return path === '/api/projects'\n      || path === `/api/projects/${projectId}`\n      || path.startsWith(`/api/projects/${projectId}/datasets`)\n      || path.startsWith(`/api/projects/${projectId}/images`)\n      || path.startsWith(`/api/projects/${projectId}/jobs`)\n      || path.startsWith(`/api/projects/${projectId}/models`)\n      || path.startsWith(`/api/v12/projects/${projectId}/labels`)\n      || path.startsWith(`/api/v12/projects/${projectId}/algorithms`) && path !== `/api/v12/projects/${projectId}/algorithms/algo-publish-r20b/versions`\n      || path.startsWith(`/api/v12/projects/${projectId}/publish/pending`)\n      || path.startsWith(`/api/v12/projects/${projectId}/test_models`)\n      || path === '/api/training_options'\n      || path === '/api/v16/inference_envs'\n      || path === '/api/system/recommendation'\n      || path === '/api/local_models'\n      || path.includes('/bootstrap/snapshot');\n  });\n  expect(forbiddenReloadRequests).toEqual([]);\n  expect(pageErrors).toEqual([]);"
if b.count(anchor2) != 1:
    raise SystemExit(f'R20b browser result anchor count={b.count(anchor2)}')
BROWSER.write_text(b.replace(anchor2, replacement2, 1), encoding='utf-8')

UNIT.write_text("""import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

const owner = "window.saveAssign=async name=>{const m=state.assigningModel||{},aid=$('#algoSel').value;const r=await safe(api(`/api/v12/projects/${pid()}/algorithms/${aid}/versions`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model_name:name,model_source:'project',version_name:$('#verName').value,remark:$('#verRemark').value,job_id:m.job_id||''})}));if(!r?.version)return;const a=(state.algorithms||[]).find(x=>x.id===aid);if(a)a.versions=[r.version,...(a.versions||[]).filter(v=>v.id!==r.version.id)];state.pending=(state.pending||[]).filter(x=>x.name!==name&&(!r.version.model_key||x.model_key!==r.version.model_key));state.assigningModel=null;closeModal();render();toast('已发布为算法版本')};";

test('final model publish owner uses authoritative mutation result', () => {
  assert.equal(app.includes(owner), true);
  assert.equal(app.includes("closeModal();await reload();toast('已发布为算法版本')"), false);
  assert.equal(app.includes("if(!r?.version)return"), true);
});

test('model publish updates algorithm versions and pending state locally', () => {
  assert.equal(app.includes("a.versions=[r.version,...(a.versions||[]).filter(v=>v.id!==r.version.id)]"), true);
  assert.equal(app.includes("state.pending=(state.pending||[]).filter(x=>x.name!==name&&(!r.version.model_key||x.model_key!==r.version.model_key))"), true);
  assert.equal(app.includes("state.assigningModel=null;closeModal();render();toast('已发布为算法版本')"), true);
});
""", encoding='utf-8')

if (ROOT / 'VERSION.txt').read_text(encoding='utf-8').strip() != '42.24.0':
    raise SystemExit('formal VERSION changed')
print('R20b model publish migrated from global reload to authoritative local state update')

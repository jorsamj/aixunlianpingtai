from pathlib import Path

app_path = Path('static/app.js')
index_path = Path('static/index.html')
test_path = Path('tests/frontend/model-config-save-refresh-owner.test.mjs')
diagnostic_path = Path('tests/browser/r20f-runtime-diagnostic.spec.mjs')

app = app_path.read_text(encoding='utf-8')
start_marker = "  window.saveVisionModelM4=async function(id=''){"
end_marker = "\n  window.testModelConfigV35=async function(id){"
start = app.find(start_marker)
if start < 0:
    raise SystemExit('live saveVisionModelM4 owner not found')
end = app.find(end_marker, start)
if end < 0:
    raise SystemExit('saveVisionModelM4 owner boundary not found')
owner = app[start:end]
if owner.count('await loadRelated();') != 1:
    raise SystemExit(f'expected exactly one loadRelated in live saveVisionModelM4 owner, got {owner.count("await loadRelated();")}')
if 'const saved=await api(' in owner:
    raise SystemExit('R20f product migration already applied')

owner = owner.replace('try{await api(', 'try{const saved=await api(', 1)
old_tail = ");closeModal();await loadRelated();renderModelConfigPageV35();toast('视觉模型配置已保存')"
new_tail = ");if(saved?.id){const rows=state.modelConfigs||[],i=rows.findIndex(x=>String(x.id)===String(saved.id));state.modelConfigs=i>=0?rows.map((x,n)=>n===i?saved:x):[saved,...rows]}closeModal();renderModelConfigPageV35();toast('视觉模型配置已保存')"
if old_tail not in owner:
    raise SystemExit('live saveVisionModelM4 success tail drifted')
owner = owner.replace(old_tail, new_tail, 1)
if 'loadRelated' in owner or 'loadAll' in owner:
    raise SystemExit('broad refresh remains in live saveVisionModelM4 owner')
app = app[:start] + owner + app[end:]
app_path.write_text(app, encoding='utf-8')

index = index_path.read_text(encoding='utf-8')
old_cache = '/static/app.js?v=42.25.81'
new_cache = '/static/app.js?v=42.25.82'
if old_cache not in index:
    raise SystemExit('expected app.js cache 42.25.81 not found')
index_path.write_text(index.replace(old_cache, new_cache, 1), encoding='utf-8')

test_path.write_text(r'''import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync('static/app.js', 'utf8');
const saveStartMarker = "  window.saveVisionModelM4=async function(id=''){";
const saveEndMarker = '\n  window.testModelConfigV35=async function(id){';
const saveStart = app.indexOf(saveStartMarker);
const saveEnd = app.indexOf(saveEndMarker, saveStart);
assert.ok(saveStart >= 0 && saveEnd > saveStart, 'live saveVisionModelM4 owner must remain addressable');
const owner = app.slice(saveStart, saveEnd);

test('live model config save owner uses authoritative mutation result without broad related refresh', () => {
  assert.equal((app.match(/window\.saveVisionModelM4=async function/g) || []).length, 1);
  assert.match(owner, /const saved=await api\(/);
  assert.match(owner, /if\(saved\?\.id\)/);
  assert.match(owner, /state\.modelConfigs=i>=0\?rows\.map\(\(x,n\)=>n===i\?saved:x\):\[saved,\.\.\.rows\]/);
  assert.doesNotMatch(owner, /loadRelated\s*\(/);
  assert.doesNotMatch(owner, /loadAll\s*\(/);
});

test('final runtime model config modal wires save to the M4 owner', () => {
  const finalOpen = app.lastIndexOf('window.openModelConfigModalV35=function');
  assert.ok(finalOpen >= 0);
  const nextBoundary = app.indexOf('\n  window.saveVisionModelM4=async function', finalOpen);
  assert.ok(nextBoundary > finalOpen, 'final model config modal must be paired with M4 save owner');
  const region = app.slice(finalOpen, nextBoundary);
  assert.match(region, /onclick=\"saveVisionModelM4\('\$\{id\}'\)\"/);
});

test('shadowed saveModelConfig427 is not the final modal save target', () => {
  const finalOpen = app.lastIndexOf('window.openModelConfigModalV35=function');
  const nextBoundary = app.indexOf('\n  window.saveVisionModelM4=async function', finalOpen);
  const region = app.slice(finalOpen, nextBoundary);
  assert.doesNotMatch(region, /saveModelConfig427/);
});
''', encoding='utf-8')

diagnostic_path.write_text(r'''import {test, expect} from '@playwright/test';

test('R20f runtime owner diagnostic', async ({page}) => {
  const requests = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/')) requests.push(`${request.method()} ${url.pathname}${url.search}`);
  });
  await page.route(/\/api\/v35\/model-configs(?:\?.*)?$/, async route => {
    const request = route.request();
    if (request.method() === 'GET') {
      await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({items: []})});
      return;
    }
    if (request.method() !== 'POST') return route.continue();
    const body = request.postDataJSON();
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({...body, id: 'cfg-r20f-diag', has_api_key: false, api_key_masked: ''})});
  });

  await page.goto('/');
  await expect.poll(async () => page.evaluate(() => state.uiReady === true), {timeout: 15_000}).toBe(true);
  const runtime = await page.evaluate(() => ({
    openSource: String(window.openModelConfigModalV35),
    saveSource: String(window.saveVisionModelM4),
    shadowedSource: String(window.saveModelConfig427),
    scripts: [...document.scripts].map(script => script.src).filter(Boolean),
  }));
  console.log('R20F_RUNTIME_BEFORE=' + JSON.stringify(runtime));
  expect(runtime.openSource).toContain('saveVisionModelM4');
  expect(runtime.saveSource).toContain('const saved=await api(');
  expect(runtime.saveSource).not.toContain('await loadRelated()');
  expect(runtime.scripts.some(src => src.includes('/static/app.js?v=42.25.82'))).toBe(true);

  await page.evaluate(() => {
    state.page = '模型配置';
    state.modelConfigs = [];
    state.promptTemplates = [];
    render();
    window.openModelConfigModalV35();
  });
  await page.locator('#mcName').fill('R20f Diagnostic');
  await page.locator('#mcModel').fill('r20f-diag-model');
  await page.locator('#mcUrl').fill('http://127.0.0.1:19021/detect');
  const actionStart = requests.length;
  await page.locator('#modalBody').getByRole('button', {name: /保存/}).click();
  await expect(page.locator('#modal')).toHaveClass(/hidden/);
  await page.waitForTimeout(250);
  const after = await page.evaluate(() => ({configs: state.modelConfigs, view: document.getElementById('view')?.innerText || '', toast: document.getElementById('toast')?.innerText || ''}));
  const actionRequests = requests.slice(actionStart);
  console.log('R20F_RUNTIME_AFTER=' + JSON.stringify(after));
  console.log('R20F_RUNTIME_REQUESTS=' + JSON.stringify(actionRequests));
  expect(after.configs.some(item => item.id === 'cfg-r20f-diag')).toBe(true);
  expect(after.view).toContain('R20f Diagnostic');
  expect(actionRequests.filter(row => row === 'POST /api/v35/model-configs')).toHaveLength(1);
  expect(actionRequests.filter(row => row.startsWith('GET /api/projects/'))).toEqual([]);
  expect(actionRequests.filter(row => row.startsWith('GET /api/v12/projects/'))).toEqual([]);
  expect(actionRequests.filter(row => row === 'GET /api/v35/model-configs')).toEqual([]);
});
''', encoding='utf-8')

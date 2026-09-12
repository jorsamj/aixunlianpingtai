from pathlib import Path

APP = Path('static/app.js')
INDEX = Path('static/index.html')
UNIT = Path('tests/frontend/v18-import-completion-scope.test.mjs')
BROWSER = Path('tests/browser/material-pagination-performance.spec.mjs')

app = APP.read_text(encoding='utf-8')
index = INDEX.read_text(encoding='utf-8')
browser = BROWSER.read_text(encoding='utf-8')

if app.count('window.doImportData=') != 1:
    raise SystemExit(f'expected one live doImportData owner, got {app.count("window.doImportData=")}')
if app.count('window.importData=') != 3:
    raise SystemExit(f'importData generation count changed; expected 3, got {app.count("window.importData=")}')
if "modal('导入素材 / 标注'" not in app or 'onclick="doImportData()"' not in app:
    raise SystemExit('final v36 import modal no longer calls doImportData')

start = app.index('window.doImportData=')
end = app.index('\n\nwindow.manageLabels=', start)
block = app[start:end]
old = ';await reload();toast(`导入完成：${r.imported_images||0}图，${r.boxes||0}框`);'
new = ";await window.refreshLabels414?.(false);if(state.page==='数据集')await window.reloadMaterialPage61?.();toast(`导入完成：${r.imported_images||0}图，${r.boxes||0}框`);"
if block.count(old) != 1:
    raise SystemExit('live v18 import broad reload anchor changed')
if 'refreshLabels414' in block or 'reloadMaterialPage61' in block:
    raise SystemExit('R20k scoped refresh already present unexpectedly')
block = block.replace(old, new, 1)
app = app[:start] + block + app[end:]

# Permanent unit contract: the live v18 success owner cannot broaden back to global reload.
UNIT.write_text(r"""import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync('static/app.js', 'utf8');

function liveImportBlock() {
  const start = app.indexOf('window.doImportData=');
  const end = app.indexOf('\n\nwindow.manageLabels=', start);
  assert.ok(start >= 0 && end > start, 'live doImportData block must exist');
  return app.slice(start, end);
}

test('final v36 import UI still delegates ZIP upload to live doImportData', () => {
  assert.match(app, /modal\('导入素材 \/ 标注',[\s\S]*?onclick="doImportData\(\)"/);
  assert.equal((app.match(/window\.doImportData=/g) || []).length, 1);
});

test('live v18 import completion refreshes only labels and paged materials', () => {
  const block = liveImportBlock();
  assert.match(block, /\/api\/v18\/projects\/\$\{pid\(\)\}\/datasets\/\$\{state\.datasetId\}\/import/);
  assert.match(block, /await window\.refreshLabels414\?\.\(false\)/);
  assert.match(block, /if\(state\.page==='数据集'\)await window\.reloadMaterialPage61\?\.\(\)/);
  for (const forbidden of ['await reload()', 'await loadAll()', 'await loadRelated()']) {
    assert.equal(block.includes(forbidden), false, `v18 import completion must not use ${forbidden}`);
  }
});
""", encoding='utf-8')

marker = "test('v18 import completion uses scoped labels and material refresh without broad reload'"
if marker in browser:
    raise SystemExit('R20k browser contract already present unexpectedly')

browser += r"""

test('v18 import completion uses scoped labels and material refresh without broad reload', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  const requests = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/')) requests.push(`${request.method()} ${url.pathname}${url.search}`);
  });

  await page.route('**/api/v61/projects/*/materials**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/materials/ids')) return route.fallback();
    const limit = Number(url.searchParams.get('limit') || 48);
    const body = limit === 1
      ? {items: [], total: 1, next_cursor: null}
      : {items: [material('m-import-r20k', 'imported-r20k.jpg')], total: 1, next_cursor: null};
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(body)});
  });

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await expect.poll(async () => page.evaluate(() => Boolean(state.uiReady))).toBe(true);
  await page.evaluate(() => {
    state.data412Tab = 'processed';
    state.materialQuery61 = '';
    window.setPage('数据集');
  });
  await expect(page.locator('.data426-shell')).toBeVisible({timeout: 10_000});
  await expect.poll(async () => page.evaluate(() => window.MaterialPaginationRuntime61?.state?.().refreshBusy ?? null)).toBe(false);

  const {projectId, datasetId} = await page.evaluate(() => ({
    projectId: state.project?.id,
    datasetId: state.datasetId,
  }));
  expect(projectId).toBeTruthy();
  expect(datasetId).toBeTruthy();
  const encodedProject = encodeURIComponent(projectId);
  const encodedDataset = encodeURIComponent(datasetId);

  await page.route(`**/api/v18/projects/${encodedProject}/datasets/${encodedDataset}/import`, async route => {
    expect(route.request().method()).toBe('POST');
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        detected_format: 'yolo',
        imported_images: 2,
        annotated_images: 1,
        boxes: 3,
        warnings: [],
      }),
    });
  });
  await page.route(`**/api/v12/projects/${encodedProject}/labels`, async route => {
    if (route.request().method() !== 'GET') return route.continue();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({items: [{class_id: 0, code: 'smoke', display_name: '烟雾', color: '#ef4444'}]}),
    });
  });

  await page.evaluate(() => window.importData());
  await expect(page.locator('#modal')).not.toHaveClass(/hidden/);
  await expect(page.locator('#modalTitle')).toContainText('导入素材 / 标注');
  await page.locator('#importFile').setInputFiles({
    name: 'r20k-yolo.zip',
    mimeType: 'application/zip',
    buffer: Buffer.from('PK-r20k-test'),
  });

  requests.length = 0;
  await page.locator('#zipImportPane').getByRole('button', {name: '开始导入'}).click();
  await expect(page.locator('#importProgressText')).toHaveText('导入完成', {timeout: 10_000});
  await expect(page.locator('#importResult')).toContainText('2');
  await expect(page.locator('#toast')).toContainText('导入完成：2图，3框');
  await expect.poll(async () => page.evaluate(() => window.MaterialPaginationRuntime61?.state?.().refreshBusy ?? null)).toBe(false);

  const importRequest = `POST /api/v18/projects/${projectId}/datasets/${datasetId}/import`;
  const labelsRequest = `GET /api/v12/projects/${projectId}/labels`;
  expect(requests.filter(row => row === importRequest)).toEqual([importRequest]);
  expect(requests.filter(row => row === labelsRequest)).toEqual([labelsRequest]);
  expect(requests.some(row => row.startsWith(`GET /api/v61/projects/${projectId}/materials?`))).toBe(true);

  const forbiddenBroadRefresh = requests.filter(row => {
    const [method, rawPath] = row.split(' ', 2);
    if (method !== 'GET') return false;
    const path = rawPath.split('?')[0];
    return path === '/api/projects'
      || path === `/api/projects/${projectId}`
      || path.startsWith(`/api/projects/${projectId}/datasets`)
      || path.startsWith(`/api/projects/${projectId}/images`)
      || path.startsWith(`/api/projects/${projectId}/jobs`)
      || path.startsWith(`/api/v12/projects/${projectId}/algorithms`)
      || path.startsWith(`/api/v12/projects/${projectId}/publish/pending`)
      || path.startsWith(`/api/v12/projects/${projectId}/test_models`)
      || path === '/api/training_options'
      || path === '/api/v16/inference_envs'
      || path === '/api/system/recommendation'
      || path === '/api/local_models'
      || path.includes('/bootstrap/snapshot');
  });
  expect(forbiddenBroadRefresh).toEqual([]);
  expect(pageErrors).toEqual([]);
});
"""

old_cache = '/static/app.js?v=42.25.86'
new_cache = '/static/app.js?v=42.25.87'
if index.count(old_cache) != 1:
    raise SystemExit('expected app.js cache 42.25.86 exactly once')
index = index.replace(old_cache, new_cache, 1)

APP.write_text(app, encoding='utf-8')
INDEX.write_text(index, encoding='utf-8')
BROWSER.write_text(browser, encoding='utf-8')
print('R20k migrated live v18 import completion from broad reload to scoped labels/material refresh')

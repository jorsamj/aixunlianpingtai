from pathlib import Path

path = Path('tests/browser/navigation-stability.spec.mjs')
text = path.read_text(encoding='utf-8')
marker = "test('base modal post-open content refresh stays functional', async ({page}) => {"
if text.count(marker) != 1:
    raise SystemExit(f'baseline insertion marker drifted: {text.count(marker)}')
if "ZIP import completion uses scoped label and material refresh" in text:
    raise SystemExit('R20g baseline already installed')

insert = r'''
test('ZIP import completion uses scoped label and material refresh', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.route(/\/api\/v19\/projects\/[^/]+\/datasets\/default\/import\/jobs$/, async route => {
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({
      id: 'zip-r20g-scoped', image_count: 2, format_hints: ['YOLO'], upload_seconds: 0.1, scan_seconds: 0.1,
    })});
  });
  await page.route(/\/api\/v19\/projects\/[^/]+\/import\/jobs\/zip-r20g-scoped\/start$/, async route => {
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({ok: true})});
  });
  await page.route(/\/api\/v19\/projects\/[^/]+\/import\/jobs\/zip-r20g-scoped$/, async route => {
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({
      id: 'zip-r20g-scoped', status: 'done', stage: '导入完成', message: '完成', progress: 100,
      processing_seconds: 0.2, report: {imported_images: 2, annotated_images: 1, boxes: 2, warnings: []},
    })});
  });
  await page.route(/\/api\/v12\/projects\/[^/]+\/labels$/, async route => {
    if (route.request().method() !== 'GET') return route.continue();
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({items: [
      {class_id: 0, code: 'smoke', display_name: '烟雾', color: '#64748b'},
    ]})});
  });
  await page.route(/\/api\/v61\/projects\/[^/]+\/materials(?:\?.*)?$/, async route => {
    const url = new URL(route.request().url());
    const limit = Number(url.searchParams.get('limit') || 48);
    const status = url.searchParams.get('processing_status');
    const total = status === 'unprocessed' ? 0 : 2;
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({
      items: limit === 1 ? [] : [{
        id: 'zip-r20g-material', filename: 'zip-r20g.jpg',
        url: 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==',
        width: 640, height: 480, processing_status: 'processed', annotated: true,
        box_count: 1, labels: ['smoke'], annotation_preview: [], storage_type: 'local', storage_source_id: 'default_local',
      }],
      total, next_cursor: null,
    })});
  });

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await expect.poll(async () => page.evaluate(() => Boolean(state.uiReady))).toBe(true);
  await page.evaluate(() => {
    state.data412Tab = 'processed';
    state.materialQuery61 = '';
    state.materialAnnotated61 = 'all';
    state.materialSourceFilter61 = 'all';
    window.setPage('数据集');
  });
  await expect(page.locator('#title')).toContainText('数据集');
  await expect(page.locator('.data426-shell')).toBeVisible({timeout: 10_000});
  await page.waitForTimeout(1_500);

  const requests = [];
  const onRequest = request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/')) requests.push(`${request.method()} ${url.pathname}${url.search}`);
  };
  page.on('request', onRequest);
  await page.evaluate(() => {
    window.__zipReviewOpenedR20g = null;
    window.showImportReview412 = jobId => { window.__zipReviewOpenedR20g = jobId; };
  });
  await page.evaluate(async () => { await window.openDataUpload426(); });
  await page.locator('#up426Zip').setInputFiles({
    name: 'r20g.zip', mimeType: 'application/zip', buffer: Buffer.from('r20g-zip-probe'),
  });
  await expect.poll(async () => page.evaluate(() => state.import411?.stage || ''), {timeout: 10_000}).toBe('导入完成');
  await expect.poll(async () => page.evaluate(() => window.__zipReviewOpenedR20g)).toBe('zip-r20g-scoped');
  await expect(page.locator('#data412Grid')).toContainText('zip-r20g.jpg', {timeout: 10_000});
  page.off('request', onRequest);

  const owned = requests.filter(row => !row.includes('/api/v19/projects/') || !row.endsWith('/import/jobs'));
  expect(owned.some(row => row === 'GET ' + row.slice(4) && row.includes('/api/v12/projects/') && row.endsWith('/labels'))).toBe(true);
  expect(owned.some(row => row.startsWith('GET /api/v61/projects/') && row.includes('/materials'))).toBe(true);

  const forbidden = owned.filter(row => (
    row === 'GET /api/projects'
    || /^GET \/api\/projects\/[^/?]+$/.test(row)
    || /\/datasets(?:\?|$)/.test(row)
    || /\/algorithms(?:\?|$)/.test(row)
    || /\/publish\/pending(?:\?|$)/.test(row)
    || /\/test_models(?:\?|$)/.test(row)
    || row.startsWith('GET /api/training_options')
    || row.startsWith('GET /api/v16/inference_envs')
    || row.startsWith('GET /api/system/recommendation')
    || row.startsWith('GET /api/local_models')
    || row.startsWith('GET /api/v35/model-configs')
    || row.startsWith('GET /api/v35/prompt-templates')
    || row.includes('/bootstrap/snapshot')
  ));
  expect(forbidden).toEqual([]);
  expect(pageErrors).toEqual([]);
});

test('server storage import confirmation avoids broad related refresh', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));
  const requests = [];

  await page.route(/\/api\/v61\/projects\/[^/]+\/storage-imports\/storage-r20g\/confirm$/, async route => {
    requests.push(`POST ${new URL(route.request().url()).pathname}`);
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({
      task_id: 'storage-r20g', status: 'RUNNING', stage: 'IMPORTING', result: {},
    })});
  });
  await page.route(/\/api\/v61\/projects\/[^/]+\/storage-imports\/storage-r20g$/, async route => {
    requests.push(`GET ${new URL(route.request().url()).pathname}`);
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({
      task_id: 'storage-r20g', status: 'SUCCEEDED', stage: 'DONE', result: {imported: 3, indexed: 3},
    })});
  });
  await page.route(/\/api\/v12\/projects\/[^/]+\/labels$/, async route => {
    if (route.request().method() !== 'GET') return route.continue();
    requests.push(`GET ${new URL(route.request().url()).pathname}`);
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({items: [
      {class_id: 0, code: 'smoke', display_name: '烟雾', color: '#64748b'},
    ]})});
  });

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await expect.poll(async () => page.evaluate(() => Boolean(state.uiReady))).toBe(true);
  await page.evaluate(() => window.setPage('素材存储配置'));
  await expect(page.locator('#title')).toContainText('素材存储配置');
  await page.evaluate(async () => { await window.openStorageImport61(); });
  await expect(page.locator('#si61ImportShell')).toBeVisible();
  await page.evaluate(() => {
    const status = document.getElementById('si61Status');
    status.innerHTML = '<div data-import-class="smoke"><input data-label-code value="smoke"><input data-create-label type="checkbox" checked></div><button id="si61Confirm">确认建立索引</button>';
  });

  const broad = [];
  const onRequest = request => {
    const url = new URL(request.url());
    if (!url.pathname.startsWith('/api/')) return;
    const row = `${request.method()} ${url.pathname}${url.search}`;
    if (
      row === 'GET /api/projects'
      || /^GET \/api\/projects\/[^/?]+$/.test(row)
      || /\/datasets(?:\?|$)/.test(row)
      || /\/algorithms(?:\?|$)/.test(row)
      || /\/publish\/pending(?:\?|$)/.test(row)
      || /\/test_models(?:\?|$)/.test(row)
      || row.startsWith('GET /api/training_options')
      || row.startsWith('GET /api/v16/inference_envs')
      || row.startsWith('GET /api/system/recommendation')
      || row.startsWith('GET /api/local_models')
      || row.startsWith('GET /api/v35/model-configs')
      || row.startsWith('GET /api/v35/prompt-templates')
      || row.includes('/bootstrap/snapshot')
      || row.startsWith('GET /api/v61/projects/') && row.includes('/materials')
    ) broad.push(row);
  };
  page.on('request', onRequest);
  await page.evaluate(async () => { await window.confirmStorageImport61('storage-r20g'); });
  await expect(page.locator('#toast')).toContainText('素材索引已建立：3 条');
  page.off('request', onRequest);

  expect(requests.filter(row => row.includes('storage-r20g'))).toEqual([
    expect.stringMatching(/^POST \/api\/v61\/projects\/[^/]+\/storage-imports\/storage-r20g\/confirm$/),
    expect.stringMatching(/^GET \/api\/v61\/projects\/[^/]+\/storage-imports\/storage-r20g$/),
  ]);
  expect(requests.some(row => row.startsWith('GET /api/v12/projects/') && row.endsWith('/labels'))).toBe(true);
  expect(broad).toEqual([]);
  expect(pageErrors).toEqual([]);
});

'''

text = text.replace(marker, insert + marker, 1)
path.write_text(text, encoding='utf-8')
print('R20g import refresh Chrome baseline installed')

import {test, expect} from '@playwright/test';

function material(id, filename, labels = ['smoke']) {
  return {
    id,
    filename,
    url: 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==',
    size_bytes: 1024,
    width: 640,
    height: 480,
    processing_status: 'processed',
    clean_status: 'ready',
    ready: true,
    annotated: true,
    annotation_status: 'annotated',
    box_count: 1,
    labels,
    annotation_preview: [],
    storage_type: 'local',
    storage_source_id: 'default_local',
  };
}
async function mockDurableZipUpload(page, {
  jobId,
  fileName = 'browser.zip',
  report = {imported_images: 1, annotated_images: 0, boxes: 0, warnings: []},
}) {
  const uploadId = `upload-${jobId}`;
  let uploaded = false;
  let started = false;
  const selecting = {
    id: jobId,
    file_name: fileName,
    status: 'selecting',
    stage: '上传与校验完成',
    message: '等待启动后台导入',
    progress: 0,
    image_count: Number(report.imported_images || 0),
    file_count: Number(report.imported_images || 0),
    uncompressed_size_mb: 1,
    format_hints: ['YOLO'],
  };
  const running = {...selecting, status: 'running', stage: '后台导入中', progress: 65};
  const done = {...running, status: 'done', stage: '导入完成', message: '完成', progress: 100, report};

  await page.route(/\/api\/v19\/projects\/[^/]+\/datasets\/default\/import\/uploads$/, async route => {
    if (route.request().method() !== 'POST') return route.continue();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        upload_id: uploadId,
        part_size: 8 * 1024 * 1024,
        completed_parts: [],
        total_parts: 1,
        upload_progress: 0,
      }),
    });
  });
  await page.route(new RegExp(`/api/v19/projects/[^/]+/import/uploads/${uploadId}/parts/\\d+$`), async route => {
    if (route.request().method() !== 'PUT') return route.continue();
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({ok: true})});
  });
  await page.route(new RegExp(`/api/v19/projects/[^/]+/import/uploads/${uploadId}/complete$`), async route => {
    if (route.request().method() !== 'POST') return route.continue();
    uploaded = true;
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(selecting)});
  });
  await page.route(new RegExp(`/api/v19/projects/[^/]+/import/jobs/${jobId}/start$`), async route => {
    if (route.request().method() !== 'POST') return route.continue();
    started = true;
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(running)});
  });
  await page.route(new RegExp(`/api/v19/projects/[^/]+/import/jobs/${jobId}$`), async route => {
    if (route.request().method() !== 'GET') return route.continue();
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(started ? done : selecting)});
  });
  await page.route(/\/api\/v19\/projects\/[^/]+\/import\/jobs$/, async route => {
    if (route.request().method() !== 'GET') return route.continue();
    const items = !uploaded ? [] : [started ? done : selecting];
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({ok: true, items})});
  });
}


test('dataset paging, search and refresh patch cards without rebuilding the shell', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  const apiRequests = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/')) apiRequests.push(`${request.method()} ${url.pathname}${url.search}`);
  });

  await page.route('**/api/v61/projects/*/materials**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/materials/ids')) return route.fallback();

    const status = url.searchParams.get('processing_status');
    const query = url.searchParams.get('query') || '';
    const cursor = url.searchParams.get('cursor') || '';
    const annotated = url.searchParams.get('annotated');
    const limit = Number(url.searchParams.get('limit') || 48);

    let body;
    if (limit === 1 && status === 'unprocessed') {
      body = {items: [], total: 0, next_cursor: null};
    } else if (limit === 1 && status === 'processed') {
      body = {items: [], total: 96, next_cursor: null};
    } else if (limit === 1 && annotated === 'true') {
      body = {items: [], total: 96, next_cursor: null};
    } else if (limit === 1) {
      body = {items: [], total: 96, next_cursor: null};
    } else if (query === 'smoke') {
      body = {items: [material('m-search', 'smoke-filtered.jpg')], total: 1, next_cursor: null};
    } else if (cursor === 'cursor-2') {
      body = {items: [material('m-2', 'page-two.jpg')], total: 96, next_cursor: null};
    } else {
      body = {items: [material('m-1', 'page-one.jpg')], total: 96, next_cursor: 'cursor-2'};
    }

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(body),
    });
  });

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await expect.poll(async () => page.evaluate(() => window.MaterialPaginationRuntime61?.build || null))
    .toBe('material-pagination-runtime-422207');

  await page.evaluate(() => {
    state.data412Tab = 'processed';
    state.materialQuery61 = '';
    state.materialAnnotated61 = 'all';
    state.materialSourceFilter61 = 'all';
    window.setPage('数据集');
  });

  await expect(page.locator('.data426-shell')).toBeVisible({timeout: 10_000});
  await expect(page.locator('#data412Grid')).toContainText('page-one.jpg', {timeout: 10_000});
  await expect(page.locator('#data412Pager')).toContainText('1 / 2');

  await page.evaluate(() => {
    document.querySelector('.data426-shell').dataset.performanceMarker = 'preserve-me';
  });

  // Once the first server page has committed, the install-time bootstrap timer must not
  // issue another reset load that can race with a user clicking Next.
  const stableSerial = await page.evaluate(() => window.MaterialPaginationRuntime61.state().requestSerial);
  await page.waitForTimeout(320);
  expect(await page.evaluate(() => window.MaterialPaginationRuntime61.state().requestSerial)).toBe(stableSerial);

  const next = page.locator('#data412Pager button:last-child');
  await expect(next).toBeEnabled();
  const secondPageRequest = page.waitForRequest(request => {
    const url = new URL(request.url());
    return url.pathname.includes('/api/v61/projects/')
      && url.pathname.endsWith('/materials')
      && url.searchParams.get('cursor') === 'cursor-2';
  });
  await next.click();
  await secondPageRequest;
  await expect(page.locator('#data412Grid')).toContainText('page-two.jpg', {timeout: 10_000});
  await expect(page.locator('#data412Pager')).toContainText('2 / 2');
  await expect(page.locator('.data426-shell')).toHaveAttribute('data-performance-marker', 'preserve-me');

  await page.locator('#data412Q').fill('smoke');
  await expect(page.locator('#data412Grid')).toContainText('smoke-filtered.jpg', {timeout: 10_000});
  await expect(page.locator('#data412Q')).toHaveValue('smoke');
  await expect(page.locator('.data426-shell')).toHaveAttribute('data-performance-marker', 'preserve-me');

  apiRequests.length = 0;
  await page.locator('#refreshBtn').click();
  await expect.poll(async () => page.evaluate(() => window.MaterialPaginationRuntime61?.state?.().refreshBusy ?? null))
    .toBe(false);
  await expect(page.locator('#data412Grid')).toContainText('smoke-filtered.jpg');
  await expect(page.locator('#data412Q')).toHaveValue('smoke');
  await expect(page.locator('.data426-shell')).toHaveAttribute('data-performance-marker', 'preserve-me');

  const materialRequests = apiRequests.filter(row => row.includes('/api/v61/projects/') && row.includes('/materials'));
  expect(materialRequests.length).toBeGreaterThan(0);
  expect(apiRequests.some(row => row.includes('/bootstrap/snapshot'))).toBe(false);
  expect(apiRequests.some(row => row.includes('/algorithms'))).toBe(false);
  expect(apiRequests.some(row => row.includes('/datasets'))).toBe(false);
  expect(apiRequests.some(row => row.includes('/labels'))).toBe(false);
  expect(apiRequests.some(row => row.includes('/publish/pending'))).toBe(false);
  expect(apiRequests.some(row => row.includes('/test_models'))).toBe(false);
  expect(apiRequests.some(row => /\/api\/projects\/[^/]+\/images/.test(row))).toBe(false);
  expect(pageErrors).toEqual([]);
});


test('dataset return paints the cached page before a background refresh replaces it', async ({page}) => {
  const pixel = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==';
  let mainReads = 0;
  let slowReturn = false;

  await page.route('**/api/v61/projects/*/materials**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/materials/ids')) return route.fallback();
    const limit = Number(url.searchParams.get('limit') || 48);
    if (limit === 1) {
      await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({items: [], total: 1, next_cursor: null})});
      return;
    }
    mainReads += 1;
    if (slowReturn && mainReads >= 2) await new Promise(resolve => setTimeout(resolve, 650));
    const name = mainReads >= 2 ? 'fresh-after-return.jpg' : 'cached-before-return.jpg';
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: [{
          id: `cache-${mainReads}`, filename: name, url: pixel, size_bytes: 1024,
          width: 640, height: 480, processing_status: 'processed', clean_status: 'ready',
          ready: true, annotated: true, annotation_status: 'annotated', box_count: 1,
          labels: ['smoke'], annotation_preview: [], storage_type: 'local', storage_source_id: 'default_local',
        }],
        total: 1, next_cursor: null,
      }),
    });
  });

  await page.goto('/');
  await expect.poll(async () => page.evaluate(() => window.MaterialPaginationRuntime61?.build || null))
    .toBe('material-pagination-runtime-422207');
  await page.evaluate(() => {
    state.data412Tab = 'processed';
    state.materialQuery61 = '';
    state.materialAnnotated61 = 'all';
    state.materialSourceFilter61 = 'all';
    window.setPage('数据集');
  });
  await expect(page.locator('#data412Grid')).toContainText('cached-before-return.jpg', {timeout: 10_000});
  await expect.poll(async () => page.evaluate(() => window.MaterialPaginationRuntime61.state().cachedItems)).toBe(1);

  await page.evaluate(() => window.setPage('训练任务'));
  await expect(page.locator('#title')).toContainText('训练任务');
  await page.evaluate(() => {
    state.images = [{
      id: 'full-pool-placeholder',
      filename: 'full-pool-should-not-flash.jpg',
      url: 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==',
      processing_status: 'processed',
    }];
  });
  slowReturn = true;

  await page.evaluate(() => window.setPage('数据集'));
  await expect(page.locator('#title')).toContainText('数据集');
  await expect(page.locator('#data412Grid')).toContainText('cached-before-return.jpg', {timeout: 250});
  await expect(page.locator('#data412Grid')).not.toContainText('full-pool-should-not-flash.jpg');
  await expect(page.locator('#data412Grid')).toContainText('fresh-after-return.jpg', {timeout: 5_000});
  expect(mainReads).toBeGreaterThanOrEqual(2);
});


test('v19 background import completion uses scoped labels and material refresh without broad reload', async ({page}) => {
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
  const importJobId = 'zip-r20k-job';
  await mockDurableZipUpload(page, {
    jobId: importJobId,
    fileName: 'r20k-yolo.zip',
    report: {imported_images: 2, annotated_images: 1, boxes: 3, warnings: []},
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
  await expect(page.locator('#toast')).toContainText('后台导入完成：2 张图片', {timeout: 10_000});
  await expect.poll(async () => page.evaluate(() => window.MaterialPaginationRuntime61?.state?.().refreshBusy ?? null)).toBe(false);
  await expect(page.locator('#data412Grid')).toContainText('imported-r20k.jpg');

  const startRequest = `POST /api/v19/projects/${projectId}/import/jobs/${importJobId}/start`;
  const listRequest = `GET /api/v19/projects/${projectId}/import/jobs`;
  const labelsRequest = `GET /api/v12/projects/${projectId}/labels`;
  expect(requests.some(row => row === `POST /api/v19/projects/${projectId}/datasets/default/import/uploads`)).toBe(true);
  expect(requests.some(row => row.startsWith(`PUT /api/v19/projects/${projectId}/import/uploads/upload-${importJobId}/parts/`))).toBe(true);
  expect(requests.some(row => row === `POST /api/v19/projects/${projectId}/import/uploads/upload-${importJobId}/complete`)).toBe(true);
  expect(requests.filter(row => row === startRequest)).toEqual([startRequest]);
  expect(requests.filter(row => row === listRequest).length).toBeGreaterThanOrEqual(1);
  expect(requests.filter(row => row === labelsRequest)).toEqual([labelsRequest]);
  expect(requests.some(row => row.startsWith(`GET /api/v61/projects/${projectId}/materials?`))).toBe(true);
  expect(requests.some(row => row.includes('/api/v18/'))).toBe(false);

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

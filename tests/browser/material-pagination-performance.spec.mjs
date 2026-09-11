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
    .toBe('material-pagination-runtime-422204');

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

  await page.locator('#data412Pager button:last-child').click();
  await expect(page.locator('#data412Grid')).toContainText('page-two.jpg');
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

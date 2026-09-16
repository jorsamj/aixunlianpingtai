import {test, expect} from '@playwright/test';

const PIXEL = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=', 'base64');

function material(index, page = 1) {
  const id = `picker-${page}-${String(index).padStart(3, '0')}`;
  return {
    id,
    filename: `${id}.jpg`,
    labels: index % 2 ? ['person'] : ['smoke'],
    annotated: true,
    box_count: 1,
    processing_status: 'processed',
    thumbnail_url: `/thumb/${id}.png`,
    content_url: `/full/${id}.png`,
  };
}

test('training material picker opens immediately, renders larger previews, and pages 60 rows from the server', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await expect.poll(async () => page.evaluate(() => window.TrainingMaterialPickerRuntime?.build || null))
    .toBe('training-material-picker-runtime-422503');

  const projectId = await page.evaluate(() => state.project?.id);
  expect(projectId).toBeTruthy();
  const encoded = encodeURIComponent(projectId);
  const requests = [];
  const thumbnailRequests = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/')) requests.push(`${request.method()} ${url.pathname}${url.search}`);
    if (url.pathname.startsWith('/thumb/')) thumbnailRequests.push(url.pathname);
  });

  let releaseFirstPage;
  const firstPageGate = new Promise(resolve => { releaseFirstPage = resolve; });
  let firstPageHeld = true;

  await page.route('**/thumb/*.png', route => route.fulfill({status: 200, contentType: 'image/png', body: PIXEL}));
  await page.route('**/full/*.png', route => route.fulfill({status: 200, contentType: 'image/png', body: PIXEL}));
  await page.route(`**/api/v62/projects/${encoded}/training-materials?*`, async route => {
    const url = new URL(route.request().url());
    const cursor = url.searchParams.get('cursor');
    const query = url.searchParams.get('query') || '';
    const isSecond = cursor === 'page-2';
    if (!cursor && !query && firstPageHeld) {
      firstPageHeld = false;
      await firstPageGate;
    }
    const rows = Array.from({length: query ? 8 : 60}, (_, index) => material(index, isSecond ? 2 : 1));
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: rows,
        total: query ? 8 : 10_000,
        limit: 60,
        next_cursor: query || isSecond ? null : 'page-2',
        repository_revision: 88,
      }),
    });
  });
  await page.route(`**/api/v62/projects/${encoded}/training-materials/bulk-selection`, async route => {
    const payload = route.request().postDataJSON();
    const count = payload?.all_available ? 10_000 : 8;
    const items = payload?.all_available
      ? Array.from({length: count}, (_, index) => `bulk-${index}`)
      : Array.from({length: count}, (_, index) => material(index, 1).id);
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({items, total: count, repository_revision: 88, selection_mode: payload?.all_available ? 'all_available' : 'filtered'}),
    });
  });

  requests.length = 0;
  thumbnailRequests.length = 0;
  await page.evaluate(() => { window.openTrainMaterialPickerV3('train'); });
  await expect(page.locator('.train-v3-picker.server-paged')).toBeVisible({timeout: 1_000});
  await expect(page.locator('.train-v3-skeleton').first()).toBeVisible({timeout: 1_000});
  expect(await page.locator('.train-v3-card').count()).toBe(0);

  releaseFirstPage();
  await expect(page.locator('.train-v3-card')).toHaveCount(60, {timeout: 5_000});
  await expect(page.locator('#trV3PickerCount')).toContainText('筛选结果 10000 张');
  await expect(page.locator('#trV3PageMeta')).toContainText('当前页 60 张');
  expect(requests.some(value => /\/api\/projects\/[^/]+\/images(?:\?|$)/.test(value))).toBe(false);
  expect(requests.filter(value => value.includes(`/api/v62/projects/${projectId}/training-materials?`))).toHaveLength(1);
  await expect.poll(() => thumbnailRequests.length).toBe(15);
  const firstViewportThumbnailCount = thumbnailRequests.length;

  const gridMetrics = await page.locator('#trV3Grid').evaluate(element => ({
    clientHeight: element.clientHeight,
    scrollHeight: element.scrollHeight,
  }));
  expect(gridMetrics.scrollHeight).toBeGreaterThan(gridMetrics.clientHeight);

  const firstCard = page.locator('.train-v3-card').first();
  const firstImage = firstCard.locator('img');
  const ratio = await firstImage.evaluate(element => getComputedStyle(element).aspectRatio);
  expect(ratio).toContain('4');

  await page.locator('#trV3Grid').evaluate(element => { element.scrollTop = element.scrollHeight; element.dispatchEvent(new Event('scroll')); });
  await expect.poll(() => thumbnailRequests.length).toBeGreaterThan(firstViewportThumbnailCount);

  const firstId = await firstCard.getAttribute('data-material-id');
  await firstCard.locator('input').check();
  await expect.poll(async () => page.evaluate(() => window.TrainingMaterialPickerRuntime?.state?.().selected)).toBe(1);

  await page.getByRole('button', {name: '下一页'}).click();
  await expect(page.locator('.train-v3-card')).toHaveCount(60);
  await expect(page.locator('#trV3Pager')).toContainText('第 2 页');
  expect(requests.some(value => value.includes('cursor=page-2'))).toBe(true);

  await page.getByRole('button', {name: '上一页'}).click();
  await expect(page.locator(`[data-material-id="${firstId}"] input`)).toBeChecked();

  await page.locator('#trV3Q').fill('smoke');
  await expect(page.locator('.train-v3-card')).toHaveCount(8, {timeout: 3_000});
  await expect(page.locator('#trV3PickerCount')).toContainText('筛选结果 8 张');
  expect(requests.some(value => value.includes('query=smoke'))).toBe(true);

  await page.getByRole('button', {name: '全选当前筛选'}).click();
  await expect.poll(async () => page.evaluate(() => window.TrainingMaterialPickerRuntime?.state?.().selected)).toBe(8);
  expect(requests.filter(value => value.includes('/training-materials/bulk-selection'))).toHaveLength(1);

  const runtimeState = await page.evaluate(() => window.TrainingMaterialPickerRuntime?.state?.());
  expect(runtimeState.pageSize).toBe(60);
  expect(runtimeState.fullPoolHydration).toBe(false);
  expect(runtimeState.bulkSelectionOwner).toBe('server');
  expect(runtimeState.viewportThumbnailLoading).toBe(true);
  expect(runtimeState.eagerThumbnailCount).toBe(15);

  await page.getByRole('button', {name: '确认选择'}).click();
  await expect(page.locator('.train-v3-picker.server-paged')).not.toBeVisible();
  await expect.poll(async () => page.evaluate(() => window.TrainingDraftRuntime?.materialIds?.() || []))
    .toContain(firstId);

  expect(pageErrors).toEqual([]);
});

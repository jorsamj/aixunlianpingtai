import {test, expect} from '@playwright/test';

const PIXEL = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=', 'base64');

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

test('training material picker opens immediately and pages 120 thumbnails from the server', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await expect.poll(async () => page.evaluate(() => window.TrainingMaterialPickerRuntime?.build || null))
    .toBe('training-material-picker-runtime-422500');

  const projectId = await page.evaluate(() => state.project?.id);
  expect(projectId).toBeTruthy();
  const encoded = encodeURIComponent(projectId);
  const requests = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/')) requests.push(`${request.method()} ${url.pathname}${url.search}`);
  });

  await page.route('**/thumb/*.png', route => route.fulfill({status: 200, contentType: 'image/png', body: PIXEL}));
  await page.route('**/full/*.png', route => route.fulfill({status: 200, contentType: 'image/png', body: PIXEL}));
  await page.route(`**/api/v62/projects/${encoded}/training-materials?*`, async route => {
    const url = new URL(route.request().url());
    const cursor = url.searchParams.get('cursor');
    const query = url.searchParams.get('query') || '';
    const isSecond = cursor === 'page-2';
    if (!cursor && !query) await new Promise(resolve => setTimeout(resolve, 250));
    const rows = Array.from({length: query ? 8 : 120}, (_, index) => material(index, isSecond ? 2 : 1));
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: rows,
        total: query ? 8 : 10_000,
        limit: 120,
        next_cursor: query || isSecond ? null : 'page-2',
        repository_revision: 88,
      }),
    });
  });

  requests.length = 0;
  await page.evaluate(() => { void window.openTrainMaterialPickerV3('train'); });
  await expect(page.locator('.train-v3-picker.server-paged')).toBeVisible({timeout: 1_000});
  await expect(page.locator('.train-v3-skeleton').first()).toBeVisible({timeout: 1_000});
  await expect(page.locator('.train-v3-card')).toHaveCount(120, {timeout: 5_000});
  await expect(page.locator('#trV3PickerCount')).toContainText('筛选结果 10000 张');
  await expect(page.locator('#trV3PageMeta')).toContainText('当前页 120 张');
  expect(requests.some(value => /\/api\/projects\/[^/]+\/images(?:\?|$)/.test(value))).toBe(false);
  expect(requests.filter(value => value.includes(`/api/v62/projects/${projectId}/training-materials?`))).toHaveLength(1);

  const firstId = await page.locator('.train-v3-card').first().getAttribute('data-material-id');
  await page.locator('.train-v3-card').first().locator('input').check();
  await expect.poll(async () => page.evaluate(() => window.TrainingMaterialPickerRuntime?.state?.().selected)).toBe(1);

  await page.getByRole('button', {name: '下一页'}).click();
  await expect(page.locator('.train-v3-card')).toHaveCount(120);
  await expect(page.locator('#trV3Pager')).toContainText('第 2 页');
  expect(requests.some(value => value.includes('cursor=page-2'))).toBe(true);

  await page.getByRole('button', {name: '上一页'}).click();
  await expect(page.locator(`[data-material-id="${firstId}"] input`)).toBeChecked();

  await page.locator('#trV3Q').fill('smoke');
  await expect(page.locator('.train-v3-card')).toHaveCount(8, {timeout: 3_000});
  await expect(page.locator('#trV3PickerCount')).toContainText('筛选结果 8 张');
  expect(requests.some(value => value.includes('query=smoke'))).toBe(true);

  const runtimeState = await page.evaluate(() => window.TrainingMaterialPickerRuntime?.state?.());
  expect(runtimeState.pageSize).toBe(120);
  expect(runtimeState.fullPoolHydration).toBe(false);

  await page.getByRole('button', {name: '确认选择'}).click();
  await expect(page.locator('.train-v3-picker.server-paged')).not.toBeVisible();
  await expect.poll(async () => page.evaluate(() => window.TrainingDraftRuntime?.materialIds?.() || []))
    .toContain(firstId);

  expect(pageErrors).toEqual([]);
});

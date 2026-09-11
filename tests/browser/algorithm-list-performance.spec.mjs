import {test, expect} from '@playwright/test';

test('algorithm cards expand locally and focused refresh avoids full bootstrap reload', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await page.evaluate(() => window.setPage('算法列表'));
  await expect(page.locator('#title')).toContainText('算法列表');
  await expect(page.locator('#alg412List')).toBeVisible({timeout: 10_000});

  await expect.poll(async () => page.evaluate(() => window.AlgorithmListRuntime?.build || null))
    .toBe('algorithm-list-runtime-422501');
  await expect.poll(async () => page.evaluate(() => Boolean(state.uiReady) && !state.__extras412))
    .toBe(true);

  await page.evaluate(() => {
    state.algorithms = [{
      id: 'algo-perf-1',
      name: '性能验收算法',
      remark: '用于算法列表浏览器性能验收',
      industry: '测试',
      algorithm_type: 'yolo_ultralytics',
      versions: [{
        id: 'version-perf-1',
        version_name: '20260911140000',
        training_status: 'done',
        status: 'done',
        model_name: 'best.pt',
        stored_path: '/tmp/best.pt',
        created_at: '2026-09-11T14:00:00Z',
        report: {metrics: {map50: 0.88}},
      }],
    }];
    state.jobs = [];
    state.alg428Expanded = {};
    window.renderAlgorithms423();
  });

  const apiRequests = [];
  const onRequest = request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/')) apiRequests.push(`${request.method()} ${url.pathname}${url.search}`);
  };
  page.on('request', onRequest);

  const card = page.locator('.alg428-card').filter({hasText: '性能验收算法'});
  await expect(card).toBeVisible();
  await card.locator('.alg428-main').click();
  await expect(card).toHaveClass(/open/);
  await expect(card.locator('.alg428-version-row')).toHaveCount(1);
  await page.waitForTimeout(250);
  expect(apiRequests).toEqual([]);

  await card.locator('.alg428-main').click();
  await expect(card).not.toHaveClass(/open/);
  await page.waitForTimeout(150);
  expect(apiRequests).toEqual([]);

  const projectId = await page.evaluate(() => state.project?.id);
  expect(projectId).toBeTruthy();
  const encoded = encodeURIComponent(projectId);

  await page.route(`**/api/v12/projects/${encoded}/algorithms`, async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({items: [{
        id: 'algo-perf-1',
        name: '性能验收算法-已刷新',
        remark: 'focused refresh',
        industry: '测试',
        algorithm_type: 'yolo_ultralytics',
        versions: [],
      }]}),
    });
  });
  await page.route(`**/api/projects/${encoded}/jobs`, async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([{id: 'job-perf-1', status: 'running', algorithm_asset_id: 'algo-perf-1'}]),
    });
  });

  apiRequests.length = 0;
  await page.locator('#refreshBtn').click();
  await expect.poll(async () => page.evaluate(() => window.AlgorithmListRuntime?.state?.().inflight ?? null))
    .toBe(false);
  await expect(page.locator('#alg412List')).toContainText('性能验收算法-已刷新');

  expect(apiRequests.sort()).toEqual([
    `GET /api/projects/${projectId}/jobs`,
    `GET /api/v12/projects/${projectId}/algorithms`,
  ].sort());
  expect(apiRequests.some(row => row.includes('/bootstrap/snapshot'))).toBe(false);
  expect(pageErrors).toEqual([]);
});

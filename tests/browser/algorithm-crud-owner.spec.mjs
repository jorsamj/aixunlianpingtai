import {test, expect} from '@playwright/test';

test('algorithm create edit delete uses authoritative local state without broad refresh', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await page.evaluate(() => window.setPage('算法列表'));
  await expect(page.locator('#alg412List')).toBeVisible({timeout: 10_000});
  await expect.poll(async () => page.evaluate(() => Boolean(state.uiReady) && !state.__extras412)).toBe(true);

  const projectId = await page.evaluate(() => state.project?.id);
  expect(projectId).toBeTruthy();
  const encoded = encodeURIComponent(projectId);
  const requests = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/')) requests.push(`${request.method()} ${url.pathname}${url.search}`);
  });

  await page.route(`**/api/v12/projects/${encoded}/algorithms`, async route => {
    if (route.request().method() !== 'POST') return route.continue();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({algorithm: {
        id: 'algo-r20h-crud',
        name: 'R20h 创建算法',
        remark: 'create local state',
        industry: '测试',
        algorithm_type: 'yolo_ultralytics',
        versions: [],
      }}),
    });
  });
  await page.route(`**/api/v12/projects/${encoded}/algorithms/algo-r20h-crud`, async route => {
    if (route.request().method() === 'PUT') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({algorithm: {
          id: 'algo-r20h-crud',
          name: 'R20h 已编辑算法',
          remark: 'edit local state',
          industry: '测试',
          algorithm_type: 'yolo_ultralytics',
          versions: [],
        }}),
      });
    }
    if (route.request().method() === 'DELETE') {
      return route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({ok: true})});
    }
    return route.continue();
  });

  await page.locator('[data-action="algorithm.create"]').click();
  await expect(page.locator('#alg414Name')).toBeVisible();
  await page.locator('#alg414Name').fill('R20h 创建算法');
  await page.locator('#alg414Industry').fill('测试');
  await page.locator('#alg414Remark').fill('create local state');
  await page.locator('#alg414Save').click();
  await expect(page.locator('#modal')).toHaveClass(/hidden/);
  await expect(page.locator('#alg412List')).toContainText('R20h 创建算法');
  await expect.poll(async () => page.evaluate(() => state.algorithms.some(x => x.id === 'algo-r20h-crud'))).toBe(true);

  const card = page.locator('.alg428-card').filter({hasText: 'R20h 创建算法'});
  await card.getByRole('button', {name: '编辑'}).click();
  await expect(page.locator('#alg414EditName')).toHaveValue('R20h 创建算法');
  await page.locator('#alg414EditName').fill('R20h 已编辑算法');
  await page.locator('#modalBody').getByRole('button', {name: '保存'}).click();
  await expect(page.locator('#modal')).toHaveClass(/hidden/);
  await expect(page.locator('#alg412List')).toContainText('R20h 已编辑算法');

  page.once('dialog', dialog => dialog.accept());
  const editedCard = page.locator('.alg428-card').filter({hasText: 'R20h 已编辑算法'});
  await editedCard.getByRole('button', {name: '删除'}).click();
  await expect(page.locator('#alg412List')).not.toContainText('R20h 已编辑算法');
  await expect.poll(async () => page.evaluate(() => state.algorithms.some(x => x.id === 'algo-r20h-crud'))).toBe(false);

  const expected = [
    `POST /api/v12/projects/${projectId}/algorithms`,
    `PUT /api/v12/projects/${projectId}/algorithms/algo-r20h-crud`,
    `DELETE /api/v12/projects/${projectId}/algorithms/algo-r20h-crud`,
  ];
  for (const row of expected) expect(requests.filter(x => x === row)).toEqual([row]);

  const forbiddenBroadRefresh = requests.filter(row => {
  if (expected.includes(row)) return false;
  const [method, rawPath] = row.split(' ', 2);
  const pathOnly = rawPath.split('?')[0];
  if (method !== 'GET') return false;
  return pathOnly === '/api/projects'
    || pathOnly === `/api/projects/${projectId}`
    || pathOnly.startsWith(`/api/projects/${projectId}/datasets`)
    || pathOnly.startsWith(`/api/projects/${projectId}/images`)
    || pathOnly.startsWith(`/api/projects/${projectId}/jobs`)
    || pathOnly.startsWith(`/api/v12/projects/${projectId}/labels`)
    || pathOnly.startsWith(`/api/v12/projects/${projectId}/algorithms`)
    || pathOnly.includes('/bootstrap/snapshot');
});
expect(forbiddenBroadRefresh).toEqual([]);
  expect(pageErrors).toEqual([]);
});

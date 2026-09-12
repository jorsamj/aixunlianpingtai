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
    .toBe('algorithm-list-runtime-422503');
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

  let owned = apiRequests.filter(row => row.includes('/algorithms') || row.includes('/bootstrap/snapshot'));
  expect(owned).toEqual([]);

  await card.locator('.alg428-main').click();
  await expect(card).not.toHaveClass(/open/);
  await page.waitForTimeout(150);
  owned = apiRequests.filter(row => row.includes('/algorithms') || row.includes('/bootstrap/snapshot'));
  expect(owned).toEqual([]);

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

  const algorithmRequests = apiRequests.filter(row => row.includes(`/api/v12/projects/${projectId}/algorithms`));
  const jobRequests = apiRequests.filter(row => row.includes(`/api/projects/${projectId}/jobs`));
  expect(algorithmRequests).toEqual([`GET /api/v12/projects/${projectId}/algorithms`]);
  expect(jobRequests).toEqual([`GET /api/projects/${projectId}/jobs`]);
  expect(apiRequests.some(row => row.includes('/bootstrap/snapshot'))).toBe(false);
  expect(pageErrors).toEqual([]);
});

test('algorithm version deletion uses focused refresh without full reload', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await page.evaluate(() => window.setPage('算法列表'));
  await expect(page.locator('#alg412List')).toBeVisible({timeout: 10_000});

  const projectId = await page.evaluate(() => state.project?.id);
  expect(projectId).toBeTruthy();
  const encoded = encodeURIComponent(projectId);
  const requests = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/')) requests.push(`${request.method()} ${url.pathname}${url.search}`);
  });

  await page.route(`**/api/v12/projects/${encoded}/algorithms/algo-version-delete/versions/version-delete-1`, async route => {
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({ok: true})});
  });
  await page.route(`**/api/v12/projects/${encoded}/algorithms`, async route => {
    if (route.request().method() !== 'GET') return route.continue();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({items: [{
        id: 'algo-version-delete',
        name: '版本删除验收算法',
        remark: 'R20 behavior baseline',
        industry: '测试',
        algorithm_type: 'yolo_ultralytics',
        versions: [],
      }]}),
    });
  });
  await page.route(`**/api/projects/${encoded}/jobs`, async route => {
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify([])});
  });

  await page.evaluate(() => {
    state.algorithms = [{
      id: 'algo-version-delete',
      name: '版本删除验收算法',
      remark: 'R20 behavior baseline',
      industry: '测试',
      algorithm_type: 'yolo_ultralytics',
      versions: [{
        id: 'version-delete-1',
        version_name: '20260912100000',
        model_name: 'best.pt',
        size_mb: 5.2,
        created_at: '2026-09-12T10:00:00Z',
      }],
    }];
    state.jobs = [];
    window.renderAlgorithms423();
    window.viewAlgorithm423('algo-version-delete');
  });

  await expect(page.locator('#modal')).not.toHaveClass(/hidden/);
  await expect(page.locator('#modalBody')).toContainText('20260912100000');
  page.once('dialog', dialog => dialog.accept());
  await page.locator('#modalBody').getByRole('button', {name: '删除版本'}).click();

  await expect(page.locator('#modal')).toHaveClass(/hidden/);
  await expect(page.locator('#alg412List')).toContainText('版本删除验收算法');
  await expect(page.locator('#alg412List')).not.toContainText('20260912100000');

  const deleteRequest = `DELETE /api/v12/projects/${projectId}/algorithms/algo-version-delete/versions/version-delete-1`;
  const algorithmRequest = `GET /api/v12/projects/${projectId}/algorithms`;
  const jobRequest = `GET /api/projects/${projectId}/jobs`;
  expect(requests.filter(row => row === deleteRequest)).toEqual([deleteRequest]);
  expect(requests.filter(row => row === algorithmRequest)).toEqual([algorithmRequest]);
  expect(requests.filter(row => row === jobRequest)).toEqual([jobRequest]);

  const forbiddenFullReloadRequests = requests.filter(row => {
    const path = row.slice(row.indexOf(' ') + 1).split('?')[0];
    return path === '/api/projects'
      || path === `/api/projects/${projectId}`
      || path.startsWith(`/api/projects/${projectId}/datasets`)
      || path.startsWith(`/api/projects/${projectId}/images`)
      || path.startsWith(`/api/v12/projects/${projectId}/labels`)
      || path.startsWith(`/api/v12/projects/${projectId}/publish/pending`)
      || path.startsWith(`/api/v12/projects/${projectId}/test_models`)
      || path === '/api/training_options'
      || path === '/api/v16/inference_envs'
      || path === '/api/system/recommendation'
      || path === '/api/local_models'
      || path.includes('/bootstrap/snapshot');
  });
  expect(forbiddenFullReloadRequests).toEqual([]);
  expect(pageErrors).toEqual([]);
});

test('publishing a pending model as an algorithm version keeps the live publish flow functional', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await page.evaluate(() => window.setPage('测试发布'));
  await expect(page.locator('#title')).toContainText('测试发布');

  const projectId = await page.evaluate(() => state.project?.id);
  expect(projectId).toBeTruthy();
  const encoded = encodeURIComponent(projectId);
  let submittedBody = null;
  await page.route(`**/api/v12/projects/${encoded}/algorithms/algo-publish-r20b/versions`, async route => {
    submittedBody = route.request().postDataJSON();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        version: {
          id: 'version-publish-r20b',
          version_name: '20260912143000',
          model_name: 'publish-r20b.pt',
          model_key: 'project::publish-r20b.pt',
          size_mb: 8.5,
          created_at: '2026-09-12T14:30:00Z',
        },
      }),
    });
  });

  await page.evaluate(() => {
    state.algorithms = [{
      id: 'algo-publish-r20b',
      name: '发布验收算法',
      remark: 'R20b publish baseline',
      industry: '测试',
      algorithm_type: 'yolo_ultralytics',
      versions: [],
    }];
    state.pending = [{
      name: 'publish-r20b.pt',
      model_key: 'project::publish-r20b.pt',
      type: 'pt',
      framework: 'ultralytics',
      size_mb: 8.5,
      job_id: 'job-publish-r20b',
      job_name: 'R20b publish baseline',
    }];
    window.assignVersion('publish-r20b.pt');
  });

  await expect(page.locator('#modal')).not.toHaveClass(/hidden/);
  await expect(page.locator('#modalBody input[disabled]').first()).toHaveValue('publish-r20b.pt');
  await expect(page.locator('#algoSel')).toHaveValue('algo-publish-r20b');
  await page.locator('#verName').fill('R20B-PUBLISH');
  await page.locator('#verRemark').fill('发布行为基线');
  await expect.poll(async () => page.evaluate(() => !state.__extras412)).toBe(true);
  const requests = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/')) requests.push(`${request.method()} ${url.pathname}${url.search}`);
  });
  await page.locator('#modalBody').getByRole('button', {name: '发布为算法版本'}).click();

  await expect(page.locator('#modal')).toHaveClass(/hidden/);
  await expect(page.locator('#toast')).toContainText('已发布为算法版本');
  expect(submittedBody).toMatchObject({
    model_name: 'publish-r20b.pt',
    model_source: 'project',
    version_name: 'R20B-PUBLISH',
    remark: '发布行为基线',
    job_id: 'job-publish-r20b',
  });
  await expect.poll(async () => page.evaluate(() => state.algorithms.find(x => x.id === 'algo-publish-r20b')?.versions?.[0]?.id || null)).toBe('version-publish-r20b');
  await expect.poll(async () => page.evaluate(() => state.pending.some(x => x.name === 'publish-r20b.pt'))).toBe(false);
  const publishRequest = `POST /api/v12/projects/${projectId}/algorithms/algo-publish-r20b/versions`;
  expect(requests.filter(row => row === publishRequest)).toEqual([publishRequest]);
  const forbiddenReloadRequests = requests.filter(row => {
    const path = row.slice(row.indexOf(' ') + 1).split('?')[0];
    return path === '/api/projects'
      || path === `/api/projects/${projectId}`
      || path.startsWith(`/api/projects/${projectId}/datasets`)
      || path.startsWith(`/api/projects/${projectId}/images`)
      || path.startsWith(`/api/projects/${projectId}/jobs`)
      || path.startsWith(`/api/projects/${projectId}/models`)
      || path.startsWith(`/api/v12/projects/${projectId}/labels`)
      || path.startsWith(`/api/v12/projects/${projectId}/algorithms`) && path !== `/api/v12/projects/${projectId}/algorithms/algo-publish-r20b/versions`
      || path.startsWith(`/api/v12/projects/${projectId}/publish/pending`)
      || path.startsWith(`/api/v12/projects/${projectId}/test_models`)
      || path === '/api/training_options'
      || path === '/api/v16/inference_envs'
      || path === '/api/system/recommendation'
      || path === '/api/local_models'
      || path.includes('/bootstrap/snapshot');
  });
  expect(forbiddenReloadRequests).toEqual([]);
  expect(pageErrors).toEqual([]);
});

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

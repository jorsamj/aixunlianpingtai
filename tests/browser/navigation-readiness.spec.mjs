import {test, expect} from '@playwright/test';

test('navigation requested during startup waits for bootstrap readiness before rendering', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  let releaseSnapshot;
  const snapshotGate = new Promise(resolve => { releaseSnapshot = resolve; });
  let snapshotSeenResolve;
  const snapshotSeen = new Promise(resolve => { snapshotSeenResolve = resolve; });
  let intercepted = false;

  await page.route(/\/api\/v53\/bootstrap\/snapshot(?:\?.*)?$/, async route => {
    if (!intercepted) {
      intercepted = true;
      snapshotSeenResolve();
    }
    await snapshotGate;
    await route.continue();
  });

  await page.goto('/');
  await Promise.race([
    snapshotSeen,
    new Promise((_, reject) => setTimeout(() => reject(new Error('startup snapshot request was not observed')), 10_000)),
  ]);

  await expect.poll(async () => page.evaluate(() => ({
    initPending: !!window.__v53InitPromise,
    navigationInstalled: !!window.NavigationStability,
    uiReady: typeof state !== 'undefined' ? !!state.uiReady : null,
  }))).toEqual({initPending: true, navigationInstalled: true, uiReady: false});

  await page.evaluate(() => {
    window.__readinessNavigationSettled = false;
    window.__readinessNavigationPromise = Promise.resolve(window.setPage('数据集')).then(() => {
      window.__readinessNavigationSettled = true;
    });
  });

  await page.waitForTimeout(250);
  expect(await page.evaluate(() => state.page)).toBe('算法列表');
  expect(await page.evaluate(() => window.__readinessNavigationSettled)).toBe(false);
  expect(await page.evaluate(() => window.PageRequestScopeRuntime?.stats?.().page || '')).toBe('数据集');

  releaseSnapshot();

  await expect.poll(async () => page.evaluate(() => window.__readinessNavigationSettled), {timeout: 15_000}).toBe(true);
  await expect(page.locator('#title')).toContainText('数据集');
  await expect(page.getByRole('button', {name: /数据集/})).toHaveClass(/active/);
  await expect.poll(async () => page.evaluate(() => {
    try {
      return JSON.parse(localStorage.getItem('mc_train_ui_state_v34') || '{}').page || '';
    } catch (_) {
      return '';
    }
  })).toBe('数据集');
  expect(await page.evaluate(() => state.uiReady)).toBe(true);
  expect(pageErrors).toEqual([]);
});


test('persisted service-node page has its owner installed in the main runtime before restore navigation', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));
  await page.addInitScript(() => {
    localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({page: '服务节点'}));
  });
  await page.route('**/api/v63/service-nodes', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({items: [], supported_capabilities: []}),
    });
  });

  await page.goto('/');
  await expect.poll(async () => page.evaluate(() => ({
    uiReady: Boolean(state.uiReady),
    runtime: window.ServiceNodeRuntime?.build || null,
    owner: Boolean(window.NavigationStability?.hasPageOwner?.('服务节点')),
  })), {timeout: 15_000}).toEqual({
    uiReady: true,
    runtime: 'service-node-runtime-422536',
    owner: true,
  });
  await expect(page.locator('#title')).toHaveText('服务节点');
  await expect(page.locator('[data-service-node-page="1"]')).toBeVisible();
  await expect(page.locator('#view')).not.toContainText('模块尚未');
  await expect(page.locator('#view')).not.toContainText('当前页面不存在');
  expect(pageErrors).toEqual([]);
});


test('startup progress keeps the same boot card while status advances', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.goto('/');
  await expect.poll(async () => page.evaluate(() => Boolean(state.uiReady)), {timeout: 15_000}).toBe(true);
  await page.evaluate(() => window.setPage('标签管理'));
  await expect(page.locator('#title')).toHaveText('标签管理');
  await page.evaluate(() => window.PollRegistryRuntime?.registry?.clearAll?.());

  let statusCalls = 0;
  let releaseSecond;
  let releaseReady;
  const secondGate = new Promise(resolve => { releaseSecond = resolve; });
  const readyGate = new Promise(resolve => { releaseReady = resolve; });

  await page.route(/\/api\/v53\/bootstrap\/status(?:\?.*)?$/, async route => {
    statusCalls += 1;
    if (statusCalls === 1) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({status:'loading', progress:10, stage:'读取算法', message:'正在读取算法数据'}),
      });
      return;
    }
    if (statusCalls === 2) {
      await secondGate;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({status:'loading', progress:60, stage:'读取任务', message:'正在恢复训练任务'}),
      });
      return;
    }
    await readyGate;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({status:'ready', progress:100, stage:'准备完成', message:'平台已就绪'}),
    });
  });

  await page.evaluate(() => {
    window.__bootProbePromise = window.loadStartupSnapshot413(false);
  });

  await expect.poll(() => statusCalls, {timeout: 5_000}).toBeGreaterThan(0);
  await expect(page.locator('[data-boot-card="1"]')).toHaveCount(1);
  await expect(page.locator('[data-boot-percent]')).toHaveText('10%');
  await page.evaluate(() => {
    window.__stableBootCard = document.querySelector('[data-boot-card="1"]');
    window.__stableBootBar = document.querySelector('[data-boot-progress-bar]');
  });

  releaseSecond();
  await expect(page.locator('[data-boot-percent]')).toHaveText('60%', {timeout: 5_000});
  await expect(page.locator('[data-boot-stage]')).toHaveText('读取任务');
  expect(await page.evaluate(() => ({
    card: window.__stableBootCard === document.querySelector('[data-boot-card="1"]'),
    bar: window.__stableBootBar === document.querySelector('[data-boot-progress-bar]'),
    transform: document.querySelector('[data-boot-progress-bar]')?.style.transform || '',
  }))).toEqual({card:true, bar:true, transform:'scaleX(0.6000)'});

  releaseReady();
  await page.evaluate(async () => {
    await window.__bootProbePromise;
    window.render?.();
  });
  await expect(page.locator('[data-boot-card="1"]')).toHaveCount(0);
  expect(pageErrors).toEqual([]);
});

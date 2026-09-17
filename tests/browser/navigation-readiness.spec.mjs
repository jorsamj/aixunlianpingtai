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

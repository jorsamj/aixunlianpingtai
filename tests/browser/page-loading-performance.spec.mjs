import {test, expect} from '@playwright/test';

function requestSummary(label, rows, visibleMs) {
  const urls = rows.map(row => `${row.method} ${row.path}${row.search}`);
  const counts = new Map();
  for (const url of urls) counts.set(url, (counts.get(url) || 0) + 1);
  const duplicates = [...counts.entries()].filter(([, count]) => count > 1).map(([url, count]) => ({url, count}));
  const slowest = [...rows].sort((left, right) => (right.durationMs || 0) - (left.durationMs || 0))[0] || null;
  return {
    label,
    requestCount: rows.length,
    duplicates,
    slowest: slowest ? {url: `${slowest.method} ${slowest.path}${slowest.search}`, durationMs: slowest.durationMs || 0} : null,
    snapshotCount: rows.filter(row => row.path === '/api/v53/bootstrap/snapshot').length,
    refreshTrue: rows.some(row => row.path === '/api/v53/bootstrap/snapshot' && row.search.includes('refresh=true')),
    visibleMs,
    urls,
  };
}

test('startup and primary pages stay within their cache-first request owners', async ({page}) => {
  const rows = [];
  const pending = new Map();
  const recordRequest = request => {
    const url = new URL(request.url());
    if (!url.pathname.startsWith('/api/')) return;
    const row = {method: request.method(), path: url.pathname, search: url.search, startedAt: Date.now(), durationMs: 0};
    rows.push(row);
    pending.set(request, row);
  };
  const finishRequest = request => {
    const row = pending.get(request);
    if (row) row.durationMs = Date.now() - row.startedAt;
    pending.delete(request);
  };
  page.on('request', recordRequest);
  page.on('requestfinished', finishRequest);
  page.on('requestfailed', finishRequest);

  const settle = async startIndex => {
    let previous = -1;
    for (let index = 0; index < 20; index += 1) {
      await page.waitForTimeout(50);
      const current = rows.length;
      const hasPending = [...pending.values()].some(row => rows.indexOf(row) >= startIndex);
      if (!hasPending && current === previous) return;
      previous = current;
    }
  };

  const startupAt = Date.now();
  await page.goto('/');
  await expect.poll(async () => page.evaluate(() => state.uiReady === true)).toBe(true);
  await expect.poll(async () => page.evaluate(() => !state.__extras412)).toBe(true);
  await settle(0);
  const reports = [requestSummary('startup', rows.slice(), Date.now() - startupAt)];

  const navigate = async (label, pageName, visible) => {
    const startIndex = rows.length;
    const startedAt = Date.now();
    await page.evaluate(target => window.setPage(target), pageName);
    await visible();
    const visibleMs = Date.now() - startedAt;
    await settle(startIndex);
    const report = requestSummary(label, rows.slice(startIndex), visibleMs);
    reports.push(report);
    return report;
  };

  const algorithm = await navigate('algorithm', '算法列表', async () => {
    await expect(page.locator('#alg412List')).toBeVisible();
  });
  const training = await navigate('training', '训练任务', async () => {
    await expect(page.locator('.train428-page')).toBeVisible();
    await expect.poll(async () => page.evaluate(() => window.TrainingTaskRuntime?.state?.().inflight ?? null)).toBe(false);
  });
  const dataset = await navigate('dataset', '数据集', async () => {
    await expect(page.locator('.data426-shell')).toBeVisible();
    await expect.poll(async () => page.evaluate(() => Boolean(state.materialFilterSignature61))).toBe(true);
  });
  const service = await navigate('service-node', '服务节点', async () => {
    await expect(page.locator('[data-service-node-page]')).toBeVisible();
    await expect(page.locator('[data-service-node-skeleton="1"]')).toHaveCount(0);
  });

  console.log(`[page-loading-inventory] ${JSON.stringify(reports)}`);

  expect(reports[0].snapshotCount).toBe(1);
  expect(reports[0].refreshTrue).toBe(false);
  for (const report of [algorithm, training, dataset, service]) {
    expect(report.snapshotCount, `${report.label} must not load the broad snapshot`).toBe(0);
    expect(report.refreshTrue, `${report.label} must not force-refresh the broad snapshot`).toBe(false);
  }
  expect(training.urls.filter(url => /GET \/api\/projects\/[^/]+\/jobs$/.test(url)).length).toBeLessThanOrEqual(1);
  expect(training.urls.some(url => url.includes('/api/training_options'))).toBe(false);
  expect(training.urls.some(url => /GET \/api\/projects\/[^/]+\/models$/.test(url))).toBe(false);
  expect(dataset.urls.some(url => url.includes('/api/v61/projects/') && url.includes('/materials?'))).toBe(true);
  expect(dataset.urls.some(url => url.includes('/algorithms') || /\/jobs(?:\?|$)/.test(url))).toBe(false);
  expect(service.urls.some(url => url.includes('/algorithms') || /\/jobs(?:\?|$)/.test(url) || url.includes('/materials'))).toBe(false);
});


test('model configuration loads prompt templates once and reuses them on revisit', async ({page}) => {
  let promptGets = 0;
  await page.route('**/api/v35/prompt-templates', async route => {
    if (route.request().method() !== 'GET') return route.continue();
    promptGets += 1;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({items: [{
        id: 'prompt-cache-1',
        name: '安全帽提示词',
        framework: 'common',
        labels: ['helmet'],
        save_format: 'internal',
        prompt: '识别安全帽',
      }]}),
    });
  });

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await page.evaluate(() => window.setPage('模型配置'));
  await expect(page.locator('#title')).toContainText('模型配置');
  await expect(page.getByText('安全帽提示词', {exact: true})).toBeVisible({timeout: 10_000});
  await expect.poll(() => promptGets).toBe(1);

  await page.evaluate(() => window.setPage('工作台'));
  await expect(page.locator('#title')).toContainText('总览');
  await page.evaluate(() => window.setPage('模型配置'));
  await expect(page.getByText('安全帽提示词', {exact: true})).toBeVisible();
  await page.waitForTimeout(150);
  expect(promptGets).toBe(1);
});

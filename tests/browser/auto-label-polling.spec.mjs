import {test, expect} from '@playwright/test';

test('auto-label active task polling updates rows without replacing the page root and stops on navigation', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  let requests = 0;
  await page.route(/\/api\/v60\/projects\/[^/]+\/annotation-tasks\?limit=50$/, async route => {
    requests += 1;
    const completed = Math.min(3, requests);
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({items: [{
        id: 'auto-browser-1',
        name: '浏览器自动标注任务',
        status: 'RUNNING',
        requested_labels: ['fire'],
        progress: completed * 25,
        completed_count: completed,
        total_count: 4,
        failed_count: 0,
        created_at: '2026-09-11T00:00:00Z',
        updated_at: '2026-09-11T00:00:10Z',
        summary: {total: 4, completed, failed: 0, boxes: completed * 2},
      }]})
    });
  });

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await expect.poll(() => page.evaluate(() => window.AutoLabelPollRuntime?.build || null))
    .toBe('auto-label-poll-422501');
  expect(await page.evaluate(() => ({
    wrapper: window.AutoLabelPollRuntime?.snapshot?.().classicWrapperOwner,
    timer: window.AutoLabelPollRuntime?.snapshot?.().timerOwner,
  }))).toEqual({wrapper: false, timer: false});

  await page.evaluate(() => window.setPage('自动标注及清洗'));
  await expect(page.locator('#title')).toContainText('自动标注及清洗');
  await expect(page.locator('#ai60TaskRows')).toBeVisible({timeout: 10_000});
  await expect(page.locator('#ai60TaskRows')).toContainText('浏览器自动标注任务');

  await page.evaluate(() => {
    window.__autoLabelStableRoot = document.getElementById('view');
  });

  await expect.poll(async () => page.evaluate(() => {
    const row = window.PollRegistryRuntime?.snapshot?.().find(item => item.key === 'auto-label-v60');
    return row ? {managed: row.managed, delay: row.delay} : null;
  })).toEqual({managed: true, delay: 1800});

  await expect.poll(() => requests, {timeout: 8_000}).toBeGreaterThanOrEqual(2);
  await expect(page.locator('#ai60TaskRows')).toContainText('2 / 4');

  const rootStayedStable = await page.evaluate(() => (
    window.__autoLabelStableRoot === document.getElementById('view')
  ));
  expect(rootStayedStable).toBe(true);

  await page.evaluate(() => window.setPage('数据集'));
  await expect(page.locator('#title')).toContainText('数据集');
  await expect.poll(async () => page.evaluate(() => (
    window.PollRegistryRuntime?.snapshot?.().some(item => item.key === 'auto-label-v60') || false
  ))).toBe(false);

  expect(pageErrors).toEqual([]);
});

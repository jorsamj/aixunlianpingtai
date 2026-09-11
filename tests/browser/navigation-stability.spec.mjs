import {test, expect} from '@playwright/test';

test('delayed request from previous page cannot jump back over the current page', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.goto('/');
  await expect(page.getByRole('button', {name: /训练任务/})).toBeVisible({timeout: 15_000});
  await expect(page.getByRole('button', {name: /数据集/})).toBeVisible();

  let release;
  const gate = new Promise(resolve => { release = resolve; });
  let interceptedResolve;
  const intercepted = new Promise(resolve => { interceptedResolve = resolve; });
  let shouldDelay = true;

  await page.route('**/api/**', async route => {
    const request = route.request();
    if (shouldDelay && request.method() === 'GET') {
      shouldDelay = false;
      interceptedResolve(request.url());
      await gate;
      try {
        await route.continue();
      } catch (_) {
        // Expected when PageRequestScope aborts the old page request.
      }
      return;
    }
    await route.continue();
  });

  await page.getByRole('button', {name: /训练任务/}).click();
  const delayedUrl = await Promise.race([
    intercepted,
    new Promise((_, reject) => setTimeout(() => reject(new Error('训练任务页面没有发出可延迟的 GET 请求')), 8_000)),
  ]);
  expect(delayedUrl).toContain('/api/');

  await expect.poll(async () => page.evaluate(() => {
    const row = window.PollRegistryRuntime?.snapshot?.().find(item => item.key === 'training-jobs');
    return row ? {managed: row.managed, owners: row.owners, delay: row.delay} : null;
  })).toMatchObject({managed: true, owners: ['训练任务', '检测台']});

  await page.getByRole('button', {name: /数据集/}).click();
  await expect(page.locator('#title')).toContainText('数据集');
  await expect(page.getByRole('button', {name: /数据集/})).toHaveClass(/active/);
  await expect.poll(async () => page.evaluate(() => (
    window.PollRegistryRuntime?.snapshot?.().some(item => item.key === 'training-jobs') || false
  ))).toBe(false);

  release();
  await page.waitForTimeout(1_500);

  await expect(page.locator('#title')).toContainText('数据集');
  await expect(page.getByRole('button', {name: /数据集/})).toHaveClass(/active/);
  expect(pageErrors).toEqual([]);
});

test('final v42.4 video polling patches rows with a PollRegistry-managed one-shot and stops on leave', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));
  let requests = 0;

  await page.route(/\/api\/v33\/projects\/[^/]+\/video-tasks(?:\?.*)?$/, async route => {
    if (route.request().method() !== 'GET') return route.continue();
    requests += 1;
    const progress = Math.min(90, requests * 20);
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({items: [{
        id: 'video-browser-1',
        video_name: 'browser-video.mp4',
        status: 'RUNNING',
        mode: 'interval_seconds',
        interval_seconds: 1,
        progress,
        current_item: `frame-${requests}`,
        result: {extracted_frames: requests * 3},
        split: 'train',
        created_at: '2026-09-11T00:00:00Z',
        updated_at: `2026-09-11T00:00:0${Math.min(requests, 9)}Z`,
      }]})
    });
  });

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});

  await page.evaluate(() => window.setPage('视频切帧'));
  await expect(page.locator('#title')).toContainText('视频切帧');
  await expect(page.locator('#video424Rows')).toBeVisible({timeout: 10_000});
  await expect(page.locator('#video424Rows')).toContainText('browser-video.mp4');

  await page.evaluate(() => {
    window.__videoStableRoot = document.getElementById('view');
  });

  await expect.poll(async () => page.evaluate(() => {
    const row = window.PollRegistryRuntime?.snapshot?.().find(item => item.key === 'video-frames');
    return row ? {managed: row.managed, owners: row.owners, delay: row.delay} : null;
  })).toEqual({managed: true, owners: ['视频切帧'], delay: 2000});

  await expect.poll(() => requests, {timeout: 8_000}).toBeGreaterThanOrEqual(2);
  await expect(page.locator('#video424Rows')).toContainText('frame-2');
  expect(await page.evaluate(() => window.__videoStableRoot === document.getElementById('view'))).toBe(true);
  expect(await page.evaluate(() => window.__videoFramePollTimer ?? null)).toBeNull();

  await page.evaluate(() => window.setPage('数据集'));
  await expect(page.locator('#title')).toContainText('数据集');
  await expect.poll(async () => page.evaluate(() => (
    window.PollRegistryRuntime?.snapshot?.().some(item => item.key === 'video-frames') || false
  ))).toBe(false);

  expect(pageErrors).toEqual([]);
});

test('source polling is PollRegistry-managed after initial page render and stops on leave', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});

  await page.evaluate(() => window.setPage('素材接入'));
  await expect(page.locator('#title')).toContainText('素材接入');
  await expect(page.locator('#source422Rows')).toBeVisible({timeout: 10_000});

  await expect.poll(async () => page.evaluate(() => {
    const row = window.PollRegistryRuntime?.snapshot?.().find(item => item.key === 'sources');
    return row ? {managed: row.managed, owners: row.owners, delay: row.delay} : null;
  })).toEqual({managed: true, owners: ['素材接入'], delay: 2500});

  await page.evaluate(() => window.setPage('数据集'));
  await expect(page.locator('#title')).toContainText('数据集');
  await expect.poll(async () => page.evaluate(() => (
    window.PollRegistryRuntime?.snapshot?.().some(item => item.key === 'sources') || false
  ))).toBe(false);

  expect(pageErrors).toEqual([]);
});

test('final navigation owner closes the mobile sidebar and backdrop', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});

  await page.evaluate(() => window.toggleMobileSidebarV37?.(true));
  await expect(page.locator('#sidebar')).toHaveClass(/mobile-open/);
  await expect(page.locator('#sideBackdrop')).toHaveClass(/show/);

  await page.evaluate(() => window.setPage('数据集'));
  await expect(page.locator('#title')).toContainText('数据集');
  await expect(page.locator('#sidebar')).not.toHaveClass(/mobile-open/);
  await expect(page.locator('#sideBackdrop')).not.toHaveClass(/show/);

  expect(pageErrors).toEqual([]);
});

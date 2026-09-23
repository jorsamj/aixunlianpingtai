import {test, expect} from '@playwright/test';

test('video progress delta keeps row and progress nodes stable', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  const projectId = await page.evaluate(() => state.project?.id);
  expect(projectId).toBeTruthy();
  const encoded = encodeURIComponent(projectId);

  let progress = 10;
  let updatedAt = '2026-09-22T00:00:01Z';
  await page.route(`**/api/v33/projects/${encoded}/video-tasks`, async route => {
    if (route.request().method() !== 'GET') return route.continue();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({items: [{
        id:'video-perf-1',
        video_name:'progress.mp4',
        status:'RUNNING',
        task_status:'RUNNING',
        phase:'extracting',
        progress_percent:progress,
        progress,
        current_item:String(Math.round(progress)),
        result:{extracted_frames:Math.round(progress / 2)},
        mode:'fixed_count',
        fixed_count:50,
        split:'train',
        created_at:'2026-09-22T00:00:00Z',
        updated_at:updatedAt,
      }]}),
    });
  });

  await page.evaluate(() => window.setPage('视频切帧'));
  const row = page.locator('[data-task-id="video-perf-1"]');
  await expect(row).toBeVisible({timeout: 10_000});
  await expect(row).toContainText('10%');

  await page.evaluate(() => {
    window.__videoStableRow = document.querySelector('[data-task-id="video-perf-1"]');
    window.__videoStableProgress = window.__videoStableRow?.querySelector('.progress424 i') || null;
  });

  progress = 46;
  updatedAt = '2026-09-22T00:00:02Z';
  await page.evaluate(() => window.refreshVideo424Delta());
  await expect(row).toContainText('46%');
  await expect(row.locator('.progress424 i')).toHaveAttribute('data-progress', '46.00');

  expect(await page.evaluate(() => ({
    row: window.__videoStableRow === document.querySelector('[data-task-id="video-perf-1"]'),
    progress: window.__videoStableProgress === document.querySelector('[data-task-id="video-perf-1"] .progress424 i'),
  }))).toEqual({row:true, progress:true});
  expect(pageErrors).toEqual([]);
});


test('video page revisit reuses the recent task snapshot without another list request', async ({page}) => {
  let listGets = 0;
  await page.route('**/api/v33/projects/*/video-tasks', async route => {
    if (route.request().method() !== 'GET') return route.continue();
    listGets += 1;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({items: [{
        id:'video-cache-1',
        video_name:'cached.mp4',
        status:'DONE',
        task_status:'SUCCEEDED',
        phase:'done',
        progress_percent:100,
        progress:100,
        result:{extracted_frames:12},
        mode:'fixed_count',
        fixed_count:12,
        split:'train',
        created_at:'2026-09-23T00:00:00Z',
        updated_at:'2026-09-23T00:00:01Z',
      }]}),
    });
  });

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout:15_000});
  await page.evaluate(() => window.setPage('视频切帧'));
  await expect(page.locator('[data-task-id="video-cache-1"]')).toBeVisible({timeout:10_000});
  await expect.poll(() => listGets).toBeGreaterThan(0);
  const firstVisitGets = listGets;

  await page.evaluate(() => window.setPage('工作台'));
  await expect(page.locator('#title')).toContainText('总览');
  await page.evaluate(() => window.setPage('视频切帧'));
  await expect(page.locator('[data-task-id="video-cache-1"]')).toBeVisible();
  await page.waitForTimeout(150);
  expect(listGets).toBe(firstVisitGets);
});

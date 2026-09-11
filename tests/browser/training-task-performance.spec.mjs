import {test, expect} from '@playwright/test';

test('training task refresh and actions patch the final table without rebuilding the page', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await page.evaluate(() => window.setPage('训练任务'));
  await expect(page.locator('#title')).toContainText('训练任务');
  await expect(page.locator('.train428-page')).toBeVisible({timeout: 10_000});
  await expect.poll(async () => page.evaluate(() => window.TrainingTaskRuntime?.build || null))
    .toBe('training-task-runtime-422503');

  const projectId = await page.evaluate(() => state.project?.id);
  expect(projectId).toBeTruthy();
  const encoded = encodeURIComponent(projectId);

  await page.evaluate(() => {
    window.PollRegistryRuntime?.clear?.('training-jobs');
    state.jobPollTimer = null;
    const shell = document.querySelector('.train428-page');
    shell.dataset.performanceMarker = 'preserve-me';
  });
  // Drain callbacks that were already queued before the managed poll was cleared.
  // The assertions below still require exactly one jobs GET for each manual refresh.
  await page.waitForTimeout(160);

  const apiRequests = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/')) apiRequests.push(`${request.method()} ${url.pathname}${url.search}`);
  });

  let jobStatus = 'running';
  await page.route(`**/api/projects/${encoded}/jobs`, async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([{
        id: 'job-focused-1',
        status: jobStatus,
        asset_algorithm_name: '局部刷新训练',
        framework: 'ultralytics',
        progress_percent: jobStatus === 'paused' ? 38 : 37,
        current_epoch: 11,
        total_epochs: 30,
        elapsed_seconds: 80,
        eta_seconds: 140,
        queue_priority: 10,
        priority_scheme: 'lower_number_first',
        execution_resource: {name: 'A800'},
        created_at: '2026-09-11T14:00:00Z',
        started_at: '2026-09-11T14:00:10Z'
      }]),
    });
  });
  await page.route(`**/api/v48/projects/${encoded}/jobs/job-focused-1/pause`, async route => {
    jobStatus = 'paused';
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({ok: true})});
  });

  apiRequests.length = 0;
  await page.locator('#refreshBtn').click();
  await expect.poll(async () => page.evaluate(() => window.TrainingTaskRuntime?.state?.().inflight ?? null))
    .toBe(false);
  await expect(page.locator('.train428-table tbody')).toContainText('局部刷新训练');
  await expect(page.locator('.train428-table tbody')).toContainText('37%');
  await expect(page.locator('.train428-page')).toHaveAttribute('data-performance-marker', 'preserve-me');

  const jobRequests = apiRequests.filter(row => row.includes(`/api/projects/${projectId}/jobs`));
  expect(jobRequests).toEqual([`GET /api/projects/${projectId}/jobs`]);
  expect(apiRequests.some(row => row.includes('/bootstrap/snapshot'))).toBe(false);
  expect(apiRequests.some(row => row.includes('/algorithms'))).toBe(false);
  expect(apiRequests.some(row => row.includes('/datasets'))).toBe(false);
  expect(apiRequests.some(row => row.includes('/materials'))).toBe(false);

  apiRequests.length = 0;
  await page.locator('.train428-refresh').click();
  await expect.poll(async () => page.evaluate(() => window.TrainingTaskRuntime?.state?.().inflight ?? null))
    .toBe(false);
  await expect(page.locator('.train428-page')).toHaveAttribute('data-performance-marker', 'preserve-me');
  expect(apiRequests.filter(row => row.includes(`/api/projects/${projectId}/jobs`)))
    .toEqual([`GET /api/projects/${projectId}/jobs`]);
  expect(apiRequests.some(row => row.includes('/bootstrap/snapshot'))).toBe(false);

  apiRequests.length = 0;
  await page.locator('[data-job-id="job-focused-1"]').getByRole('button', {name: '暂停'}).click();
  await expect.poll(async () => page.evaluate(() => window.TrainingTaskRuntime?.state?.().mutations ?? null))
    .toBe(0);
  await expect(page.locator('[data-job-id="job-focused-1"]')).toContainText('已暂停');
  await expect(page.locator('[data-job-id="job-focused-1"]')).toContainText('38%');
  await expect(page.locator('.train428-page')).toHaveAttribute('data-performance-marker', 'preserve-me');
  expect(apiRequests.filter(row => row.includes(`/api/v48/projects/${projectId}/jobs/job-focused-1/pause`)))
    .toEqual([`POST /api/v48/projects/${projectId}/jobs/job-focused-1/pause`]);
  expect(apiRequests.filter(row => row.includes(`/api/projects/${projectId}/jobs`)))
    .toEqual([`GET /api/projects/${projectId}/jobs`]);
  expect(apiRequests.some(row => row.includes('/bootstrap/snapshot'))).toBe(false);
  expect(apiRequests.some(row => row.includes('/datasets'))).toBe(false);
  expect(apiRequests.some(row => row.includes('/materials'))).toBe(false);
  expect(pageErrors).toEqual([]);
});

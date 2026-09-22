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
    .toBe('training-task-runtime-422507');

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
        dataset_revision_id: 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
        snapshot_id: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
        created_at: '2026-09-11T14:00:00Z',
        started_at: '2026-09-11T14:00:10Z'
      }]),
    });
  });
  await page.route(`**/api/v48/projects/${encoded}/jobs/job-focused-1/pause`, async route => {
    jobStatus = 'paused';
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({ok: true})});
  });
  await page.route(`**/api/projects/${encoded}/jobs/job-focused-1`, async route => {
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({
      id:'job-focused-1',task_id:'job-focused-1',status:jobStatus,requested_device:'auto',assigned_device:'cuda:0',actual_device:'cuda:0',
      dataset_revision_id:'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
      snapshot_id:'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
      current_epoch:11,total_epochs:30,message:'训练中',
    })});
  });
  await page.route(`**/api/projects/${encoded}/jobs/job-focused-1/log`, async route => {
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify('mock log')});
  });

  apiRequests.length = 0;
  await page.locator('#refreshBtn').click();
  await expect.poll(async () => page.evaluate(() => window.TrainingTaskRuntime?.state?.().inflight ?? null))
    .toBe(false);
  await expect(page.locator('.train428-table tbody')).toContainText('局部刷新训练');
  await expect(page.locator('.train428-table tbody')).toContainText('37%');
  await expect(page.locator('.train428-table thead')).not.toContainText('执行框架');
  await expect(page.locator('[data-training-task-shell="canonical"]')).toBeVisible();
  await expect(page.locator('[data-job-id="job-focused-1"]')).not.toContainText('job-focused-1');
  await expect(page.locator('[data-job-id="job-focused-1"]')).not.toContainText('Ultralytics / YOLO');
  await expect(page.locator('.train428-page')).toHaveAttribute('data-performance-marker', 'preserve-me');
  await page.evaluate(() => {
    window.__trainingStableRow = document.querySelector('[data-job-id="job-focused-1"]');
    window.__trainingStableProgress = window.__trainingStableRow?.querySelector('.progress424 i') || null;
  });

  const jobRequests = apiRequests.filter(row => row.includes(`/api/projects/${projectId}/jobs`));
  expect(jobRequests).toEqual([`GET /api/projects/${projectId}/jobs`]);
  expect(apiRequests.some(row => row.includes('/bootstrap/snapshot'))).toBe(false);
  expect(apiRequests.some(row => row.includes('/algorithms'))).toBe(false);
  expect(apiRequests.some(row => row.includes('/datasets'))).toBe(false);
  expect(apiRequests.some(row => row.includes('/materials'))).toBe(false);

  await page.evaluate(() => window.showTrainLog423('job-focused-1'));
  await expect(page.locator('.trainlog428')).toContainText('数据版本');
  await expect(page.locator('.trainlog428')).toContainText('bbbbbbbbbbbb');
  await expect(page.locator('.trainlog428')).toContainText('训练快照');
  await expect(page.locator('.trainlog428')).toContainText('aaaaaaaaaaaa');
  await page.locator('.trainlog428').getByRole('button', {name: '关闭', exact: true}).click();

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
  expect(await page.evaluate(() => (
    window.__trainingStableRow === document.querySelector('[data-job-id="job-focused-1"]')
  ))).toBe(true);
  expect(await page.evaluate(() => (
    window.__trainingStableProgress === document.querySelector('[data-job-id="job-focused-1"] .progress424 i')
  ))).toBe(true);
  expect(apiRequests.filter(row => row.includes(`/api/v48/projects/${projectId}/jobs/job-focused-1/pause`)))
    .toEqual([`POST /api/v48/projects/${projectId}/jobs/job-focused-1/pause`]);
  expect(apiRequests.filter(row => row.includes(`/api/projects/${projectId}/jobs`)))
    .toEqual([`GET /api/projects/${projectId}/jobs`]);
  expect(apiRequests.some(row => row.includes('/bootstrap/snapshot'))).toBe(false);
  expect(apiRequests.some(row => row.includes('/datasets'))).toBe(false);
  expect(apiRequests.some(row => row.includes('/materials'))).toBe(false);
  expect(pageErrors).toEqual([]);
});


test('hard refresh restores a live training task even when the bootstrap snapshot is stale and empty', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.addInitScript(() => {
    localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({page: '训练任务'}));
  });

  let bootstrapRequests = 0;
  await page.route('**/api/v53/bootstrap/snapshot**', async route => {
    bootstrapRequests += 1;
    const response = await route.fetch();
    const payload = await response.json();
    payload.jobs = [];
    payload.generated_at = '2026-09-21T00:00:00Z';
    await route.fulfill({
      response,
      contentType: 'application/json',
      body: JSON.stringify(payload),
    });
  });

  let jobRequests = 0;
  await page.route(/\/api\/projects\/[^/]+\/jobs$/, async route => {
    if (route.request().method() !== 'GET') return route.continue();
    jobRequests += 1;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([{
        id: 'live-after-reload',
        task_id: 'live-after-reload',
        status: 'running',
        task_status: 'RUNNING',
        asset_algorithm_name: '刷新后仍可见训练',
        task_name: '运行中任务',
        framework: 'ultralytics',
        queue_priority: 3,
        priority_scheme: 'lower_number_first',
        progress_percent: 37,
        current_epoch: 11,
        total_epochs: 30,
        elapsed_seconds: 80,
        eta_seconds: 140,
        phase: 'training',
        current_item: 'Epoch 11/30',
        created_at: '2026-09-21T00:00:00Z',
        started_at: '2026-09-21T00:00:10Z',
      }]),
    });
  });

  await page.goto('/');

  await expect(page.locator('#title')).toContainText('训练任务', {timeout: 15_000});
  await expect(page.locator('.train428-page')).toBeVisible({timeout: 10_000});
  await expect(page.locator('[data-job-id="live-after-reload"]')).toContainText('刷新后仍可见训练', {timeout: 10_000});
  await expect(page.locator('[data-job-id="live-after-reload"]')).toContainText('37%');

  expect(bootstrapRequests).toBeGreaterThan(0);
  expect(jobRequests).toBeGreaterThan(0);
  expect(pageErrors).toEqual([]);
});


test('batch mode appears on demand and pauses eligible tasks with one canonical refresh', async ({page}) => {
  const pageErrors=[];
  page.on('pageerror',error=>pageErrors.push(error));
  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout:15_000});
  const projectId=await page.evaluate(()=>state.project?.id);
  expect(projectId).toBeTruthy();
  const encoded=encodeURIComponent(projectId);

  let paused=false;
  let jobsGets=0;
  let pausePosts=0;
  await page.route(`**/api/projects/${encoded}/jobs`,async route=>{
    if(route.request().method()!=='GET')return route.continue();
    jobsGets+=1;
    await route.fulfill({
      status:200,contentType:'application/json',
      body:JSON.stringify([{
        id:'batch-browser-1',task_id:'batch-browser-1',
        status:paused?'paused':'running',task_status:paused?'PAUSED':'RUNNING',
        asset_algorithm_name:'批量烟火检测',task_name:'批量训练 1',
        queue_priority:2,priority_scheme:'lower_number_first',
        progress_percent:33,current_epoch:10,total_epochs:30,
        elapsed_seconds:60,eta_seconds:120,phase:paused?'paused':'training',
        started_at:'2026-09-22T00:00:00Z',
      }]),
    });
  });
  await page.route(`**/api/v48/projects/${encoded}/jobs/batch-browser-1/pause`,async route=>{
    pausePosts+=1;paused=true;
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({ok:true})});
  });

  await page.evaluate(()=>window.setPage('训练任务'));
  await expect(page.locator('[data-training-task-shell="canonical"]')).toBeVisible({timeout:10_000});
  await page.evaluate(()=>window.TrainingTaskRuntime.refresh({render:true,force:true,source:'test'}));
  const row=page.locator('[data-job-id="batch-browser-1"]');
  await expect(row).toContainText('批量烟火检测');
  await expect(row.locator('[data-training-batch-select]')).toHaveCount(0);

  await page.locator('[data-training-batch-toggle]').click();
  await expect(row.locator('[data-training-batch-select]')).toBeVisible();
  await row.locator('[data-training-batch-select]').check();
  await expect(page.locator('[data-training-batch-count]')).toHaveText('已选 1 项');

  const beforeGets=jobsGets;
  await page.locator('[data-training-batch-action="pause"]').click();
  await expect(row).toContainText('已暂停');
  await expect(row.locator('[data-training-batch-select]')).toHaveCount(0);
  expect(pausePosts).toBe(1);
  expect(jobsGets-beforeGets).toBe(1);
  expect(pageErrors).toEqual([]);
});

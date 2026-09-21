import {test, expect} from '@playwright/test';

test('deployment conversion polling keeps job and progress nodes stable', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));
  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  const projectId = await page.evaluate(() => state.project?.id);
  expect(projectId).toBeTruthy();
  const encoded = encodeURIComponent(projectId);

  let progress = 12;
  let stage = '正在转换';
  await page.route(`**/api/v39/projects/${encoded}/deploy/jobs`, async route => {
    if (route.request().method() !== 'GET') return route.continue();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({items: [{
        id:'deploy-perf-1',
        source_name:'best.pt',
        target:'rockchip',
        status:'running',
        stage,
        progress,
        params:{chip:'rk3568'},
        resource:{name:'RKNN Agent'},
        worker_id:'worker-rknn',
      }]}),
    });
  });

  await page.evaluate(() => {
    state.page = '部署转换';
    state.deployLoaded = true;
    state.deployTarget = 'rockchip';
    state.deploySources = [];
    state.deployResources = [];
    state.deployArtifacts = [];
    state.deployJobs = [{
      id:'deploy-perf-1', source_name:'best.pt', target:'rockchip',
      status:'running', stage:'正在转换', progress:12,
      params:{chip:'rk3568'}, resource:{name:'RKNN Agent'}, worker_id:'worker-rknn',
    }];
    window.renderDeployCenter();
  });

  const card = page.locator('[data-deploy-job-id="deploy-perf-1"]');
  await expect(card).toBeVisible();
  await expect(card).toContainText('12%');
  await page.evaluate(() => {
    window.__deployStableCard = document.querySelector('[data-deploy-job-id="deploy-perf-1"]');
    window.__deployStableProgress = window.__deployStableCard?.querySelector('.progress-bar i') || null;
  });

  progress = 63;
  stage = 'RKNN 编译中';
  await page.evaluate(() => window.refreshDeployJobsV39());
  await expect(card).toContainText('63%');
  await expect(card).toContainText('RKNN 编译中');
  await expect(card.locator('.progress-bar i')).toHaveAttribute('data-progress', '63.00');

  expect(await page.evaluate(() => ({
    card: window.__deployStableCard === document.querySelector('[data-deploy-job-id="deploy-perf-1"]'),
    progress: window.__deployStableProgress === document.querySelector('[data-deploy-job-id="deploy-perf-1"] .progress-bar i'),
  }))).toEqual({card:true, progress:true});

  await expect.poll(() => page.evaluate(() => (
    window.PollRegistryRuntime?.snapshot?.().some(row => row.key === 'deploy-jobs-v39') || false
  ))).toBe(true);
  await page.evaluate(() => window.setPage('工作台'));
  await expect.poll(() => page.evaluate(() => (
    window.PollRegistryRuntime?.snapshot?.().some(row => row.key === 'deploy-jobs-v39') || false
  ))).toBe(false);
  expect(pageErrors).toEqual([]);
});

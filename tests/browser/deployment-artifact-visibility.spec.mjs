import {test, expect} from '@playwright/test';


test('completed conversion becomes visible in deployment artifacts without manual refresh', async ({page, request}) => {
  const project = await (await request.post('/api/projects', {data: {
    name: `部署产物联动-${Date.now()}`,
    labels: [{code: 'fire', display_name: '明火'}]
  }})).json();

  const job = {
    id: 'deploy-artifact-job',
    source_name: 'best.pt',
    target: 'onnx',
    resource: {name: 'Ultralytics'},
    params: {precision: 'fp16', input_size: 640},
    status: 'running',
    stage: '导出 ONNX',
    progress: 42,
    created_at: '2026-09-13 00:00:00'
  };
  const artifact = {
    job_id: job.id,
    name: 'converted.onnx',
    source_name: 'best.pt',
    target: 'onnx',
    params: {precision: 'fp16', input_size: 640},
    size_mb: 1.25,
    created_at: '2026-09-13 00:01:00',
    download_url: '/download/converted.onnx'
  };

  let jobsCalls = 0;
  let artifactCalls = 0;
  await page.route(`**/api/v39/projects/${project.id}/deploy/jobs`, route => {
    jobsCalls += 1;
    route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({
      ok: true,
      items: [{...job, status: 'done', stage: '转换完成', progress: 100, finished_at: '2026-09-13 00:01:00'}]
    })});
  });
  await page.route(`**/api/v39/projects/${project.id}/deploy/artifacts`, route => {
    artifactCalls += 1;
    route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({
      ok: true,
      items: jobsCalls > 0 ? [artifact] : []
    })});
  });

  await page.addInitScript(({projectId, cachedJob}) => {
    localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({projectId, page: '工作台'}));
    localStorage.setItem(`cl_algo_deploy_cache_${projectId}`, JSON.stringify({
      ts: Date.now(), resources: [], sources: [], jobs: [cachedJob], artifacts: []
    }));
  }, {projectId: project.id, cachedJob: job});

  await page.goto('/');
  await page.evaluate(() => window.setPage('部署转换'));
  await expect.poll(() => jobsCalls, {timeout: 10_000}).toBeGreaterThan(0);
  await expect.poll(() => artifactCalls, {timeout: 10_000}).toBeGreaterThanOrEqual(2);

  await page.evaluate(() => window.setPage('部署产物'));
  await expect(page.getByText('converted.onnx', {exact: true})).toBeVisible();
  await expect(page.getByRole('link', {name: '下载'})).toHaveAttribute('href', '/download/converted.onnx');
});

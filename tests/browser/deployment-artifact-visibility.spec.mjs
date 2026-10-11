import {test, expect} from '@playwright/test';

async function selectIsolatedTestProject(page, projectId) {
  await page.route('**/api/v53/bootstrap/snapshot**', async route => {
    const url = new URL(route.request().url());
    url.searchParams.set('preferred_project_id', projectId);
    await route.continue({url: url.toString()});
  });
}

test('completed conversion becomes visible in canonical version dialog without manual refresh', async ({page, request}) => {
  const project = await (await request.post('/api/projects', {data: {
    name: `版本转换产物联动-${Date.now()}`,
    labels: [{code: 'fire', display_name: '明火'}],
  }})).json();
  const algorithmId = 'artifact-visible-algorithm';
  const versionId = 'artifact-visible-version';
  let complete = false;
  let historyCalls = 0;
  let retiredArtifactCalls = 0;

  await page.route(
    `**/api/v42/projects/${project.id}/algorithms/${algorithmId}/versions/${versionId}/deployments`,
    route => {
      historyCalls += 1;
      const item = {
        id: 'deploy-artifact-job',
        source_name: 'best.pt',
        target: 'onnx',
        target_name: '通用 ONNX',
        resource_name: 'Ultralytics',
        params: {precision: 'fp16', input_size: 640},
        status: complete ? 'done' : 'running',
        stage: complete ? '转换完成' : '导出 ONNX',
        message: complete ? '转换完成' : '导出 ONNX',
        progress: complete ? 100 : 42,
        created_at: '2026-09-24 00:00:00',
        finished_at: complete ? '2026-09-24 00:01:00' : null,
        outputs: complete ? [{
          name: 'converted.onnx',
          size_mb: 1.25,
          exists: true,
          download_url: '/download/converted.onnx',
        }] : [],
        package_url: complete ? '/download/deploy-package.zip' : '',
      };
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          algorithm: {id: algorithmId, name: '转换产物算法'},
          version: {
            id: versionId,
            version_name: '20260924000100',
            model_name: 'best.pt',
            stored_path: '/models/best.pt',
          },
          items: [item],
        }),
      });
    },
  );

  await page.route(`**/api/v39/projects/${project.id}/deploy/artifacts`, route => {
    retiredArtifactCalls += 1;
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({items: []}),
    });
  });

  await selectIsolatedTestProject(page, project.id);
  await page.addInitScript(() => {
    localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({page: '算法列表'}));
  });
  await page.goto('/');
  await expect.poll(() => page.evaluate(() => (
    typeof window.openVersionConvert428 === 'function'
    && typeof state !== 'undefined'
    && state.uiReady === true
    && Boolean(state.project?.id)
  ))).toBe(true);

  await page.evaluate(([aid, vid]) => {
    const projectId = state.project.id;
    localStorage.removeItem(`cl_train_v428_verdeploy_${projectId}_${aid}_${vid}`);
    window.openVersionConvert428(aid, vid);
  }, [algorithmId, versionId]);

  const dialog = page.getByRole('dialog', {name: '版本转换'});
  await expect(dialog).toBeVisible();
  const job = dialog.locator('[data-conversion-job-id="deploy-artifact-job"]');
  await expect(job.locator('[data-conversion-progress]')).toHaveAttribute('data-progress', '42.00');
  await expect(job.getByText('converted.onnx', {exact: true})).toHaveCount(0);

  complete = true;
  await expect.poll(() => historyCalls, {timeout: 8_000}).toBeGreaterThanOrEqual(2);
  await expect(job.getByText('converted.onnx', {exact: true}), {timeout: 8_000}).toBeVisible();
  await expect(job.getByRole('link', {name: '下载', exact: true})).toHaveAttribute('href', '/download/converted.onnx');
  expect(retiredArtifactCalls).toBe(0);
});

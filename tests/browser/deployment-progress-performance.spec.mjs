import {test, expect} from '@playwright/test';

test('canonical version conversion polling keeps job and progress nodes stable', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));
  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await expect.poll(
    () => page.evaluate(() => state.project?.id || null),
    {timeout: 15_000},
  ).not.toBeNull();

  const projectId = await page.evaluate(() => state.project.id);
  const encoded = encodeURIComponent(projectId);
  const algorithmId = 'algorithm-conversion-perf';
  const versionId = 'version-conversion-perf';
  let progress = 12;
  let stage = '正在转换';

  await page.route(
    `**/api/v42/projects/${encoded}/algorithms/${algorithmId}/versions/${versionId}/deployments`,
    async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          algorithm: {id: algorithmId, name: '转换进度算法'},
          version: {
            id: versionId,
            version_name: '20260924100000',
            model_name: 'best.pt',
            stored_path: '/models/best.pt',
          },
          items: [{
            id: 'deploy-perf-1',
            source_name: 'best.pt',
            target: 'rockchip',
            target_name: '瑞芯微 RKNN',
            status: 'running',
            stage,
            message: stage,
            progress,
            params: {chip: 'rk3568', precision: 'fp16'},
            resource_name: 'RKNN Agent',
            worker_id: 'worker-rknn',
            outputs: [],
          }],
        }),
      });
    },
  );

  await page.evaluate(([aid, vid]) => {
    const pid = state.project.id;
    localStorage.removeItem(`cl_train_v428_verdeploy_${pid}_${aid}_${vid}`);
    window.openVersionConvert428(aid, vid);
  }, [algorithmId, versionId]);

  const dialog = page.getByRole('dialog', {name: '版本转换'});
  await expect(dialog).toBeVisible();
  const card = dialog.locator('[data-conversion-job-id="deploy-perf-1"]');
  await expect(card).toBeVisible();
  await expect(card.locator('[data-conversion-progress]')).toHaveAttribute('data-progress', '12.00');
  await page.evaluate(() => {
    window.__conversionStableCard = document.querySelector('[data-conversion-job-id="deploy-perf-1"]');
    window.__conversionStableProgress = window.__conversionStableCard?.querySelector('[data-conversion-progress]') || null;
  });

  await expect.poll(() => page.evaluate(({algorithmId, versionId}) => (
    window.PollRegistryRuntime?.snapshot?.().some(
      row => row.key === `version-conversion:${algorithmId}:${versionId}`,
    ) || false
  ), {algorithmId, versionId})).toBe(true);

  progress = 63;
  stage = 'RKNN 编译中';
  await expect(card.locator('[data-conversion-progress]'), {timeout: 5_000})
    .toHaveAttribute('data-progress', '63.00');
  await expect(card.locator('[data-conversion-message]')).toContainText('RKNN 编译中');

  expect(await page.evaluate(() => ({
    card: window.__conversionStableCard === document.querySelector('[data-conversion-job-id="deploy-perf-1"]'),
    progress: window.__conversionStableProgress === document.querySelector('[data-conversion-job-id="deploy-perf-1"] [data-conversion-progress]'),
  }))).toEqual({card:true, progress:true});

  await page.evaluate(() => window.setPage('总览'));
  await expect.poll(() => page.evaluate(({algorithmId, versionId}) => (
    window.PollRegistryRuntime?.snapshot?.().some(
      row => row.key === `version-conversion:${algorithmId}:${versionId}`,
    ) || false
  ), {algorithmId, versionId})).toBe(false);
  expect(pageErrors).toEqual([]);
});


test('canonical version conversion coalesces history and resource reads', async ({page}) => {
  await page.goto('/');
  await expect.poll(
    () => page.evaluate(() => state.project?.id || null),
    {timeout: 15_000},
  ).not.toBeNull();

  const projectId = await page.evaluate(() => state.project.id);
  const encoded = encodeURIComponent(projectId);
  const algorithmId = 'algorithm-conversion-coalesce';
  const versionId = 'version-conversion-coalesce';
  let historyGets = 0;
  let resourceGets = 0;

  await page.route(
    `**/api/v42/projects/${encoded}/algorithms/${algorithmId}/versions/${versionId}/deployments`,
    async route => {
      historyGets += 1;
      await new Promise(resolve => setTimeout(resolve, 180));
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          algorithm: {id: algorithmId, name: '转换缓存算法'},
          version: {
            id: versionId,
            version_name: '20260924103000',
            model_name: 'best.pt',
            stored_path: '/models/best.pt',
          },
          items: [],
        }),
      });
    },
  );
  await page.route('**/api/v39/deploy/resources', async route => {
    resourceGets += 1;
    await new Promise(resolve => setTimeout(resolve, 180));
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({items: [{
        id: 'onnx-coalesce',
        name: 'ONNX 导出环境',
        kind: 'ultralytics',
        mode: 'local',
        status: 'ready',
        targets: ['onnx'],
        message: 'ready',
      }]}),
    });
  });

  await page.evaluate(async ([aid, vid]) => {
    const pid = state.project.id;
    localStorage.removeItem(`cl_train_v428_verdeploy_${pid}_${aid}_${vid}`);
    localStorage.removeItem(`cl_train_v428_deployresources_${pid}_`);
    await Promise.all([
      window.loadVersionConversionHistory428(aid, vid, false),
      window.loadVersionConversionHistory428(aid, vid, false),
    ]);
    window.openVersionConvert428(aid, vid);
  }, [algorithmId, versionId]);

  const historyDialog = page.getByRole('dialog', {name: '版本转换'});
  await expect(historyDialog).toBeVisible();
  await expect.poll(() => historyGets).toBe(1);

  await historyDialog.getByRole('button', {name: '选择转换目标'}).click();
  const createDialog = page.getByRole('dialog', {name: '新建版本转换'});
  await expect(createDialog).toBeVisible();
  await expect(createDialog.locator('#conv428Resource')).toContainText('ONNX 导出环境');
  await expect.poll(() => resourceGets).toBe(1);
  expect(historyGets).toBe(1);

  await createDialog.getByRole('button', {name: '取消'}).click();
  await historyDialog.getByRole('button', {name: '选择转换目标'}).click();
  const reopened = page.getByRole('dialog', {name: '新建版本转换'});
  await expect(reopened.locator('#conv428Resource')).toContainText('ONNX 导出环境');
  await page.waitForTimeout(100);
  expect({historyGets, resourceGets}).toEqual({historyGets:1, resourceGets:1});
});

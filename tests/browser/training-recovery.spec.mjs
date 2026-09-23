import {test, expect} from '@playwright/test';

test('failed final validation exposes backend-approved checkpoint recovery and requeues the same task', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));
  page.on('dialog', dialog => dialog.accept());

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await page.evaluate(() => window.setPage('训练任务'));
  await expect(page.locator('.train428-page')).toBeVisible({timeout: 10_000});
  await expect.poll(async () => page.evaluate(() => window.TrainingRecoveryRuntime?.build || null))
    .toBe('training-recovery-runtime-422506');
  await expect.poll(async () => page.evaluate(() => window.TrainingTaskRuntime?.build || null))
    .toBe('training-task-runtime-422506');

  const projectId = await page.evaluate(() => state.project?.id);
  expect(projectId).toBeTruthy();
  const encoded = encodeURIComponent(projectId);

  await page.evaluate(() => window.PollRegistryRuntime?.clear?.('training-jobs'));
  await page.waitForTimeout(160);

  let retried = false;
  const requests = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.pathname.includes('/training-tasks/') || url.pathname.endsWith(`/projects/${projectId}/jobs`)) {
      requests.push(`${request.method()} ${url.pathname}`);
    }
  });

  const recovery = {
    task_id: 'job-recovery-1',
    project_id: projectId,
    task_status: 'FAILED',
    available: true,
    recoverable: true,
    checkpoint_available: true,
    recovery_action: 'revalidate_checkpoint',
    declared_recovery_action: 'revalidate_checkpoint',
    failure_stage: 'final_validation',
    failure_reason: 'final validation worker returned non-zero',
    process_returncode: -9,
    process_signal: 'SIGKILL',
    training_loop_completed: true,
    completed_epochs: 100,
    requested_epochs: 100,
    checkpoint: {kind: 'best', filename: 'best.pt', size_bytes: 1048576, hash_recorded: true},
    attempt: 1,
    retry_of: null,
  };

  await page.route(`**/api/projects/${encoded}/jobs`, async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([{
        id: 'job-recovery-1',
        status: retried ? 'queued' : 'failed',
        task_status: retried ? 'QUEUED' : 'FAILED',
        task_stage: retried ? 'queued' : 'failed',
        retry_of: retried ? 'job-recovery-1' : null,
        asset_algorithm_name: '最终验证恢复测试',
        framework: 'ultralytics',
        progress_percent: retried ? 0 : 100,
        current_epoch: 100,
        total_epochs: 100,
        elapsed_seconds: 900,
        eta_seconds: 0,
        failure_stage: 'final_validation',
        current_item: retried ? '等待重新验证资源' : '最终模型验证失败',
        created_at: '2026-09-15T10:00:00Z',
      }]),
    });
  });

  await page.route(`**/api/v62/projects/${encoded}/training-tasks/recovery-query`, async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ok: true, items: retried ? {} : {'job-recovery-1': recovery}}),
    });
  });

  await page.route(`**/api/v62/projects/${encoded}/training-tasks/job-recovery-1/recovery`, async route => {
    if (route.request().method() === 'GET') {
      await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({ok: true, recovery})});
      return;
    }
    retried = true;
    await route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        task_id: 'job-recovery-1',
        status: 'QUEUED',
        stage: 'queued',
        retry_of: 'job-recovery-1',
        recovery_requested: true,
        recovery_action: 'revalidate_checkpoint',
      }),
    });
  });

  await page.locator('#refreshBtn').click();
  await page.evaluate(() => {
    state.train428Tab = 'history';
    window.TrainingTaskRuntime?.patch?.();
  });
  const row = page.locator('[data-job-id="job-recovery-1"]');
  await expect(row).toBeVisible();
  await expect(row).toContainText('最终验证恢复测试');
  await expect(row).toContainText('可恢复 · Checkpoint 已保留');
  await expect(row).toContainText('100/100');

  await row.getByRole('button', {name: '详情'}).click();
  const dialog = page.locator('[data-training-recovery-overlay]');
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText('训练已完成 · 模型验证失败');
  await expect(dialog).toContainText('100 / 100');
  await expect(dialog).toContainText('最终模型验证');
  await expect(dialog).toContainText('best.pt');
  await expect(dialog.getByRole('button', {name: '重新验证 Checkpoint'})).toBeVisible();

  await dialog.getByRole('button', {name: '重新验证 Checkpoint'}).click();
  await expect(dialog).toBeHidden();
  await expect.poll(() => retried).toBe(true);
  await page.evaluate(() => {
    state.train428Tab = 'active';
    window.TrainingTaskRuntime?.patch?.();
  });
  await expect(row).toBeVisible();
  await expect(row).toContainText('排队中');

  expect(requests).toContain(`POST /api/v62/projects/${projectId}/training-tasks/recovery-query`);
  expect(requests).toContain(`GET /api/v62/projects/${projectId}/training-tasks/job-recovery-1/recovery`);
  expect(requests).toContain(`POST /api/v62/projects/${projectId}/training-tasks/job-recovery-1/recovery`);
  expect(pageErrors).toEqual([]);
});

test('successful training detail never presents completion text as an error', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await page.evaluate(() => window.setPage('训练任务'));
  await expect(page.locator('.train428-page')).toBeVisible({timeout: 10_000});

  const projectId = await page.evaluate(() => state.project?.id);
  expect(projectId).toBeTruthy();
  const encoded = encodeURIComponent(projectId);
  const job = {
    id: 'job-success-detail-1',
    task_id: 'job-success-detail-1',
    status: 'done',
    task_status: 'SUCCEEDED',
    persisted_status: 'SUCCEEDED',
    phase: 'succeeded',
    progress_percent: 100,
    current_epoch: 30,
    total_epochs: 30,
    current_item: '训练完成',
    message: '训练完成，模型产物校验通过',
    training_outcome: 'completed',
    completion_reason: 'requested_epochs_completed',
    asset_algorithm_name: '成功状态详情测试',
    actual_device: 'cuda:0',
    actual_train_params: {batch: 32, workers: 8, cache: 'ram', effective_precision: 'fp16'},
    created_at: '2026-09-23T10:00:00Z',
    started_at: '2026-09-23T10:01:00Z',
    finished_at: '2026-09-23T10:31:00Z',
  };

  await page.route(`**/api/projects/${encoded}/jobs`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([job]),
  }));
  await page.route(`**/api/projects/${encoded}/jobs/job-success-detail-1`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(job),
  }));
  await page.route(`**/api/projects/${encoded}/jobs/job-success-detail-1/log`, route => route.fulfill({
    status: 200,
    contentType: 'text/plain',
    body: 'Epoch 30/30\\ntraining completed',
  }));

  await page.locator('#refreshBtn').click();
  await page.evaluate(() => {
    state.train428Tab = 'history';
    window.TrainingTaskRuntime?.patch?.();
  });

  const row = page.locator('[data-job-id="job-success-detail-1"]');
  await expect(row).toBeVisible();
  await expect(row).toContainText('已完成');
  await row.getByRole('button', {name: '详情'}).click();

  const dialog = page.locator('[data-training-recovery-overlay]');
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText('训练已完成');
  await expect(dialog).toContainText('训练完成，模型产物校验通过');
  await expect(dialog).toContainText('cuda:0');
  await expect(dialog).not.toContainText('失败原因');
  await expect(dialog).not.toContainText('失败证据');
  await expect(dialog).not.toContainText('训练失败');

  // Live detail refresh must update the canonical dialog in place. Replacing the
  // whole overlay every 1.5s causes visible flicker and resets browser UI state.
  const dialogShell = dialog.locator('.training-recovery-dialog');
  await dialog.evaluate(node => { node.dataset.identityProbe = 'overlay-stable'; });
  await dialogShell.evaluate(node => { node.dataset.identityProbe = 'dialog-stable'; });
  await dialog.getByRole('button', {name: '立即刷新'}).click();
  await expect(dialog).toHaveAttribute('data-identity-probe', 'overlay-stable');
  await expect(dialogShell).toHaveAttribute('data-identity-probe', 'dialog-stable');

  expect(pageErrors).toEqual([]);
});


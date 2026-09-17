import {test, expect} from '@playwright/test';

test('interrupted training resume is visible and operable without colliding with final-validation retry', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await page.evaluate(() => window.setPage('训练任务'));
  await expect(page.locator('.train428-page')).toBeVisible({timeout: 10_000});
  await expect.poll(async () => page.evaluate(() => Boolean(window.TrainingCheckpointResumeUI)))
    .toBe(true);

  const projectId = await page.evaluate(() => state.project?.id);
  expect(projectId).toBeTruthy();
  const encoded = encodeURIComponent(projectId);
  await page.evaluate(() => window.PollRegistryRuntime?.clear?.('training-jobs'));
  await page.waitForTimeout(120);

  const resumeJob = {
    id: 'job-resume-36',
    status: 'running',
    task_status: 'RUNNING',
    persisted_status: 'RUNNING',
    phase: 'resuming_training',
    task_stage: 'resuming_training',
    asset_algorithm_name: '烟火识别算法',
    framework: 'ultralytics',
    progress_percent: 48,
    recovery_mode: 'training_checkpoint_resume',
    recovery_state: 'training',
    recovery_auto: true,
    recovery_attempted: true,
    recovery_completed: false,
    resume_from_epoch: 36,
    resume_checkpoint: '/data/projects/p1/runs/train_job-resume-36/weights/last.pt',
    resume_checkpoint_sha256: 'a'.repeat(64),
    current_epoch: 41,
    total_epochs: 100,
    requested_epochs: 100,
    assigned_device: 'cuda:0',
    actual_device: 'cuda:0',
    task_worker_id: 'gpu-worker-a',
    current_item: '断点续训 · Epoch 41/100',
    elapsed_seconds: 1800,
    eta_seconds: 2200,
    created_at: '2026-09-17T00:00:00Z',
    training_progress: {
      epoch: 41,
      total_epochs: 100,
      resume_from_epoch: 36,
      resumed: true,
      metrics: {'metrics/mAP50(B)': 0.62},
    },
  };

  await page.route(`**/api/projects/${encoded}/jobs`, async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([resumeJob]),
    });
  });

  const jobsResponse = page.waitForResponse(response => {
    const url = new URL(response.url());
    return url.pathname === `/api/projects/${projectId}/jobs` && response.request().method() === 'GET';
  });
  await page.locator('#refreshBtn').click();
  await jobsResponse;
  await expect.poll(async () => page.evaluate(() => state.jobs?.some(job => job.id === 'job-resume-36') || false))
    .toBe(true);
  await page.evaluate(() => {
    state.train428Tab = 'active';
    window.TrainingTaskRuntime?.patch?.();
    window.TrainingCheckpointResumeUI?.decorate?.();
  });

  const row = page.locator('[data-job-id="job-resume-36"]');
  await expect(row).toBeVisible({timeout: 10_000});
  await expect(row).toContainText('烟火识别算法');
  await expect(row).toContainText('Epoch 41/100');
  await expect(row).toContainText('断点续训 · 从 Epoch 36');
  await expect(row.locator('.checkpoint-resume-badge')).toHaveCount(1);

  await row.getByRole('button', {name: '详情'}).click();
  const dialog = page.locator('[data-checkpoint-resume-overlay]');
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText('正在从 Checkpoint 恢复训练');
  await expect(dialog).toContainText('Epoch 36');
  await expect(dialog).toContainText('41 / 100');
  await expect(dialog).toContainText('last.pt');
  await expect(dialog).toContainText('cuda:0');
  await expect(dialog).toContainText('gpu-worker-a');
  await expect(dialog.getByRole('button', {name: '重新验证 Checkpoint'})).toHaveCount(0);

  await page.evaluate(() => {
    window.__resumeLogTask = null;
    window.showTrainLog423 = id => { window.__resumeLogTask = id; };
  });
  await dialog.getByRole('button', {name: '查看训练日志'}).click();
  await expect(dialog).toBeHidden();
  await expect.poll(async () => page.evaluate(() => window.__resumeLogTask)).toBe('job-resume-36');
  expect(pageErrors).toEqual([]);
});

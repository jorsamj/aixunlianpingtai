import {test, expect} from '@playwright/test';

test('automatic training recovery is visible and operable without colliding with final-validation retry', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await expect.poll(
    () => page.evaluate(() => typeof window.setPage === 'function' && typeof state !== 'undefined' && state.uiReady === true),
    {timeout: 15_000},
  ).toBe(true);
  await page.evaluate(() => window.setPage('训练任务'));
  await expect(page.locator('.train428-page')).toBeVisible({timeout: 10_000});
  await expect.poll(async () => page.evaluate(() => Boolean(window.TrainingCheckpointResumeUI)))
    .toBe(true);
  await expect.poll(async () => page.evaluate(() => window.TrainingTaskRuntime?.build || null))
    .toBe('training-task-runtime-422506');

  const projectId = await page.evaluate(() => state.project?.id);
  expect(projectId).toBeTruthy();
  const encoded = encodeURIComponent(projectId);
  await page.evaluate(() => {
    window.PollRegistryRuntime?.clear?.('training-jobs');
    state.jobPollTimer = null;
  });
  await expect.poll(async () => page.evaluate(() => window.TrainingTaskRuntime?.state?.().inflight ?? null))
    .toBe(false);
  // Drain callbacks that were already queued before the managed poll was cleared.
  // This mirrors the permanent training-task refresh acceptance contract.
  await page.waitForTimeout(180);

  const startNavigationEpoch = await page.evaluate(() => Number(state.__navigationEpoch || 0));
  const apiRequests = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.pathname === `/api/projects/${projectId}/jobs`) {
      apiRequests.push(`${request.method()} ${url.pathname}${url.search}`);
    }
  });

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
    resume_epoch_source: 'checkpoint_start_epoch',
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

  const finalizationReplayJob = {
    id: 'job-finalize-replay',
    status: 'running',
    task_status: 'RUNNING',
    persisted_status: 'RUNNING',
    phase: 'finalizing_commit',
    task_stage: 'finalizing_commit',
    asset_algorithm_name: '烟火识别算法 · 归档恢复',
    framework: 'ultralytics',
    progress_percent: 98,
    recovery_mode: 'finalization_replay',
    recovery_state: 'finalizing_commit',
    recovery_auto: true,
    recovery_attempted: true,
    recovery_completed: false,
    final_validation_reused: true,
    current_epoch: 100,
    total_epochs: 100,
    requested_epochs: 100,
    assigned_device: 'cuda:0',
    actual_device: 'cuda:0',
    task_worker_id: 'gpu-worker-b',
    current_item: 'Final Validation 已通过，正在恢复结果与算法版本归档',
    elapsed_seconds: 2400,
    eta_seconds: 0,
    created_at: '2026-09-17T00:01:00Z',
    training_progress: {
      epoch: 100,
      total_epochs: 100,
      resumed: false,
    },
  };

  await page.route(`**/api/projects/${encoded}/jobs`, async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([resumeJob, finalizationReplayJob]),
    });
  });

  apiRequests.length = 0;
  await page.locator('#refreshBtn').click();
  await expect.poll(async () => page.evaluate(() => window.TrainingTaskRuntime?.state?.().inflight ?? null))
    .toBe(false);
  expect(await page.evaluate(() => Number(state.__navigationEpoch || 0))).toBe(startNavigationEpoch);
  expect(apiRequests).toEqual([`GET /api/projects/${projectId}/jobs`]);
  await expect.poll(async () => page.evaluate(() => {
    const ids = new Set((state.jobs || []).map(job => job.id));
    return ids.has('job-resume-36') && ids.has('job-finalize-replay');
  })).toBe(true);
  await page.evaluate(() => {
    state.train428Tab = 'active';
    window.TrainingTaskRuntime?.patch?.();
    window.TrainingCheckpointResumeUI?.decorate?.();
  });

  const resumeRow = page.locator('[data-job-id="job-resume-36"]');
  await expect(resumeRow).toBeVisible({timeout: 10_000});
  await expect(resumeRow).toContainText('烟火识别算法');
  await expect(resumeRow).toContainText('Epoch 41/100');
  await expect(resumeRow).toContainText('断点续训 · 从 Epoch 36');
  await expect(resumeRow.locator('.checkpoint-resume-badge')).toHaveCount(1);

  await resumeRow.getByRole('button', {name: '详情'}).click();
  let dialog = page.locator('[data-checkpoint-resume-overlay]');
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText('正在从 Checkpoint 恢复训练');
  await expect(dialog).toContainText('Epoch 36');
  await expect(dialog).toContainText('41 / 100');
  await expect(dialog).toContainText('last.pt');
  await expect(dialog).toContainText('cuda:0');
  await expect(dialog).toContainText('gpu-worker-a');
  await expect(dialog).toContainText('按 Checkpoint 内的 start_epoch 校正真实恢复轮次');
  await expect(dialog.getByRole('button', {name: '重新验证 Checkpoint'})).toHaveCount(0);

  await page.evaluate(() => {
    window.__resumeLogTask = null;
    window.showTrainLog423 = id => { window.__resumeLogTask = id; };
  });
  await dialog.getByRole('button', {name: '查看训练日志'}).click();
  await expect(dialog).toBeHidden();
  await expect.poll(async () => page.evaluate(() => window.__resumeLogTask)).toBe('job-resume-36');

  const replayRow = page.locator('[data-job-id="job-finalize-replay"]');
  await expect(replayRow).toBeVisible();
  await expect(replayRow).toContainText('烟火识别算法 · 归档恢复');
  await expect(replayRow).toContainText('恢复归档 · 跳过重训和重验证');
  await expect(replayRow.locator('.checkpoint-resume-badge')).toHaveCount(1);

  await replayRow.getByRole('button', {name: '详情'}).click();
  dialog = page.locator('[data-checkpoint-resume-overlay]');
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText('正在恢复训练结果归档');
  await expect(dialog).toContainText('Final Validation');
  await expect(dialog).toContainText('已通过并复用');
  await expect(dialog).toContainText('结果与版本归档');
  await expect(dialog).toContainText('不重新训练，也不重新执行 Final Validation');
  await expect(dialog).toContainText('gpu-worker-b');
  await expect(dialog.getByRole('button', {name: '重新验证 Checkpoint'})).toHaveCount(0);
  await dialog.getByRole('button', {name: '关闭'}).first().click();
  await expect(dialog).toBeHidden();

  expect(pageErrors).toEqual([]);
});

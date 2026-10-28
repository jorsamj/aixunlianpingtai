import {test, expect} from '@playwright/test';
import path from 'node:path';

test('failed final validation exposes backend-approved checkpoint recovery and requeues the same task', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));
  page.on('dialog', dialog => dialog.accept());

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await expect.poll(
    () => page.evaluate(() => typeof window.setPage === 'function' && typeof state !== 'undefined' && state.uiReady === true),
    {timeout: 15_000},
  ).toBe(true);
  await page.evaluate(() => window.setPage('训练任务'));
  await expect(page.locator('.train428-page')).toBeVisible({timeout: 10_000});
  await expect.poll(async () => page.evaluate(() => window.TrainingRecoveryRuntime?.build || null))
    .toBe('training-recovery-runtime-4226391');
  await expect.poll(async () => page.evaluate(() => window.TrainingTaskRuntime?.build || null))
    .toMatch(/^training-task-runtime-/);

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
  await page.evaluate(() => window.setTrainTab428?.('history'));
  const row = page.locator('[data-job-id="job-recovery-1"]');
  await expect(row).toBeVisible();
  await expect(row).toContainText('最终验证恢复测试');
  await expect(row).toContainText('可恢复 · Checkpoint 已保留');
  await expect(row).toContainText('100/100');

  await row.getByRole('button', {name: '详情'}).click();
  const dialog = page.locator('[data-training-recovery-overlay]');
  await expect(dialog).toBeVisible();
  await page.evaluate(()=>document.body.insertAdjacentHTML('beforeend','<div id="training-acceptance-fixture-badge" style="position:fixed;right:12px;bottom:12px;z-index:10000;padding:7px 11px;border-radius:8px;background:#7c2d12;color:white;font:700 12px system-ui">验收夹具 · 非生产数据</div>'));
  await expect(dialog).toContainText('训练主体已完成 · 模型验证失败');
  await expect(dialog).toContainText('100 / 100');
  await expect(dialog).toContainText('最终模型验证');
  await expect(dialog).toContainText('best.pt');
  await expect(dialog.getByRole('button', {name: '重新验证 Checkpoint'})).toBeVisible();

  await dialog.getByRole('button', {name: '重新验证 Checkpoint'}).click();
  await expect(dialog).toBeHidden();
  await expect.poll(() => retried).toBe(true);
  await page.evaluate(() => window.setTrainTab428?.('active'));
  await expect(row).toBeVisible();
  await expect(row).toContainText('排队中');

  expect(requests).toContain(`POST /api/v62/projects/${projectId}/training-tasks/recovery-query`);
  expect(requests).toContain(`GET /api/v62/projects/${projectId}/training-tasks/job-recovery-1/recovery`);
  expect(requests).toContain(`POST /api/v62/projects/${projectId}/training-tasks/job-recovery-1/recovery`);
  expect(pageErrors).toEqual([]);
});

test('successful training detail never presents completion text as an error', async ({page},testInfo) => {
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
    runtime_metrics: {epochs:Array.from({length:30},(_,i)=>({epoch:i+1,losses:{box_loss:1-i*.02},metrics:{'metrics/mAP50(B)':i*.025}})),
      samples:[{sampled_at:'2026-09-23T10:02:00Z',gpu_utilization:80,gpu_memory_percent:70,cpu_percent:40},
        {sampled_at:'2026-09-23T10:32:00Z',gpu_utilization:0,gpu_memory_percent:0,cpu_percent:0}]},
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
  await page.evaluate(() => window.setTrainTab428?.('history'));

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
  const curveTab=dialog.getByRole('tab',{name:'训练曲线',exact:true});
  await curveTab.focus();
  await curveTab.press('ArrowRight');
  await expect(dialog.getByRole('tab',{name:'训练资源',exact:true})).toBeFocused();
  await expect(dialog.getByRole('tab',{name:'训练资源',exact:true})).toHaveAttribute('aria-selected','true');
  await dialog.getByRole('tab',{name:'训练资源',exact:true}).press('End');
  await expect(dialog.getByRole('tab',{name:'日志与诊断',exact:true})).toBeFocused();
  await dialog.getByRole('tab',{name:'日志与诊断',exact:true}).press('Home');
  await expect(curveTab).toBeFocused();

  // Live detail refresh must update the canonical dialog in place. Replacing the
  // whole overlay every 1.5s causes visible flicker and resets browser UI state.
  const dialogShell = dialog.locator('.training-recovery-dialog');
  await dialog.evaluate(node => { node.dataset.identityProbe = 'overlay-stable'; });
  await dialogShell.evaluate(node => { node.dataset.identityProbe = 'dialog-stable'; });
  await dialog.getByRole('button', {name: '立即刷新'}).click();
  await expect(dialog).toHaveAttribute('data-identity-probe', 'overlay-stable');
  await expect(dialogShell).toHaveAttribute('data-identity-probe', 'dialog-stable');
  const tabGeometry = await curveTab.evaluate(element => ({
    width: element.getBoundingClientRect().width,
    height: element.getBoundingClientRect().height,
    color: getComputedStyle(element).color,
  }));
  expect(tabGeometry.width).toBeGreaterThan(70);
  expect(tabGeometry.height).toBeGreaterThanOrEqual(40);
  expect(tabGeometry.color).not.toBe('rgba(0, 0, 0, 0)');

  for(const [width,height] of [[1920,1080],[1440,900],[1366,768],[375,812]]){
    await page.setViewportSize({width,height});
    await dialog.getByRole('tab',{name:'训练曲线',exact:true}).click();
    // Three interactive groups replace the two legacy static curves and retain actual resource observations.
    await expect(dialog.locator('[data-report-chart]')).toHaveCount(3);
    await expect(dialog.locator('[data-report-chart] canvas')).toHaveCount(3);
    expect(await dialog.locator('[data-report-chart=utilization]').evaluate(node=>window.echarts.getInstanceByDom(node).getOption().series.find(row=>row.name==='GPU %').data)).toEqual([80]);
    expect(await dialogShell.evaluate(el=>el.scrollWidth<=el.clientWidth+1)).toBe(true);
    await page.screenshot({path:path.resolve(process.env.CODEX_VISUAL_EVIDENCE_DIR||testInfo.outputPath('visuals'),'detail-'+width+'.png')});
    if(width===375)await expect(dialog.locator('.training-tabs-scroll-hint')).toBeVisible();
    await dialog.getByRole('tab',{name:'训练资源',exact:true}).click();
    await expect(dialog.locator('[role=tabpanel]:visible')).toContainText('80.0%');
    await dialog.getByRole('button',{name:'立即刷新'}).click();
    await expect(dialog.getByRole('tab',{name:'训练资源',exact:true})).toHaveAttribute('aria-selected','true');
    await dialog.getByRole('tab',{name:'数据与配置',exact:true}).click();
    await expect(dialog.locator('[data-training-panel=data]').first()).toContainText('32');
    await dialog.getByRole('tab',{name:'日志与诊断',exact:true}).click();
    await expect(dialog.locator('[data-training-tech-log] pre')).toContainText('training completed');
  }

  expect(pageErrors).toEqual([]);
});

test('running training detail shows frozen resource truth, closes with Escape, and restores focus', async ({page}, testInfo) => {
  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await expect.poll(
    () => page.evaluate(() => typeof window.setPage === 'function' && typeof state !== 'undefined' && state.uiReady === true),
    {timeout: 15_000},
  ).toBe(true);
  await page.evaluate(() => window.setPage('训练任务'));
  const projectId = await page.evaluate(() => state.project?.id);
  const encoded = encodeURIComponent(projectId);
  const taskId = 'job-running-resource-truth';
  const job = {
    id: taskId,
    task_id: taskId,
    status: 'running',
    task_status: 'RUNNING',
    task_stage: 'training',
    progress_percent: 18,
    current_epoch: 3,
    total_epochs: 80,
    current_batch: 21,
    total_batches: 103,
    elapsed_seconds: 95,
    eta_seconds: 2400,
    asset_algorithm_name: '道路病害检测',
    task_name: 'A800 自动资源训练',
    created_at: '2026-10-15T12:00:00Z',
    started_at: '2026-10-15T12:01:00Z',
    requested_resources: {resource_strategy: 'auto', resource_profile: 'performance', batch: 75, workers: 11, precision: 'fp16', cache: false},
    resolved_resources: {
      resource_strategy: 'auto', resource_profile: 'performance', resolved_batch: 64, resolved_workers: 6,
      resolved_precision: 'fp16', resolved_cache: false, host_memory_source: 'cgroup_v2',
      available_ram_bytes: 20 * 1024 ** 3, host_memory_budget_bytes: 14 * 1024 ** 3,
      estimated_host_memory_bytes: 12 * 1024 ** 3, cgroup_memory_limit_bytes: 31 * 1024 ** 3,
      host_memory_prefetch_factor: 2, reasons: ['Execution-node host memory joint budget'],
    },
    runtime_resources: {runtime_batch: 64, runtime_workers: 6, runtime_cache: false, actual_precision: 'fp16'},
    runtime_metrics: {latest: {
      sampled_at: '2026-10-15T12:02:30Z', gpu_utilization: 81, gpu_memory_percent: 62,
      cpu_percent: 45, memory_percent: 70, io_wait_percent: 2,
      process_tree_memory_bytes: 9 * 1024 ** 3, process_tree_peak_memory_bytes: 10 * 1024 ** 3,
      process_tree_count: 8, process_tree_memory_measure: 'uss',
    }},
  };
  await page.route(`**/api/projects/${encoded}/jobs`, route => route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify([job])}));
  await page.route(`**/api/projects/${encoded}/jobs/${taskId}*`, route => route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(job)}));
  await page.route(`**/api/projects/${encoded}/jobs/${taskId}/log`, route => route.fulfill({status: 200, contentType: 'text/plain', body: 'Epoch 3/80'}));

  await page.locator('#refreshBtn').click();
  await page.evaluate(() => window.setTrainTab428?.('active'));
  const detailButton = page.locator(`[data-job-id="${taskId}"]`).getByRole('button', {name: '详情'});
  await detailButton.click();
  const dialog = page.locator('[data-training-recovery-overlay]');
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText('偏好 75');
  await dialog.getByRole('tab', {name: '训练资源', exact: true}).click();
  await expect(dialog).toContainText('12.00 GB / 14.00 GB');
  await expect(dialog).toContainText('9.00 GB · 峰值 10.00 GB');
  await expect(dialog).not.toContainText('mAP50 0.0%');
  await page.setViewportSize({width: 1440, height: 900});
  await page.waitForTimeout(240);
  const runningTabs = await dialog.locator('[data-training-tab]').evaluateAll(elements => elements.map(element => ({
    text: element.textContent?.trim(),
    width: element.getBoundingClientRect().width,
    height: element.getBoundingClientRect().height,
    color: getComputedStyle(element).color,
    display: getComputedStyle(element).display,
    visibility: getComputedStyle(element).visibility,
  })));
  expect(runningTabs.map(tab => tab.text)).toEqual(['训练曲线', '训练资源', '数据与配置', '日志与诊断']);
  expect(runningTabs.every(tab => tab.width > 70 && tab.height >= 40)).toBe(true);
  expect(runningTabs.every(tab => tab.display !== 'none' && tab.visibility === 'visible')).toBe(true);
  expect(runningTabs.every(tab => tab.color !== 'rgba(0, 0, 0, 0)')).toBe(true);
  await page.screenshot({path: path.resolve(process.env.CODEX_VISUAL_EVIDENCE_DIR || testInfo.outputPath('visuals'), 'detail-running-1440.png')});
  await page.keyboard.press('Escape');
  // Reopening during the 190ms exit transition must cancel the stale removal
  // timer instead of deleting the newly rendered detail dialog.
  await detailButton.evaluate(button => button.click());
  await expect(page.locator('[data-training-recovery-overlay]')).toBeVisible();
  await page.waitForTimeout(240);
  await expect(page.locator('[data-training-recovery-overlay]')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.locator('[data-training-recovery-overlay]')).toBeHidden();
  await expect(detailButton).toBeFocused();
});

test('failed SIGKILL detail shows backend uncertainty, actions, and no false recovery', async ({page}, testInfo) => {
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

  const projectId = await page.evaluate(() => state.project?.id);
  const encoded = encodeURIComponent(projectId);
  const taskId = 'job-sigkill-unknown';
  const job = {
    id: taskId,
    task_id: taskId,
    status: 'failed',
    task_status: 'FAILED',
    task_stage: 'training_process',
    failure_stage: 'training_process',
    process_returncode: -9,
    process_signal: 'SIGKILL',
    current_epoch: 1,
    total_epochs: 80,
    asset_algorithm_name: '道路病害检测',
    current_item: '训练进程异常终止',
    actual_device: 'cuda:0',
    actual_train_params: {batch: 117, workers: 11, cache: false, effective_precision: 'fp16'},
  };
  const recovery = {
    task_id: taskId,
    project_id: projectId,
    task_status: 'FAILED',
    available: false,
    recoverable: false,
    checkpoint_available: false,
    failure_stage: 'training_process',
    primary_stage: 'worker_process',
    primary_message: 'training process terminated by SIGKILL',
    process_returncode: -9,
    process_signal: 'SIGKILL',
    diagnosis: {
      code: 'SIGKILL_CAUSE_UNKNOWN',
      certainty: 'unknown',
      title: '训练被系统强制终止',
      summary: '训练进程收到 SIGKILL，但目前没有足够证据确认发送者或原因。',
      evidence: ['训练进程收到 SIGKILL（returncode=-9）。', '未找到与本任务关联的 Kernel/cgroup OOM 证据。'],
      possible_causes: ['系统内存不足', 'Worker 执行权限或租约变化', '外部进程终止', '服务或容器资源限制'],
      suggestions: ['查看系统 OOM、Worker 和任务执行日志。', '确认运行环境后重新创建训练任务。'],
      checkpoint_message: '当前没有可恢复的训练断点，需要重新创建训练任务。',
    },
  };

  await page.route(`**/api/projects/${encoded}/jobs`, route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify([job]),
  }));
  await page.route(`**/api/projects/${encoded}/jobs/${taskId}`, route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify(job),
  }));
  await page.route(`**/api/projects/${encoded}/jobs/${taskId}/log`, route => route.fulfill({
    status: 200, contentType: 'text/plain', body: 'training process terminated by SIGKILL',
  }));
  await page.route(`**/api/v62/projects/${encoded}/training-tasks/recovery-query`, route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({ok: true, items: {[taskId]: recovery}}),
  }));
  await page.route(`**/api/v62/projects/${encoded}/training-tasks/${taskId}/recovery`, route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({ok: true, recovery}),
  }));

  await page.locator('#refreshBtn').click();
  await page.evaluate(() => window.setTrainTab428?.('history'));
  const row = page.locator(`[data-job-id="${taskId}"]`);
  await expect(row).toBeVisible();
  await row.getByRole('button', {name: '详情'}).click();

  const dialog = page.locator('[data-training-recovery-overlay]');
  const diagnosis = dialog.locator('[data-training-failure-diagnosis]');
  await expect(diagnosis).toBeVisible();
  await expect(diagnosis).toContainText('训练被系统强制终止');
  await expect(diagnosis).toContainText('原因未明');
  await expect(diagnosis.locator('[data-training-diagnosis-evidence]')).toContainText('SIGKILL');
  await expect(diagnosis.locator('[data-training-diagnosis-suggestions]')).toContainText('查看系统 OOM');
  await expect(diagnosis).toContainText('当前没有可恢复的训练断点，需要重新创建训练任务。');
  await expect(dialog.getByRole('button', {name: '重新验证 Checkpoint'})).toHaveCount(0);
  await expect(dialog.locator('[data-training-failure-technical]')).not.toHaveAttribute('open', '');

  await page.setViewportSize({width: 1366, height: 768});
  await page.waitForTimeout(240);
  const screenshotPath = path.resolve(
    process.env.CODEX_VISUAL_EVIDENCE_DIR || testInfo.outputPath('visuals'),
    'training-failure-diagnosis-1366x768.png',
  );
  await page.screenshot({path: screenshotPath, fullPage: false});
  expect(await dialog.locator('.training-recovery-dialog').evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
  await page.setViewportSize({width: 375, height: 812});
  await expect(diagnosis).toBeVisible();
  expect(await dialog.locator('.training-recovery-dialog').evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
  expect(pageErrors).toEqual([]);
});


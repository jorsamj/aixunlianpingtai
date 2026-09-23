import {test, expect} from '@playwright/test';

async function selectIsolatedTestProject(page, projectId, pageName = '算法列表') {
  await page.route('**/api/v53/bootstrap/snapshot**', async route => {
    const url = new URL(route.request().url());
    url.searchParams.set('preferred_project_id', projectId);
    await route.fallback({url: url.toString()});
  });
  await page.addInitScript(savedPage => {
    localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({page: savedPage}));
  }, pageName);
}

async function seedProject(request) {
  const project = await (await request.post('/api/projects', {data: {
    name: `首次训练弹窗-${Date.now()}`,
    labels: [{code: 'smoke', display_name: '烟雾'}],
  }})).json();
  const created = await (await request.post(`/api/v12/projects/${project.id}/algorithms`, {data: {
    name: '首次打开配置回归',
    industry: '测试',
    algorithm_type: 'yolo_ultralytics',
    remark: '',
  }})).json();
  return {project, algorithmId: created.algorithm.id};
}

test('hard refresh first training open shows a shell before hydrating configuration', async ({page, request}) => {
  const {project} = await seedProject(request);
  let trainingOptionsCalls = 0;
  let recommendationCalls = 0;
  let trainingDeviceCalls = 0;
  let holdHydration = false;
  let releaseHydration;
  const hydrationGate = new Promise(resolve => { releaseHydration = resolve; });

  await page.route('**/api/v53/bootstrap/snapshot**', async route => {
    const response = await route.fetch();
    const snapshot = await response.json();
    snapshot.targets = [{id: 'stale-ready-target', name: '未完成配置', status: 'ready'}];
    snapshot.recommendation = null;
    await route.fulfill({response, json: snapshot});
  });
  await page.route('**/api/training_options**', route => {
    trainingOptionsCalls += 1;
    return (async () => {
      if (holdHydration) await hydrationGate;
      return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({targets: [{
        id: 'first-open-ultralytics',
        name: '首次打开 Ultralytics',
        type: 'local',
        framework: 'ultralytics',
        status: 'ready',
        algorithms: [{
          key: 'yolo_detect',
          name: 'Ultralytics Detect',
          base_model: 'yolo11n.pt',
          default_epochs: 20,
          default_imgsz: 640,
          default_batch: 4,
        }],
        base_models: [{value: 'yolo11n.pt', label: 'YOLO11n'}],
      }]})
      });
    })();
  });
  await page.route('**/api/system/recommendation', route => {
    recommendationCalls += 1;
    return (async () => {
      if (holdHydration) await hydrationGate;
      return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({device: 'cpu', batch: 4, workers: 0}),
      });
    })();
  });
  await page.route('**/api/v62/training-devices', route => {
    trainingDeviceCalls += 1;
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({recommended: 'cpu', options: [{id: 'cpu', label: 'CPU', available: true}]}),
    });
  });

  await selectIsolatedTestProject(page, project.id, '算法列表');

  await page.goto('/');
  await expect.poll(async () => page.evaluate(() => window.TrainingCreateHydrationRuntime?.build || null))
    .toBe('training-create-hydration-422535');

  // Reproduce the user's actual sequence: refresh, then open the training dialog once.
  await page.reload();
  await expect.poll(async () => page.evaluate(() => window.TrainingCreateHydrationRuntime?.build || null))
    .toBe('training-create-hydration-422535');
  await expect.poll(async () => page.evaluate(() => state.uiReady === true)).toBe(true);
  expect(await page.evaluate(() => ({
    targetId: state.targets?.[0]?.id,
    hasAlgorithms: Array.isArray(state.targets?.[0]?.algorithms),
    recommendation: state.rec,
  }))).toEqual({
    targetId: 'stale-ready-target',
    hasAlgorithms: false,
    recommendation: null,
  });

  const beforeOptions = trainingOptionsCalls;
  const beforeRecommendation = recommendationCalls;
  holdHydration = true;
  const card = page.locator('.alg428-card', {hasText: '首次打开配置回归'});
  await card.getByRole('button', {name: '训练'}).click();

  const shell = page.locator('[data-training-create-shell="1"]');
  await expect(shell).toBeVisible({timeout: 1_000});
  await expect(shell.getByRole('button', {name: '重试'})).toBeDisabled();
  releaseHydration();
  const dialog = page.getByRole('dialog', {name: '训练 · 首次打开配置回归'});
  await expect(dialog).toBeVisible({timeout: 10_000});
  await expect(dialog.locator('#tr429Target')).toHaveValue('first-open-ultralytics');
  await expect(dialog.locator('#tr429Target')).toContainText('首次打开 Ultralytics');
  await expect(dialog.locator('#tr429Alg')).toHaveValue('yolo_detect');
  await expect(dialog.locator('#tr429Model')).toHaveText('yolo11n.pt');

  expect(trainingOptionsCalls).toBe(beforeOptions + 1);
  expect(recommendationCalls).toBe(beforeRecommendation + 1);
  expect(await page.evaluate(() => ({
    targetId: state.targets?.[0]?.id,
    algorithmKey: state.targets?.[0]?.algorithms?.[0]?.key,
    model: state.targets?.[0]?.base_models?.[0]?.value,
    recommendationDevice: state.rec?.device,
  }))).toEqual({
    targetId: 'first-open-ultralytics',
    algorithmKey: 'yolo_detect',
    model: 'yolo11n.pt',
    recommendationDevice: 'cpu',
  });
  await expect.poll(() => trainingDeviceCalls).toBeGreaterThan(0);
  const deviceCallsAfterFirstOpen = trainingDeviceCalls;
  expect(await page.evaluate(projectId => {
    const cached = JSON.parse(localStorage.getItem(`cl_training_devices_v3_${projectId}`) || 'null');
    return {
      hasCache: Boolean(cached?.devices?.options?.length),
      recommended: cached?.devices?.recommended || null,
    };
  }, project.id)).toEqual({hasCache: true, recommended: 'cpu'});

  // A full browser reload must restore the recent 24h device inventory instead of probing hardware again.
  await page.evaluate(() => window.closeModal());
  await page.reload();
  await expect.poll(async () => page.evaluate(() => state.uiReady === true)).toBe(true);
  const reloadedCard = page.locator('.alg428-card', {hasText: '首次打开配置回归'});
  await reloadedCard.getByRole('button', {name: '训练'}).click();
  const secondDialog = page.getByRole('dialog', {name: '训练 · 首次打开配置回归'});
  await expect(secondDialog).toBeVisible({timeout: 10_000});
  await expect(secondDialog.locator('#trV3Device')).toContainText('CPU');
  await page.waitForTimeout(180);
  expect(trainingDeviceCalls).toBe(deviceCallsAfterFirstOpen);
});


test('training target is the only automatic early-stop control', async ({page, request}) => {
  const {project} = await seedProject(request);

  await page.route('**/api/training_options**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({targets: [{
      id: 'target-stop-training',
      name: '目标停止训练',
      type: 'local',
      framework: 'ultralytics',
      status: 'ready',
      algorithms: [{
        key: 'yolo_detect',
        name: 'Ultralytics Detect',
        base_model: 'yolo11n.pt',
        default_epochs: 100,
        default_imgsz: 640,
        default_batch: 4,
      }],
      base_models: [{value: 'yolo11n.pt', label: 'YOLO11n'}],
    }]})
  }));
  await page.route('**/api/system/recommendation', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({device: 'cpu', batch: 4, workers: 0}),
  }));
  await page.route('**/api/v62/training-devices', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({recommended: 'cpu', options: [{id: 'cpu', label: 'CPU', available: true}]}),
  }));

  await selectIsolatedTestProject(page, project.id, '算法列表');
  await page.goto('/');
  await expect.poll(async () => page.evaluate(() => state.uiReady === true)).toBe(true);

  const card = page.locator('.alg428-card', {hasText: '首次打开配置回归'});
  await card.getByRole('button', {name: '训练'}).click();
  const dialog = page.getByRole('dialog', {name: '训练 · 首次打开配置回归'});
  await expect(dialog).toBeVisible({timeout: 10_000});

  await dialog.getByText('进阶配置（可选）', {exact: true}).click();
  await expect(dialog.getByRole('button', {name: '编辑全部训练参数'})).toBeVisible();
  await dialog.getByRole('button', {name: '编辑全部训练参数'}).click();
  const settings = page.getByRole('dialog', {name: '训练配置设置'});
  await expect(settings).toBeVisible();
  await expect(settings.getByText('阶段试验与目标')).toBeVisible();
  await expect(settings.getByText('未达继续 / 达标提前完成')).toBeVisible();
  await expect(settings.getByText('目标指标', {exact: true})).toBeVisible();
  await expect(settings.locator('#ts428Metric')).toHaveValue('map50');
  await expect(settings.getByText('目标正确率', {exact: true})).toBeVisible();
  await expect(settings.locator('#ts428Goal')).toHaveValue('90');
  await expect(settings.locator('#ts428Low')).toHaveCount(0);
  await expect(settings.locator('#ts428Patience')).toHaveCount(0);
  await expect(settings.getByText('低于此正确率停止')).toHaveCount(0);

  await settings.getByRole('button', {name: '应用配置'}).click();
  await expect(dialog.locator('#tr429Gate')).toContainText('≥ 90.0%');
  const config = await page.evaluate(() => window.trainingConfigCanonical428?.());
  expect(config.stop_threshold).toBe(0.9);
  expect(config.continue_threshold).toBe(0);
});


test('frozen feedback candidates stay aligned with training submit provenance', async ({page, request}) => {
  const {project, algorithmId} = await seedProject(request);
  let submitted = null;
  let durableTask = null;
  let jobListReads = 0;

  await page.route('**/api/v53/bootstrap/snapshot**', async route => {
    const response = await route.fetch();
    const snapshot = await response.json();
    snapshot.jobs = durableTask ? [{
      ...durableTask,
      id: durableTask.task_id,
      asset_algorithm_id: algorithmId,
      framework: 'ultralytics',
      queue_priority: 50,
    }] : [];
    await route.fulfill({response, json: snapshot});
  });
  await page.route('**/api/projects/*/jobs', async route => {
    jobListReads += 1;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(durableTask ? [{
        ...durableTask,
        id: durableTask.task_id,
        asset_algorithm_id: algorithmId,
        framework: 'ultralytics',
        queue_priority: 50,
      }] : []),
    });
  });

  await page.route('**/api/training_options**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({targets: [{
      id: 'feedback-training-target',
      name: 'Feedback Training',
      type: 'local',
      framework: 'ultralytics',
      status: 'ready',
      algorithms: [{
        key: 'yolo_detect',
        name: 'Ultralytics Detect',
        base_model: 'yolo11n.pt',
        default_epochs: 20,
        default_imgsz: 640,
        default_batch: 4,
      }],
      base_models: [{value: 'yolo11n.pt', label: 'YOLO11n'}],
    }]})
  }));
  await page.route('**/api/system/recommendation', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({device: 'cpu', batch: 4, workers: 0}),
  }));
  await page.route('**/api/v62/training-devices', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      recommended: 'cpu',
      options: [{id: 'cpu', label: 'CPU', available: true}],
    }),
  }));
  await page.route('**/api/v62/projects/*/training-materials/selection-summary', async route => {
    const body = route.request().postDataJSON();
    const count = Array.isArray(body?.image_ids) ? body.image_ids.length : 0;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        requested_count: count,
        matched_count: count,
        eligible_count: count,
        eligible_total: count,
        box_count: count,
        size_bytes: count * 1024,
        label_codes: ['smoke'],
        label_counts: {smoke: count},
        repository_revision: 1,
      }),
    });
  });
  await page.route('**/api/v12/projects/*/train/start', async route => {
    submitted = route.request().postDataJSON();
    durableTask = {
      task_id: submitted.task_id,
      kind: 'TRAINING',
      task_type: 'TRAINING',
      status: 'QUEUED',
      persisted_status: 'QUEUED',
      phase: 'queued',
      progress_percent: 0,
      created_at: '2026-09-21T08:00:00Z',
    };
    await route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify({ok: true, task: durableTask}),
    });
  });

  await selectIsolatedTestProject(page, project.id, '算法列表');
  await page.goto('/');
  await expect.poll(async () => page.evaluate(() => state.uiReady === true)).toBe(true);

  const card = page.locator('.alg428-card', {hasText: '首次打开配置回归'});
  await card.getByRole('button', {name: '训练'}).click();
  const dialog = page.getByRole('dialog', {name: '训练 · 首次打开配置回归'});
  await expect(dialog).toBeVisible({timeout: 10_000});
  await expect(dialog.locator('#tr429Target')).toHaveValue('feedback-training-target');

  await page.evaluate(({algorithmId}) => {
    const asset = (state.algorithms || []).find(row => String(row?.id || '') === String(algorithmId));
    if (!asset) throw new Error('algorithm missing from browser state');
    asset.current_version_id = 'feedback-version';
    asset.versions = [{
      id: 'feedback-version',
      version_name: '20260919120000',
      training_status: 'SUCCEEDED',
      artifact_verified: true,
      trainable: true,
      framework: 'ultralytics',
      label_schema: [{code: 'smoke', class_id: 0}],
      supplement_data_candidate_set: {
        schema_version: 1,
        status: 'confirmed',
        candidate_set_id: 'a'.repeat(64),
        material_ids: ['feedback-material'],
      },
    }];
    window.TrainingDraftRuntime.update({algorithmId});
    window.TrainingDraftRuntime.setMaterialIds(['feedback-material', 'normal-material']);
  }, {algorithmId});

  await expect(dialog.locator('[data-supplement-candidate-summary]')).toContainText('反馈补数据');
  await expect(dialog.locator('[data-supplement-candidate-value]')).toHaveText('1 / 1 张');

  const submitButton = dialog.getByRole('button', {name: '开始训练'});
  await expect(submitButton).toBeEnabled();
  const jobListReadsBeforeSubmit = jobListReads;
  await submitButton.click();
  await expect.poll(() => submitted).not.toBeNull();
  expect(submitted.supplement_candidate_set_id).toBe('a'.repeat(64));
  expect(submitted.train_image_ids).toEqual(['feedback-material', 'normal-material']);
  const createdTaskId = submitted.task_id;
  await expect.poll(async () => page.evaluate(taskId => (
    state.jobs || []
  ).some(job => String(job.task_id || job.id || '') === taskId), createdTaskId)).toBe(true);
  expect(jobListReads).toBe(jobListReadsBeforeSubmit + 1);
  const jobListReadsAfterSubmit = jobListReads;

  await page.evaluate(() => window.setPage('训练任务'));
  const createdRow = page.locator(`.train428-table tbody tr[data-job-id="${createdTaskId}"]`);
  await expect(createdRow).toBeVisible();
  await expect(createdRow).not.toContainText(createdTaskId);
  await expect.poll(() => jobListReads).toBeGreaterThan(jobListReadsAfterSubmit);

  await page.reload();
  await expect.poll(async () => page.evaluate(() => state.uiReady === true)).toBe(true);
  expect(await page.evaluate(taskId => (
    state.jobs || []
  ).some(job => String(job.task_id || job.id || '') === taskId), createdTaskId)).toBe(true);
  await page.evaluate(() => window.setPage('训练任务'));
  const restoredRow = page.locator(`.train428-table tbody tr[data-job-id="${createdTaskId}"]`);
  await expect(restoredRow).toBeVisible();
  await expect(restoredRow).not.toContainText(createdTaskId);
});


test('verified fixed benchmark stays aligned from backend availability to training submit', async ({page, request}) => {
  const {project, algorithmId} = await seedProject(request);
  let submitted = null;
  const scopeId = 'b'.repeat(64);
  await page.route('**/api/training_options**', route => route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({targets:[{id:'benchmark-training-target',name:'Benchmark Training',type:'local',framework:'ultralytics',status:'ready',algorithms:[{key:'yolo_detect',name:'Ultralytics Detect',base_model:'yolo11n.pt',default_epochs:20,default_imgsz:640,default_batch:4}],base_models:[{value:'yolo11n.pt',label:'YOLO11n'}]}]})}));
  await page.route('**/api/system/recommendation', route => route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({device:'cpu',batch:4,workers:0})}));
  await page.route('**/api/v62/training-devices', route => route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({recommended:'cpu',options:[{id:'cpu',label:'CPU',available:true}]})}));
  await page.route('**/api/v12/projects/*/algorithms/*/benchmark-reuse', route => route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({available:true,algorithm_id:algorithmId,source_version_id:'benchmark-version',source_version_name:'20260919150000',scope_id:scopeId,snapshot_id:'snapshot-benchmark',test_image_count:11,binding_level:'bundle_verified'})}));
  await page.route('**/api/v62/projects/*/training-materials/selection-summary', async route => {const body=route.request().postDataJSON(),count=Array.isArray(body?.image_ids)?body.image_ids.length:0;await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({requested_count:count,matched_count:count,eligible_count:count,eligible_total:count,box_count:count,size_bytes:count*1024,label_codes:['smoke'],label_counts:{smoke:count},repository_revision:1})});});
  await page.route('**/api/v12/projects/*/train/start', async route => {submitted=route.request().postDataJSON();await route.fulfill({status:202,contentType:'application/json',body:JSON.stringify({ok:true,task:{task_id:submitted.task_id,kind:'TRAINING',task_type:'TRAINING',status:'QUEUED',persisted_status:'QUEUED',phase:'queued',progress_percent:0}})});});
  await selectIsolatedTestProject(page, project.id, '算法列表');
  await page.goto('/');
  await expect.poll(async () => page.evaluate(() => state.uiReady === true)).toBe(true);
  await page.evaluate(({algorithmId}) => {const asset=(state.algorithms||[]).find(row=>String(row?.id||'')===String(algorithmId));if(!asset)throw new Error('algorithm missing from browser state');asset.current_version_id='benchmark-version';asset.versions=[{id:'benchmark-version',version_name:'20260919150000',training_status:'SUCCEEDED',artifact_verified:true,trainable:true,framework:'ultralytics',label_schema:[{code:'smoke',class_id:0}]}];}, {algorithmId});
  const card=page.locator('.alg428-card',{hasText:'首次打开配置回归'});
  await card.getByRole('button',{name:'训练'}).click();
  const dialog=page.getByRole('dialog',{name:'训练 · 首次打开配置回归'});
  await expect(dialog).toBeVisible({timeout:10000});
  await expect(dialog.locator('[data-benchmark-reuse="available"]')).toContainText('11 张');
  await expect(dialog.locator('#trV3BenchmarkReuse')).toBeChecked();
  await expect(dialog.locator('[data-benchmark-mode]')).toContainText('服务端固定 Benchmark');
  await expect(dialog.locator('.train-v3-summary>div').first().locator('span')).toHaveText('训练候选素材');
  await expect(dialog.locator('.train-v3-note')).toContainText('系统自动保留');
  await page.evaluate(({algorithmId}) => {window.TrainingDraftRuntime.update({algorithmId});window.TrainingDraftRuntime.setMaterialIds(['train-material-a','train-material-b']);window.TrainingSubmitRuntime.updateReadiness();}, {algorithmId});
  const submitButton=dialog.getByRole('button',{name:'开始训练'});
  await expect(submitButton).toBeEnabled();
  await submitButton.click();
  await expect.poll(()=>submitted).not.toBeNull();
  expect(submitted.benchmark_source_version_id).toBe('benchmark-version');
  expect(submitted.benchmark_scope_id).toBe(scopeId);
  expect(submitted.test_image_ids).toBeUndefined();
  expect(submitted.experiment_percent).toBeUndefined();
});

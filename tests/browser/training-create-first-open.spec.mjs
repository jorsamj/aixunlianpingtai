import {test, expect} from '@playwright/test';

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

test('hard refresh first training open hydrates configuration before showing the dialog', async ({page, request}) => {
  const {project} = await seedProject(request);
  let trainingOptionsCalls = 0;
  let recommendationCalls = 0;

  await page.route('**/api/v53/bootstrap/snapshot**', async route => {
    const response = await route.fetch();
    const snapshot = await response.json();
    snapshot.targets = [{id: 'stale-ready-target', name: '未完成配置', status: 'ready'}];
    snapshot.recommendation = null;
    await route.fulfill({response, json: snapshot});
  });
  await page.route('**/api/training_options**', route => {
    trainingOptionsCalls += 1;
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
  });
  await page.route('**/api/system/recommendation', route => {
    recommendationCalls += 1;
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({device: 'cpu', batch: 4, workers: 0}),
    });
  });
  await page.route('**/api/v62/training-devices', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({recommended: 'cpu', options: [{id: 'cpu', label: 'CPU', available: true}]}),
  }));

  await page.addInitScript(projectId => {
    localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({projectId, page: '算法列表'}));
  }, project.id);

  await page.goto('/');
  await expect.poll(async () => page.evaluate(() => window.TrainingCreateHydrationRuntime?.build || null))
    .toBe('training-create-hydration-422532');

  // Reproduce the user's actual sequence: refresh, then open the training dialog once.
  await page.reload();
  await expect.poll(async () => page.evaluate(() => window.TrainingCreateHydrationRuntime?.build || null))
    .toBe('training-create-hydration-422532');
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
  const card = page.locator('.alg428-card', {hasText: '首次打开配置回归'});
  await card.getByRole('button', {name: '训练'}).click();

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
});


test('frozen feedback candidates stay aligned with training submit provenance', async ({page, request}) => {
  const {project, algorithmId} = await seedProject(request);
  let submitted = null;

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
    await route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify({ok: true, task: {id: 'train_feedback_browser'}}),
    });
  });

  await page.addInitScript(projectId => {
    localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({projectId, page: '算法列表'}));
  }, project.id);
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
  await submitButton.click();
  await expect.poll(() => submitted).not.toBeNull();
  expect(submitted.supplement_candidate_set_id).toBe('a'.repeat(64));
  expect(submitted.train_image_ids).toEqual(['feedback-material', 'normal-material']);
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
  await page.route('**/api/v12/projects/*/train/start', async route => {submitted=route.request().postDataJSON();await route.fulfill({status:202,contentType:'application/json',body:JSON.stringify({ok:true,task:{id:'train_benchmark_browser'}})});});
  await page.addInitScript(projectId => {localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({projectId, page:'算法列表'}));}, project.id);
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

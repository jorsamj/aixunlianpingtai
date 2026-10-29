import {returnToTrainingConfiguration} from './helpers/training-admission.mjs';
import {test, expect} from '@playwright/test';
import {mkdir,readFile,writeFile} from 'node:fs/promises';
import path from 'node:path';

test('global robustness editor sends complete policy and retains task choices across CAS conflict',async({page,request})=>{
  const {project}=await seedProject(request);
  const originalPolicy=(await(await request.get('/api/v62/training/robustness-policy')).json()).policy;
  try{
  await page.route('**/api/training_options**',route=>route.fulfill({json:{targets:[{id:'global-policy-cpu',name:'CPU',type:'local',framework:'ultralytics',status:'ready',algorithms:[{key:'yolo_detect',default_epochs:150,default_imgsz:640}],base_models:[{value:'yolo11n.pt',model_status:'FOUND'}]}]}}));
  await page.route('**/api/system/recommendation',route=>route.fulfill({json:{device:'cpu',batch:1,workers:0}}));await page.route('**/api/v62/training-devices',route=>route.fulfill({json:{recommended:'cpu',options:[{id:'cpu',label:'CPU',available:true}]}}));
  await selectIsolatedTestProject(page,project.id);await page.goto('/');await expect.poll(()=>page.evaluate(()=>Boolean(window.TrainingCreateHydrationRuntime&&state.uiReady))).toBe(true);await page.locator('.alg428-card',{hasText:'首次打开配置回归'}).getByRole('button',{name:'训练',exact:true}).click();const dialog=page.getByRole('dialog',{name:'创建训练任务'});await dialog.locator('[data-training-step-next]').click();
  const global=dialog.locator('.training-global-policy');await global.locator('summary').click();await expect(global.locator('[data-robustness-global-save]')).toBeEnabled();const taskBefore=await page.evaluate(()=>JSON.stringify(state.trainingDraft.robustness_policy));
  await global.locator('[data-robustness-global-mode]').selectOption('enabled');await global.locator('[data-global-selection]').selectOption('count');await global.locator('[data-global-count]').fill('12');await global.locator('[data-global-copies]').fill('2');await global.locator('[data-global-seed]').fill('19');await global.locator('[data-global-preset="bt601_full"]').uncheck();
  const put=page.waitForResponse(response=>response.url().endsWith('/api/v62/training/robustness-policy')&&response.request().method()==='PUT');await global.locator('[data-robustness-global-save]').click();const response=await put;expect(response.ok()).toBe(true);const payload=response.request().postDataJSON();expect(payload.policy).toMatchObject({mode:'enabled',selection:{mode:'count',count:12},copies:2,seed:19,presets:['bt601_limited','bt709_limited','bt709_full']});expect(payload.expected_revision).toBeDefined();await expect(global.locator('[data-robustness-global-feedback]')).toContainText('已保存');expect(await page.evaluate(()=>JSON.stringify(state.trainingDraft.robustness_policy))).toBe(taskBefore);await expect(dialog.locator('[data-robustness-global-preview]')).toContainText('12');
  const latest=await(await request.get('/api/v62/training/robustness-policy')).json();const external=await request.put('/api/v62/training/robustness-policy',{data:{policy:{...latest.policy,seed:20},expected_revision:latest.revision}});expect(external.ok()).toBe(true);await global.locator('[data-global-seed]').fill('21');const conflict=page.waitForResponse(res=>res.url().endsWith('/api/v62/training/robustness-policy')&&res.request().method()==='PUT');await global.locator('[data-robustness-global-save]').click();expect((await conflict).status()).toBe(409);await expect(global.locator('[data-robustness-global-feedback]')).not.toContainText('已保存');await expect(global.locator('[data-global-seed]')).toHaveValue('21');expect(await page.evaluate(()=>JSON.stringify(state.trainingDraft.robustness_policy))).toBe(taskBefore);
  }finally{const current=await(await request.get('/api/v62/training/robustness-policy')).json();const restored=await request.put('/api/v62/training/robustness-policy',{data:{policy:originalPolicy,expected_revision:current.revision}});expect(restored.ok()).toBe(true)}
});

test('formal workbench opens while independent resources and recommendation settle without losing edits',async({page,request,context})=>{
  const {project}=await seedProject(request),samples=[];
  for(const controlled of [false,true]){
    const probe=controlled?await context.newPage():page;
    let releaseResources,releaseRecommendation,optionsCalls=0,recommendationCalls=0,failedDiagnostics=null;
    const resourceGate=new Promise(resolve=>releaseResources=resolve),recommendationGate=new Promise(resolve=>releaseRecommendation=resolve);
    const options={targets:[{id:'progressive-cpu',name:'隔离CPU',type:'local',framework:'ultralytics',status:'ready',algorithms:[{key:'yolo_detect',default_epochs:150,default_imgsz:640,default_batch:1}],base_models:[{value:'yolo11n.pt',label:'YOLO11n',model_status:'FOUND'}]}]};
    await probe.route('**/api/training_options**',async route=>{optionsCalls++;if(controlled)await resourceGate;return route.fulfill({json:options})});
    await probe.route('**/api/system/recommendation',async route=>{recommendationCalls++;if(controlled&&recommendationCalls===1){await recommendationGate;return route.fulfill({status:500,json:{detail:'controlled recommendation failure'}})}return route.fulfill({json:{device:'cpu',batch:1,workers:0}})});
    await probe.route('**/api/v62/training-devices',route=>route.fulfill({json:{recommended:'cpu',options:[{id:'cpu',label:'CPU',available:true}]}}));
    // This isolated hydration test must supply an actually selected formal
    // positive fixture; the full project catalog is no longer label evidence.
    await probe.route('**/api/v62/projects/*/training-materials/selection-summary',async route=>{
      const ids=route.request().postDataJSON()?.image_ids||[];
      const count=ids.includes('hydration-positive-smoke')?1:0;
      await route.fulfill({json:{requested_count:ids.length,matched_count:count,selectable_count:count,
        eligible_count:count,eligible_total:count,box_count:count,size_bytes:count*1024,
        label_codes:count?['smoke']:[],positive_label_codes:count?['smoke']:[],
        label_counts:count?{smoke:count}:{},repository_revision:1}});
    });
    await selectIsolatedTestProject(probe,project.id);await probe.goto('/');await expect.poll(()=>probe.evaluate(()=>Boolean(window.TrainingCreateHydrationRuntime&&state.uiReady))).toBe(true);
    const button=probe.locator('.alg428-card',{hasText:'首次打开配置回归'}).getByRole('button',{name:'训练',exact:true});await button.evaluate(node=>node.addEventListener('click',()=>{window.__formalTrainingClickAt=performance.now()},{once:true}));await button.click();
    const dialog=probe.getByRole('dialog',{name:'创建训练任务'});await expect(dialog.locator('[data-training-step-panel="1"]')).toBeVisible();const openedInMs=await probe.evaluate(()=>performance.now()-window.__formalTrainingClickAt);expect(openedInMs).toBeLessThan(1000);
    if(controlled){
      await probe.evaluate(()=>window.TrainingDraftRuntime.setMaterialIds(['hydration-positive-smoke']));
      await expect(dialog.locator('[data-training-label-code="smoke"]')).toBeVisible();
      await expect(dialog.locator('[data-training-input="resources"]')).toHaveAttribute('data-status','loading');await dialog.locator('[data-training-label-code="smoke"]').check();await dialog.locator('[data-training-step-next]').click();await dialog.locator('[data-mode="custom"]').click();await dialog.locator('#trainWorkbenchParameters details').first().locator('summary').click();await dialog.locator('#ts428Epoch').fill('77');await dialog.locator('[data-training-step-next]').click();await expect(dialog.locator('.train-ui-submit')).toBeDisabled();
      await new Promise(resolve=>setTimeout(resolve,1000));releaseResources();releaseRecommendation();await expect.poll(()=>probe.evaluate(()=>window.TrainingCreateHydrationRuntime.diagnostics().resources.status)).toBe('ready');await expect.poll(()=>probe.evaluate(()=>window.TrainingCreateHydrationRuntime.diagnostics().recommendation.status)).toBe('error');
      failedDiagnostics=await probe.evaluate(()=>window.TrainingCreateHydrationRuntime.diagnostics());
      await dialog.locator('[data-training-step="1"]').click();await expect(dialog.locator('[data-training-label-code="smoke"]')).toBeChecked();await dialog.locator('[data-training-input-retry="recommendation"]').click();await expect.poll(()=>probe.evaluate(()=>window.TrainingCreateHydrationRuntime.diagnostics().recommendation.status)).toBe('ready');await expect(dialog.locator('[data-training-label-code="smoke"]')).toBeChecked();await dialog.locator('[data-training-step-next]').click();await expect(dialog.locator('#ts428Epoch')).toHaveValue('77');
    }else await expect.poll(()=>probe.evaluate(()=>window.TrainingCreateHydrationRuntime.diagnostics().resources.status)).toBe('ready');
    samples.push({scenario:controlled?'controlled pending then recommendation 500 and isolated retry':'normal mocked isolated inputs',clickToFormalRootMs:Math.round(openedInMs),optionsCalls,recommendationCalls,failedDiagnostics,diagnostics:await probe.evaluate(()=>window.TrainingCreateHydrationRuntime.diagnostics()),controlledGateMinimumMs:controlled?1000:0});
    expect(optionsCalls).toBe(1);expect(recommendationCalls).toBe(controlled?2:1);await probe.locator('.train-ui-cancel').click();if(controlled)await probe.close();
  }
  const directory=path.resolve('docs/images/training-workbench-20261028');await mkdir(directory,{recursive:true});const filename=path.join(directory,'load-measurements.json');let existing={};try{existing=JSON.parse(await readFile(filename,'utf8'))}catch{}await writeFile(filename,JSON.stringify({...existing,scope:existing.scope||'Isolated Chrome with intercepted resource/recommendation responses; not production latency. Timing samples and any separately measured baseline are recorded independently.',samples},null,2));
});

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

async function routeCompatibleTrainingMaterials(page) {
  // These two provenance fixtures use synthetic material IDs, like their existing compatibility stub.
  await page.route('**/api/v62/projects/*/training-materials/negative-preview',route=>route.fulfill({json:{counts:{positive:route.request().postDataJSON().train_image_ids.length,confirmed_negative:0,pending_negative:0,pending_review:0},pending_count:0,effective_label_codes:['smoke']}}));
  await page.route('**/api/v62/projects/*/training-materials/compatibility', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      compatible: true, issue_count: 0, items: [], issue_counts: {},
      filtered_count: 0, next_cursor: null,
    }),
  }));
}

test('hard refresh algorithm list prewarms training configuration before the first click', async ({page, request}) => {
  const {project} = await seedProject(request);
  let trainingOptionsCalls = 0;
  let recommendationCalls = 0;
  let trainingDeviceCalls = 0;

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
        base_models: [{value: 'yolo11n.pt', label: 'YOLO11n', model_status:'FOUND'}],
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
    .toMatch(/^training-create-hydration-/);

  // Reproduce the user's actual sequence: refresh, then open the training dialog once.
  await page.reload();
  await expect.poll(async () => page.evaluate(() => window.TrainingCreateHydrationRuntime?.build || null))
    .toMatch(/^training-create-hydration-/);
  await expect.poll(async () => page.evaluate(() => state.uiReady === true)).toBe(true);
  await expect.poll(async () => page.evaluate(() => ({
    targetId: state.targets?.[0]?.id,
    hasAlgorithms: Array.isArray(state.targets?.[0]?.algorithms),
    recommendationDevice: state.rec?.device || null,
  })), {timeout: 10_000}).toEqual({
    targetId: 'first-open-ultralytics',
    hasAlgorithms: true,
    recommendationDevice: 'cpu',
  });
  expect(trainingOptionsCalls).toBeGreaterThan(0);
  expect(recommendationCalls).toBeGreaterThan(0);

  const beforeOptions = trainingOptionsCalls;
  const beforeRecommendation = recommendationCalls;
  const card = page.locator('[data-algorithm-card]', {hasText: '首次打开配置回归'});
  await card.getByRole('button', {name: '训练'}).click();

  const dialog = page.getByRole('dialog', {name: '创建训练任务'});
  await expect(dialog).toBeVisible({timeout: 1_500});
  await expect(page.locator('[data-training-create-shell="1"]')).toHaveCount(0);
  await expect(dialog.locator('#tr429Target')).toHaveValue('first-open-ultralytics');
  await expect(dialog.locator('#tr429Target')).toContainText('首次打开 Ultralytics');
  await expect(dialog.locator('#tr429Alg')).toHaveValue('yolo_detect');
  await expect(dialog.locator('#tr429MotherModel')).toHaveValue('yolo11n.pt');
  await expect(page.locator('[data-training-admission-dialog]')).toHaveCount(0);
  await expect(dialog.locator('[data-training-admission-open]:visible')).toHaveCount(0);
  await expect(dialog.locator('.train-ui-submit')).toBeEnabled();
  await expect(dialog.locator('[data-mode="full"]')).toHaveAttribute('aria-pressed', 'true');
  // Data and labels share the first persistent panel; modes have one owner in step two.
  await expect(dialog.locator('[data-training-step-panel="1"] .train-ui-data-card')).toBeVisible();
  await expect(dialog.locator('[data-training-step-panel="1"] .train-ui-labels-card')).toBeVisible();
  await expect(dialog.locator('[data-training-step-panel="2"]')).toBeHidden();
  await expect(dialog.locator('#trainUiSummary')).toBeVisible();
  await expect(dialog.locator('.train-ui-submit')).toBeHidden();

  expect(trainingOptionsCalls).toBe(beforeOptions);
  expect(recommendationCalls).toBe(beforeRecommendation);
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
  const reloadedCard = page.locator('[data-algorithm-card]', {hasText: '首次打开配置回归'});
  await reloadedCard.getByRole('button', {name: '训练'}).click();
  const secondDialog = page.getByRole('dialog', {name: '创建训练任务'});
  await expect(secondDialog).toBeVisible({timeout: 10_000});
  await expect(secondDialog.locator('#trV3Device')).toContainText('CPU');
  await page.waitForTimeout(180);
  expect(trainingDeviceCalls).toBe(deviceCallsAfterFirstOpen);

  // Small screens keep data and labels ordered in step one; modes remain in step two.
  await page.setViewportSize({width: 760, height: 820});
  const mobileLayout = await secondDialog.evaluate(node => {
    const top = selector => node.querySelector(selector).getBoundingClientRect().top;
    return {algorithm: top('.train-ui-algorithm-card'), materials: top('.train-ui-data-card'),
      labels: top('.train-ui-labels-card')};
  });
  expect(mobileLayout.algorithm).toBeLessThan(mobileLayout.materials);
  expect(mobileLayout.materials).toBeLessThan(mobileLayout.labels);
  await expect(secondDialog.locator('[data-training-step-panel="2"]')).toBeHidden();
  await secondDialog.locator('[data-training-step="2"]').click();
  await expect(secondDialog.locator('[data-training-step-panel="1"]')).toBeHidden();
  await expect(secondDialog.locator('.train-v3-mode-card')).toBeVisible();
});



test('training dialog shows canonical inherited labels horizontally without historical audit', async ({page, request}) => {
  const {project, algorithmId} = await seedProject(request);

  await page.route('**/api/training_options**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({targets: [{
      id: 'merged-label-training',
      name: 'Merged Label Training',
      type: 'local',
      framework: 'ultralytics',
      status: 'ready',
      algorithms: [{key: 'yolo_detect', name: 'Ultralytics Detect', base_model: 'yolo11n.pt', default_epochs: 20, default_imgsz: 640, default_batch: 4}],
      base_models: [{value: 'yolo11n.pt', label: 'YOLO11n', model_status:'FOUND'}],
    }]})
  }));
  await page.route('**/api/system/recommendation', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({device: 'cpu', batch: 4, workers: 0}),
  }));
  await page.route('**/api/v62/training-devices', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({recommended: 'cpu', options: [{id: 'cpu', label: 'CPU', available: true}]}),
  }));
  await page.route('**/api/v62/projects/*/training-labels/inherited**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      has_previous_version: true,
      base_version_id: 'merged-label-version',
      base_version_name: '20260928180000',
      labels: [{code: 'smoke', display_name: '烟雾'}],
    }),
  }));
  await page.route('**/api/v62/projects/*/training-materials/selection-summary', async route => {
    const body = route.request().postDataJSON();
    const count = Array.isArray(body?.image_ids) ? body.image_ids.length : 0;
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({
        requested_count: count, matched_count: count, selectable_count: count,
        eligible_count: count, pending_annotation_count: 0, eligible_total: count,
        box_count: count, size_bytes: count * 1024,
        label_codes: ['fire', 'smoke'], positive_label_codes: ['fire', 'smoke'], label_counts: {fire: count, smoke: count}, repository_revision: 1,
      }),
    });
  });

  await selectIsolatedTestProject(page, project.id, '算法列表');
  await page.goto('/');
  await expect.poll(async () => page.evaluate(() => state.uiReady === true)).toBe(true);

  const card = page.locator('[data-algorithm-card]', {hasText: '首次打开配置回归'});
  await card.getByRole('button', {name: '训练'}).click();
  const dialog = page.getByRole('dialog', {name: '创建训练任务'});
  await expect(dialog).toBeVisible({timeout: 10_000});
  await returnToTrainingConfiguration(page);

  await page.evaluate(({algorithmId}) => {
    const algorithm = (state.algorithms || []).find(row => String(row?.id || '') === String(algorithmId));
    if (!algorithm) throw new Error('algorithm missing from browser state');
    algorithm.current_version_id = 'merged-label-version';
    algorithm.versions = [{
      id: 'merged-label-version', version_name: '20260928180000',
      training_status: 'SUCCEEDED', artifact_verified: true, trainable: true, framework: 'ultralytics',
      label_schema: [{code: 'legacy_smoke', class_id: 0}, {code: 'smoke', class_id: 1}],
    }];
    const activeSmoke = (state.labels || []).find(row => String(row?.code || '') === 'smoke')
      || {code: 'smoke', display_name: '烟雾', class_id: 0, status: 'active'};
    const activeFire = (state.labels || []).find(row => String(row?.code || '') === 'fire')
      || {code: 'fire', display_name: '明火', class_id: 0, status: 'active'};
    state.labels = [{...activeFire, status: 'active'}, {...activeSmoke, status: 'active'}];
    state.labelGovernance414 = [
      {...activeSmoke, status: 'active'},
      {code: 'legacy_smoke', display_name: '旧烟雾', class_id: 99, status: 'merged', merged_into: 'smoke'},
    ];
    window.TrainingDraftRuntime.update({algorithmId, baseVersionId: 'merged-label-version'});
    window.TrainingDraftRuntime.setMaterialIds(['merged-label-material']);
  }, {algorithmId});

  const panel = dialog.locator('#trainingLabelContractPanel');
  await expect(panel).toBeVisible();
  await expect(panel).toContainText('训练标签');
  await expect(panel).toContainText('上一版本继承');
  await expect(panel.locator('[data-training-base-label="smoke"]')).toHaveCount(1);
  await expect(panel.locator('.training-label-base-list')).toHaveCSS('display', 'flex');
  await expect(panel.locator('[data-training-label-code="smoke"]')).toHaveCount(0);
  await expect(panel.locator('[data-training-label-code="fire"]')).toHaveCount(1);
  await expect(panel.locator('.training-label-contract-count')).toHaveText('新增 0');
  await expect(panel).not.toContainText('legacy_smoke');
  await expect(panel).not.toContainText('合并关系');
  await expect(panel).not.toContainText('Schema Changed');

  await panel.locator('[data-training-label-code="fire"]').check();
  await expect(panel.locator('.training-label-contract-count')).toHaveText('新增 1');
});

test('same selected materials reload canonical labels after a completed label unification', async ({page, request}) => {
  const {project} = await seedProject(request);
  let unified = false;
  let selectedSummaryCalls = 0;

  await page.route('**/api/training_options**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({targets: [{
      id: 'label-unify-refresh',
      name: 'Label Unify Refresh',
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
      base_models: [{value: 'yolo11n.pt', label: 'YOLO11n', model_status:'FOUND'}],
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
  await page.route('**/api/v62/projects/*/training-materials/selection-summary', async route => {
    const body = route.request().postDataJSON();
    const ids = Array.isArray(body?.image_ids) ? body.image_ids.map(String) : [];
    if (ids.includes('same-material-after-unify')) selectedSummaryCalls += 1;
    const labels = unified ? ['smoke'] : ['fire'];
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        requested_count: ids.length,
        matched_count: ids.length,
        selectable_count: ids.length,
        eligible_count: ids.length,
        pending_annotation_count: 0,
        selectable_total: ids.length,
        eligible_total: ids.length,
        box_count: ids.length,
        size_bytes: ids.length * 1024,
        label_codes: ids.length ? labels : [],
        positive_label_codes: ids.length ? labels : [],
        label_counts: ids.length ? {[labels[0]]: ids.length} : {},
        repository_revision: unified ? 2 : 1,
      }),
    });
  });

  await selectIsolatedTestProject(page, project.id, '算法列表');
  await page.goto('/');
  await expect.poll(async () => page.evaluate(() => state.uiReady === true)).toBe(true);

  let card = page.locator('[data-algorithm-card]', {hasText: '首次打开配置回归'});
  await card.getByRole('button', {name: '训练'}).click();
  let dialog = page.getByRole('dialog', {name: '创建训练任务'});
  await expect(dialog).toBeVisible({timeout: 10_000});
  await returnToTrainingConfiguration(page);
  await page.evaluate(() => {
    if (!(state.labels || []).some(row => String(row?.code || '') === 'fire')) {
      state.labels = [...(state.labels || []), {
        code: 'fire', display_name: '明火', class_id: 1, active: true, status: 'active',
      }];
    }
    window.TrainingDraftRuntime.setMaterialIds(['same-material-after-unify']);
  });

  let panel = dialog.locator('#trainingLabelContractPanel');
  await expect(panel.locator('[data-training-label-code="fire"]')).toHaveCount(1);
  await expect(panel).toContainText('明火');
  await expect(panel).not.toContainText('上一版本');
  await expect(panel).not.toContainText('合并关系');
  await expect.poll(() => selectedSummaryCalls).toBeGreaterThanOrEqual(1);

  await page.evaluate(() => window.closeModal());
  unified = true;
  await page.evaluate(() => {
    state.labels = (state.labels || []).filter(row => String(row?.code || '') !== 'fire');
  });

  card = page.locator('[data-algorithm-card]', {hasText: '首次打开配置回归'});
  await card.getByRole('button', {name: '训练'}).click();
  dialog = page.getByRole('dialog', {name: '创建训练任务'});
  await expect(dialog).toBeVisible({timeout: 10_000});
  await returnToTrainingConfiguration(page);
  await page.evaluate(() => window.TrainingDraftRuntime.setMaterialIds(['same-material-after-unify']));

  panel = dialog.locator('#trainingLabelContractPanel');
  await expect.poll(() => selectedSummaryCalls).toBeGreaterThanOrEqual(2);
  await expect(panel.locator('[data-training-label-code="fire"]')).toHaveCount(0);
  await expect(panel.locator('[data-training-label-code="smoke"]')).toHaveCount(1);
  await expect(panel).toContainText('烟雾');
  await expect(panel).not.toContainText('上一版本');
  await expect(panel).not.toContainText('合并关系');
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
      base_models: [{value: 'yolo11n.pt', label: 'YOLO11n', model_status:'FOUND'}],
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

  const card = page.locator('[data-algorithm-card]', {hasText: '首次打开配置回归'});
  await card.getByRole('button', {name: '训练'}).click();
  const dialog = page.getByRole('dialog', {name: '创建训练任务'});
  await expect(dialog).toBeVisible({timeout: 10_000});
  await returnToTrainingConfiguration(page);

  await dialog.locator('[data-training-step="2"]').click();
  await dialog.locator('[data-mode="custom"]').click();
  const settings=dialog.locator('#trainWorkbenchParameters');
  await expect(settings).toBeVisible();
  await expect(page.getByRole('dialog',{name:'训练配置设置'})).toHaveCount(0);
  await settings.locator('details').filter({has:page.locator('#ts428Metric')}).locator('summary').click();
  await settings.locator('details').filter({has:page.locator('#ts428EarlyStop')}).locator('summary').click();
  await expect(settings.getByText('目标指标', {exact: true})).toBeVisible();
  await expect(settings.locator('#ts428Metric')).toHaveValue('map50');
  await expect(settings.getByText('目标正确率', {exact: true})).toBeVisible();
  await expect(settings.locator('#ts428Goal')).toHaveValue('90');
  await expect(settings.locator('#ts428Low')).toHaveCount(0);
  await expect(settings.locator('#ts428Patience')).toHaveCount(0); // Original target/early-stop contract has no second patience editor
  await expect(settings.locator('#ts428EarlyStop')).not.toBeChecked();
  await expect(settings.getByText('低于此正确率停止')).toHaveCount(0);

  await expect(settings).toContainText('以 Worker 回执为准');
  await expect(dialog.locator('[data-mode="custom"]')).toHaveAttribute('aria-pressed', 'true');
  const config = await page.evaluate(() => window.trainingConfigCanonical428?.());
  expect(config.stop_threshold).toBe(0.9);
  expect(config.continue_threshold).toBe(0);
});


test('frozen feedback candidates stay aligned with training submit provenance', async ({page, request}) => {
  const {project, algorithmId} = await seedProject(request);
  await routeCompatibleTrainingMaterials(page);
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
      base_models: [{value: 'yolo11n.pt', label: 'YOLO11n', model_status:'FOUND'}],
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
        positive_label_codes: ['smoke'],
        label_counts: {smoke: count},
        repository_revision: 1,
      }),
    });
  });
  await page.route('**/api/v12/projects/*/train/start', async route => {
    submitted = route.request().postDataJSON();
    durableTask = {
      task_id: submitted.task_id,
      project_id: project.id,
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

  const card = page.locator('[data-algorithm-card]', {hasText: '首次打开配置回归'});
  await card.getByRole('button', {name: '训练'}).click();
  const dialog = page.getByRole('dialog', {name: '创建训练任务'});
  await expect(dialog).toBeVisible({timeout: 10_000});
  await returnToTrainingConfiguration(page);
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

  await dialog.locator('[data-training-step="3"]').click();
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
  await routeCompatibleTrainingMaterials(page);
  let submitted = null;
  const scopeId = 'b'.repeat(64);
  await page.route('**/api/training_options**', route => route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({targets:[{id:'benchmark-training-target',name:'Benchmark Training',type:'local',framework:'ultralytics',status:'ready',algorithms:[{key:'yolo_detect',name:'Ultralytics Detect',base_model:'yolo11n.pt',default_epochs:20,default_imgsz:640,default_batch:4}],base_models:[{value:'yolo11n.pt',label:'YOLO11n',model_status:'FOUND'}]}]})}));
  await page.route('**/api/system/recommendation', route => route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({device:'cpu',batch:4,workers:0})}));
  await page.route('**/api/v62/training-devices', route => route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({recommended:'cpu',options:[{id:'cpu',label:'CPU',available:true}]})}));
  await page.route('**/api/v12/projects/*/algorithms/*/benchmark-reuse', route => route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({available:true,algorithm_id:algorithmId,source_version_id:'benchmark-version',source_version_name:'20260919150000',scope_id:scopeId,snapshot_id:'snapshot-benchmark',test_image_count:11,binding_level:'bundle_verified'})}));
  await page.route('**/api/v62/projects/*/training-materials/selection-summary', async route => {const body=route.request().postDataJSON(),count=Array.isArray(body?.image_ids)?body.image_ids.length:0;await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({requested_count:count,matched_count:count,eligible_count:count,eligible_total:count,box_count:count,size_bytes:count*1024,label_codes:['smoke'],positive_label_codes:['smoke'],label_counts:{smoke:count},repository_revision:1})});});
  await page.route('**/api/v12/projects/*/train/start', async route => {submitted=route.request().postDataJSON();await route.fulfill({status:202,contentType:'application/json',body:JSON.stringify({ok:true,task:{task_id:submitted.task_id,project_id:project.id,kind:'TRAINING',task_type:'TRAINING',status:'QUEUED',persisted_status:'QUEUED',phase:'queued',progress_percent:0}})});});
  await selectIsolatedTestProject(page, project.id, '算法列表');
  await page.goto('/');
  await expect.poll(async () => page.evaluate(() => state.uiReady === true)).toBe(true);
  await page.evaluate(({algorithmId}) => {const asset=(state.algorithms||[]).find(row=>String(row?.id||'')===String(algorithmId));if(!asset)throw new Error('algorithm missing from browser state');asset.current_version_id='benchmark-version';asset.versions=[{id:'benchmark-version',version_name:'20260919150000',training_status:'SUCCEEDED',artifact_verified:true,trainable:true,framework:'ultralytics',label_schema:[{code:'smoke',class_id:0}]}];}, {algorithmId});
  const card=page.locator('[data-algorithm-card]',{hasText:'首次打开配置回归'});
  await card.getByRole('button',{name:'训练'}).click();
  const dialog=page.getByRole('dialog',{name:'创建训练任务'});
  await expect(dialog).toBeVisible({timeout:10000});
  await returnToTrainingConfiguration(page);
  await expect(dialog.locator('[data-benchmark-reuse="available"]')).toContainText('11 张');
  // Availability alone must NOT silently replace the default 60/20/20 split.
  await expect(dialog.locator('#trV3BenchmarkReuse')).not.toBeChecked();
  // Data partition is its own disclosure in the new creation form.
  const splitDetails = dialog.locator('.train-create-split-details');
  if (!(await splitDetails.getAttribute('open'))) await splitDetails.locator(':scope > summary').click();
  await expect(dialog.locator('#trV3Experiment')).toHaveValue('20');
  await expect(dialog.locator('#trV3Validation')).toHaveValue('20');
  await dialog.locator('#trV3BenchmarkReuse').check();
  await expect(dialog.locator('#trV3BenchmarkReuse')).toBeChecked();
  await expect(dialog.locator('[data-benchmark-mode]')).toContainText('服务端固定 Benchmark');
  await expect(dialog.locator('.train-v3-summary>div').first().locator('span')).toHaveText('训练候选素材');
  await expect(dialog.locator('.train-v3-note')).toContainText('系统自动保留');
  await page.evaluate(({algorithmId}) => {window.TrainingDraftRuntime.update({algorithmId});window.TrainingDraftRuntime.setMaterialIds(['train-material-a','train-material-b']);window.TrainingSubmitRuntime.updateReadiness();}, {algorithmId});
  await dialog.locator('[data-training-step="3"]').click();
  const submitButton=dialog.getByRole('button',{name:'开始训练'});
  await expect(submitButton).toBeEnabled();
  await submitButton.click();
  await expect.poll(()=>submitted).not.toBeNull();
  expect(submitted.benchmark_source_version_id).toBe('benchmark-version');
  expect(submitted.benchmark_scope_id).toBe(scopeId);
  expect(submitted.test_image_ids).toBeUndefined();
  expect(submitted.experiment_percent).toBeUndefined();
});


test('late training device preparation cannot rewrite a closed form or another business modal',async({page,request})=>{
  const {project,algorithmId}=await seedProject(request);
  let release;const gate=new Promise(resolve=>{release=resolve;});let reads=0;
  await page.route('**/api/v62/training-devices',async route=>{reads++;await gate;return route.fulfill({json:{recommended:'cpu',options:[{id:'cpu',available:true}]}});});
  await selectIsolatedTestProject(page,project.id,'算法列表');await page.goto('/');
  await expect.poll(()=>page.evaluate(()=>state.uiReady===true)).toBe(true);
  await page.evaluate(async algorithmId=>{
    state.targets=[{id:'local',type:'local',framework:'ultralytics',status:'ready',algorithms:[{key:'detect',base_model:'yolo11n.pt'}],base_models:[{value:'yolo11n.pt',model_status:'FOUND'}]}];state.rec={device:'auto'};state.trainingDevicesV3={options:[]};state.trainingDevicesV3LoadedAt=0;
    await window.openTrainingCreateCanonical429(algorithmId);
  },algorithmId);
  await expect.poll(()=>reads).toBe(1);
  const before=await page.evaluate(()=>JSON.stringify(state.trainingDraft));
  await page.evaluate(()=>{window.closeModal();window.modal('其他业务','<input id="other-business" value="保留">');});
  release();await page.waitForResponse('**/api/v62/training-devices');
  await expect(page.locator('#other-business')).toHaveValue('保留');
  expect(await page.evaluate(()=>JSON.stringify(state.trainingDraft))).toBe(before);
});

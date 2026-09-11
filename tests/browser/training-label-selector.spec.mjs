import {test, expect} from '@playwright/test';

function bmp(width = 100, height = 80, rgb = [90, 140, 210]) {
  const rowBytes = Math.ceil(width * 3 / 4) * 4;
  const buffer = Buffer.alloc(54 + rowBytes * height);
  buffer.write('BM', 0, 'ascii');
  buffer.writeUInt32LE(buffer.length, 2);
  buffer.writeUInt32LE(54, 10);
  buffer.writeUInt32LE(40, 14);
  buffer.writeInt32LE(width, 18);
  buffer.writeInt32LE(height, 22);
  buffer.writeUInt16LE(1, 26);
  buffer.writeUInt16LE(24, 28);
  buffer.writeUInt32LE(rowBytes * height, 34);
  for (let offset = 54; offset < buffer.length; offset += 3) {
    buffer[offset] = rgb[2]; buffer[offset + 1] = rgb[1]; buffer[offset + 2] = rgb[0];
  }
  return buffer;
}

async function seedProject(request) {
  const project = await (await request.post('/api/projects', {data: {
    name: `标签选择-${Date.now()}`,
    labels: [
      {code: 'fire', display_name: '明火'},
      {code: 'smoke', display_name: '烟雾'},
    ],
  }})).json();

  const images = [];
  for (const [name, label, color] of [
    ['fire-a.bmp', 'fire', [190, 70, 50]],
    ['smoke-a.bmp', 'smoke', [80, 90, 190]],
    ['smoke-b.bmp', 'smoke', [70, 160, 90]],
  ]) {
    const upload = await request.post(`/api/projects/${project.id}/images`, {multipart: {
      dataset_id: 'default', files: {name, mimeType: 'image/bmp', buffer: bmp(100, 80, color)},
    }});
    const image = (await upload.json()).uploaded[0];
    images.push(image);
    const save = await request.post(`/api/projects/${project.id}/annotations/${image.id}`, {data: {boxes: [{
      class_id: label === 'fire' ? 0 : 1,
      label,
      x1: 10, y1: 10, x2: 70, y2: 60,
    }]}});
    expect(save.ok()).toBeTruthy();
  }

  const created = await (await request.post(`/api/v12/projects/${project.id}/algorithms`, {data: {
    name: '烟火标签算法',
    industry: '工业安全',
    algorithm_type: 'yolo_ultralytics',
    remark: '',
  }})).json();
  return {project, imageIds: images.map(item => item.id), algorithmId: created.algorithm.id};
}

test('training dialog uses TrainingDraft + TrainingSubmitRuntime as the only live request path', async ({page, request}) => {
  const {project, imageIds, algorithmId} = await seedProject(request);
  let submitted;

  await page.route('**/api/training_options**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({targets: [{
      id: 'browser-ultralytics',
      name: '浏览器测试 Ultralytics',
      type: 'local',
      framework: 'ultralytics',
      status: 'ready',
      algorithms: [{
        key: 'yolo_detect', name: 'Ultralytics Detect', base_model: 'yolo11n.pt',
        default_epochs: 10, default_imgsz: 640, default_batch: 2,
      }],
      base_models: [{value: 'yolo11n.pt', label: 'YOLO11n'}],
    }]})
  }));
  await page.route('**/api/v62/training-devices', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({recommended: 'cpu', options: [{id: 'cpu', label: 'CPU', available: true}]}),
  }));
  await page.route(`**/api/v12/projects/${project.id}/train/start`, async route => {
    submitted = route.request().postDataJSON();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ok: true, job: {id: 'label-browser-job', status: 'queued'}}),
    });
  });

  await page.addInitScript(projectId => {
    localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({projectId, page: '算法列表'}));
  }, project.id);

  await page.goto('/');
  await expect.poll(async () => page.evaluate(() => window.TrainingDraftRuntime?.build || null))
    .toBe('training-draft-runtime-422513');
  await expect.poll(async () => page.evaluate(() => window.TrainingSubmitRuntime?.build || null))
    .toBe('training-submit-422504');
  expect(await page.evaluate(() => ({
    draftOwnsNetwork: window.TrainingDraftRuntime.state().networkOwner,
    submitOwnsNetwork: window.TrainingSubmitRuntime.state().networkOwner,
  }))).toEqual({draftOwnsNetwork: false, submitOwnsNetwork: true});

  await page.getByRole('button', {name: /算法列表/}).click();
  const card = page.locator('.alg428-card', {hasText: '烟火标签算法'});
  await card.getByRole('button', {name: '训练'}).click();
  const dialog = page.getByRole('dialog', {name: '训练 · 烟火标签算法'});
  await expect(dialog).toBeVisible({timeout: 10_000});

  await dialog.getByRole('button', {name: '选择训练素材'}).click();
  const picker = page.getByRole('dialog', {name: '选择本次训练素材'});
  await picker.getByRole('button', {name: '全选全部可用素材'}).click();
  await expect(picker.locator('#trV3PickerCount')).toContainText(`已选 ${imageIds.length} 张`);
  await picker.getByRole('button', {name: '确认选择'}).click();
  await expect(dialog).toBeVisible();

  const labels = dialog.locator('#trainingLabelContractPanel');
  await expect(labels).toContainText('明火');
  await expect(labels).toContainText('烟雾');
  const smoke = labels.locator('input[data-training-label-code="smoke"]');
  await smoke.uncheck();

  await dialog.locator('#trV3Experiment').fill('35');
  await dialog.locator('#trV3Validation').fill('18');
  await dialog.locator('#tr429Priority').fill('7');
  await dialog.locator('#trV3ResourceStrategy').selectOption('manual');
  await dialog.locator('#trV3GpuPolicy').selectOption('exclusive');

  await dialog.getByRole('button', {name: '配置设置'}).click();
  const settings = page.getByRole('dialog', {name: '训练配置设置'});
  await settings.locator('#ts428Epoch').fill('30');
  await settings.locator('#ts428Batch').fill('16');
  await settings.locator('details.advanced427-box summary').click();
  await settings.locator('#ts428Workers').fill('4');
  await settings.locator('#ts428Opt').selectOption('AdamW');
  await settings.locator('#ts428Cache').selectOption('False');
  await settings.getByRole('button', {name: '应用配置'}).click();
  await expect(dialog).toBeVisible();

  await expect.poll(async () => page.evaluate(() => ({
    algorithmId: state.trainingDraft?.algorithmId,
    materials: state.trainingDraft?.materialIds || [],
    labels: state.trainingDraft?.newLabelCodes || [],
    experiment: state.trainingDraft?.experimentPercent,
    validation: state.trainingDraft?.validationPercent,
    priority: state.trainingDraft?.priority,
    strategy: state.trainingDraft?.resource?.strategy,
    device: state.trainingDraft?.resource?.device,
    gpuPolicy: state.trainingDraft?.resource?.gpuPolicy,
    epochs: state.trainingDraft?.config?.epochs,
    batch: state.trainingDraft?.resource?.batch,
    workers: state.trainingDraft?.resource?.workers,
    cache: state.trainingDraft?.resource?.cache,
    optimizer: state.trainingDraft?.config?.optimizer,
    retiredLabelMirror: Object.hasOwn(state, 'trainingLabelSelected'),
    retiredSplitMirror: Object.hasOwn(state, 'trainSplitV3'),
  }))).toEqual({
    algorithmId,
    materials: imageIds,
    labels: ['fire'],
    experiment: 35,
    validation: 18,
    priority: 7,
    strategy: 'manual',
    device: 'cpu',
    gpuPolicy: 'exclusive',
    epochs: 30,
    batch: 16,
    workers: 4,
    cache: false,
    optimizer: 'AdamW',
    retiredLabelMirror: false,
    retiredSplitMirror: false,
  });

  await page.evaluate(() => {
    state.train428AlgorithmId = 'stale-algorithm';
    state.train429Selected = new Set(['stale-material']);
    state.train428Config = {device: 'stale-device', batch: 1, workers: 0, cache: true, optimizer: 'SGD'};
    window.TrainingDraftRuntime.sync();
  });
  expect(await page.evaluate(() => ({
    algorithmId: state.trainingDraft.algorithmId,
    materials: state.trainingDraft.materialIds,
    device: state.trainingDraft.resource.device,
    batch: state.trainingDraft.resource.batch,
    optimizer: state.trainingDraft.config.optimizer,
  }))).toEqual({
    algorithmId,
    materials: imageIds,
    device: 'cpu',
    batch: 16,
    optimizer: 'AdamW',
  });
  await expect(dialog.getByRole('button', {name: '开始训练'})).toBeEnabled();
  expect(await dialog.getByRole('button', {name: '开始训练'}).getAttribute('data-training-submit-owner'))
    .toBe('TrainingSubmitRuntime');

  submitted = undefined;
  await page.evaluate(async projectId => {
    await fetch(`/api/v12/projects/${projectId}/train/start`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({algorithm_asset_id: 'raw-caller', train_image_ids: ['raw-id'], train_labels: ['raw-label']}),
    });
  }, project.id);
  await expect.poll(() => submitted).toBeTruthy();
  expect(submitted).toEqual({algorithm_asset_id: 'raw-caller', train_image_ids: ['raw-id'], train_labels: ['raw-label']});

  submitted = undefined;
  expect(await page.evaluate(() => window.submitTrain429?.__trainingSubmitRuntime === true)).toBe(true);
  await dialog.getByRole('button', {name: '开始训练'}).click();
  await expect.poll(async () => {
    if (submitted) return 'submitted';
    const runtime = await page.evaluate(() => window.TrainingSubmitRuntime?.state?.() || null);
    const toast = await page.locator('#toast').textContent();
    if (runtime?.lastError) return `${runtime.lastStage}: ${runtime.lastError} | toast=${toast || ''}`;
    return `waiting:${runtime?.lastStage || 'none'} | toast=${toast || ''}`;
  }).toBe('submitted');

  expect(submitted.algorithm_asset_id).toBe(algorithmId);
  expect(submitted.train_image_ids).toEqual(imageIds);
  expect(submitted.train_labels).toEqual(['fire']);
  expect(submitted.experiment_percent).toBe(35);
  expect(submitted.validation_percent).toBe(18);
  expect(submitted.queue_priority).toBe(7);
  expect(submitted.resource_strategy).toBe('manual');
  expect(submitted.device).toBe('cpu');
  expect(submitted.gpu_policy).toBe('exclusive');
  expect(submitted.epochs).toBe(30);
  expect(submitted.batch).toBe(16);
  expect(submitted.workers).toBe(4);
  expect(submitted.cache).toBe(false);
  expect(submitted.optimizer).toBe('AdamW');
  expect(submitted.framework).toBe('ultralytics');
  expect(submitted.algorithm).toBe('yolo_detect');
  expect(submitted.ai_intervention_enabled).toBe(false);
  await expect(page.locator('#toast')).toContainText('训练任务已进入后台队列');
});
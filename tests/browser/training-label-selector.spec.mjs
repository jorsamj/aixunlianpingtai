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

  const rows = [
    ['fire-a.bmp', 'fire', [190, 70, 50]],
    ['smoke-a.bmp', 'smoke', [80, 90, 190]],
    ['smoke-b.bmp', 'smoke', [70, 160, 90]],
  ];
  for (const [name, label, color] of rows) {
    const upload = await request.post(`/api/projects/${project.id}/images`, {multipart: {
      dataset_id: 'default', files: {name, mimeType: 'image/bmp', buffer: bmp(100, 80, color)},
    }});
    const image = (await upload.json()).uploaded[0];
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
  return {project, algorithmId: created.algorithm.id};
}

async function selectAllMaterials(page, dialog) {
  await dialog.getByRole('button', {name: '选择训练素材'}).click();
  const picker = page.getByRole('dialog', {name: '选择本次训练素材'});
  await expect(picker).toBeVisible();
  await picker.getByRole('button', {name: '全选全部可用素材'}).click();
  await picker.getByRole('button', {name: '确认选择'}).click();
  await expect(dialog).toBeVisible();
}

test('final train-v3 dialog shows material-derived label selector and submits train_labels', async ({page, request}) => {
  const {project} = await seedProject(request);
  let submitted;

  const trainingOptions = {
    targets: [{
      id: 'browser-ultralytics',
      name: '浏览器测试 Ultralytics',
      type: 'local',
      framework: 'ultralytics',
      status: 'ready',
      algorithms: [{
        key: 'yolo_detect',
        name: 'Ultralytics Detect',
        base_model: 'yolo11n.pt',
        default_epochs: 10,
        default_imgsz: 640,
        default_batch: 2,
      }],
      base_models: [{value: 'yolo11n.pt', label: 'YOLO11n'}],
    }],
  };

  await page.route('**/api/training_options**', async route => {
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(trainingOptions)});
  });
  await page.route('**/api/v62/training-devices', async route => {
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({
      recommended: 'cpu',
      options: [{id: 'cpu', label: 'CPU', available: true}],
    })});
  });
  await page.route(`**/api/v12/projects/${project.id}/train/start`, async route => {
    submitted = route.request().postDataJSON();
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({
      ok: true,
      job: {id: 'label-browser-job', status: 'queued'},
    })});
  });

  await page.addInitScript(projectId => {
    localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({projectId, page: '算法列表'}));
  }, project.id);

  await page.goto('/');
  await page.getByRole('button', {name: /算法列表/}).click();
  const card = page.locator('.alg428-card', {hasText: '烟火标签算法'});
  await card.getByRole('button', {name: '训练'}).click();

  const dialog = page.getByRole('dialog', {name: '训练 · 烟火标签算法'});
  await expect(dialog).toBeVisible({timeout: 10_000});
  await expect(dialog.locator('.train-v3-summary')).toBeVisible();

  const labels = dialog.locator('#trainingLabelContractPanel');
  await expect(labels).toBeVisible({timeout: 10_000});
  await expect(labels).toContainText('本次训练标签');
  await expect(labels).toContainText('请先选择训练素材');

  await selectAllMaterials(page, dialog);
  await expect(labels).toBeVisible();
  await expect(labels).toContainText('明火');
  await expect(labels).toContainText('fire');
  await expect(labels).toContainText('烟雾');
  await expect(labels).toContainText('smoke');

  const fire = labels.locator('input[data-training-label-code="fire"]');
  const smoke = labels.locator('input[data-training-label-code="smoke"]');
  await expect(fire).toBeChecked();
  await expect(smoke).toBeChecked();

  // Prove that the UI choice, not the project label library, controls the request.
  await smoke.uncheck();
  await expect(smoke).not.toBeChecked();
  await dialog.locator('#tr429Priority').fill('7');
  await dialog.getByRole('button', {name: '开始训练'}).click();

  await expect.poll(() => submitted).toBeTruthy();
  expect(submitted.train_labels).toEqual(['fire']);
});

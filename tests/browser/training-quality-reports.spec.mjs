import {test, expect} from '@playwright/test';
import {promises as fs} from 'node:fs';
import os from 'node:os';
import path from 'node:path';


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

async function seedTrainingProject(request, {withVersion = false} = {}) {
  const project = await (await request.post('/api/projects', {data: {
    name: `训练浏览器-${Date.now()}`,
    labels: [{code: 'fire', display_name: '明火'}, {code: 'smoke', display_name: '烟雾'}]
  }})).json();
  const images = [];
  for (const [name, color] of [['train.bmp', [190, 70, 50]], ['val.bmp', [80, 90, 190]]]) {
    const upload = await request.post(`/api/projects/${project.id}/images`, {multipart: {
      dataset_id: 'default', files: {name, mimeType: 'image/bmp', buffer: bmp(100, 80, color)}
    }});
    images.push((await upload.json()).uploaded[0]);
  }
  for (const [index, image] of images.entries()) {
    await request.post(`/api/projects/${project.id}/annotations/${image.id}`, {data: {boxes: [{
      class_id: index, label: index ? 'smoke' : 'fire', x1: 10, y1: 10, x2: 70, y2: 60
    }]}});
    await request.patch(`/api/v12/projects/${project.id}/images/${image.id}`, {data: {split: index ? 'val' : 'train'}});
  }
  const algorithm = await (await request.post(`/api/v12/projects/${project.id}/algorithms`, {data: {
    name: '烟火迭代算法', industry: '工业安全', algorithm_type: 'yolo_ultralytics', remark: ''
  }})).json();
  if (withVersion) {
    const modelPath = path.join(os.tmpdir(), `browser-version-${Date.now()}.pt`);
    await fs.writeFile(modelPath, Buffer.from('browser model fixture'));
    const assigned = await request.post(`/api/v12/projects/${project.id}/algorithms/${algorithm.algorithm.id}/versions`, {data: {
      model_name: path.basename(modelPath), model_source: 'local', local_path: modelPath
    }});
    expect(assigned.ok()).toBeTruthy();
  }
  const listed = await (await request.get(`/api/v12/projects/${project.id}/algorithms`)).json();
  return {project, algorithm: listed.items.find(item => item.id === algorithm.algorithm.id)};
}

async function selectAllTrainingMaterials(page, trainingDialog) {
  await trainingDialog.getByRole('button', {name: '选择素材'}).click();
  const picker = page.getByRole('dialog', {name: '选择训练素材'});
  await picker.getByRole('button', {name: '全选当前'}).click();
  await picker.getByRole('button', {name: '确定'}).click();
}

test('training dialog exposes iteration base, stacked quality charts, and report levels', async ({page, request}) => {
  const {project} = await seedTrainingProject(request);
  await page.addInitScript(projectId => {
    localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({projectId, page: '算法列表'}));
  }, project.id);
  await page.goto('/');
  await page.getByRole('button', {name: /算法列表/}).click();
  const algorithmCard = page.locator('.alg428-card', {hasText: '烟火迭代算法'});
  await expect(algorithmCard.getByRole('button', {name: '综合报告'})).toBeVisible({timeout: 20_000});
  await algorithmCard.getByRole('button', {name: '训练'}).click();

  const trainingDialog = page.getByRole('dialog', {name: '训练 · 烟火迭代算法'});
  await expect(trainingDialog).toBeVisible();
  await expect(trainingDialog.locator('#tr429Count')).toHaveText('0 张');
  await expect(trainingDialog.getByText('首次训练：使用所选母模型')).toBeVisible();
  await expect(trainingDialog.getByText('每次随机抽取试验集比例')).toBeVisible();
  await expect(trainingDialog.locator('#tr429ExperimentPercent')).toHaveValue('20');
  const priority = trainingDialog.locator('#tr429Priority');
  await expect(priority).toHaveAttribute('type', 'number');
  await expect(priority).toHaveAttribute('min', '1');
  await expect(priority).toHaveAttribute('max', '999');
  await expect(priority).toHaveValue('50');
  await expect(trainingDialog.getByText('1 最高，数字越大优先级越低')).toBeVisible();
  await trainingDialog.getByRole('button', {name: '配置设置'}).click();
  const settingsDialog = page.getByRole('dialog', {name: '训练配置设置'});
  await expect(settingsDialog).toBeVisible();
  const advanced = settingsDialog.locator('details.advanced427-box');
  await expect(advanced).not.toHaveAttribute('open', '');
  await advanced.locator('summary').click();
  await expect(settingsDialog.getByText('最终学习率 lrf')).toBeVisible();
  await settingsDialog.getByRole('button', {name: '取消'}).click();
  await selectAllTrainingMaterials(page, trainingDialog);
  await trainingDialog.getByRole('button', {name: '查看数据质量'}).click();

  const qualityDialog = page.getByRole('dialog', {name: '训练素材 · 数据质量'});
  await expect(qualityDialog).toBeVisible();
  await expect(qualityDialog.locator('.quality414-radar')).toBeVisible();
  await expect(qualityDialog.getByText('质量维度')).toBeVisible();
  await expect(qualityDialog.getByText('标签分布')).toBeVisible();
  await expect(trainingDialog).toBeVisible();
  await qualityDialog.locator('.quality414 .row.end .btn').click();
  await trainingDialog.getByRole('button', {name: '取消'}).click();

  await algorithmCard.getByRole('button', {name: '综合报告'}).click();
  await expect(page.getByRole('dialog', {name: '算法综合训练报告'})).toBeVisible();
});

test('training submit sends the selected candidate pool and configured experiment percentage', async ({page, request}) => {
  const {project} = await seedTrainingProject(request);
  let submitted;
  await page.route(`**/api/v12/projects/${project.id}/train/start`, async route => {
    submitted = route.request().postDataJSON();
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({ok: true, job: {id: 'browser-job', status: 'queued'}})});
  });
  await page.addInitScript(projectId => {
    localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({projectId, page: '算法列表'}));
  }, project.id);
  await page.goto('/');
  await page.getByRole('button', {name: /算法列表/}).click();
  const card = page.locator('.alg428-card', {hasText: '烟火迭代算法'});
  await card.getByRole('button', {name: '训练'}).click();
  const dialog = page.getByRole('dialog', {name: '训练 · 烟火迭代算法'});
  await expect(dialog).toBeVisible();
  await expect(dialog.locator('#tr429Count')).toHaveText('0 张');
  await selectAllTrainingMaterials(page, dialog);
  await dialog.locator('#tr429ExperimentPercent').fill('35');
  await dialog.locator('#tr429Priority').fill('7');
  await dialog.getByRole('button', {name: '配置设置'}).click();
  const settings = page.getByRole('dialog', {name: '训练配置设置'});
  await settings.locator('details.advanced427-box summary').click();
  await settings.locator('#ts428SingleCls').check();
  await settings.getByRole('button', {name: '应用配置'}).click();
  await expect(dialog).toBeVisible();
  await dialog.getByRole('button', {name: '开始训练'}).click();
  await expect.poll(() => submitted).toBeTruthy();
  expect(submitted.experiment_percent).toBe(35);
  expect(submitted.random_experiment_split).toBe(true);
  expect(submitted.single_cls).toBe(true);
  expect(submitted.queue_priority).toBe(7);
  expect(submitted.selected_image_ids).toHaveLength(2);
  expect(submitted.train_image_ids).toBeUndefined();
});

test('versioned training locks the latest version and projects the current random split', async ({page, request}) => {
  const {project, algorithm} = await seedTrainingProject(request, {withVersion: true});
  await page.route(`**/api/v54/projects/${project.id}/algorithms/${algorithm.id}/iteration-base?framework=ultralytics`, async route => {
    await new Promise(resolve => setTimeout(resolve, 1200));
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({ok: true, base: {
      version_id: 'latest-version', version_name: 'v3', model_name: 'latest-best.pt', path: 'C:/models/latest-best.pt'
    }})});
  });
  await page.addInitScript(projectId => {
    localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({projectId, page: '算法列表'}));
  }, project.id);
  await page.goto('/');
  await page.getByRole('button', {name: /算法列表/}).click();
  const card = page.locator('.alg428-card', {hasText: '烟火迭代算法'});
  await card.getByRole('button', {name: '训练'}).click();
  const dialog = page.getByRole('dialog', {name: '训练 · 烟火迭代算法'});

  await expect(dialog).not.toContainText('YOLO11n 目标检测', {timeout: 500});
  await expect(dialog.locator('#tr429Count')).toHaveText('0 张');
  await expect(dialog.getByText('训练引擎（迭代任务锁定）')).toBeVisible();
  await expect(dialog.getByText('Ultralytics Detect', {exact: true})).toBeVisible();
  await expect(dialog.locator('#tr429Model')).toHaveText('v3 · latest-best.pt');
  await expect(dialog.locator('.train429-split-summary')).toContainText('预计训练 0 张 / 试验 0 张');
  await expect(dialog.getByText('YOLO11n 目标检测', {exact: true})).toBeHidden();
  await dialog.getByRole('button', {name: '配置设置'}).click();
  const settings = page.getByRole('dialog', {name: '训练配置设置'});
  await expect(settings.locator('#ts428Model')).toBeDisabled();
  await expect(settings.locator('#ts428Model option:checked')).toHaveText('v3 · latest-best.pt');
});

test('training queue displays numeric priorities and orders each resource by priority then FIFO', async ({page, request}) => {
  const project = await (await request.post('/api/projects', {data: {
    name: `优先级队列-${Date.now()}`, labels: [{code: 'target', display_name: '目标'}]
  }})).json();
  const queuedJobs = [
    {id: 'fifo-new', asset_algorithm_name: '同级后到', status: 'queued', resource_key: 'local:cpu', queue_priority: 7, priority_scheme: 'lower_number_first', queued_at: '2026-08-30T10:02:00Z'},
    {id: 'highest', asset_algorithm_name: '最高优先', status: 'queued', resource_key: 'local:cpu', queue_priority: 1, priority_scheme: 'lower_number_first', queued_at: '2026-08-30T10:03:00Z'},
    {id: 'fifo-old', asset_algorithm_name: '同级先到', status: 'queued', resource_key: 'local:cpu', queue_priority: 7, priority_scheme: 'lower_number_first', queued_at: '2026-08-30T10:01:00Z'}
  ];
  await page.route(`**/api/projects/${project.id}`, async route => {
    const response = await route.fetch();
    const body = await response.json();
    await route.fulfill({response, json: {...body, jobs: queuedJobs}});
  });
  await page.addInitScript(projectId => {
    localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({projectId, page: '训练任务'}));
  }, project.id);
  await page.goto('/');
  await page.evaluate(jobs => {
    state.jobs = jobs;
    state.page = '训练任务';
    render();
  }, queuedJobs);

  const rows = page.locator('.train428-table tbody tr');
  await expect(rows).toHaveCount(3);
  expect(await rows.locator('.train428-taskname b').allTextContents()).toEqual(['最高优先', '同级先到', '同级后到']);
  await expect(rows.nth(0).locator('.queuepriority428')).toHaveText('优先级 1');
  await expect(rows.nth(1).locator('.queuepriority428')).toHaveText('优先级 7');
  await expect(rows.nth(0).locator('.queuepos428')).toHaveText('队列第 1 位');
  await expect(rows.nth(2).locator('.queuepos428')).toHaveText('队列第 3 位');
});

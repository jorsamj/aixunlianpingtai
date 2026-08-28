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

async function seedTrainingProject(request) {
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
  return {project, algorithm: algorithm.algorithm};
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
  await expect(trainingDialog.getByText('首次训练：使用所选母模型')).toBeVisible();
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

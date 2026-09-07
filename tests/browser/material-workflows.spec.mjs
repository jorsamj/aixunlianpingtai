import {test, expect} from '@playwright/test';


function bmp(width = 100, height = 80, rgb = [42, 120, 210]) {
  const rowBytes = Math.ceil(width * 3 / 4) * 4;
  const pixelBytes = rowBytes * height;
  const buffer = Buffer.alloc(54 + pixelBytes);
  buffer.write('BM', 0, 'ascii');
  buffer.writeUInt32LE(buffer.length, 2);
  buffer.writeUInt32LE(54, 10);
  buffer.writeUInt32LE(40, 14);
  buffer.writeInt32LE(width, 18);
  buffer.writeInt32LE(height, 22);
  buffer.writeUInt16LE(1, 26);
  buffer.writeUInt16LE(24, 28);
  buffer.writeUInt32LE(pixelBytes, 34);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const offset = 54 + y * rowBytes + x * 3;
      buffer[offset] = rgb[2];
      buffer[offset + 1] = rgb[1];
      buffer[offset + 2] = rgb[0];
    }
  }
  return buffer;
}

async function createMaterialProject(request, name) {
  const response = await request.post('/api/projects', {
    data: {
      name,
      description: 'browser material workflow',
      labels: [
        {code: 'person', display_name: '人员', color: '#ef4444'},
        {code: 'vehicle', display_name: '车辆', color: '#3b82f6'}
      ]
    }
  });
  expect(response.ok()).toBeTruthy();
  return response.json();
}

async function uploadImage(request, projectId, filename, color) {
  const response = await request.post(`/api/projects/${projectId}/images`, {
    multipart: {
      dataset_id: 'default',
      files: {name: filename, mimeType: 'image/bmp', buffer: bmp(100, 80, color)}
    }
  });
  expect(response.ok()).toBeTruthy();
  const result = await response.json();
  expect(result.uploaded_count).toBe(1);
  return result.uploaded[0];
}

async function selectProject(page, projectId) {
  await page.addInitScript(id => {
    localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({projectId: id, page: '数据集'}));
  }, projectId);
}

test('manual annotation saves, survives reload, and updates the thumbnail', async ({page, request}) => {
  const project = await createMaterialProject(request, `标注回归-${Date.now()}`);
  const image = await uploadImage(request, project.id, 'annotation-flow.bmp', [42, 120, 210]);
  await request.post(`/api/v52/projects/${project.id}/images/mark-ready`, {
    data: {image_ids: [image.id]}
  });
  await selectProject(page, project.id);

  await page.goto('/');
  await page.getByRole('button', {name: /数据集/}).click();
  await page.getByRole('button', {name: /已处理/}).click();
  const card = page.locator('.data412-card', {hasText: 'annotation-flow.bmp'});
  await expect(card).toBeVisible();
  await card.getByRole('button', {name: '标注'}).click();

  const dialog = page.getByRole('dialog', {name: '图片标注'});
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole('button', {name: '管理标签'})).toHaveCount(0);
  await expect(dialog.getByText('当前标签', {exact: true})).toHaveCount(0);
  await expect(dialog.getByLabel('绘制标签')).toBeVisible();
  await expect(dialog.getByLabel('绘制标签').locator('option')).toHaveText(['人员 · person', '车辆 · vehicle']);
  await expect(dialog.getByText('连续标注', {exact: true})).toBeVisible();
  const imageBox = await dialog.locator('#annImg').boundingBox();
  expect(imageBox).not.toBeNull();
  await page.mouse.move(imageBox.x + imageBox.width * 0.2, imageBox.y + imageBox.height * 0.2);
  await page.mouse.down();
  await page.mouse.move(imageBox.x + imageBox.width * 0.75, imageBox.y + imageBox.height * 0.75, {steps: 5});
  await page.mouse.up();
  await expect(dialog.locator('.box424')).toHaveCount(1);
  await dialog.getByRole('button', {name: '保存并继续'}).click();
  await expect(dialog.getByText('已保存 · 1框')).toBeVisible();

  const savedResponse = await request.get(`/api/projects/${project.id}/annotations/${image.id}`);
  const saved = await savedResponse.json();
  expect(saved.boxes).toHaveLength(1);
  expect(saved.boxes[0].label).toBe('person');

  await page.reload();
  await page.getByRole('button', {name: /数据集/}).click();
  await page.getByRole('button', {name: /已处理/}).click();
  const reloadedCard = page.locator('.data412-card', {hasText: 'annotation-flow.bmp'});
  await expect(reloadedCard.locator('.data412-box')).toHaveCount(1);
  await expect(reloadedCard.getByText(/已标注 · 1框/)).toBeVisible();
});

test('batch annotation opens a thumbnail queue and manual save advances to the next image', async ({page, request}) => {
  const project = await createMaterialProject(request, `连续标注-${Date.now()}`);
  const first = await uploadImage(request, project.id, 'queue-one.bmp', [90, 120, 180]);
  const second = await uploadImage(request, project.id, 'queue-two.bmp', [180, 120, 90]);
  await request.post(`/api/v52/projects/${project.id}/images/mark-ready`, {
    data: {image_ids: [first.id, second.id]}
  });
  await selectProject(page, project.id);

  await page.goto('/');
  await page.getByRole('button', {name: /数据集/}).click();
  await page.getByRole('button', {name: /已处理/}).click();
  await page.getByRole('button', {name: '批量操作'}).click();
  const cards = page.locator('.data412-card');
  await cards.filter({hasText: 'queue-one.bmp'}).getByRole('checkbox').check();
  await cards.filter({hasText: 'queue-two.bmp'}).getByRole('checkbox').check();
  await page.getByRole('button', {name: '批量标注'}).click();

  const dialog = page.getByRole('dialog', {name: '图片标注'});
  await expect(dialog.getByText('1 / 2', {exact: true})).toBeVisible();
  await expect(dialog.locator('#ann420Filename')).toHaveText('queue-one.bmp');
  await expect(dialog.getByRole('button', {name: /queue-two\.bmp/})).toBeVisible();
  await dialog.getByRole('button', {name: '保存并继续'}).click();
  await expect(dialog.getByText('2 / 2', {exact: true})).toBeVisible();
  await expect(dialog.locator('.ann414-state')).toContainText('queue-two.bmp');
});

test('material filters come from the label library and unprocessed data exposes batch decisions', async ({page, request}) => {
  const project = await createMaterialProject(request, `素材筛选-${Date.now()}`);
  const person = await uploadImage(request, project.id, 'person.bmp', [180, 70, 70]);
  const vehicle = await uploadImage(request, project.id, 'vehicle.bmp', [70, 90, 180]);
  await uploadImage(request, project.id, 'unprocessed.bmp', [80, 170, 90]);
  for (const [image, classId, label] of [[person, 0, 'person'], [vehicle, 1, 'vehicle']]) {
    const response = await request.post(`/api/projects/${project.id}/annotations/${image.id}`, {
      data: {boxes: [{class_id: classId, label, x1: 10, y1: 10, x2: 70, y2: 60}]}
    });
    expect(response.ok()).toBeTruthy();
  }
  await selectProject(page, project.id);

  await page.goto('/');
  await page.getByRole('button', {name: /数据集/}).click();
  await page.getByRole('button', {name: /未处理/}).click();
  await expect(page.getByRole('button', {name: '批量清洗'})).toBeVisible();
  await expect(page.getByRole('button', {name: '批量无需清洗'})).toBeVisible();
  await page.getByRole('button', {name: /已处理/}).click();
  await expect(page.locator('.data426-chips').getByText('person')).toBeVisible();
  await expect(page.locator('.data426-chips').getByText('vehicle')).toBeVisible();
  await page.locator('.data426-chips').getByRole('button', {name: /person/}).click();
  await page.locator('.data426-chips').getByRole('button', {name: /vehicle/}).click();
  await expect(page.locator('.data412-card')).toHaveCount(2);
});

test('single and multi-image uploads always end with cleaning decisions', async ({page, request}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  const project = await createMaterialProject(request, `上传决策-${Date.now()}`);
  await selectProject(page, project.id);
  await page.goto('/');
  await page.getByRole('button', {name: /数据集/}).click();

  await page.getByRole('button', {name: '上传'}).click();
  await page.locator('#up426Images').setInputFiles({
    name: 'single.bmp', mimeType: 'image/bmp', buffer: bmp(100, 80, [80, 120, 210])
  });
  const singleDialog = page.getByRole('dialog', {name: '图片上传'});
  await expect(singleDialog.getByText('成功上传 1 张')).toBeVisible();
  await expect(singleDialog.getByText('本次上传 1 张素材')).toBeVisible();
  await expect(singleDialog.getByText('本次图片是否需要清洗？')).toHaveCount(0);
  expect(await singleDialog.getByRole('button', {name: '批量无需清洗'}).getAttribute('onclick')).toContain('openBatch414');
  await singleDialog.getByRole('button', {name: '批量无需清洗'}).click();
  expect(pageErrors).toEqual([]);
  const readyDialog = page.getByRole('dialog', {name: '批量无需清洗'});
  await expect(readyDialog.getByText('共 1 张未处理素材')).toBeVisible();
  await readyDialog.getByRole('button', {name: '确认无需清洗'}).click();
  await expect(page.getByRole('button', {name: /已处理1/})).toBeVisible();

  await page.getByRole('button', {name: '上传'}).click();
  await page.locator('#up426Images').setInputFiles([
    {name: 'multi-one.bmp', mimeType: 'image/bmp', buffer: bmp(100, 80, [160, 80, 80])},
    {name: 'multi-two.bmp', mimeType: 'image/bmp', buffer: bmp(100, 80, [80, 160, 80])}
  ]);
  const multiDialog = page.getByRole('dialog', {name: '图片上传'});
  await expect(multiDialog.getByText('成功上传 2 张')).toBeVisible();
  await expect(multiDialog.getByText('本次上传 2 张素材')).toBeVisible();
  await multiDialog.getByRole('button', {name: '批量清洗'}).click();
  const cleanDialog = page.getByRole('dialog', {name: '批量清洗'});
  await expect(cleanDialog.getByText('共 2 张未处理素材')).toBeVisible();
  await expect(cleanDialog.getByRole('button', {name: '开始清洗'})).toBeVisible();
});

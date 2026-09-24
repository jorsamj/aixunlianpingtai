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
  await page.route('**/api/v53/bootstrap/snapshot**', async route => {
    const url = new URL(route.request().url());
    url.searchParams.set('preferred_project_id', projectId);
    await route.fallback({url: url.toString()});
  });
  await page.addInitScript(() => {
    localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({page: '数据集'}));
  });
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

  const dialog = page.getByRole('dialog', {name: '图片标注工作台', exact: true});
  await expect(dialog).toBeVisible();
  await expect(page.locator('.annotation-workbench-modal')).toBeVisible();
  await expect(dialog.locator('#annLabels')).toBeVisible();
  await expect(dialog.locator('#annBoxes')).toBeVisible();
  await expect(dialog.locator('.ann420-toolbar-primary')).toBeVisible();
  const workbenchOutcome = await Promise.race([
    expect(dialog.locator('#annSaveState')).toHaveText('已保存').then(() => 'ready'),
    expect(page.getByText('打开标注失败：LABEL_SCHEMA_CACHE_TTL_MS is not defined')).toBeVisible().then(() => 'ttl-error'),
  ]);
  expect(workbenchOutcome).toBe('ready');
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

  const box = dialog.locator('.box424').first();
  const beforeMove = await box.boundingBox();
  expect(beforeMove).not.toBeNull();
  const moveDx = Math.max(6, imageBox.width * 0.08);
  const moveDy = Math.max(5, imageBox.height * 0.08);
  await page.mouse.move(beforeMove.x + beforeMove.width / 2, beforeMove.y + beforeMove.height / 2);
  await page.mouse.down();
  await page.mouse.move(
    beforeMove.x + beforeMove.width / 2 + moveDx,
    beforeMove.y + beforeMove.height / 2 + moveDy,
    {steps: 4}
  );
  await page.mouse.up();
  const afterMove = await box.boundingBox();
  expect(afterMove.x).toBeGreaterThan(beforeMove.x + 2);
  expect(afterMove.y).toBeGreaterThan(beforeMove.y + 2);

  const resizeHandle = box.locator('.handle424.se');
  await expect(resizeHandle).toBeVisible();
  const beforeResize = await box.boundingBox();
  const handleBox = await resizeHandle.boundingBox();
  expect(handleBox).not.toBeNull();
  await page.mouse.move(handleBox.x + handleBox.width / 2, handleBox.y + handleBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(
    handleBox.x + handleBox.width / 2 + moveDx,
    handleBox.y + handleBox.height / 2 + moveDy,
    {steps: 4}
  );
  await page.mouse.up();
  const afterResize = await box.boundingBox();
  expect(afterResize.width).toBeGreaterThan(beforeResize.width + 2);
  expect(afterResize.height).toBeGreaterThan(beforeResize.height + 2);

  await page.mouse.move(imageBox.x + 2, imageBox.y + 2);
  await page.mouse.wheel(0, -120);
  await expect(dialog.locator('#zoomText')).toHaveText('110%');
  await dialog.getByRole('button', {name: '100%', exact: true}).click();
  await expect(dialog.locator('#zoomText')).toHaveText('100%');
  await dialog.getByRole('button', {name: '适应窗口', exact: true}).click();
  await expect(dialog.locator('#zoomText')).toHaveText(/^\d+%$/);
  await expect(dialog.locator('#annStage')).toHaveAttribute('style', /transform:\s*scale\(/);

  await dialog.getByRole('button', {name: '删除框', exact: true}).click();
  await expect(dialog.locator('.box424')).toHaveCount(0);
  await expect(dialog.getByRole('button', {name: '确认无目标', exact: true})).toBeVisible();
  await dialog.getByRole('button', {name: '撤销', exact: true}).click();
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
  await expect(reloadedCard.getByText(/人工标注 · 1框/)).toBeVisible();
});

test('annotation paints stale cached labels before authoritative label revalidation completes', async ({page, request}) => {
  const project = await createMaterialProject(request, `标签首屏-${Date.now()}`);
  const image = await uploadImage(request, project.id, 'cached-labels.bmp', [110, 150, 190]);
  await request.post(`/api/v52/projects/${project.id}/images/mark-ready`, {
    data: {image_ids: [image.id]}
  });
  const labelsResponse = await request.get(`/api/v12/projects/${project.id}/labels`);
  expect(labelsResponse.ok()).toBeTruthy();
  const cachedLabels = (await labelsResponse.json()).items || [];
  expect(cachedLabels.length).toBeGreaterThan(0);

  let releaseLabels;
  const labelGate = new Promise(resolve => { releaseLabels = resolve; });
  let labelGets = 0;

  await page.route('**/api/v53/bootstrap/snapshot**', async route => {
    const url = new URL(route.request().url());
    url.searchParams.set('preferred_project_id', project.id);
    const response = await route.fetch({url: url.toString()});
    const snapshot = await response.json();
    snapshot.labels = [];
    await route.fulfill({response, json: snapshot});
  });
  await page.route(`**/api/v12/projects/${project.id}/labels`, async route => {
    if (route.request().method() !== 'GET') return route.continue();
    labelGets += 1;
    await labelGate;
    const authoritative = cachedLabels.map(label => (
      label.code === 'person' ? {...label, display_name: '人员（权威）'} : label
    ));
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({items: authoritative}),
    });
  });
  await page.addInitScript(({projectId, labels}) => {
    localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({page: '数据集'}));
    localStorage.setItem(`mc_label_schema_v1:${projectId}`, JSON.stringify({
      ts: Date.now() - 3 * 60 * 1000,
      items: labels,
    }));
  }, {projectId: project.id, labels: cachedLabels});

  await page.goto('/');
  await page.getByRole('button', {name: /数据集/}).click();
  await page.getByRole('button', {name: /已处理/}).click();
  const card = page.locator('.data412-card', {hasText: 'cached-labels.bmp'});
  await expect(card).toBeVisible();
  await card.getByRole('button', {name: '标注'}).click();

  const dialog = page.getByRole('dialog', {name: '图片标注工作台', exact: true});
  await expect(dialog).toBeVisible({timeout: 1_000});
  const selector = dialog.getByLabel('绘制标签');
  await expect(selector).toBeVisible();
  await expect(selector.locator('option')).toHaveText(['人员 · person', '车辆 · vehicle']);
  await expect.poll(() => labelGets).toBe(1);

  releaseLabels();
  await expect(selector.locator('option')).toHaveText(['人员（权威） · person', '车辆 · vehicle'], {timeout: 5_000});
  expect(await page.evaluate(projectId => {
    const cached = JSON.parse(localStorage.getItem(`mc_label_schema_v1:${projectId}`) || 'null');
    return cached?.items?.find(label => label.code === 'person')?.display_name || null;
  }, project.id)).toBe('人员（权威）');
});


test('batch annotation requires explicit empty confirmation and advances across consecutive images', async ({page, request}) => {
  const project = await createMaterialProject(request, `连续空标注-${Date.now()}`);
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

  const dialog = page.getByRole('dialog', {name: '图片标注工作台', exact: true});
  await expect(dialog.getByText('1 / 2', {exact: true})).toBeVisible();
  await expect(dialog.locator('#ann420Filename')).toHaveText('queue-one.bmp');

  const firstConfirm = dialog.getByRole('button', {name: '确认无目标', exact: true});
  await expect(firstConfirm).toBeVisible();
  await expect(firstConfirm).toBeEnabled();
  await firstConfirm.click();

  await expect(dialog.getByText('2 / 2', {exact: true})).toBeVisible();
  await expect(dialog.locator('#ann420Filename')).toHaveText('queue-two.bmp');
  const secondConfirm = dialog.getByRole('button', {name: '确认无目标', exact: true});
  await expect(secondConfirm).toBeVisible();
  await expect(secondConfirm).toBeEnabled();
  await secondConfirm.click();
  await expect(dialog.getByRole('button', {name: '✓ 已确认负样本'})).toBeVisible();

  for (const image of [first, second]) {
    const response = await request.get(`/api/projects/${project.id}/annotations/${image.id}`);
    expect(response.ok()).toBeTruthy();
    const annotation = await response.json();
    expect(annotation.boxes).toEqual([]);
    expect(annotation.annotation_state).toBe('confirmed_empty');
  }
});

test('late annotation response cannot replace the newer image in the stable workbench', async ({page, request}) => {
  const project = await createMaterialProject(request, `标注竞态-${Date.now()}`);
  const first = await uploadImage(request, project.id, 'stale-one.bmp', [75, 130, 190]);
  const second = await uploadImage(request, project.id, 'stale-two.bmp', [190, 130, 75]);
  await request.post(`/api/v52/projects/${project.id}/images/mark-ready`, {
    data: {image_ids: [first.id, second.id]}
  });
  await selectProject(page, project.id);

  let releaseFirst;
  const firstGate = new Promise(resolve => { releaseFirst = resolve; });
  let firstSeenResolve;
  const firstSeen = new Promise(resolve => { firstSeenResolve = resolve; });
  let delayed = false;
  await page.route(`**/api/projects/${project.id}/annotations/*`, async route => {
    const req = route.request();
    if (req.method() === 'GET' && new URL(req.url()).pathname.endsWith(`/annotations/${first.id}`) && !delayed) {
      delayed = true;
      firstSeenResolve();
      await firstGate;
    }
    await route.continue();
  });

  await page.goto('/');
  await page.getByRole('button', {name: /数据集/}).click();
  await page.getByRole('button', {name: /已处理/}).click();
  await page.getByRole('button', {name: '批量操作'}).click();
  const cards = page.locator('.data412-card');
  await cards.filter({hasText: 'stale-one.bmp'}).getByRole('checkbox').check();
  await cards.filter({hasText: 'stale-two.bmp'}).getByRole('checkbox').check();
  await page.getByRole('button', {name: '批量标注'}).click();

  await firstSeen;
  const dialog = page.getByRole('dialog', {name: '图片标注工作台', exact: true});
  await expect(dialog.locator('#ann420Filename')).toHaveText('stale-one.bmp');
  await dialog.locator('#ann420Next').click();
  await expect(dialog.locator('#ann420Filename')).toHaveText('stale-two.bmp');
  await expect(dialog.locator('#annSaveState')).toHaveText('已保存');

  const lateResponse = page.waitForResponse(res =>
    res.request().method() === 'GET' &&
    new URL(res.url()).pathname.endsWith(`/annotations/${first.id}`)
  );
  releaseFirst();
  await lateResponse;
  await expect(dialog.locator('#ann420Filename')).toHaveText('stale-two.bmp');
  await expect(dialog.getByText('2 / 2', {exact: true})).toBeVisible();
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

  await page.locator('.data426-head button[onclick="openDataUpload426()"]').click();
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

  await page.locator('.data426-head button[onclick="openDataUpload426()"]').click();
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


test('label management create and edit stay page-scoped without loading the full material pool', async ({page, request}) => {
  const project = await createMaterialProject(request, `标签管理-${Date.now()}`);
  await selectProject(page, project.id);

  let usageGets = 0;
  const countUsage = req => {
    if (req.method() !== 'GET') return;
    const url = new URL(req.url());
    if (url.pathname === `/api/v54/projects/${project.id}/label-schema`) usageGets += 1;
  };
  page.on('request', countUsage);

  await page.goto('/');
  await page.getByRole('button', {name: /标签管理/}).click();
  await expect(page.locator('.label414-shell')).toBeVisible();
  await expect.poll(() => usageGets).toBeGreaterThan(0);
  const firstVisitUsageGets = usageGets;

  await page.evaluate(() => window.setPage('工作台'));
  await expect(page.locator('#title')).toContainText('总览');
  await page.evaluate(() => window.setPage('标签管理'));
  await expect(page.locator('.label414-shell')).toBeVisible();
  await page.waitForTimeout(150);
  expect(usageGets).toBe(firstVisitUsageGets);

  const saveRequests = [];
  const capture = req => {
    const url = new URL(req.url());
    if (url.pathname.startsWith('/api/')) saveRequests.push(`${req.method()} ${url.pathname}${url.search}`);
  };
  page.on('request', capture);

  await page.getByRole('button', {name: '＋ 新建标签'}).click();
  let dialog = page.getByRole('dialog', {name: '新建标签'});
  await expect(dialog).toBeVisible();
  await dialog.locator('#label414Code').fill('helmet');
  await dialog.locator('#label414Cn').fill('安全帽');
  await dialog.locator('#label414Aliases').fill('toukui1、toukui2');
  await dialog.locator('#label414Hotkey').fill('3');
  await dialog.getByRole('button', {name: '保存', exact: true}).click();

  await expect(dialog).toBeHidden();
  const row = page.locator('.label414-row', {hasText: 'helmet'}).last();
  await expect(row).toBeVisible();
  await expect(row).toContainText('安全帽');
  await expect(row).toContainText('toukui1');
  await expect(row).toContainText('toukui2');

  expect(saveRequests.some(value =>
    value.startsWith(`GET /api/projects/${project.id}/images`)
  )).toBe(false);

  await row.getByRole('button', {name: '编辑'}).click();
  dialog = page.getByRole('dialog', {name: '编辑标签'});
  await expect(dialog).toBeVisible();
  await dialog.locator('#label414Cn').fill('安全头盔');
  await dialog.locator('#label414Aliases').fill('toukui1、helmet_old');
  await dialog.getByRole('button', {name: '保存', exact: true}).click();

  await expect(dialog).toBeHidden();
  const edited = page.locator('.label414-row', {hasText: 'helmet'}).last();
  await expect(edited).toContainText('安全头盔');
  await expect(edited).toContainText('helmet_old');

  const labelsResponse = await request.get(`/api/v12/projects/${project.id}/labels`);
  expect(labelsResponse.ok()).toBeTruthy();
  const labels = (await labelsResponse.json()).items || [];
  const helmet = labels.find(item => item.code === 'helmet');
  expect(helmet).toBeTruthy();
  expect(helmet.display_name).toBe('安全头盔');
  expect(helmet.aliases).toContain('helmet_old');

  page.off('request', capture);
  page.off('request', countUsage);
});


test('previous and next navigation auto-save the current annotation', async ({page, request}) => {
  const project = await createMaterialProject(request, `标注前后切换-${Date.now()}`);
  const first = await uploadImage(request, project.id, 'nav-one.bmp', [70, 120, 200]);
  const second = await uploadImage(request, project.id, 'nav-two.bmp', [200, 120, 70]);
  await request.post(`/api/v52/projects/${project.id}/images/mark-ready`, {
    data: {image_ids: [first.id, second.id]}
  });
  await selectProject(page, project.id);

  await page.goto('/');
  await page.getByRole('button', {name: /数据集/}).click();
  await page.getByRole('button', {name: /已处理/}).click();
  await page.getByRole('button', {name: '批量操作'}).click();
  const cards = page.locator('.data412-card');
  await cards.filter({hasText: 'nav-one.bmp'}).getByRole('checkbox').check();
  await cards.filter({hasText: 'nav-two.bmp'}).getByRole('checkbox').check();
  await page.getByRole('button', {name: '批量标注'}).click();

  const dialog = page.getByRole('dialog', {name: '图片标注工作台', exact: true});
  await expect(dialog.locator('#ann420Filename')).toHaveText('nav-one.bmp');
  const imageBox = await dialog.locator('#annImg').boundingBox();
  expect(imageBox).not.toBeNull();
  await page.mouse.move(imageBox.x + imageBox.width * 0.2, imageBox.y + imageBox.height * 0.2);
  await page.mouse.down();
  await page.mouse.move(imageBox.x + imageBox.width * 0.7, imageBox.y + imageBox.height * 0.7, {steps: 4});
  await page.mouse.up();
  await expect(dialog.locator('.box424')).toHaveCount(1);
  await expect(dialog.locator('#annSaveState')).toHaveText('未保存');

  await dialog.locator('#ann420Next').click();
  await expect(dialog.locator('#ann420Filename')).toHaveText('nav-two.bmp');
  await expect(dialog.getByText('2 / 2', {exact: true})).toBeVisible();

  const savedResponse = await request.get(`/api/projects/${project.id}/annotations/${first.id}`);
  expect(savedResponse.ok()).toBeTruthy();
  const saved = await savedResponse.json();
  expect(saved.boxes).toHaveLength(1);

  await dialog.locator('#ann420Prev').click();
  await expect(dialog.locator('#ann420Filename')).toHaveText('nav-one.bmp');
  await expect(dialog.getByText('1 / 2', {exact: true})).toBeVisible();
  await expect(dialog.locator('.box424')).toHaveCount(1);
  await expect(dialog.locator('#annSaveState')).toHaveText('已保存');
});

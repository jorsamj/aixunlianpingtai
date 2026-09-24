import {test, expect} from '@playwright/test';

async function selectIsolatedTestProject(page, projectId) {
  await page.route('**/api/v53/bootstrap/snapshot**', async route => {
    const url = new URL(route.request().url());
    url.searchParams.set('preferred_project_id', projectId);
    await route.continue({url: url.toString()});
  });
}

function crc32(buffer) {
  let crc = 0xffffffff;
  for (const byte of buffer) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function storedZip(entries) {
  const locals = [];
  const centrals = [];
  let offset = 0;
  for (const [name, raw] of entries) {
    const data = Buffer.isBuffer(raw) ? raw : Buffer.from(raw);
    const filename = Buffer.from(name);
    const crc = crc32(data);
    const local = Buffer.alloc(30 + filename.length);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4);
    local.writeUInt16LE(0, 6);
    local.writeUInt16LE(0, 8);
    local.writeUInt32LE(crc, 14);
    local.writeUInt32LE(data.length, 18);
    local.writeUInt32LE(data.length, 22);
    local.writeUInt16LE(filename.length, 26);
    filename.copy(local, 30);
    locals.push(local, data);

    const central = Buffer.alloc(46 + filename.length);
    central.writeUInt32LE(0x02014b50, 0);
    central.writeUInt16LE(20, 4);
    central.writeUInt16LE(20, 6);
    central.writeUInt16LE(0, 8);
    central.writeUInt16LE(0, 10);
    central.writeUInt32LE(crc, 16);
    central.writeUInt32LE(data.length, 20);
    central.writeUInt32LE(data.length, 24);
    central.writeUInt16LE(filename.length, 28);
    central.writeUInt32LE(offset, 42);
    filename.copy(central, 46);
    centrals.push(central);
    offset += local.length + data.length;
  }
  const centralOffset = offset;
  const centralData = Buffer.concat(centrals);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(entries.length, 8);
  end.writeUInt16LE(entries.length, 10);
  end.writeUInt32LE(centralData.length, 12);
  end.writeUInt32LE(centralOffset, 16);
  return Buffer.concat([...locals, centralData, end]);
}

async function createProject(request, labels = []) {
  const response = await request.post('/api/projects', {data: {name: `ZIP恢复-${Date.now()}`, labels}});
  expect(response.ok()).toBeTruthy();
  return response.json();
}

async function createSelectingZipJob(request, projectId, {className = 'object', fileName = 'refresh-recovery.zip'} = {}) {
  const zip = storedZip([
    ['images/train/sample.jpg', Buffer.from('not-decoded-during-scan')],
    ['data.yaml', Buffer.from(`train: images/train\nnames: [${className}]\n`)],
  ]);
  const response = await request.post(`/api/v19/projects/${projectId}/datasets/default/import/jobs`, {
    multipart: {file: {name: fileName, mimeType: 'application/zip', buffer: zip}},
  });
  expect(response.ok()).toBeTruthy();
  const body = await response.json();
  expect(body.status).toBe('selecting');
  return body;
}

test('exact platform label code is reused without creating a duplicate label', async ({page, request}) => {
  const project = await createProject(request, [
    {code: 'object', display_name: '对象', color: '#3b82f6'}
  ]);
  const job = await createSelectingZipJob(request, project.id, {className: 'object', fileName: 'exact-code.zip'});
  expect(job.label_confirmation_required).toBeTruthy();
  expect(job.external_classes?.[0]?.name).toBe('object');

  await selectIsolatedTestProject(page, project.id);
  await page.addInitScript(() => {
    localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({page: '数据集'}));
  });

  const labelPosts = [];
  page.on('request', req => {
    const url = new URL(req.url());
    if (req.method() === 'POST' && url.pathname === `/api/projects/${project.id}/labels`) labelPosts.push(req);
  });

  await page.goto('/');
  await page.getByRole('button', {name: /数据集/}).click();
  const taskCenter = page.locator('#uploadTaskCenter');
  await expect(taskCenter).toBeVisible({timeout: 10_000});
  await taskCenter.locator('[data-utc-toggle]').click();
  const zipRow = taskCenter.locator(`[data-utc-id="zip:${job.id}"]`);
  await expect(zipRow).toBeVisible();
  await zipRow.click();

  const importDialog = page.getByRole('dialog', {name: 'ZIP 数据导入'});
  await expect(importDialog).toBeVisible();
  await expect(importDialog.getByText('自动匹配', {exact: true})).toBeVisible();
  const target = importDialog.locator('[data-zip-target]');
  await expect(target).toHaveValue('object');
  await expect(target.locator('option[value="__create__"]')).toHaveCount(0);

  const startRequestPromise = page.waitForRequest(req =>
    req.method() === 'POST' &&
    new URL(req.url()).pathname === `/api/v19/projects/${project.id}/import/jobs/${job.id}/start`
  );
  const startResponsePromise = page.waitForResponse(res =>
    res.request().method() === 'POST' &&
    new URL(res.url()).pathname === `/api/v19/projects/${project.id}/import/jobs/${job.id}/start`
  );
  await importDialog.getByRole('button', {name: '确认标签并开始导入'}).click();
  const startRequest = await startRequestPromise;
  const startResponse = await startResponsePromise;
  expect(startResponse.ok()).toBeTruthy();
  const mapping = startRequest.postDataJSON().label_mapping;
  expect(mapping[String(job.external_classes[0].class_id)]).toBe('object');
  expect(labelPosts).toHaveLength(0);
});

test('server-persisted ZIP job restores explicit file-label creation after refresh and confirms it through the label API', async ({page, request}) => {
  const project = await createProject(request);
  const job = await createSelectingZipJob(request, project.id, {className: 'helmet', fileName: 'refresh-recovery.zip'});
  expect(job.id).toBeTruthy();
  expect(job.label_confirmation_required).toBeTruthy();
  expect(job.external_classes?.[0]?.name).toBe('helmet');

  await selectIsolatedTestProject(page, project.id);
  await page.addInitScript(() => {
    localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({page: '数据集'}));
  });

  await page.goto('/');
  await page.getByRole('button', {name: /数据集/}).click();
  const taskCenter = page.locator('#uploadTaskCenter');
  await expect(taskCenter).toBeVisible({timeout: 10_000});
  await expect(taskCenter).toContainText('数据导入 / 上传');

  await taskCenter.locator('[data-utc-toggle]').click();
  await expect(taskCenter).toContainText('refresh-recovery.zip');
  await expect(taskCenter).toContainText(/等待确认标注|等待中|后台/);
  let zipRow = taskCenter.locator(`[data-utc-id="zip:${job.id}"]`);
  await expect(zipRow).toBeVisible();
  await zipRow.click();

  let importDialog = page.getByRole('dialog', {name: 'ZIP 数据导入'});
  await expect(importDialog).toBeVisible();
  await expect(importDialog.getByText('将新增', {exact: true})).toBeVisible();
  let target = importDialog.locator('[data-zip-target]');
  await expect(target).toHaveValue('__create__');
  await expect(target.locator('option:checked')).toHaveText('＋ 使用文件标签“helmet”并新增');
  await importDialog.getByRole('button', {name: '关闭窗口'}).click();

  await page.reload();
  await expect(taskCenter).toBeVisible({timeout: 10_000});
  await taskCenter.locator('[data-utc-toggle]').click();
  await expect(taskCenter).toContainText('refresh-recovery.zip');
  zipRow = taskCenter.locator(`[data-utc-id="zip:${job.id}"]`);
  await expect(zipRow).toBeVisible();
  await zipRow.click();

  importDialog = page.getByRole('dialog', {name: 'ZIP 数据导入'});
  await expect(importDialog).toBeVisible();
  target = importDialog.locator('[data-zip-target]');
  await expect(target).toHaveValue('__create__');
  await expect(target.locator('option:checked')).toHaveText('＋ 使用文件标签“helmet”并新增');

  const labelRequestPromise = page.waitForRequest(req =>
    req.method() === 'POST' &&
    new URL(req.url()).pathname === `/api/projects/${project.id}/labels`
  );
  const startRequestPromise = page.waitForRequest(req =>
    req.method() === 'POST' &&
    new URL(req.url()).pathname === `/api/v19/projects/${project.id}/import/jobs/${job.id}/start`
  );
  const startResponsePromise = page.waitForResponse(res =>
    res.request().method() === 'POST' &&
    new URL(res.url()).pathname === `/api/v19/projects/${project.id}/import/jobs/${job.id}/start`
  );

  await importDialog.getByRole('button', {name: '确认标签并开始导入'}).click();
  const labelRequest = await labelRequestPromise;
  expect(labelRequest.postDataJSON().label).toBe('helmet');
  const startRequest = await startRequestPromise;
  const startResponse = await startResponsePromise;
  expect(startResponse.ok()).toBeTruthy();
  const mapping = startRequest.postDataJSON().label_mapping;
  expect(mapping[String(job.external_classes[0].class_id)]).toBe('helmet');

  const labelsResponse = await request.get(`/api/v12/projects/${project.id}/labels`);
  expect(labelsResponse.ok()).toBeTruthy();
  const labels = (await labelsResponse.json()).items || [];
  expect(labels.some(label => label.code === 'helmet')).toBeTruthy();

  // The retired single-task ZIP dock must stay hidden when the unified task center owns visibility.
  await expect(page.locator('#zipImportDurableDock')).toBeHidden();
});

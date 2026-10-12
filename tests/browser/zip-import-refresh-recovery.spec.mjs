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

test('exact English source label reuses existing canonical code without recreating it', async ({page, request}) => {
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
  await expect(importDialog.locator('#zipBatchQueueList')).toHaveCount(0);
  await expect(importDialog.locator('.zip-label-destination b').first()).toHaveText(/object|helmet/);
  const target = importDialog.locator('[data-zip-target]');
  await expect(target).toHaveValue('object');
  await expect(target.locator('option[value="__create__"]')).toHaveCount(0);
  await expect(importDialog.getByRole('button',{name:'确认标签并导入'})).toBeEnabled();

  const startRequestPromise = page.waitForRequest(req =>
    req.method() === 'POST' &&
    new URL(req.url()).pathname === `/api/v19/projects/${project.id}/import/jobs/${job.id}/start`
  );
  const startResponsePromise = page.waitForResponse(res =>
    res.request().method() === 'POST' &&
    new URL(res.url()).pathname === `/api/v19/projects/${project.id}/import/jobs/${job.id}/start`
  );
  await importDialog.getByRole('button', {name: '确认标签并导入'}).click();
  const startRequest = await startRequestPromise;
  const startResponse = await startResponsePromise;
  expect(startResponse.ok()).toBeTruthy();
  const mapping = startRequest.postDataJSON().label_mapping;
  expect(mapping[String(job.external_classes[0].class_id)]).toBe('object');
  expect(labelPosts).toHaveLength(0);
});

test('explicit source label creation survives refresh and exact mapping is restored safely', async ({page, request}) => {
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
  await expect(importDialog.locator('.zip-label-unmapped')).toBeVisible();
  let target = importDialog.locator('[data-zip-target]');
  await expect(target).toHaveValue('');

  const labelRequestPromise = page.waitForRequest(req =>
    req.method() === 'POST' &&
    new URL(req.url()).pathname === `/api/projects/${project.id}/labels`
  );
  await importDialog.getByRole('button', {name: '手动调整'}).click();
  await importDialog.getByRole('button', {name: '新建平台标签', exact: true}).click();
  const createDialog = page.getByRole('dialog', {name: '新建平台标签'});
  await expect(createDialog).toBeVisible();
  await createDialog.locator('#inlineLabel414Code').fill('helmet');
  await createDialog.locator('#inlineLabel414Name').fill('安全帽');
  await createDialog.getByRole('button', {name: '创建并使用'}).click();
  const labelRequest = await labelRequestPromise;
  expect(labelRequest.postDataJSON().label).toBe('helmet');

  const labelsResponse = await request.get(`/api/v12/projects/${project.id}/labels`);
  expect(labelsResponse.ok()).toBeTruthy();
  const labels = (await labelsResponse.json()).items || [];
  expect(labels.some(label => label.code === 'helmet')).toBeTruthy();

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
  await expect(target).toHaveValue('helmet');
  await expect(importDialog.locator('.zip-label-destination b').first()).toHaveText(/object|helmet/);

  const startRequestPromise = page.waitForRequest(req =>
    req.method() === 'POST' &&
    new URL(req.url()).pathname === `/api/v19/projects/${project.id}/import/jobs/${job.id}/start`
  );
  const startResponsePromise = page.waitForResponse(res =>
    res.request().method() === 'POST' &&
    new URL(res.url()).pathname === `/api/v19/projects/${project.id}/import/jobs/${job.id}/start`
  );

  await importDialog.getByRole('button', {name: '确认标签并导入'}).click();
  const startRequest = await startRequestPromise;
  const startResponse = await startResponsePromise;
  expect(startResponse.ok()).toBeTruthy();
  const mapping = startRequest.postDataJSON().label_mapping;
  expect(mapping[String(job.external_classes[0].class_id)]).toBe('helmet');

  // The retired single-task ZIP dock must stay hidden when the unified task center owns visibility.
  await expect(page.locator('#zipImportDurableDock')).toBeHidden();
});

test('two selected ZIP archives upload their multipart data concurrently while label review stays single-task',async({page,request})=>{
  const project=await createProject(request);
  await selectIsolatedTestProject(page,project.id);
  await page.goto('/');
  await expect.poll(()=>page.evaluate(()=>Boolean(window.ZipImportRuntime?.uploadBatch))).toBe(true);
  const urls=[];
  let releaseUploads;
  const gate=new Promise(resolve=>{releaseUploads=resolve});
  await page.route('**/api/v19/projects/*/import/uploads/*/parts/*',async route=>{
    const url=new URL(route.request().url());
    if(url.pathname.includes('/projects/'+project.id+'/')) {
      urls.push(url.pathname);
      await gate;
    }
    await route.continue();
  });
  const makeArchive=label=>storedZip([
    ['images/train/'+label+'.jpg',Buffer.from('sample-image-content')],
    ['data.yaml',Buffer.from('train: images/train\nnames: ['+label+']\n')],
  ]);
  try{
    await page.evaluate(()=>window.importData());
    await page.locator('#importFile').setInputFiles([
      {name:'parallel-one.zip',mimeType:'application/zip',buffer:makeArchive('helmet')},
      {name:'parallel-two.zip',mimeType:'application/zip',buffer:makeArchive('smoke')},
    ]);
    await page.evaluate(()=>{void window.doImportUploadV19()});
    await expect.poll(()=>new Set(urls.map(url=>url.split('/import/uploads/')[1]?.split('/')[0])).size,{timeout:30000}).toBe(2);
    const dialog=page.getByRole('dialog',{name:'ZIP 数据导入'});
    await expect(dialog).toBeVisible();
    await expect(dialog.locator('#zipBatchQueueList')).toHaveCount(0);
  }finally{
    releaseUploads();
  }
  await expect.poll(async()=>page.evaluate(()=>{
    const names=window.ZipImportRuntime?.snapshot?.().jobs.map(job=>job.file_name)||[];
    return ['parallel-one.zip','parallel-two.zip'].filter(name=>names.includes(name)).length;
  }),{timeout:30000}).toBe(2);
  await expect(page.locator('.zip-label-confirm')).toHaveCount(1,{timeout:30000});
});

test('three ZIPs finish upload and independently await human label confirmation',async({page,request})=>{
  const project=await createProject(request);
  await selectIsolatedTestProject(page,project.id);
  await page.goto('/');
  await expect.poll(()=>page.evaluate(()=>Boolean(window.ZipImportRuntime?.uploadBatch))).toBe(true);
  const startRequests=[];
  page.on('request',req=>{
    if(req.method()==='POST'&&new URL(req.url()).pathname.includes('/projects/'+project.id+'/import/jobs/')&&
       new URL(req.url()).pathname.endsWith('/start'))startRequests.push(req);
  });
  const zip=label=>storedZip([
    ['images/train/'+label+'.jpg',Buffer.from('scan-only-image')],
    ['data.yaml',Buffer.from('train: images/train\nnames: ['+label+']\n')],
  ]);
  const filenames=['await-dog.zip','await-cat.zip','await-helmet.zip'];
  await page.evaluate(()=>window.importData());
  await page.locator('#importFile').setInputFiles([
    {name:filenames[0],mimeType:'application/zip',buffer:zip('dog')},
    {name:filenames[1],mimeType:'application/zip',buffer:zip('cat')},
    {name:filenames[2],mimeType:'application/zip',buffer:zip('helmet')},
  ]);
  await page.evaluate(()=>{void window.doImportUploadV19()});
  const jobsUrl='/api/v19/projects/'+project.id+'/import/jobs';
  await expect.poll(async()=>{
    const response=await request.get(jobsUrl);
    if(!response.ok())return [];
    const rows=(await response.json()).items||[];
    return filenames.filter(name=>rows.some(row=>
      row.file_name===name&&row.status==='selecting'&&row.label_confirmation_required
    ));
  },{timeout:60000}).toEqual(filenames);
  expect(startRequests).toHaveLength(0);
  const dialog=page.getByRole('dialog',{name:'ZIP 数据导入'});
  await expect(dialog.locator('.zip-label-confirm')).toHaveCount(1);
  await dialog.getByRole('button',{name:'关闭窗口'}).click();
  await page.locator('#uploadTaskCenter [data-utc-toggle]').click();
  await expect(page.locator('#uploadTaskCenter')).toContainText(filenames[2]);
  const rows=(await (await request.get(jobsUrl)).json()).items||[];
  const third=rows.find(row=>row.file_name===filenames[2]);
  expect(third?.id).toBeTruthy();
  await page.locator('[data-utc-id="zip:'+third.id+'"]').click();
  await expect(dialog).toContainText(filenames[2]);
  await expect(dialog.locator('.zip-label-confirm')).toHaveCount(1);
  expect(startRequests).toHaveLength(0);
});

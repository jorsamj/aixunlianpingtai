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
  await page.setViewportSize({width: 1366, height: 768});
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
  await expect(importDialog.locator('.zip-label-workspace')).toBeVisible();
  await expect(importDialog.locator('[data-zip-class-samples]')).toBeVisible();
  await expect(importDialog.locator('.zip-label-destination b').first()).toHaveText(/object|helmet/);
  const target = importDialog.locator('[data-zip-target]');
  await expect(target).toHaveValue('object');
  await expect(target.locator('option[value="__create__"]')).toHaveCount(0);
  const confirmButton = importDialog.getByRole('button',{name:'确认标签并导入'});
  await expect(confirmButton).toBeEnabled();
  await expect(confirmButton).toBeInViewport();
  const confirmBox = await confirmButton.boundingBox();
  expect(confirmBox).not.toBeNull();
  expect(confirmBox.y + confirmBox.height).toBeLessThanOrEqual(768);
  await expect(taskCenter).toHaveCSS('z-index','900');

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

test('single-step original label mapping creates formal labels only at final import confirmation', async ({page, request}) => {
  const project = await createProject(request);
  const job = await createSelectingZipJob(request, project.id, {className: 'helmet', fileName: 'one-step-helmet.zip'});
  expect(job.label_confirmation_required).toBeTruthy();
  await selectIsolatedTestProject(page, project.id);
  await page.addInitScript(() => {
    localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({page: '数据集'}));
  });
  const labelPosts = [];
  page.on('request', req => {
    if (req.method() === 'POST' && new URL(req.url()).pathname === `/api/projects/${project.id}/labels`) labelPosts.push(req);
  });
  await page.goto('/');
  await page.getByRole('button', {name: /数据集/}).click();
  const taskCenter = page.locator('#uploadTaskCenter');
  await expect(taskCenter).toBeVisible({timeout: 10_000});
  await taskCenter.locator('[data-utc-toggle]').click();
  await expect(taskCenter).toContainText('one-step-helmet.zip');
  await taskCenter.locator(`[data-utc-id="zip:${job.id}"]`).click();

  const importDialog = page.getByRole('dialog', {name: 'ZIP 数据导入'});
  await expect(importDialog).toBeVisible();
  const target = importDialog.locator('[data-zip-target]');
  await expect(target).toBeVisible();
  await expect(target).toHaveValue('');
  await importDialog.getByRole('button',{name:'一键使用原始标签'}).click();
  await expect(target).toHaveValue('helmet');
  await expect(importDialog.locator('.zip-label-pending')).toContainText('helmet');
  await expect(importDialog.getByRole('button',{name:'创建标签并导入'})).toBeEnabled();
  await expect(taskCenter).toHaveCSS('z-index','900');
  expect(labelPosts).toHaveLength(0);

  const before = await request.get(`/api/v12/projects/${project.id}/labels`);
  expect(before.ok()).toBeTruthy();
  expect(((await before.json()).items || []).some(label => label.code === 'helmet')).toBeFalsy();

  const createResponse = page.waitForResponse(res =>
    res.request().method() === 'POST' && new URL(res.url()).pathname === `/api/projects/${project.id}/labels`
  );
  const startRequest = page.waitForRequest(req =>
    req.method() === 'POST' && new URL(req.url()).pathname === `/api/v19/projects/${project.id}/import/jobs/${job.id}/start`
  );
  const startResponse = page.waitForResponse(res =>
    res.request().method() === 'POST' && new URL(res.url()).pathname === `/api/v19/projects/${project.id}/import/jobs/${job.id}/start`
  );
  await importDialog.getByRole('button',{name:'创建标签并导入'}).click();
  expect((await createResponse).ok()).toBeTruthy();
  const requestStart = await startRequest;
  expect((await startResponse).ok()).toBeTruthy();
  expect(labelPosts).toHaveLength(1);
  expect(labelPosts[0].postDataJSON().label).toBe('helmet');
  expect(requestStart.postDataJSON().label_mapping[String(job.external_classes[0].class_id)]).toBe('helmet');

  await page.reload();
  const persisted = await request.get(`/api/v12/projects/${project.id}/labels`);
  expect(persisted.ok()).toBeTruthy();
  expect(((await persisted.json()).items || []).some(label => label.code === 'helmet')).toBeTruthy();
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
    // The dock must remain clickable above the still-open upload modal.
    const toggle=page.locator('#uploadTaskCenter [data-utc-toggle]');
    await expect(toggle).toBeVisible();
    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-expanded','true');
    const taskRows=page.locator('#uploadTaskCenter .utc-row[data-utc-kind="zip"]');
    await expect(taskRows).toHaveCount(2);
    // Reopening from a minimized upload modal must restore the same dialog.
    await dialog.locator('[data-import-minimize]').click();
    await expect(dialog).toHaveClass(/import350-minimized/);
    await taskRows.first().click();
    await expect(dialog).not.toHaveClass(/import350-minimized/);
    await expect(page.getByRole('dialog',{name:'ZIP 数据导入'})).toHaveCount(1);
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
  await expect(dialog.locator('[data-zip-class-samples]')).toHaveCSS('position','static');
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

test('late ZIP inventory response cannot cross a project switch',async({page})=>{
  await page.goto('/');
  const result=await page.evaluate(async()=>{
    window.ZipImportRuntime?.destroy?.();
    const {installZipImportRuntime}=await import('/static/modules/zip-import-runtime.js?v=project-fence-test');
    const state={project:{id:'project-a'},labels:[],page:'数据集'};
    let releaseProjectA;
    const requests=[];
    const response=body=>({ok:true,status:200,json:async()=>body});
    const fetchImpl=url=>{
      const value=String(url);requests.push(value);
      if(value.includes('/projects/project-a/import/jobs'))return new Promise(resolve=>{releaseProjectA=()=>resolve(response({items:[{id:'job-a',status:'done',file_name:'A.zip'}]}))});
      if(value.includes('/projects/project-b/import/jobs'))return Promise.resolve(response({items:[{id:'job-b',status:'done',file_name:'B.zip'}]}));
      return Promise.resolve(response({items:[]}));
    };
    const runtime=installZipImportRuntime({getState:()=>state,projectId:()=>state.project.id,fetchImpl,pollMs:60000});
    for(let index=0;index<20&&!releaseProjectA;index++)await new Promise(resolve=>setTimeout(resolve,0));
    state.project={id:'project-b'};
    void runtime.reconcile('project-switch-test');
    releaseProjectA();
    for(let index=0;index<50;index++){
      const ids=runtime.snapshot().jobs.map(job=>job.id);
      if(ids.includes('job-b'))break;
      await new Promise(resolve=>setTimeout(resolve,10));
    }
    const ids=runtime.snapshot().jobs.map(job=>job.id);
    runtime.destroy();
    return {ids,requests};
  });
  expect(result.ids).toEqual(['job-b']);
  expect(result.ids).not.toContain('job-a');
  expect(result.requests.some(url=>url.includes('/projects/project-b/import/jobs'))).toBeTruthy();
});

test('narrow label review cancels one server job without touching its sibling',async({page,request})=>{
  const project=await createProject(request);
  const first=await createSelectingZipJob(request,project.id,{className:'helmet',fileName:'cancel-only-this.zip'});
  const second=await createSelectingZipJob(request,project.id,{className:'smoke',fileName:'keep-this.zip'});
  await page.setViewportSize({width:375,height:812});
  await selectIsolatedTestProject(page,project.id);
  await page.addInitScript(()=>localStorage.setItem('mc_train_ui_state_v34',JSON.stringify({page:'数据集'})));
  await page.goto('/');
  await expect.poll(()=>page.evaluate(()=>window.ZipImportRuntime?.snapshot?.().jobs.length||0)).toBeGreaterThanOrEqual(2);
  await page.evaluate(()=>window.PollRegistryRuntime?.clear?.('zip-import-runtime'));
  await page.waitForTimeout(200);
  const observationReads=[];
  const captureObservation=requestEvent=>{
    const url=new URL(requestEvent.url());
    if(requestEvent.method()==='GET'&&url.pathname===`/api/v19/projects/${project.id}/import/jobs`)observationReads.push(url.pathname);
  };
  page.on('request',captureObservation);
  await page.evaluate(()=>window.ZipImportRuntime.reconcile('request-count-audit'));
  page.off('request',captureObservation);
  expect(observationReads).toHaveLength(1);
  console.log(`[zip-reconcile-inventory] observation-only list GET before=2 after=${observationReads.length}`);
  const taskCenter=page.locator('#uploadTaskCenter');
  await expect(taskCenter).toBeVisible({timeout:10000});
  await taskCenter.locator('[data-utc-toggle]').click();
  await taskCenter.locator(`[data-utc-id="zip:${first.id}"]`).click();

  const dialog=page.getByRole('dialog',{name:'ZIP 数据导入'});
  await expect(dialog.locator('.zip-label-confirm')).toBeVisible();
  await expect(dialog.locator('.zip-label-footer-actions')).toHaveCSS('display','grid');
  expect(await dialog.evaluate(node=>node.scrollWidth<=node.clientWidth+1)).toBeTruthy();

  page.once('dialog',confirmation=>confirmation.accept());
  const cancelledResponse=page.waitForResponse(response=>
    response.request().method()==='POST'&&
    new URL(response.url()).pathname===`/api/v19/projects/${project.id}/import/jobs/${first.id}/cancel`
  );
  await dialog.getByRole('button',{name:'取消当前 ZIP 导入任务'}).click();
  const cancelResult=await cancelledResponse;
  expect(cancelResult.ok()).toBeTruthy();
  expect((await cancelResult.json()).cleanup_status).toBe('complete');

  await expect.poll(async()=>{
    const response=await request.get(`/api/v19/projects/${project.id}/import/jobs`);
    const items=(await response.json()).items||[];
    return {
      first:items.find(item=>item.id===first.id)?.status,
      second:items.find(item=>item.id===second.id)?.status,
    };
  }).toEqual({first:'cancelled',second:'selecting'});

  await taskCenter.locator(`[data-utc-id="zip:${second.id}"]`).click();
  await expect(dialog).toContainText('keep-this.zip');
  await expect(dialog.locator('.zip-label-confirm')).toBeVisible();
});

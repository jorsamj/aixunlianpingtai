import {test, expect} from '@playwright/test';

function bmp(width = 40, height = 30, rgb = [42, 120, 210]) {
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

async function createProject(request) {
  const response = await request.post('/api/projects', {data: {name: `分批上传-${Date.now()}`, labels: []}});
  expect(response.ok()).toBeTruthy();
  return response.json();
}

async function selectIsolatedTestProject(page, projectId) {
  await page.route('**/api/v53/bootstrap/snapshot**', async route => {
    const url = new URL(route.request().url());
    url.searchParams.set('preferred_project_id', projectId);
    await route.fallback({url: url.toString()});
  });
  await page.addInitScript(() => {
    localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({page: '数据集'}));
  });
}

test('65 browser-selected images upload as two sequential server-confirmed chunks', async ({page, request}) => {
  const project = await createProject(request);
  await selectIsolatedTestProject(page, project.id);

  const uploadRequests = [];
  let active = 0;
  let maxActive = 0;
  page.on('request', req => {
    const url = new URL(req.url());
    if (req.method() === 'POST' && url.pathname === `/api/projects/${project.id}/images`) {
      uploadRequests.push(req);
      active += 1;
      maxActive = Math.max(maxActive, active);
    }
  });
  page.on('response', response => {
    const req = response.request();
    const url = new URL(req.url());
    if (req.method() === 'POST' && url.pathname === `/api/projects/${project.id}/images`) active -= 1;
  });

  await page.goto('/');
  await page.getByRole('button', {name: /数据集/}).click();
  await page.getByRole('button', {name: '上传'}).click();
  const payloads = Array.from({length: 65}, (_, index) => ({
    name: `chunk-${String(index + 1).padStart(2, '0')}.bmp`,
    mimeType: 'image/bmp',
    buffer: bmp(40, 30, [40 + index % 100, 90, 160]),
  }));
  await page.locator('#up426Images').setInputFiles(payloads);

  const dialog = page.locator('[data-upload-confirmation]');
  await expect(dialog.getByRole('heading',{name:'本次上传图片'})).toBeVisible({timeout:60_000});
  await expect(dialog.locator('.uc-summary')).toContainText('成功入库 65 张');
  await expect(dialog.locator('.uc-summary')).toContainText('本次选择 65 张');
  expect(uploadRequests).toHaveLength(2);
  expect(maxActive).toBe(1);
  await page.locator('[data-utc-toggle]').click();
  const task=page.locator('.utc-row[data-utc-kind="browser-upload"]').filter({hasText:'图片上传 · 65 张'});
  await expect(task).toContainText('上传完成');
  await task.getByRole('button',{name:'查看详情'}).click();
  await expect(page.locator('.utc-upload-details')).toContainText('成功 65 · 失败 0');
});


for(const corrupt of [false,true])test(`Uppy five image receipt workspace ${corrupt?'keeps one failed file out':'opens original annotation without creating GT'}`,async({page,request})=>{
 const errors=[];page.on('pageerror',error=>errors.push(error.message));const project=await createProject(request);await selectIsolatedTestProject(page,project.id);const uploads=[];
 page.on('request',r=>{if(r.method()==='POST'&&new URL(r.url()).pathname===`/api/projects/${project.id}/images`)uploads.push(r)});
 await page.goto('/');await page.getByRole('button',{name:'上传',exact:true}).click();await page.getByRole('button',{name:/上传图片/}).click();
 const root=page.locator('[data-image-uppy-view]');await expect(root.locator('.uppy-Dashboard')).toBeVisible();
 const files=Array.from({length:5},(_,i)=>({name:`actual-${i}.bmp`,mimeType:'image/bmp',buffer:corrupt&&i===4?Buffer.from('corrupt'):bmp(40,30,[40+i*10,90,120])}));
 await root.locator('input[type=file]').first().setInputFiles(files);await expect.poll(()=>page.evaluate(()=>window.ImageUppyView.uppy.getFiles().length)).toBe(5);
 await root.locator('.uppy-StatusBar-actionBtn--upload').click();const workspace=page.locator('[data-upload-confirmation]');await expect(workspace.getByRole('heading',{name:'本次上传图片'})).toBeVisible();await expect(workspace.locator('.uc-grid article')).toHaveCount(corrupt?4:5);
 expect(uploads).toHaveLength(1);expect((uploads[0].postDataBuffer().toString().match(/filename="/g)||[])).toHaveLength(5);
 const stored=await page.evaluate(pid=>JSON.parse(localStorage.getItem(`material-upload-session:${pid}`)),project.id);expect(stored.batchIds).toHaveLength(1);
 const receipt=await(await request.get(`/api/v55/projects/${project.id}/upload-batches/${stored.batchIds[0]}`)).json();expect(receipt.items).toHaveLength(corrupt?4:5);expect(receipt.upload_failed).toHaveLength(corrupt?1:0);
 await workspace.locator('[data-preview]').first().click();await expect(page.getByRole('dialog',{name:'图片详情',exact:true})).toBeVisible();await page.evaluate(()=>window.closeModal());
 if(corrupt){
  await expect(workspace).toContainText('上传失败 1 张');await page.reload();await expect(page.locator('[data-upload-confirmation] .uc-grid article')).toHaveCount(4);
  await page.locator('[data-upload-confirmation] [data-id]').first().check();await page.getByRole('button',{name:'开始清洗',exact:true}).click();await expect(page.locator('[data-upload-confirmation]')).toContainText('已提交清洗');
  const mixed=await(await request.get(`/api/v55/projects/${project.id}/upload-batches/${stored.batchIds[0]}`)).json();expect(mixed.clean_task_id).toBeTruthy();expect(mixed.items.filter(row=>row.decision==='clean')).toHaveLength(1);expect(mixed.items.filter(row=>row.decision==='pending')).toHaveLength(3);
  await page.getByRole('button',{name:'稍后处理',exact:true}).click();await page.reload();await expect.poll(()=>page.evaluate(()=>state.uiReady)).toBe(true);await expect(page.locator('[data-upload-confirmation] .uc-workspace')).toHaveCount(0);await expect(page.locator('[data-upload-confirmation]')).toContainText('3 张待处理');expect(errors).toEqual([]);return;
 }
 await workspace.locator('[data-upload-action=all]').check();await workspace.getByRole('button',{name:'无需清洗，进入标注',exact:true}).click();await expect(page.locator('.ann420-stable')).toBeVisible();
 const after=await(await request.get(`/api/v55/projects/${project.id}/upload-batches/${stored.batchIds[0]}`)).json();expect(after.items.every(row=>row.decision==='ready'&&row.image.annotation_state==='unannotated')).toBe(true);
 await page.reload();await expect.poll(()=>page.evaluate(()=>state.uiReady)).toBe(true);await expect(page.locator('.ann420-stable')).toHaveCount(0);await expect(page.locator('[data-upload-confirmation] .uc-workspace')).toHaveCount(0);expect(errors).toEqual([]);
});

import {test, expect} from '@playwright/test';

const PIXEL = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=', 'base64');

function material(index, page = 1) {
  const id = `picker-${page}-${String(index).padStart(3, '0')}`;
  return {
    id,
    filename: `${id}.jpg`,
    labels: index === 59 ? [] : (index % 2 ? ['person'] : ['smoke']),
    annotated: index !== 59,
    box_count: index === 59 ? 0 : 1,
    width: 400,
    height: 200,
    annotation_state: index === 59 ? 'unannotated' : 'annotated',
    boxes: index === 59 ? [] : [{id: `box-${id}`, label: index % 2 ? 'person' : 'smoke', x1: 40, y1: 20, x2: 200, y2: 100}],
    processing_status: 'processed',
    thumbnail_url: `/thumb/${id}.png`,
    content_url: `/full/${id}.png`,
  };
}

test('training material picker opens immediately, renders larger previews, and pages 60 rows from the server', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await expect.poll(async () => page.evaluate(() => window.TrainingMaterialPickerRuntime?.build || null))
    .toBe('training-material-picker-runtime-422615');
  await expect.poll(async () => page.evaluate(() => state.uiReady === true)).toBe(true);

  const projectId = await page.evaluate(() => state.project?.id);
  expect(projectId).toBeTruthy();
  const encoded = encodeURIComponent(projectId);
  const requests = [];
  const thumbnailRequests = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/')) requests.push(`${request.method()} ${url.pathname}${url.search}`);
    if (url.pathname.startsWith('/thumb/')) thumbnailRequests.push(url.pathname);
  });

  let releaseFirstPage;
  const firstPageGate = new Promise(resolve => { releaseFirstPage = resolve; });
  let firstPageHeld = true;

  await page.route('**/thumb/*.png', route => route.fulfill({status: 200, contentType: 'image/png', body: PIXEL}));
  await page.route('**/full/*.png', route => route.fulfill({status: 200, contentType: 'image/png', body: PIXEL}));
  await page.route(`**/api/v62/projects/${encoded}/training-materials?*`, async route => {
    const url = new URL(route.request().url());
    const requestedPage = Number(url.searchParams.get('page') || 1);
    const pageSize = Number(url.searchParams.get('page_size') || 60);
    const query = url.searchParams.get('query') || '';
    if (requestedPage === 1 && !query && firstPageHeld) {
      firstPageHeld = false;
      await firstPageGate;
    }
    const total = query ? 8 : 10_000;
    const totalPages = Math.ceil(total / pageSize);
    const rows = Array.from({length: query ? 8 : pageSize}, (_, index) => material(index, requestedPage));
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: rows,
        total,
        page: requestedPage,
        page_size: pageSize,
        total_pages: totalPages,
        has_previous: requestedPage > 1,
        has_next: requestedPage < totalPages,
        limit: pageSize,
        next_cursor: null,
        repository_revision: 88,
      }),
    });
  });
  await page.route(`**/api/v62/projects/${encoded}/training-materials/bulk-selection`, async route => {
    const payload = route.request().postDataJSON();
    const count = payload?.all_available ? 10_000 : 8;
    const items = payload?.all_available
      ? Array.from({length: count}, (_, index) => `bulk-${index}`)
      : Array.from({length: count}, (_, index) => material(index, 1).id);
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({items, total: count, repository_revision: 88, selection_mode: payload?.all_available ? 'all_available' : 'filtered'}),
    });
  });

  requests.length = 0;
  thumbnailRequests.length = 0;
  await page.evaluate(() => { window.openTrainMaterialPickerV3('train'); });
  await expect(page.locator('.train-v3-picker.server-paged')).toBeVisible({timeout: 1_000});
  await expect(page.locator('.train-v3-skeleton').first()).toBeVisible({timeout: 1_000});
  expect(await page.locator('.train-v3-card').count()).toBe(0);

  releaseFirstPage();
  await expect(page.locator('.train-v3-card')).toHaveCount(60, {timeout: 5_000});
  await expect(page.locator('#trV3PickerCount')).toContainText('筛选结果 10000 张');
  await expect(page.locator('#trV3PageMeta')).toContainText('当前页 60 张');
  expect(requests.some(value => /\/api\/projects\/[^/]+\/images(?:\?|$)/.test(value))).toBe(false);
  expect(requests.filter(value => value.includes(`/api/v62/projects/${projectId}/training-materials?`))).toHaveLength(1);
  await expect.poll(() => thumbnailRequests.length).toBe(15);
  const firstViewportThumbnailCount = thumbnailRequests.length;

  const gridMetrics = await page.locator('#trV3Grid').evaluate(element => ({
    clientHeight: element.clientHeight,
    scrollHeight: element.scrollHeight,
  }));
  expect(gridMetrics.scrollHeight).toBeGreaterThan(gridMetrics.clientHeight);

  const firstCard = page.locator('.train-v3-card').first();
  const firstImage = firstCard.locator('img');
  const ratio = await firstImage.evaluate(element => getComputedStyle(element).aspectRatio);
  expect(ratio).toContain('4');
  expect(await firstImage.evaluate(element => getComputedStyle(element).objectFit)).toBe('contain');
  await expect(firstCard.locator('svg.train-v3-box-layer')).toHaveAttribute('viewBox', '0 0 400 200');
  await expect(firstCard.locator('svg.train-v3-box-layer rect[data-label="smoke"]')).toHaveAttribute('x', '40');
  await expect(firstCard.locator('.train-v3-annotation-state[data-annotation-state="annotated"]')).toContainText('已标注 · 1 框');
  const pendingCard = page.locator('[data-material-id="picker-1-059"]');
  await expect(pendingCard.locator('.train-v3-annotation-state[data-annotation-state="unannotated"]')).toContainText('已清洗 · 待标注');
  await expect(pendingCard.locator('input')).toBeEnabled();

  await page.locator('#trV3Grid').evaluate(element => { element.scrollTop = element.scrollHeight; element.dispatchEvent(new Event('scroll')); });
  await expect.poll(() => thumbnailRequests.length).toBeGreaterThan(firstViewportThumbnailCount);

  const firstId = await firstCard.getAttribute('data-material-id');
  await firstCard.locator('input').check();
  await expect.poll(async () => page.evaluate(() => window.TrainingMaterialPickerRuntime?.state?.().selected)).toBe(1);

  await page.getByRole('button', {name: '下一页'}).click();
  await expect(page.locator('.train-v3-card')).toHaveCount(60);
  await expect(page.locator('#trV3Pager')).toContainText('第 2 页');
  expect(requests.some(value => value.includes('page=2') && value.includes('page_size=60'))).toBe(true);

  await page.getByLabel('指定页码').fill('100');
  await page.getByRole('button', {name: '跳转'}).click();
  await expect(page.locator('#trV3Pager')).toContainText('当前第 100 页');
  expect(requests.some(value => value.includes('page=100'))).toBe(true);

  await page.getByLabel('指定页码').fill('1');
  await page.getByLabel('指定页码').press('Enter');
  await expect(page.locator(`[data-material-id="${firstId}"] input`)).toBeChecked();

  await page.locator('#trV3Q').fill('smoke');
  await expect(page.locator('.train-v3-card')).toHaveCount(8, {timeout: 3_000});
  await expect(page.locator('#trV3PickerCount')).toContainText('筛选结果 8 张');
  expect(requests.some(value => value.includes('query=smoke'))).toBe(true);

  await page.getByRole('button', {name: '全选当前筛选'}).click();
  await expect.poll(async () => page.evaluate(() => window.TrainingMaterialPickerRuntime?.state?.().selected)).toBe(8);
  expect(requests.filter(value => value.includes('/training-materials/bulk-selection'))).toHaveLength(1);

  const runtimeState = await page.evaluate(() => window.TrainingMaterialPickerRuntime?.state?.());
  expect(runtimeState.pageSize).toBe(60);
  expect(runtimeState.fullPoolHydration).toBe(false);
  expect(runtimeState.bulkSelectionOwner).toBe('server');
  expect(runtimeState.viewportThumbnailLoading).toBe(true);
  expect(runtimeState.eagerThumbnailCount).toBe(15);

  await page.getByRole('button', {name: '确认选择'}).click();
  await expect(page.locator('.train-v3-picker.server-paged')).not.toBeVisible();
  await expect.poll(async () => page.evaluate(() => window.TrainingDraftRuntime?.materialIds?.() || []))
    .toContain(firstId);

  await page.evaluate(() => { window.openTrainMaterialPickerV3('test'); });
  await expect(page.locator('.train-v3-card')).toHaveCount(60, {timeout: 5_000});
  const pendingTestCard = page.locator('[data-material-id="picker-1-059"]');
  await expect(pendingTestCard.locator('input')).toBeDisabled();
  await expect(pendingTestCard).toHaveAttribute('data-block-reason', '试验集必须已标注');
  await page.getByRole('button', {name: '取消'}).click();

  expect(pageErrors).toEqual([]);
});


test('vest first training reviews person without changing source boxes or adding a class',async({page,request})=>{
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const project=await(await request.post('/api/projects',{data:{name:`跨标签-${Date.now()}`,labels:[{code:'vest'},{code:'person'}]}})).json();
 const created=await(await request.post(`/api/v12/projects/${project.id}/algorithms`,{data:{name:'反光衣识别',industry:'测试',algorithm_type:'yolo_ultralytics'}})).json();
 const bytes=Buffer.alloc(54+300*80);bytes.write('BM');bytes.writeUInt32LE(bytes.length,2);bytes.writeUInt32LE(54,10);bytes.writeUInt32LE(40,14);bytes.writeInt32LE(100,18);bytes.writeInt32LE(80,22);bytes.writeUInt16LE(1,26);bytes.writeUInt16LE(24,28);
 const ids=[];let personBefore;
 for(const [index,label] of ['vest','person'].entries()){
  bytes.fill(index?140:80,54);
  const up=await(await request.post(`/api/projects/${project.id}/images`,{multipart:{files:{name:`${label}.bmp`,mimeType:'image/bmp',buffer:Buffer.from(bytes)},dataset_id:'default'}})).json();
  const image=up.uploaded[0];ids.push(image.id);
  const ann=await(await request.get(`/api/projects/${project.id}/annotations/${image.id}`)).json();
  const saved=await(await request.post(`/api/projects/${project.id}/annotations/${image.id}`,{data:{boxes:[{id:label,label,class_id:index,x1:10,y1:10,x2:80,y2:70}],annotation_state:'annotated',expected_version:ann.annotation.version,source_content_sha256:image.content_sha256,reviewed_label_codes:[label]}})).json();
  if(label==='person')personBefore=saved.annotation;
 }
 await page.route('**/api/v53/bootstrap/snapshot**',async route=>{const u=new URL(route.request().url());u.searchParams.set('preferred_project_id',project.id);await route.fallback({url:u.toString()})});
 await page.goto('/');await expect.poll(()=>page.evaluate(()=>state.uiReady)).toBe(true);
 await page.evaluate(({id,ids})=>{window.TrainingDraftRuntime.update({algorithmId:id,materialIds:ids,newLabelCodes:['vest'],config:{model:'yolo11n.pt'}});window.openTrainMaterialPickerV3('train')},{id:created.algorithm.id,ids});
 await expect(page.locator('.train-v3-card')).toHaveCount(2);
 await expect(page.locator('#trV3TrainingLabels')).toContainText('vest');
 await expect(page.locator('#trV3RoleCounts')).toContainText('待确认负样本 1');
 await page.getByRole('button',{name:'审核待确认素材',exact:true}).click();await expect(page.locator('.train-v3-card')).toHaveCount(1);
 await expect(page.locator('svg.train-v3-box-layer rect[data-label="person"]')).toBeVisible();
 await page.locator('.train-v3-card input').check();page.once('dialog',dialog=>dialog.accept());
 await page.getByRole('button',{name:'确认所勾选图片不含本次训练目标',exact:true}).click();
 await expect(page.locator('#trV3ReviewProgress')).toContainText('已保存 1/1');
 await expect(page.locator('#trV3RoleCounts')).toContainText('已确认负样本 1');
 await page.getByRole('button',{name:'结束本批审核',exact:true}).click();
 await page.getByRole('combobox',{name:'训练样本角色'}).selectOption('confirmed_negative');
 await expect(page.locator('.train-v3-card')).toHaveCount(1);
 await expect(page.locator('.train-v3-card')).toContainText('可作为 vest 负样本');
 const after=await(await request.get(`/api/projects/${project.id}/annotations/${ids[1]}`)).json();
 expect(after.annotation).toEqual(personBefore);
 expect(errors).toEqual([]);
});

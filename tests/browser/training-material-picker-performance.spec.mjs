import {test, expect} from '@playwright/test';
import {mkdirSync, writeFileSync} from 'node:fs';

const PIXEL = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=', 'base64');

function syntheticThumbnailBmp(size = 192) {
  // A real decodable 24-bit image, rather than the 1x1 network-only fixture.
  // Its deterministic pixels carry no user identity, GT or external content.
  const rowSize = Math.ceil(size * 3 / 4) * 4;
  const image = Buffer.alloc(54 + rowSize * size);
  image.write('BM', 0);
  image.writeUInt32LE(image.length, 2);
  image.writeUInt32LE(54, 10);
  image.writeUInt32LE(40, 14);
  image.writeInt32LE(size, 18);
  image.writeInt32LE(size, 22);
  image.writeUInt16LE(1, 26);
  image.writeUInt16LE(24, 28);
  image.writeUInt32LE(rowSize * size, 34);
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    const offset = 54 + y * rowSize + x * 3;
    image[offset] = (x + y) % 256;
    image[offset + 1] = (x * 3) % 256;
    image[offset + 2] = (y * 5) % 256;
  }
  return image;
}

function nearestRankSummary(durations) {
  const values = [...durations].sort((a, b) => a - b);
  const mid = values.length / 2;
  return {samples: values.length,
    p50_ms: Number(((values[Math.floor(mid - 0.5)] + values[Math.ceil(mid - 0.5)]) / 2).toFixed(3)),
    p95_ms: Number(values[Math.ceil(values.length * 0.95) - 1].toFixed(3)),
    min_ms: Number(values[0].toFixed(3)),max_ms: Number(values.at(-1).toFixed(3))};
}

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
    .toBe('training-material-picker-runtime-422616');
  await expect.poll(async () => page.evaluate(() => state.uiReady === true)).toBe(true);

  const projectId = await page.evaluate(() => state.project?.id);
  expect(projectId).toBeTruthy();
  const statusRead = await page.evaluate(async pid => {
    const start=performance.now();
    const response=await fetch(`/api/projects/${encodeURIComponent(pid)}/jobs`);
    const headersAt=performance.now(),text=await response.text();
    return {environment:'isolated browser test boot project; NOT production',status:response.status,
      response_bytes:new TextEncoder().encode(text).length,rows:JSON.parse(text).length,
      headers_observed_ms:headersAt-start,total_ms:performance.now()-start,
      request_id:response.headers.get('X-Request-ID'),server_timing:response.headers.get('Server-Timing')};
  },projectId);
  expect(statusRead.status).toBe(200);
  if(statusRead.request_id)expect(statusRead.request_id).toMatch(/^[0-9a-f]{32}$/);
  if(process.env.MC_PERF_AUDIT_OUTPUT){mkdirSync(process.env.MC_PERF_AUDIT_OUTPUT,{recursive:true});writeFileSync(process.env.MC_PERF_AUDIT_OUTPUT+'/browser-status.json',JSON.stringify(statusRead,null,2));}
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

  await page.route('**/thumb/*.png', route => route.fulfill({status: 200, contentType: 'image/svg+xml', body: Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" width="400" height="200"><rect width="400" height="200" fill="#e4eef3"/><rect x="0" y="140" width="400" height="60" fill="#71818b"/><rect x="230" y="40" width="130" height="100" fill="#c2d2da"/><circle cx="120" cy="90" r="16" fill="#637d91"/><path d="M100 115h40v50h-40z" fill="#637d91"/><text x="12" y="24" font-size="14" fill="#405567">ISOLATED SCENE FIXTURE</text></svg>')}));
  await page.route('**/full/*.png', route => route.fulfill({status: 200, contentType: 'image/svg+xml', body: Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" width="400" height="200"><rect width="400" height="200" fill="#e4eef3"/><rect x="0" y="140" width="400" height="60" fill="#71818b"/><rect x="230" y="40" width="130" height="100" fill="#c2d2da"/><circle cx="120" cy="90" r="16" fill="#637d91"/><path d="M100 115h40v50h-40z" fill="#637d91"/><text x="12" y="24" font-size="14" fill="#405567">ISOLATED SCENE FIXTURE</text></svg>')}));
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
  await expect.poll(() => thumbnailRequests.length).toBe(10);
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
  await expect(pendingCard.locator('.train-v3-annotation-state[data-annotation-state="unannotated"]')).toContainText('未标注 · 已清洗');
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

  for (const [width,height] of [[1920,1080],[1366,768],[1024,768],[390,844]]) {
    await page.setViewportSize({width,height});
    await expect(page.getByRole('button',{name:'确认选择',exact:true})).toBeVisible();
    const layout=await page.evaluate(()=>{
      const grid=document.getElementById('trV3Grid');
      const sidebar=document.querySelector('.train-v3-filters').getBoundingClientRect();
      const browse=document.querySelector('.train-v3-results').getBoundingClientRect();
      const footer=document.querySelector('.train-v3-footer').getBoundingClientRect();
      const cards=[...grid.querySelectorAll('.train-v3-card')].map(c=>c.getBoundingClientRect());
      return {columns:getComputedStyle(grid).gridTemplateColumns.split(' ').length,
        sidebarRight:sidebar.right,browseLeft:browse.left,browseWidth:browse.width,
        gridHeight:grid.clientHeight,footerBottom:footer.bottom,
        overlap:cards.some((r,i)=>i>0 && r.top>cards[0].top && r.top<cards[0].bottom)};
    });
    expect(layout.columns).toBe(width>1180?4:width>960?3:2);
    if(width>760){
      expect(layout.browseLeft).toBeGreaterThanOrEqual(layout.sidebarRight - 1);
      expect(layout.browseWidth).toBeGreaterThan(width * .55);
    }
    expect(layout.gridHeight).toBeGreaterThan(120);
    expect(layout.footerBottom).toBeLessThanOrEqual(height);
    expect(layout.overlap).toBe(false);
    mkdirSync('docs/evidence/material-workbench-20261104',{recursive:true});
    await page.screenshot({path:`docs/evidence/material-workbench-20261104/picker-two-column-${width}.png`});
  }
  await page.setViewportSize({width:1366,height:768});
  const beforeAdvanced=await page.locator('#trV3Grid').evaluate(element=>element.clientHeight);
  await page.locator('.train-v3-advanced>summary').click();
  await expect(page.locator('.train-v3-advanced-panel')).toBeVisible();
  expect(await page.locator('#trV3Grid').evaluate(element=>element.clientHeight)).toBe(beforeAdvanced);
  await page.locator('.train-v3-advanced>summary').click();
  await page.locator('.train-v3-selected>summary').click();
  await expect(page.locator('#trV3SelectedList')).toBeVisible();
  await expect(page.locator('#trV3SelectedTotal')).toHaveText('8');
  await page.locator('.train-v3-selected>summary').click();
  await page.setViewportSize({width:390,height:844});
  await page.locator('.train-v3-mobile-toggle').click();
  await expect(page.locator('.train-v3-filters')).toHaveAttribute('open','');
  await expect(page.locator('#trV3Chips')).toBeVisible();
  await page.locator('.train-v3-mobile-toggle').click();
  await expect(page.locator('.train-v3-filters')).not.toHaveAttribute('open','');
  await page.setViewportSize({width:1440,height:900});
  await page.locator('.train-v3-policy select').selectOption('include_history');
  await expect.poll(()=>page.evaluate(()=>window.TrainingDraftRuntime.current().history_policy)).toBe('include_history');
  await expect.poll(()=>page.evaluate(()=>window.TrainingMaterialPickerRuntime.state().selected)).toBe(8);
  const runtimeState = await page.evaluate(() => window.TrainingMaterialPickerRuntime?.state?.());
  expect(runtimeState.pageSize).toBe(60);
  expect(runtimeState.fullPoolHydration).toBe(false);
  expect(runtimeState.bulkSelectionOwner).toBe('server');
  expect(runtimeState.viewportThumbnailLoading).toBe(true);
  expect(runtimeState.eagerThumbnailCount).toBe(10);

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

test('isolated Chrome records picker click-to-decoded-paint and long tasks for 192px previews', async ({page}) => {
  await page.goto('/');
  await expect.poll(() => page.evaluate(() => state.uiReady === true)).toBe(true);
  const projectId = await page.evaluate(() => state.project?.id);
  expect(projectId).toBeTruthy();
  const image = syntheticThumbnailBmp();
  let pageRequests = 0, revisionRequests = 0, thumbnailRequests = 0;
  await page.route('**/thumb/*.bmp', route => {
    thumbnailRequests++;
    return route.fulfill({status: 200, contentType: 'image/bmp', body: image,
      headers: {'Cache-Control': 'no-store'}});
  });
  await page.route(`**/api/v62/projects/${encodeURIComponent(projectId)}/training-materials/revision?*`, route => {
    revisionRequests++;
    return route.fulfill({json:{repository_revision:88,annotation_revision:0,usage_revision:'unknown',
      negative_confirmation_revision:0,negative_pool_revision:0}});
  });
  await page.route(`**/api/v62/projects/${encodeURIComponent(projectId)}/training-materials?*`, route => {
    pageRequests++;
    return route.fulfill({json:{
      items:Array.from({length:60},(_,index)=>{
        const item=material(index);
        return {...item,thumbnail_url:`/thumb/${item.id}.bmp`};
      }),total:10000,page:1,page_size:60,total_pages:167,
      repository_revision:88,annotation_revision:0,usage_revision:'unknown',
      negative_confirmation_revision:0,negative_pool_revision:0,
    }});
  });
  await page.route(`**/api/v61/projects/${encodeURIComponent(projectId)}/negative-pool/categories`,
    route => route.fulfill({json:{items:[]}}));
  await page.evaluate(() => {
    window.__pickerLongTasks=[];
    if (PerformanceObserver.supportedEntryTypes.includes('longtask')) {
      window.__pickerLongTaskObserver=new PerformanceObserver(list => {
        for(const task of list.getEntries())window.__pickerLongTasks.push({start:task.startTime,duration:task.duration});
      });
      window.__pickerLongTaskObserver.observe({type:'longtask'});
    }
  });
  const samples=[];
  for (let run=0; run<21; run++) {
    const thumbnailsBefore=thumbnailRequests;
    // Keep the whole stopwatch in the browser. Playwright polling/IPC must
    // not be mistaken for synchronous rendering or image decode time.
    const observed=await page.evaluate(() => new Promise((resolve,reject) => {
      const start=performance.now();
      const observer=new MutationObserver(() => {
        const cards=document.querySelectorAll('#trV3Grid .train-v3-card');
        const images=[...document.querySelectorAll('#trV3Grid img[src^="/thumb/"]')];
        if(cards.length!==60 || images.length!==10)return;
        observer.disconnect();
        Promise.all(images.map(image=>image.decode())).then(async()=>{
          await new Promise(done=>requestAnimationFrame(()=>requestAnimationFrame(done)));
          await new Promise(done=>setTimeout(done,0));
          const end=performance.now();
          resolve({click_to_decoded_paint_ms:Number((end-start).toFixed(3)),
            decoded_images:images.filter(image=>image.naturalWidth===192&&image.naturalHeight===192).length,
            long_tasks:window.__pickerLongTasks.filter(item=>item.start>=start&&item.start<end)
              .map(item=>Number(item.duration.toFixed(3)))});
        }).catch(reject);
      });
      observer.observe(document.body,{childList:true,subtree:true});
      window.openTrainMaterialPickerV3('train');
    }));
    expect(observed.decoded_images).toBe(10);
    await expect(page.locator('#trV3Grid .train-v3-card')).toHaveCount(60);
    samples.push({...observed,thumbnail_requests:thumbnailRequests-thumbnailsBefore});
    await page.getByRole('button',{name:'取消'}).click();
  }
  await page.evaluate(() => window.__pickerLongTaskObserver?.disconnect());
  expect(pageRequests).toBe(1);
  expect(revisionRequests).toBe(20);
  expect(samples[0].thumbnail_requests).toBe(10);
  const report={scope:'ISOLATED TEST — NOT PRODUCTION VERIFIED; real Chrome; '
    +'60 mocked cards; 10 eager deterministic 192x192 BMP images per open; '
    +'Playwright in-process image/page interception; no WAN, server image I/O or GT',
    cold_first:samples[0],warm:nearestRankSummary(samples.slice(1).map(row=>row.click_to_decoded_paint_ms)),
    warm_total_long_tasks:samples.slice(1).reduce((count,row)=>count+row.long_tasks.length,0),
    warm_max_long_task_ms:Math.max(0,...samples.slice(1).flatMap(row=>row.long_tasks)),
    browser_longtask_supported:await page.evaluate(()=>PerformanceObserver.supportedEntryTypes.includes('longtask')),
    requests:{page:pageRequests,revision:revisionRequests,
      first_thumbnail:samples[0].thumbnail_requests,warm_thumbnail_counts:samples.slice(1).map(row=>row.thumbnail_requests)},
  };
  console.log('picker_browser_render',JSON.stringify(report));
  if(process.env.MC_PERF_AUDIT_OUTPUT){
    mkdirSync(process.env.MC_PERF_AUDIT_OUTPUT,{recursive:true});
    writeFileSync(`${process.env.MC_PERF_AUDIT_OUTPUT}/browser-picker-render.json`,
      JSON.stringify(report,null,2));
  }
});


test('vest first training selects person as candidate without picker confirmation or GT mutation',async({page,request})=>{
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
 // First page defers role projection and counts; the active draft label is
 // already frozen, so the role filter is available without another dialog.
 const roleFilter=page.getByRole('combobox',{name:'按训练目标筛选素材'});
 await expect(roleFilter).toBeVisible();
 await expect(roleFilter.locator('option[value="pending_negative"]')).toHaveText('候选背景素材');
 await expect(page.locator('[data-sample-role]')).toHaveCount(0);
 await expect(page.getByRole('button',{name:'确认目标范围内无目标',exact:true})).toHaveCount(0);
 await roleFilter.selectOption('pending_negative');
 await expect(page.locator('.train-v3-card')).toHaveCount(1);
 await expect(page.locator('[data-sample-role="pending_negative"]')).toBeVisible();
 await expect(page.locator('[data-sample-role="pending_negative"]')).toContainText('vest');
 await expect(page.locator('svg.train-v3-box-layer rect[data-label="person"]')).toBeVisible();
 await expect(page.locator('.train-v3-card input')).toBeChecked();
 await page.getByRole('button',{name:'确认选择',exact:true}).click();
 await expect.poll(()=>page.evaluate(()=>window.TrainingDraftRuntime.materialIds())).toEqual(ids);
 const after=await(await request.get(`/api/projects/${project.id}/annotations/${ids[1]}`)).json();
 expect(after.annotation).toEqual(personBefore);
 expect(errors).toEqual([]);
});


test('large frozen selection keeps browser POST compact without downloading all IDs',async({page})=>{
 await page.goto('/');await expect.poll(()=>page.evaluate(()=>state.uiReady)).toBe(true);
 const pid=await page.evaluate(()=>state.project.id);
 const base=`**/api/v62/projects/${pid}/training-materials`;
 const ref='trainselection_0123456789ab4def89abcdef01234567';
 let freezeBody,posted;
 await page.route(base+'?**',r=>r.fulfill({json:{items:Array.from({length:60},(_,i)=>material(i)),total:200000,page:1,page_size:60,has_next:true,repository_revision:88}}));
 await page.route(base+'/bulk-selection',r=>r.fulfill({status:422,json:{detail:'筛选结果共200000张，超过单次选择上限50000张'}}));
 await page.route(base+'/selection-reference',r=>{freezeBody=r.request().postDataJSON();return r.fulfill({json:{selection_ref:ref,count:200000,role:'train'}})});
 await page.route(base+'/selection-membership',r=>r.fulfill({json:{items:r.request().postDataJSON().image_ids}}));
 await page.route('**/api/projects/'+pid+'/train/start',r=>{posted=r.request().postDataJSON();return r.fulfill({json:{ok:true,task:{task_id:'isolated-reference'}}})});
 await page.evaluate(()=>{window.TrainingDraftRuntime.update({algorithmId:'isolated-algorithm',newLabelCodes:['smoke']});window.openTrainMaterialPickerV3('train')});
 await expect(page.locator('.train-v3-card')).toHaveCount(60);
 await page.getByRole('button',{name:'全选当前筛选',exact:true}).click();
 await expect(page.locator('#trV3SelectedTotal')).toHaveText('200000');
 await expect(page.locator('.train-v3-card input').first()).toBeChecked();
 await page.getByRole('button',{name:'确认选择',exact:true}).click();
 await expect.poll(()=>page.evaluate(()=>window.TrainingDraftRuntime.current().trainSelectionRef)).toBe(ref);
 await page.evaluate(async pid=>{const module=await import('/static/modules/training-draft.js');
  const payload=module.trainingDraftToRequest(window.TrainingDraftRuntime.current());
  await fetch(`/api/projects/${pid}/train/start`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
 },pid);
 expect(posted.train_selection_ref).toBe(ref);expect(posted.train_image_ids).toEqual([]);
 expect(JSON.stringify(posted).length).toBeLessThan(5000);
 expect(JSON.stringify(freezeBody).length).toBeLessThan(5000);
});

test('large all-available fallback does not freeze only the active filtered subset',async({page})=>{
 await page.goto('/');await expect.poll(()=>page.evaluate(()=>state.uiReady)).toBe(true);
 const pid=await page.evaluate(()=>state.project.id);
 const base=`**/api/v62/projects/${pid}/training-materials`;
 let frozenScope=null;
 await page.route(base+'?**',route=>route.fulfill({json:{
   items:Array.from({length:60},(_,i)=>material(i)),total:200000,page:1,page_size:60,
   has_next:true,repository_revision:88,
 }}));
 await page.route(base+'/bulk-selection',route=>route.fulfill({
   status:422,json:{detail:'筛选结果共200000张，超过单次选择上限50000张'},
 }));
 await page.route(base+'/selection-reference',route=>{
   frozenScope=route.request().postDataJSON();
   return route.fulfill({json:{selection_ref:'trainselection_0123456789ab4def89abcdef01234567',count:200000,role:'train'}});
 });
 await page.route(base+'/selection-membership',route=>route.fulfill({json:{items:[]}}));
 await page.evaluate(()=>{window.TrainingDraftRuntime.update({algorithmId:'isolated-algorithm',newLabelCodes:['smoke']});window.openTrainMaterialPickerV3('train')});
 await expect(page.locator('.train-v3-card')).toHaveCount(60);
 await page.evaluate(()=>window.TrainingMaterialPickerRuntime.setFilter('sourceIds','temporary-only'));
 await expect(page.locator('.train-v3-card')).toHaveCount(60);
 await page.locator('.train-v3-more>summary').click();
 await page.getByRole('button',{name:'全选全部可用素材',exact:true}).click();
 await expect.poll(()=>frozenScope).not.toBeNull();
 expect(frozenScope.sample_role).toBe('');
 expect(frozenScope.query).toBe('');
 expect(frozenScope.labels).toEqual([]);
 expect(frozenScope.storage_source_ids).toBeUndefined();
 expect(frozenScope.negative_pool_only).toBeUndefined();
 await expect(page.locator('#trV3SelectedTotal')).toHaveText('200000');
});


for (const frozenCount of [20_000, 30_000]) {
  test('frozen filtered browser create journey preserves ' + frozenCount + ' IDs and GT label summary', async ({page, request}) => {
    test.setTimeout(120_000);
    const created = await request.post('/api/projects', {data: {
      name: 'isolated-frozen-browser-' + frozenCount + '-' + Date.now(),
      labels: [{code: 'smoke', display_name: '烟雾'}],
    }});
    expect(created.ok()).toBeTruthy();
    const project = await created.json();
    const algResponse = await request.post('/api/v12/projects/' + project.id + '/algorithms', {
      data: {name: '冻结浏览器训练算法', algorithm_type: 'yolo_ultralytics'},
    });
    expect(algResponse.ok()).toBeTruthy();
    const algorithmId = (await algResponse.json()).algorithm.id;
    const ref = 'trainselection_' + (frozenCount === 20_000 ? 'a' : 'b').repeat(32);
    let freezeBody = null;
    let submitted = null;
    let bulkCalls = 0;
    let pageTwoSeen = false;

    await page.route('**/api/v53/bootstrap/snapshot**', route => {
      const url = new URL(route.request().url());
      url.searchParams.set('preferred_project_id', project.id);
      return route.fallback({url: url.toString()});
    });
    await page.route('**/api/training_options**', route => route.fulfill({json: {targets: [{
      id: 'browser-ultralytics', name: 'Chrome 测试 Ultralytics',
      type: 'local', framework: 'ultralytics', status: 'ready',
      algorithms: [{key: 'yolo_detect', name: 'Ultralytics Detect', base_model: 'yolo11n.pt',
        default_epochs: 10, default_imgsz: 640, default_batch: 2}],
      base_models: [{value: 'yolo11n.pt', label: 'YOLO11n', model_status: 'FOUND'}],
    }]}}));
    await page.route('**/api/v62/training-devices', route => route.fulfill({json: {
      recommended: 'cpu', options: [{id: 'cpu', label: 'CPU', available: true}],
    }}));
    await page.route('**/api/system/recommendation', route => route.fulfill({json: {
      ok: true, recommendation: {device: 'cpu', batch: 2, workers: 0, precision: 'auto', safe_batch_max: 32},
    }}));
    await page.route('**/api/v62/projects/*/training-materials/compatibility', route =>
      route.fulfill({json: {compatible: true, issue_count: 0, items: [], issue_counts: {}}));
    await page.route('**/api/v62/projects/' + project.id + '/training-materials?*', route => {
      const url = new URL(route.request().url());
      const number = Number(url.searchParams.get('page') || 1);
      const term = url.searchParams.get('query') || '';
      if (term === 'picker' && number === 2) pageTwoSeen = true;
      const total = term === 'picker' ? frozenCount : 200_000;
      const rows = Array.from({length: 60}, (_, i) => ({
        ...material(i, number), labels: ['smoke'], annotation_state: 'annotated',
        annotated: true, box_count: 1,
        boxes: [{label: 'smoke', x1: 40, y1: 20, x2: 200, y2: 100}],
      }));
      return route.fulfill({json: {items: rows, page: number, page_size: 60,
        total, total_pages: Math.ceil(total / 60), has_next: number * 60 < total,
        repository_revision: 88, annotation_revision: 91,
        usage_revision: '3', negative_pool_revision: '1', negative_confirmation_revision: 0}});
    });
    await page.route('**/api/v62/projects/' + project.id + '/training-materials/bulk-selection', route => {
      bulkCalls++;
      return route.fulfill({status: 500, json: {detail: 'large selection must stay server-frozen'}});
    });
    await page.route('**/api/v62/projects/' + project.id + '/training-materials/selection-reference', route => {
      freezeBody = route.request().postDataJSON();
      return route.fulfill({json: {selection_ref: ref, count: frozenCount, role: 'train'}});
    });
    await page.route('**/api/v62/projects/' + project.id + '/training-materials/selection-membership', route => {
      const ids = route.request().postDataJSON().image_ids || [];
      return route.fulfill({json: {items: ids}});
    });
    await page.route('**/api/v62/projects/' + project.id + '/training-materials/selection-summary', route => {
      const payload = route.request().postDataJSON();
      if (payload.train_selection_ref !== ref) return route.fallback();
      expect(payload.image_ids).toEqual([]);
      return route.fulfill({json: {
        selection_reference: true, requested_count: frozenCount, matched_count: frozenCount,
        selectable_count: frozenCount, eligible_count: frozenCount, pending_annotation_count: 0,
        selectable_total: 200_000, eligible_total: frozenCount, pending_annotation_total: 200_000 - frozenCount,
        box_count: frozenCount, label_codes: ['smoke'], positive_label_codes: ['smoke'],
        label_counts: {smoke: frozenCount}, repository_revision: 88, annotation_revision: 91,
      }});
    });
    await page.route('**/api/v12/projects/' + project.id + '/train/start', route => {
      submitted = route.request().postDataJSON();
      return route.fulfill({status: 202, json: {ok: true, task: {
        id: submitted.task_id, task_id: submitted.task_id, project_id: project.id,
        algorithm_id: algorithmId, kind: 'TRAINING', task_type: 'TRAINING',
        status: 'QUEUED', persisted_status: 'QUEUED', phase: 'queued',
      }, training_input_state: 'PREPARING'}});
    });
    await page.addInitScript(() => {
      window.MC_TRAIN_ADMISSION_MODE = 'background';
      localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({page: '算法列表'}));
    });
    await page.goto('/');
    await expect.poll(() => page.evaluate(() => state.uiReady === true)).toBe(true);
    await page.getByRole('button', {name: /算法列表/}).click();
    const card = page.locator('.alg428-card', {hasText: '冻结浏览器训练算法'});
    await card.getByRole('button', {name: '训练'}).click();
    const dialog = page.getByRole('dialog', {name: '创建训练任务'});
    await expect(dialog).toBeVisible();
    await dialog.getByRole('button', {name: '选择训练素材'}).click();
    const picker = page.getByRole('dialog', {name: '选择本次训练素材'});
    await expect(picker.locator('.train-v3-card')).toHaveCount(60);
    await picker.locator('#trV3Q').fill('picker');
    await expect(picker.locator('#trV3PickerCount')).toContainText('筛选结果 ' + frozenCount + ' 张');
    await picker.getByRole('button', {name: '下一页'}).click();
    await expect(picker.locator('#trV3Pager')).toContainText('第 2 页');
    expect(pageTwoSeen).toBe(true);
    await picker.getByRole('button', {name: '全选当前筛选', exact: true}).click();
    await expect(picker.locator('#trV3SelectedTotal')).toHaveText(String(frozenCount));
    expect(freezeBody).toMatchObject({algorithm_asset_id: algorithmId, query: 'picker', role: 'train'});
    expect(bulkCalls).toBe(0);
    expect(JSON.stringify(freezeBody).length).toBeLessThan(5000);
    await picker.getByRole('button', {name: '确认选择', exact: true}).click();
    await expect.poll(() => page.evaluate(() => {
      const draft = window.TrainingDraftRuntime.current();
      return {ref: draft.trainSelectionRef, count: draft.trainSelectionCount, ids: draft.materialIds.length};
    })).toEqual({ref, count: frozenCount, ids: 0});
    await expect(dialog.locator('#tr429Labels')).toContainText('烟雾');
    await expect(dialog.locator('#tr429Labels')).toContainText('正式标注 ' + frozenCount);
    const label = dialog.locator('#trainingLabelContractPanel input[data-training-label-code="smoke"]');
    await expect(label).toBeVisible();
    await label.check();
    await page.evaluate(() => window.setTrainingWorkbenchStep(3));
    const backgroundConfirm = dialog.locator('#tr429BackgroundScopeConfirm');
    await expect(backgroundConfirm).toBeVisible();
    await backgroundConfirm.check();
    await dialog.getByRole('button', {name: '开始训练'}).click();
    await expect.poll(() => submitted).not.toBeNull();
    expect(submitted.algorithm_asset_id).toBe(algorithmId);
    expect(submitted.train_selection_ref).toBe(ref);
    expect(submitted.train_image_ids).toEqual([]);
    expect(submitted.train_labels).toEqual(['smoke']);
    expect(submitted.admission_mode).toBe('background');
    expect(JSON.stringify(submitted).length).toBeLessThan(5000);
  });
}

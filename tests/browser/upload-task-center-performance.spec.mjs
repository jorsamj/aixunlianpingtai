import {test, expect} from '@playwright/test';

test('progress storms preserve pressed action, rekey identity and bounded synchronous storage', async ({page}) => {
  await page.goto('/');
  await expect.poll(() => page.evaluate(() => Boolean(state.uiReady))).toBe(true);
  await page.evaluate(() => {
    window.__utcCalls=[];
    window.__utcOriginalZip=window.ZipImportRuntime;
    window.ZipImportRuntime={pauseUpload:async id=>{window.__utcCalls.push(id)}};
    window.UploadTaskCenterRuntime.upsert({id:'zip:press-local',kind:'zip',title:'pressed.zip',status:'UPLOADING',progress:1,browserTransfer:true,localOnly:false});
  });
  await page.locator('[data-utc-toggle]').click();
  const button=page.locator('[data-utc-id="zip:press-local"] [data-utc-action="pause"]');
  await button.focus();
  const box=await button.boundingBox();
  await page.mouse.move(box.x+box.width/2,box.y+box.height/2);
  await page.mouse.down();
  const result=await page.evaluate(() => {
    const button=document.activeElement;
    const row=button.closest('.utc-row');
    const original=Storage.prototype.setItem;
    let writes=0;
    Storage.prototype.setItem=function(key,value){if(key.startsWith('mc_upload_task_center_v1:'))writes++;return original.call(this,key,value)};
    for(let i=0;i<150;i++)window.UploadTaskCenterRuntime.upsert({id:'zip:press-local',status:'UPLOADING',progress:1+i/2,browserTransfer:true});
    window.UploadTaskCenterRuntime.rekey('zip:press-local','zip:press-formal');
    Storage.prototype.setItem=original;
    window.__utcPressedButton=button;window.__utcPressedRow=row;
    return {writes};
  });
  await page.waitForTimeout(80);
  expect(await page.evaluate(()=>window.__utcPressedButton===document.querySelector('[data-utc-id="zip:press-formal"] [data-utc-action="pause"]'))).toBe(true);
  expect(await page.evaluate(()=>document.activeElement===window.__utcPressedButton)).toBe(true);
  expect(result.writes).toBeLessThanOrEqual(2);
  await page.mouse.up();
  await expect.poll(()=>page.evaluate(()=>window.__utcCalls)).toEqual(['press-formal']);
  await page.evaluate(()=>{window.ZipImportRuntime=window.__utcOriginalZip;window.UploadTaskCenterRuntime.remove('zip:press-formal')});
});

test('mixed tasks keep order, coalesce paints and storage, save pause immediately and expose image details', async ({page}) => {
  await page.goto('/');
  await expect.poll(() => page.evaluate(() => Boolean(state.uiReady))).toBe(true);
  await page.evaluate(() => {
    const center=window.UploadTaskCenterRuntime;
    for(const [id,status] of [['b','UPLOADING'],['a','UPLOADING'],['c','WAITING_UPLOAD'],['d','WAITING_UPLOAD']]) {
      center.upsert({id:`zip:${id}`,kind:'zip',title:`${id}.zip`,status,progress:0,createdAt:'2026-10-22T00:00:00Z',browserTransfer:status==='UPLOADING',localOnly:status==='WAITING_UPLOAD'});
    }
    center.upsert({id:'images:mixed',kind:'browser-upload',title:'隔离图片',status:'UPLOADING',progress:2,detail:'已确认 1/10'});
    window.__utcOriginalSetItem=Storage.prototype.setItem;window.__utcWrites=0;
    Storage.prototype.setItem=function(key,value){if(key.startsWith('mc_upload_task_center_v1:'))window.__utcWrites++;return window.__utcOriginalSetItem.call(this,key,value)};
  });
  await page.locator('[data-utc-toggle]').click();
  const before=await page.locator('.utc-row').evaluateAll(rows=>rows.map(row=>row.dataset.utcId));
  await page.evaluate(()=>{
    const center=window.UploadTaskCenterRuntime;
    window.__utcBeforeButton=document.querySelector('[data-utc-id="zip:b"] button');
    window.__utcMutations=0;
    window.__utcObserver=new MutationObserver(changes=>{window.__utcMutations+=changes.filter(change=>change.type==='childList'&&[...change.removedNodes].some(node=>node.nodeType===1)).length});
    window.__utcObserver.observe(document.querySelector('.utc-body'),{subtree:true,childList:true});
    window.__utcStormStarted=performance.now();
    window.__utcStorm=(async()=>{for(let frame=0;frame<30;frame++){
      for(let update=0;update<20;update++) center.upsert({id:'zip:b',progress:frame*2+update/10,status:'UPLOADING',browserTransfer:true});
      await new Promise(requestAnimationFrame);
    }})();
  });
  for(let i=0;i<6;i++)await page.locator('[data-utc-toggle]').click();
  await page.evaluate(()=>window.__utcStorm);
  expect(await page.locator('.utc-row').evaluateAll(rows=>rows.map(row=>row.dataset.utcId))).toEqual(before);
  const result=await page.evaluate(()=>{
    window.__utcObserver.disconnect();
    const result={writes:window.__utcWrites,elapsedMs:performance.now()-window.__utcStormStarted,removed:window.__utcMutations,button:window.__utcBeforeButton===document.querySelector('[data-utc-id="zip:b"] button')};
    window.UploadTaskCenterRuntime.upsert({id:'zip:b',status:'PAUSED',stage:'上传已暂停'});
    result.saved=JSON.parse(localStorage.getItem(`mc_upload_task_center_v1:${state.project.id}`)).find(row=>row.id==='zip:b').status;
    Storage.prototype.setItem=window.__utcOriginalSetItem;
    return result;
  });
  expect(result).toMatchObject({removed:0,button:true,saved:'PAUSED'});
  expect(result.writes).toBeLessThanOrEqual(Math.ceil(result.elapsedMs/500)+1);
  console.log(`[utc-storm] 600 updates, writes=${result.writes}, removed elements=${result.removed}, elapsed=${Math.round(result.elapsedMs)}ms`);
  await page.locator('[data-utc-id="images:mixed"] [data-utc-action="details"]').click();
  await expect(page.locator('.utc-upload-details')).toContainText('已确认 1/10');
  await expect(page.locator('.utc-upload-details')).toContainText('images:mixed');
  await page.evaluate(()=>window.UploadTaskCenterRuntime.upsert({id:'images:mixed',status:'FAILED',stage:'上传中断',detail:'隔离网络失败，可按请求身份核验'}));
  await expect(page.locator('.utc-upload-details')).toContainText('隔离网络失败');
  // Unrelated dialogs own the overlay; the dock must not intercept their buttons.
  expect(await page.evaluate(()=>{
    const button=document.querySelector('[data-utc-toggle]');const r=button.getBoundingClientRect();
    return button.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));
  })).toBe(false);
  await page.keyboard.press('Escape');
  await expect(page.locator('.utc-upload-details')).not.toBeVisible();
});

test('original upload modal and minimized window allow dock clicks while unrelated nested modal owns input',async({page})=>{
  await page.goto('/');
  await expect.poll(()=>page.evaluate(()=>Boolean(state.uiReady))).toBe(true);
  await page.evaluate(()=>{
    window.UploadTaskCenterRuntime.upsert({id:'zip:modal',kind:'zip',title:'modal.zip',status:'UPLOADING',browserTransfer:true});
    window.modal('ZIP 上传','<p>隔离传输视图</p>');
  });
  await page.locator('[data-utc-toggle]').click();
  await expect(page.locator('[data-utc-id="zip:modal"]')).toBeVisible();
  await page.getByRole('button',{name:'最小化导入窗口'}).click();
  await page.locator('[data-utc-toggle]').click();
  await expect(page.locator('[data-utc-toggle]')).toHaveAttribute('aria-expanded','false');
  await page.locator('[data-utc-toggle]').click();
  await page.evaluate(()=>window.modal('操作确认','<p>隔离业务确认</p>'));
  expect(await page.evaluate(()=>{
    const button=document.querySelector('[data-utc-toggle]'),r=button.getBoundingClientRect();
    return button.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));
  })).toBe(false);
  await page.keyboard.press('Escape');
  await page.locator('[data-utc-toggle]').click();
  await expect(page.locator('[data-utc-toggle]')).toHaveAttribute('aria-expanded','false');
});

test('late durable reads cannot overwrite newer progress or a switched project, and pagehide flushes pending bytes',async({page})=>{
  await page.goto('/');
  await expect.poll(()=>page.evaluate(()=>Boolean(state.uiReady))).toBe(true);
  const result=await page.evaluate(async()=>{
    window.UploadTaskCenterRuntime.destroy();
    const {installUploadTaskCenter}=await import('/static/modules/upload-task-center.js');
    let project='utc-isolated-a',resolveRead;
    const runtime=installUploadTaskCenter({projectId:()=>project,pollRegistry:{clear(){},startTimeout(){}},fetchImpl:()=>new Promise(resolve=>resolveRead=resolve)});
    runtime.upsert({id:'durable',kind:'browser-upload',status:'UPLOADING',progress:10,serverUrl:'/isolated-status'});
    const first=runtime.refresh();
    runtime.upsert({id:'durable',progress:70});
    resolveRead(Response.json({status:'UPLOADING',progress:12}));await first;
    const current=runtime.list()[0].progress;
    const second=runtime.refresh();
    project='utc-isolated-b';runtime.switchProject();
    runtime.upsert({id:'durable',kind:'browser-upload',status:'UPLOADING',progress:5});
    resolveRead(Response.json({status:'DONE',progress:100}));await second;
    runtime.upsert({id:'durable',progress:9});
    window.dispatchEvent(new Event('pagehide'));
    const next=runtime.list()[0];
    const saved=JSON.parse(localStorage.getItem('mc_upload_task_center_v1:utc-isolated-b'))[0];
    const prior=JSON.parse(localStorage.getItem('mc_upload_task_center_v1:utc-isolated-a'))[0];
    runtime.destroy();
    return {current,next:next.progress,status:next.status,saved:saved.progress,prior:prior.progress};
  });
  expect(result).toEqual({current:70,next:9,status:'UPLOADING',saved:9,prior:70});
});

test('pending actions are single-flight and recover on errors; phase transitions keep the original row', async ({page}) => {
  await page.goto('/');
  await expect.poll(() => page.evaluate(() => Boolean(state.uiReady))).toBe(true);
  await page.evaluate(()=>{
    window.__utcActions=[];
    window.ZipImportRuntime={
      pauseUpload:id=>{window.__utcActions.push(['pause',id]);return new Promise(resolve=>window.__utcResolve=resolve)},
      promptResume:async id=>{window.__utcActions.push(['resume',id]);throw new Error('隔离恢复失败')},
      cancelUpload:async id=>window.__utcActions.push(['cancel',id]),
      openTask:async id=>window.__utcActions.push(['open',id]),
    };
    window.UploadTaskCenterRuntime.upsert({id:'zip:actions',kind:'zip',title:'actions.zip',status:'UPLOADING',browserTransfer:true});
  });
  await page.locator('[data-utc-toggle]').click();
  const row=page.locator('[data-utc-id="zip:actions"]');
  await row.locator('[data-utc-action="pause"]').click();
  await expect(row.locator('[data-utc-action="pause"]')).toHaveAttribute('aria-busy','true');
  expect(await row.locator('[data-utc-action="pause"]').evaluate(node=>getComputedStyle(node,'::before').animationName)).toBe('spin');
  await page.evaluate(()=>{
    const center=window.UploadTaskCenterRuntime;
    for(let i=0;i<120;i++)center.upsert({id:'zip:actions',progress:i/2});
    document.querySelector('[data-utc-id="zip:actions"] [data-utc-action="cancel"]').click();
  });
  expect(await page.evaluate(()=>window.__utcActions)).toEqual([['pause','actions']]);
  await page.evaluate(()=>{window.UploadTaskCenterRuntime.upsert({id:'zip:actions',status:'PAUSED'});window.__utcResolve()});
  await row.locator('[data-utc-action="resume"]').click();
  await expect(row.locator('[data-utc-action="resume"]')).toBeEnabled();
  await row.locator('[data-utc-action="cancel"]').click();
  await page.evaluate(()=>{window.__utcPhaseRow=document.querySelector('[data-utc-id="zip:actions"]')});
  for(const [status,stage,progress] of [['MERGING','合并分片',0],['VALIDATING','校验 ZIP',20],['MAPPING_LABELS','标签映射',0],['RUNNING','素材入库',35],['DONE','导入完成',100]]){
    await page.evaluate(task=>window.UploadTaskCenterRuntime.upsert({id:'zip:actions',...task}),{status,stage,progress,browserTransfer:false});
    await expect(row).toContainText(stage);
    expect(await page.evaluate(()=>window.__utcPhaseRow===document.querySelector('[data-utc-id="zip:actions"]'))).toBe(true);
  }
  await row.locator('[data-utc-action="open"]').click();
  await expect.poll(()=>page.evaluate(()=>window.__utcActions)).toEqual([['pause','actions'],['resume','actions'],['cancel','actions'],['open','actions']]);
  await expect(row.locator('[data-utc-action="open"]')).toBeEnabled();
  await page.evaluate(()=>{window.ZipImportRuntime=null});
  await row.locator('[data-utc-action="open"]').click();
  await expect(page.locator('.toast').filter({hasText:'上传模块尚未就绪'})).toBeVisible();
});

test('an action deadline ends the spinner without repeating an unresolved original control request',async({page})=>{
  await page.goto('/');
  await expect.poll(()=>page.evaluate(()=>Boolean(state.uiReady))).toBe(true);
  await page.clock.install();
  await page.evaluate(()=>{
    window.__utcUncertainCalls=0;
    window.ZipImportRuntime={pauseUpload:()=>{window.__utcUncertainCalls++;return new Promise(resolve=>window.__utcUncertainResolve=resolve)}};
    window.UploadTaskCenterRuntime.upsert({id:'zip:uncertain',kind:'zip',title:'uncertain.zip',status:'UPLOADING',browserTransfer:true});
  });
  await page.locator('[data-utc-toggle]').click();
  const button=page.locator('[data-utc-id="zip:uncertain"] [data-utc-action="pause"]');
  await button.click();
  await expect(button).toHaveAttribute('aria-busy','true');
  await page.clock.runFor(30_010);
  await expect(button).toHaveText('等待结果确认');
  await expect(button).not.toHaveAttribute('aria-busy','true');
  await page.evaluate(()=>document.querySelector('[data-utc-id="zip:uncertain"] [data-utc-action="cancel"]').click());
  expect(await page.evaluate(()=>window.__utcUncertainCalls)).toBe(1);
  await page.evaluate(()=>window.__utcUncertainResolve());
  await expect(button).toBeEnabled();
  await expect(button).toHaveText('暂停');
});

test('late history cleanup cannot resurrect a destroyed task center or replace its successor',async({page})=>{
  await page.goto('/');
  await expect.poll(()=>page.evaluate(()=>Boolean(state.uiReady))).toBe(true);
  expect(await page.evaluate(async()=>{
    window.UploadTaskCenterRuntime.destroy();
    const {installUploadTaskCenter}=await import('/static/modules/upload-task-center.js');
    let resolveDelete;
    const registry={clear(){},startTimeout(){}};
    const old=installUploadTaskCenter({projectId:()=> 'utc-cleanup',pollRegistry:registry,fetchImpl:()=>new Promise(resolve=>resolveDelete=resolve)});
    old.upsert({id:'zip:old',kind:'zip',status:'DONE'});
    const pending=old.clearCompleted();await Promise.resolve();old.destroy();
    const current=installUploadTaskCenter({projectId:()=> 'utc-successor',pollRegistry:registry});
    current.upsert({id:'image:new',kind:'browser-upload',title:'新实例',status:'UPLOADING'});
    const shell=document.querySelector('.utc-shell');
    resolveDelete(Response.json({ok:true}));await pending;
    const result=window.UploadTaskCenterRuntime===current&&document.querySelector('.utc-shell')===shell&&current.list()[0].id==='image:new';
    current.destroy();
    return result;
  })).toBe(true);
});

test('upload task center patches progress without rebuilding shell row or progress node', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await expect.poll(() => page.evaluate(() => Boolean(state.uiReady))).toBe(true);
  await expect.poll(() => page.evaluate(() => window.UploadTaskCenterRuntime?.build || null))
    .toBe('upload-task-center-4');

  await page.evaluate(() => {
    window.UploadTaskCenterRuntime.upsert({
      id:'upload-perf-browser',
      kind:'browser-upload',
      title:'浏览器素材上传',
      status:'UPLOADING',
      progress:10,
      stage:'上传中',
      detail:'100 / 1000',
    });
  });

  await page.locator('[data-utc-toggle]').click();
  const row = page.locator('[data-utc-id="upload-perf-browser"]');
  await expect(row).toBeVisible();
  await expect(row).toContainText('10%');

  await page.evaluate(() => {
    window.__uploadCenterShell = document.querySelector('#uploadTaskCenter .utc-shell');
    window.__uploadCenterRow = document.querySelector('[data-utc-id="upload-perf-browser"]');
    window.__uploadCenterProgress = window.__uploadCenterRow?.querySelector('.utc-progress i') || null;

    window.UploadTaskCenterRuntime.upsert({
      id:'upload-perf-browser',
      kind:'browser-upload',
      title:'浏览器素材上传',
      status:'UPLOADING',
      progress:57.5,
      stage:'服务器处理中',
      detail:'575 / 1000',
    });
  });

  await expect(row).toContainText('57.5%');
  await expect(row).toContainText('服务器处理中');
  await expect(row.locator('.utc-progress i')).toHaveAttribute('data-progress', '57.50');

  expect(await page.evaluate(() => ({
    shell: window.__uploadCenterShell === document.querySelector('#uploadTaskCenter .utc-shell'),
    row: window.__uploadCenterRow === document.querySelector('[data-utc-id="upload-perf-browser"]'),
    progress: window.__uploadCenterProgress === document.querySelector('[data-utc-id="upload-perf-browser"] .utc-progress i'),
  }))).toEqual({shell:true,row:true,progress:true});

  await page.evaluate(() => window.UploadTaskCenterRuntime.remove('upload-perf-browser'));
  expect(pageErrors).toEqual([]);
});

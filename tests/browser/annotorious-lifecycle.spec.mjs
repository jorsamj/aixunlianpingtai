import {test,expect} from '@playwright/test';
import {writeFile} from 'node:fs/promises';

function bmp() {
  const width=640,height=480,row=width*3,b=Buffer.alloc(54+row*height,120);
  b.fill(0,0,54);b.write('BM');b.writeUInt32LE(b.length,2);b.writeUInt32LE(54,10);b.writeUInt32LE(40,14);
  b.writeInt32LE(width,18);b.writeInt32LE(height,22);b.writeUInt16LE(1,26);b.writeUInt16LE(24,28);b.writeUInt32LE(row*height,34);return b;
}
async function fixture(request) {
  const created=await request.post('/api/projects',{data:{name:`Annotation lifecycle ${Date.now()} ${Math.random()}`,
    labels:[{code:'person',display_name:'人员',color:'#ef4444'},{code:'vehicle',display_name:'车辆',color:'#3b82f6'}]}});
  expect(created.ok()).toBeTruthy();const project=await created.json();
  const upload=await request.post(`/api/projects/${project.id}/images`,{multipart:{dataset_id:'default',files:{name:'lifecycle.bmp',mimeType:'image/bmp',buffer:bmp()}}});
  expect(upload.ok()).toBeTruthy();const image=(await upload.json()).uploaded[0];
  const ready=await request.post(`/api/v52/projects/${project.id}/images/mark-ready`,{data:{image_ids:[image.id]}});expect(ready.ok()).toBeTruthy();
  return {project,image,url:`/api/projects/${project.id}/annotations/${image.id}`};
}
async function start(page,fx) {
  await page.route('**/api/v53/bootstrap/snapshot**',async route=>{
    const url=new URL(route.request().url());url.searchParams.set('preferred_project_id',fx.project.id);await route.fallback({url:url.toString()});
  });
  await page.addInitScript(()=>localStorage.setItem('mc_train_ui_state_v34',JSON.stringify({page:'数据集'})));
  await page.goto('/');await expect.poll(()=>page.evaluate(()=>state.uiReady)).toBe(true);
  await page.getByRole('button',{name:/数据集/}).click();await page.getByRole('button',{name:/已处理/}).click();
}
async function open(page,fx,{ready=true}={}) {
  await page.locator('.data412-card',{hasText:fx.image.filename}).getByRole('button',{name:/^(标注|编辑标注)$/}).click();
  const dialog=page.getByRole('dialog',{name:'图片标注工作台',exact:true});await expect(dialog).toBeVisible();
  if(ready)await expect(dialog.locator('svg.a9s-annotationlayer')).toHaveCount(1);
  return dialog;
}
async function drag(page,selector,from,to) {
  const target=page.locator(selector),rect=await target.boundingBox(),size=await target.evaluate(img=>({w:img.naturalWidth,h:img.naturalHeight}));
  const point=([x,y])=>({x:rect.x+x*rect.width/size.w,y:rect.y+y*rect.height/size.h});const a=point(from),b=point(to);
  await page.mouse.move(a.x,a.y);await page.mouse.down();await page.mouse.move(b.x,b.y,{steps:6});await page.mouse.up();
}
async function dirty(page,dialog) {
  await dialog.locator('[data-ann-mode="draw"]').click();await drag(page,'#annImg',[100,100],[240,200]);
  await expect.poll(()=>page.evaluate(()=>state.ann.boxes.length)).toBe(1);
}
function latch() {let release;const promise=new Promise(resolve=>release=resolve);return {promise,release};}
const frames=page=>page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));

test('AI official candidate editing saves a review draft without GT writes and submits through the original decision API',async({page,request})=>{
  const fx=await fixture(request);await start(page,fx);let gtPosts=0,decisionBody;
  page.on('request',req=>{if(req.method()==='POST'&&req.url().endsWith(fx.url))gtPosts++;});
  const task=`/api/v60/projects/${fx.project.id}/annotation-tasks/isolated-review`;
  await page.route(`**${task}/candidates?**`,route=>route.fulfill({json:{total:1,items:[{...fx.image,image_id:fx.image.id,status:'succeeded',
    boxes:[{id:'candidate-old',class_id:0,label:'person',x1:80,y1:80,x2:180,y2:160,confidence:.8,source:'ai_candidate'}]}],label_summary:[{label:'person',box_count:1,image_count:1}]}}));
  await page.route(`**${task}/decisions`,route=>{
    decisionBody=route.request().postDataJSON();return route.fulfill({json:{queued_for_commit:false,applied_images:1,boxes_added:decisionBody.decisions[0].boxes.length,image_summaries:[]}});
  });
  await page.evaluate(()=>window.reviewAiLabel427('isolated-review'));
  const review=page.getByRole('dialog',{name:'AI标注审核工作台 · 待确认',exact:true});await expect(review).toBeVisible();
  await review.getByRole('button',{name:'编辑候选框',exact:true}).click();
  const edit=page.getByRole('dialog',{name:'编辑AI候选框',exact:true});await expect(edit.locator('svg.a9s-annotationlayer')).toHaveCount(1);
  await edit.locator('[data-ai60-mode="draw"]').click();await drag(page,'#ai60EditImg',[300,200],[400,300]);
  await expect.poll(()=>page.evaluate(()=>state.ai60Edit.boxes.length)).toBe(2);
  await edit.getByRole('button',{name:'保存候选修改',exact:true}).click();await expect(edit).toHaveCount(0);
  expect(gtPosts).toBe(0);expect((await (await request.get(fx.url)).json()).boxes).toEqual([]);
  await expect(review.getByText('已人工修改',{exact:true})).toBeVisible();
  await review.getByRole('button',{name:'采用已选择',exact:true}).click();await expect.poll(()=>!!decisionBody).toBe(true);
  expect(decisionBody.commit).toBe(true);expect(decisionBody.reject_unmentioned).toBe(true);
  expect(decisionBody.decisions[0].image_id).toBe(fx.image.id);expect(decisionBody.decisions[0].accepted).toBe(true);
  expect(decisionBody.decisions[0].boxes).toHaveLength(2);expect(decisionBody.decisions[0].boxes[0].id).toBe('candidate-old');
  expect(decisionBody.decisions[0].boxes.every(box=>box.source==='ai_candidate_reviewed')).toBe(true);
  expect(gtPosts).toBe(0);
  // Only the decision receiver is an isolated response. No inference job or
  // real review commit has been created; this proves the existing UI contract.
});

for(const status of [200,422])test(`dirty close waits for save ${status} before destroying or preserving the official editor`,async({page,request})=>{
  const fx=await fixture(request);await start(page,fx);const dialog=await open(page,fx);await dirty(page,dialog);
  const seen=latch(),gate=latch();
  await page.route(`**${fx.url}`,async route=>{
    if(route.request().method()!=='POST')return route.continue();
    const response=status===200?await route.fetch():null;seen.release();await gate.promise;
    if(response)return route.fulfill({response});return route.fulfill({status:422,json:{detail:'isolated validation rejection'}});
  });
  await dialog.getByRole('button',{name:'关闭',exact:true}).click();await seen.promise;
  await expect(dialog).toBeVisible();expect(await page.evaluate(()=>state.annotationEditor.snapshot().destroyed)).toBe(false);
  gate.release();
  if(status===200){await expect(dialog).toHaveCount(0);expect((await (await request.get(fx.url)).json()).boxes).toHaveLength(1);}
  else {await expect(dialog.locator('#ann414Save')).toBeEnabled();await expect(dialog).toBeVisible();expect(await page.evaluate(()=>state.annDirty)).toBe(true);}
});

test('a late successful close-save cannot dismiss a newer modal opened by the original Modal Stack',async({page,request})=>{
  const fx=await fixture(request);await start(page,fx);const dialog=await open(page,fx);await dirty(page,dialog);
  const seen=latch(),gate=latch();
  await page.route(`**${fx.url}`,async route=>{if(route.request().method()!=='POST')return route.continue();const response=await route.fetch();seen.release();await gate.promise;await route.fulfill({response});});
  await dialog.getByRole('button',{name:'关闭',exact:true}).click();await seen.promise;
  await page.evaluate(()=>window.modal('晚响应隔离验证','<p>新弹窗保持打开</p>'));
  const later=page.getByRole('dialog',{name:'晚响应隔离验证',exact:true});await expect(later).toBeVisible();
  gate.release();await expect(dialog.locator('#ann414Save')).toBeEnabled();await frames(page);
  await expect(later).toBeVisible();await expect(dialog).toHaveCount(1);
});

test('changing the project identity fences a late save result from clearing current dirty state',async({page,request})=>{
  const fx=await fixture(request),other=await fixture(request);await start(page,fx);const dialog=await open(page,fx);await dirty(page,dialog);
  const seen=latch(),gate=latch();
  await page.route(`**${fx.url}`,async route=>{if(route.request().method()!=='POST')return route.continue();const response=await route.fetch();seen.release();await gate.promise;await route.fulfill({response});});
  await page.keyboard.press('Control+s');await seen.promise;
  // The app has one default-workspace UI. This controlled identity update
  // exercises the save ownership fence, not an invented project selector UI.
  await page.evaluate(project=>{state.project=project;},other.project);
  const response=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith(fx.url));gate.release();await response;await frames(page);
  expect(await page.evaluate(()=>state.project.id)).toBe(other.project.id);expect(await page.evaluate(()=>state.annDirty)).toBe(true);
  expect((await (await request.get(`/api/projects/${other.project.id}/annotations/${other.image.id}`)).json()).boxes).toEqual([]);
});

for(const extension of ['js','css'])test(`offline official ${extension} resource failure exposes retry and recreates one real editor`,async({page,request})=>{
  const fx=await fixture(request);let failed=false;
  await page.route(new RegExp(`/static/vendor/annotorious/annotorious\\.${extension}(?:\\?.*)?$`),route=>{
    if(!failed){failed=true;return route.abort('failed');}return route.continue();
  });
  await start(page,fx);const dialog=await open(page,fx,{ready:false});
  await expect(dialog.locator('[data-ann-editor-status]')).toContainText('失败');
  await expect(dialog.locator('[data-ann-editor-retry]')).toBeVisible();await dialog.locator('[data-ann-editor-retry]').click();
  await expect(dialog.locator('svg.a9s-annotationlayer')).toHaveCount(1);await expect(dialog.locator('[data-ann-editor-status]')).toBeHidden();
});

test('closing during a pending official asset load prevents a late component and allows a fresh reopen',async({page,request})=>{
  const fx=await fixture(request),seen=latch(),gate=latch();let held=false;
  await page.route(/\/static\/vendor\/annotorious\/annotorious\.js(?:\?.*)?$/,async route=>{
    if(held)return route.continue();held=true;const response=await route.fetch();seen.release();await gate.promise;await route.fulfill({response});
  });
  await start(page,fx);const dialog=await open(page,fx,{ready:false});await seen.promise;
  await dialog.getByRole('button',{name:'关闭',exact:true}).click();await expect(dialog).toHaveCount(0);
  const loaded=page.waitForResponse(r=>r.url().includes('/static/vendor/annotorious/annotorious.js'));gate.release();await loaded;await frames(page);
  await expect(page.locator('svg.a9s-annotationlayer')).toHaveCount(0);
  const reopened=await open(page,fx);await expect(reopened.locator('svg.a9s-annotationlayer')).toHaveCount(1);
});

test('immediate real pointer selection then Escape clears selection without closing the workbench',async({page,request})=>{
  const fx=await fixture(request);await start(page,fx);const dialog=await open(page,fx);await dirty(page,dialog);
  await dialog.locator('[data-ann-mode="select"]').click();
  expect(await page.evaluate(()=>state.annotationEditor.snapshot().selectedId)).toBe(null);
  // Use the actual stable SVG target: source-image coordinates can miss while
  // fit/centering settles. Do not wait for deferred selectionChanged before Esc.
  const rectangle=dialog.locator('g.a9s-annotation rect.a9s-inner').first();
  await rectangle.evaluate(node=>{
    window.__escapeEditor=state.annotationEditor;
    window.__escapePointerHit=false;
    node.ownerSVGElement.addEventListener('pointerup',event=>{
      window.__escapePointerHit=!!event.target.closest('.a9s-annotation');
    },{capture:true,once:true});
  });
  await rectangle.click();await page.keyboard.press('Escape');await frames(page);
  expect(await page.evaluate(()=>window.__escapePointerHit)).toBe(true);
  await expect(dialog).toBeVisible();
  expect(await page.evaluate(()=>state.annotationEditor===window.__escapeEditor)).toBe(true);
  expect(await page.evaluate(()=>state.annotationEditor.snapshot().selectedId)).toBe(null);
});

test('twenty actual open close cycles report garbage-collected DOM and listener samples with bounded growth',async({page,request},testInfo)=>{
  test.setTimeout(120_000);const fx=await fixture(request);await start(page,fx);const session=await page.context().newCDPSession(page),samples=[];
  for(let cycle=1;cycle<=20;cycle++) {
    const dialog=await open(page,fx);await dialog.getByRole('button',{name:'关闭',exact:true}).click();
    await expect(dialog).toHaveCount(0);await expect(page.locator('svg.a9s-annotationlayer')).toHaveCount(0);
    if([4,8,12,16,20].includes(cycle)) {
      await session.send('HeapProfiler.collectGarbage');const counters=await session.send('Memory.getDOMCounters');
      const heap=await session.send('Runtime.getHeapUsage');samples.push({cycle,...counters,usedSize:heap.usedSize,totalSize:heap.totalSize});
    }
  }
  const first=samples[0],last=samples.at(-1);
  expect(last.documents).toBeLessThanOrEqual(first.documents+2);
  expect(last.nodes).toBeLessThanOrEqual(first.nodes+100);
  expect(last.jsEventListeners).toBeLessThanOrEqual(first.jsEventListeners+10);
  const artifact=testInfo.outputPath('annotorious-lifecycle-cdp-samples.json');
  await writeFile(artifact,JSON.stringify({scope:'whole page after 4 warmup cycles and CDP garbage collection; bounded DOM/listener growth in this fixture, not proof of absolute leak freedom',samples},null,2));
  await testInfo.attach('actual-CDP-lifecycle-samples',{path:artifact,contentType:'application/json'});
});

import {test, expect} from '@playwright/test';
import {writeFile} from 'node:fs/promises';

function bmp(width=640,height=480,color=[60,120,180]) {
  const row=Math.ceil(width*3/4)*4, result=Buffer.alloc(54+row*height);
  result.write('BM');result.writeUInt32LE(result.length,2);result.writeUInt32LE(54,10);
  result.writeUInt32LE(40,14);result.writeInt32LE(width,18);result.writeInt32LE(height,22);
  result.writeUInt16LE(1,26);result.writeUInt16LE(24,28);result.writeUInt32LE(row*height,34);
  for(let y=0;y<height;y++)for(let x=0;x<width;x++){
    const p=54+y*row+x*3;result[p]=color[2];result[p+1]=color[1];result[p+2]=color[0];
  }
  return result;
}

async function fixture(request,{count=1,width=640,height=480,boxes=[]}={}) {
  const created=await request.post('/api/projects',{data:{name:`Annotorious-${Date.now()}-${Math.random()}`,labels:[
    {code:'person',display_name:'人员',color:'#ef4444'},{code:'vehicle',display_name:'车辆',color:'#3b82f6'},
  ]}});
  expect(created.ok()).toBeTruthy();const project=await created.json();
  const labels=await (await request.get(`/api/v12/projects/${project.id}/labels`)).json();
  const images=[];
  for(let i=0;i<count;i++) {
    const uploaded=await request.post(`/api/projects/${project.id}/images`,{multipart:{dataset_id:'default',
      files:{name:`anno-${String(i).padStart(2,'0')}.bmp`,mimeType:'image/bmp',buffer:bmp(width,height,[60+i*3,120+i,180-i])}}});
    expect(uploaded.ok()).toBeTruthy();images.push((await uploaded.json()).uploaded[0]);
    if(boxes.length) {
      const saved=await request.post(`/api/projects/${project.id}/annotations/${images[i].id}`,{data:{boxes,
        expected_version:images[i].annotation_version,source_content_sha256:images[i].content_sha256}});
      expect(saved.ok()).toBeTruthy();
    }
  }
  const ready=await request.post(`/api/v52/projects/${project.id}/images/mark-ready`,{data:{image_ids:images.map(i=>i.id)}});
  expect(ready.ok()).toBeTruthy();
  return {project,images,labels:labels.items||[],width,height};
}

async function open(page,fx,{batch=false}={}) {
  await page.route('**/api/v53/bootstrap/snapshot**',async route=>{
    const url=new URL(route.request().url());url.searchParams.set('preferred_project_id',fx.project.id);
    await route.fallback({url:url.toString()});
  });
  await page.addInitScript(()=>localStorage.setItem('mc_train_ui_state_v34',JSON.stringify({page:'数据集'})));
  await page.goto('/');
  await expect.poll(()=>page.evaluate(()=>state.uiReady)).toBe(true);
  await page.getByRole('button',{name:/数据集/}).click();
  await page.getByRole('button',{name:/已处理/}).click();
  if(batch) {
    await page.getByRole('button',{name:'批量操作',exact:true}).click();
    for(const image of fx.images)await page.locator('.data412-card',{hasText:image.filename}).getByRole('checkbox').check();
    await page.getByRole('button',{name:'批量标注',exact:true}).click();
  } else await page.locator('.data412-card',{hasText:fx.images[0].filename}).getByRole('button',{name:/^(标注|编辑标注)$/}).click();
  const dialog=page.getByRole('dialog',{name:'图片标注工作台',exact:true});
  await expect(dialog).toBeVisible();
  await expect(dialog.locator('#annSaveState')).toHaveText(/^已保存/);
  return dialog;
}

async function official(page,dialog) {
  await expect(dialog.locator('#annStage svg.a9s-annotationlayer')).toHaveCount(1);
  await expect.poll(()=>page.evaluate(()=>{
    const key=`${state.project?.id}:${state.activeImage?.id||''}:${state.activeImage?.url||''}`;
    return !!state.annotationEditor?.snapshot && state.annotationEditorIdentity===key
      && !state.annotationHydrating420 && !state.annotationEditorFlight && !state.annotationEditor.snapshot().locked;
  })).toBe(true);
  await expect(dialog.locator('.box424,.drawBox,.handle424')).toHaveCount(0);
}

async function drag(page,from,to) {
  const rect=await page.locator('#annImg').boundingBox();
  const size=await page.locator('#annImg').evaluate(img=>({w:img.naturalWidth,h:img.naturalHeight}));
  const point=([x,y])=>({x:rect.x+x*rect.width/size.w,y:rect.y+y*rect.height/size.h});
  const a=point(from),b=point(to);
  if(from[0]===to[0]&&from[1]===to[1]){await page.mouse.click(a.x,a.y);return;}
  await page.mouse.move(a.x,a.y);await page.mouse.down();await page.mouse.move(b.x,b.y,{steps:8});await page.mouse.up();
}
const gt=page=>page.evaluate(()=>structuredClone(state.ann.boxes));
const snapshot=page=>page.evaluate(()=>state.annotationEditor.snapshot());
const annotationUrl=(fx,i=0)=>`/api/projects/${fx.project.id}/annotations/${fx.images[i].id}`;
const boxes=(count=1)=>Array.from({length:count},(_,i)=>({id:`existing-${i}`,class_id:i%2,label:i%2?'vehicle':'person',
  x1:8+(i%20)*25,y1:8+Math.floor(i/20)*25,x2:25+(i%20)*25,y2:25+Math.floor(i/20)*25,source:'manual'}));

test('formal workbench mounts exactly one official offline annotation layer',async({page,request})=>{
  const fx=await fixture(request);const dialog=await open(page,fx);await official(page,dialog);
  await expect(dialog.locator('[data-ann-mode="draw"]')).toBeVisible();
  await expect(dialog.locator('[data-ann-mode="select"]')).toBeVisible();
  await expect(dialog.locator('[data-ann-mode="pan"]')).toBeVisible();
  expect((await snapshot(page)).destroyed).toBe(false);
});

test('drawing mode creates consecutive rectangles without a selection editor swallowing the next gesture',async({page,request})=>{
  const fx=await fixture(request),dialog=await open(page,fx);await official(page,dialog);
  await page.keyboard.press('1');
  await drag(page,[100,100],[200,180]);await expect.poll(async()=> (await gt(page)).length).toBe(1);
  await page.keyboard.press('2');
  await drag(page,[300,220],[420,310]);await expect.poll(async()=> (await gt(page)).length).toBe(2);
  expect((await gt(page)).map(box=>box.label)).toEqual(['person','vehicle']);
  expect((await snapshot(page)).mode).toBe('draw');
  const before=await gt(page);
  await dialog.locator('.ann420-class-visibility summary').click();
  await dialog.locator('[data-ann-visible-code="person"]').uncheck();
  await expect(dialog.locator('.a9s-annotation[data-id]')).toHaveCount(1);
  await page.keyboard.press('Delete');expect(await gt(page)).toEqual(before);
  await dialog.locator('[data-ann-visible-code="person"]').check();
  await expect(dialog.locator('.a9s-annotation[data-id]')).toHaveCount(2);expect(await gt(page)).toEqual(before);
});

test('real pointer draw move resize reclass delete undo redo persists through the formal save API',async({page,request})=>{
  const fx=await fixture(request);const dialog=await open(page,fx);await official(page,dialog);
  await dialog.locator('[data-ann-mode="draw"]').click();
  await drag(page,[100,100],[240,200]);
  await expect.poll(async()=> (await gt(page)).length).toBe(1);
  const first=(await gt(page))[0];
  expect(first.id).toBeTruthy();expect(first.x1).toBeCloseTo(100,0);expect(first.x2).toBeCloseTo(240,0);
  await dialog.locator('[data-ann-mode="select"]').click();
  await drag(page,[170,150],[170,150]);
  await expect.poll(async()=> (await snapshot(page)).selectedId).toBe(first.id);
  await drag(page,[170,150],[190,170]);
  await expect.poll(async()=> (await gt(page))[0].x1).toBeCloseTo(120,0);
  await drag(page,[260,220],[290,250]);
  await expect.poll(async()=> (await gt(page))[0].x2).toBeCloseTo(290,0);
  await expect.poll(async()=> (await gt(page))[0].y2).toBeCloseTo(250,0);
  await dialog.locator('#annBoxes select').first().selectOption(String(fx.labels.find(l=>l.code==='vehicle').class_id));
  await expect.poll(async()=> (await gt(page))[0].label).toBe('vehicle');
  await drag(page,[205,185],[205,185]);
  await page.keyboard.press('Backspace');await expect.poll(async()=> (await gt(page)).length).toBe(0);
  await page.keyboard.press('Control+z');await expect.poll(async()=> (await gt(page)).length).toBe(1);
  await page.keyboard.press('Control+Shift+z');await expect.poll(async()=> (await gt(page)).length).toBe(0);
  await page.keyboard.press('Control+z');await expect.poll(async()=> (await gt(page)).length).toBe(1);
  const expected=(await gt(page))[0];expect(expected.id).toBe(first.id);
  const sent=page.waitForRequest(r=>r.method()==='POST'&&r.url().endsWith(annotationUrl(fx)));
  await page.keyboard.press('Control+s');
  const payload=(await sent).postDataJSON();
  expect(payload.expected_version).toEqual(expect.any(Number));
  expect(payload.source_content_sha256).toBe(fx.images[0].content_sha256);
  expect(payload.boxes[0].id).toBe(first.id);
  await expect(dialog.locator('#annSaveState')).toHaveText(/^已保存/);
  const stored=await (await request.get(annotationUrl(fx))).json();
  expect(stored.boxes).toHaveLength(1);expect(stored.boxes[0].id).toBe(expected.id);expect(stored.boxes[0].label).toBe(expected.label);
  for(const key of ['x1','y1','x2','y2'])expect(stored.boxes[0][key]).toBeCloseTo(expected[key],1);
  await page.reload();
  await page.getByRole('button',{name:/已处理/}).click();
  await page.locator('.data412-card',{hasText:fx.images[0].filename}).getByRole('button',{name:/^(标注|编辑标注)$/}).click();
  await expect.poll(async()=> (await gt(page))[0]?.id).toBe(first.id);
});

test('class filtering and H hide only the official projection and preserve every GT box',async({page,request})=>{
  const initial=boxes(2),fx=await fixture(request,{boxes:initial}),dialog=await open(page,fx);await official(page,dialog);
  const before=await gt(page);
  const filter=dialog.locator('[data-ann-filter]');
  const option=await filter.locator('option').evaluateAll(options=>options.find(o=>o.textContent.includes('person')).value);
  await filter.selectOption(option);
  expect(await gt(page)).toEqual(before);
  await dialog.locator('[data-ann-mode="select"]').click();
  await drag(page,[40,16],[50,26]);
  expect(await gt(page)).toEqual(before);
  await dialog.locator('[data-ann-visibility]').click();
  expect((await snapshot(page)).visible).toBe(false);
  await drag(page,[12,12],[40,40]);expect(await gt(page)).toEqual(before);
  await page.keyboard.press('h');expect((await snapshot(page)).visible).toBe(true);
  expect(await gt(page)).toEqual(before);
});

test('input focus guards delete label hotkeys undo save and H',async({page,request})=>{
  const fx=await fixture(request,{boxes:boxes(1)}),dialog=await open(page,fx);await official(page,dialog);
  await dialog.locator('[data-ann-mode="select"]').click();await drag(page,[16,16],[16,16]);
  await expect.poll(async()=> (await snapshot(page)).selectedId).toBe('existing-0');
  const before=await gt(page),view=await snapshot(page);let writes=0;
  page.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith(annotationUrl(fx)))writes++;});
  await dialog.locator('#ann420Label').focus();
  for(const key of ['Delete','Backspace','1','h','Control+z','Control+s'])await page.keyboard.press(key);
  expect(await gt(page)).toEqual(before);expect((await snapshot(page)).visible).toBe(view.visible);expect(writes).toBe(0);
});

test('an isolated historical unknown-label response stays visible until explicit user correction',async({page,request})=>{
  const fx=await fixture(request,{boxes:boxes(1)});
  await page.route(`**${annotationUrl(fx)}`,async route=>{
    if(route.request().method()!=='GET')return route.continue();
    const response=await route.fetch(),body=await response.json();
    const replace=rows=>rows.map(box=>({...box,class_id:999,label:'retired_legacy_label'}));
    if(body.annotation)body.annotation.boxes=replace(body.annotation.boxes);
    if(body.boxes)body.boxes=replace(body.boxes);
    await route.fulfill({response,json:body});
  });
  const dialog=await open(page,fx);await official(page,dialog);
  expect((await gt(page))[0].label).toBe('retired_legacy_label');expect((await gt(page))[0].class_id).toBe(999);
  await expect(dialog.locator('#annBoxes')).toContainText('retired_legacy_label');
  await dialog.locator('#annBoxes select').first().selectOption(String(fx.labels.find(l=>l.code==='vehicle').class_id));
  expect((await gt(page))[0].label).toBe('vehicle');
});

test('Escape cancels an in-progress official rectangle before closing the clean workbench',async({page,request})=>{
  const fx=await fixture(request),dialog=await open(page,fx);await official(page,dialog);
  await dialog.locator('[data-ann-mode="draw"]').click();
  const rect=await dialog.locator('#annImg').boundingBox();
  await page.mouse.move(rect.x+rect.width*.2,rect.y+rect.height*.2);await page.mouse.down();
  await page.mouse.move(rect.x+rect.width*.4,rect.y+rect.height*.4,{steps:4});
  await page.keyboard.press('Escape');await page.mouse.up();
  expect(await gt(page)).toEqual([]);await expect(dialog).toBeVisible();
  await page.keyboard.press('Escape');await expect(dialog).toHaveCount(0);
});

test('fit 100 percent wheel zoom and pan keep transformed pointer geometry in original pixels',async({page,request})=>{
  const fx=await fixture(request),dialog=await open(page,fx);await official(page,dialog);
  await dialog.getByRole('button',{name:'100%',exact:true}).click();
  expect((await snapshot(page)).scale).toBeCloseTo(1,3);
  const image=await dialog.locator('#annImg').boundingBox();
  await page.mouse.move(image.x+image.width*.5,image.y+image.height*.5);await page.mouse.wheel(0,-120);
  await expect.poll(async()=> (await snapshot(page)).scale).toBeGreaterThan(1);
  await dialog.locator('[data-ann-mode="pan"]').click();const before=await gt(page);
  await drag(page,[250,200],[270,220]);expect(await gt(page)).toEqual(before);
  await dialog.getByRole('button',{name:'适应窗口',exact:true}).click();
  await dialog.locator('[data-ann-mode="draw"]').click();await drag(page,[100,100],[200,180]);
  await expect.poll(async()=> (await gt(page)).length).toBe(1);
  const box=(await gt(page))[0];expect(box.x1).toBeCloseTo(100,0);expect(box.y1).toBeCloseTo(100,0);expect(box.x2).toBeCloseTo(200,0);
});

for(const [width,height] of [[640,480],[800,600],[1920,1080],[3840,2160]]) {
  test(`original ${width}x${height} pixels retain a small boundary rectangle across a save round trip`,async({page,request})=>{
    const boundary={id:'boundary-legacy',class_id:0,label:'person',x1:0,y1:0,x2:8,y2:8,source:'manual'};
    const fx=await fixture(request,{width,height,boxes:[boundary]}),dialog=await open(page,fx);await official(page,dialog);
    const actual=(await gt(page))[0];expect(actual.id).toBe(boundary.id);expect(actual.x1).toBe(0);expect(actual.x2).toBe(8);
    await dialog.getByRole('button',{name:'适应窗口',exact:true}).click();
    expect((await gt(page))[0]).toEqual(actual);
    await page.keyboard.press('Control+s');
    const response=await request.get(annotationUrl(fx));expect(response.ok()).toBeTruthy();
    expect((await response.json()).boxes[0]).toEqual(actual);
  });
}

test('last-box deletion saves unannotated while explicit no-target review saves confirmed_empty',async({page,request})=>{
  const fx=await fixture(request,{boxes:boxes(1)}),dialog=await open(page,fx);await official(page,dialog);
  await dialog.locator('[data-ann-mode="select"]').click();await drag(page,[16,16],[16,16]);
  await expect.poll(async()=> (await snapshot(page)).selectedId).toBe('existing-0');
  await page.keyboard.press('Delete');await expect.poll(async()=> (await gt(page)).length).toBe(0);
  await page.keyboard.press('Control+s');await expect(dialog.locator('#annSaveState')).toHaveText(/^已保存/);
  const empty=await (await request.get(annotationUrl(fx))).json();
  expect(empty.annotation_state).toBe('unannotated');expect(empty.annotation_scope).toEqual([]);
  await dialog.locator('#ann420ReviewPanel summary').click();
  for(const input of await dialog.locator('#ann420ReviewPanel input[type=checkbox]').all())await input.check();
  await dialog.getByRole('button',{name:'确认无目标',exact:true}).click();
  await expect.poll(async()=> (await (await request.get(annotationUrl(fx))).json()).annotation_state).toBe('confirmed_empty');
});

test('immediate pointer selection followed by Delete retains no deferred-selection race',async({page,request})=>{
  const fx=await fixture(request,{boxes:boxes(1)}),dialog=await open(page,fx);await official(page,dialog);
  await dialog.locator('[data-ann-mode="select"]').click();
  // Deliberately no snapshot poll or delay between the actual click and key.
  await drag(page,[16,16],[16,16]);await page.keyboard.press('Delete');
  await expect.poll(async()=> (await gt(page)).length).toBe(0);
});

test('HTTP validation failure and 409 keep dirty geometry and never auto-overwrite',async({page,request})=>{
  const fx=await fixture(request),dialog=await open(page,fx);await official(page,dialog);
  await dialog.locator('[data-ann-mode="draw"]').click();await drag(page,[80,80],[160,160]);
  await expect.poll(async()=> (await gt(page)).length).toBe(1);const before=await gt(page);let posts=0,status=422;
  await page.route(`**${annotationUrl(fx)}`,route=>{
    if(route.request().method()!=='POST')return route.continue();posts++;
    return route.fulfill({status,json:{detail:status===409?'ANNOTATION_VERSION_CONFLICT':'isolated save outage'}});
  });
  await page.keyboard.press('Control+s');await expect.poll(()=>posts).toBe(1);
  await expect(dialog.locator('#ann414Save')).toBeEnabled();
  await expect.poll(()=>page.evaluate(()=>!!state.annDirty)).toBe(true);expect(await gt(page)).toEqual(before);
  status=409;await page.keyboard.press('Control+s');await expect.poll(()=>posts).toBe(2);
  await expect(dialog.locator('#ann414Save')).toBeEnabled();
  expect(await gt(page)).toEqual(before);expect(await page.evaluate(()=>state.annDirty)).toBe(true);
  expect((await (await request.get(annotationUrl(fx))).json()).boxes).toEqual([]);
});

test('four viewport layouts retain the official canvas and usable toolbar without horizontal overflow',async({page,request},testInfo)=>{
  const fx=await fixture(request,{boxes:boxes(2)}),dialog=await open(page,fx);await official(page,dialog);
  for(const [width,height]of [[1920,1080],[1440,900],[1366,768],[375,812]]) {
    await page.setViewportSize({width,height});await dialog.getByRole('button',{name:'适应窗口',exact:true}).click();
    await expect(dialog.locator('svg.a9s-annotationlayer')).toBeVisible();
    const bounds=await dialog.evaluate(node=>{
      const dialog=node.getBoundingClientRect(),canvas=node.querySelector('.ann-canvas-wrap').getBoundingClientRect();
      return {width:document.documentElement.scrollWidth,dialog:dialog.width,dialogLeft:dialog.left,dialogRight:dialog.right,
        canvasLeft:canvas.left,canvasRight:canvas.right,canvasWidth:canvas.width,canvasTop:canvas.top,toolbarBottom:node.querySelector('.ann420-toolbar').getBoundingClientRect().bottom};
    });
    expect(bounds.width).toBeLessThanOrEqual(width);expect(bounds.dialog).toBeLessThanOrEqual(width);
    expect(bounds.canvasLeft).toBeGreaterThanOrEqual(bounds.dialogLeft);
    expect(bounds.canvasRight).toBeLessThanOrEqual(bounds.dialogRight);
    expect(bounds.canvasWidth).toBeGreaterThan(Math.min(260,width*.48));
    expect(bounds.canvasTop).toBeGreaterThanOrEqual(bounds.toolbarBottom);
    await expect(dialog.locator('[data-ann-mode="draw"]')).toBeInViewport();
    await page.screenshot({path:testInfo.outputPath(`annotorious-workbench-${width}x${height}.png`)});
  }
});

test('twenty-image queue measures 100 and 300 real official boxes and browser heap samples',async({page,request},testInfo)=>{
  test.setTimeout(120_000);
  const fx=await fixture(request,{count:20,boxes:boxes(100)}),dialog=await open(page,fx,{batch:true});await official(page,dialog);
  await expect(dialog.locator('#ann420Position')).toHaveText('1 / 20');
  const samples=[];
  for(const count of [100,300]) {
    if(count===300) {
      const next=await (await request.get(annotationUrl(fx))).json();
      const saved=await request.post(annotationUrl(fx),{data:{boxes:boxes(300),expected_version:next.version,source_content_sha256:fx.images[0].content_sha256}});
      expect(saved.ok()).toBeTruthy();await page.reload();
      await page.getByRole('button',{name:/已处理/}).click();
      await page.locator('.data412-card',{hasText:fx.images[0].filename}).getByRole('button',{name:/^(标注|编辑标注)$/}).click();
    }
    await expect.poll(async()=> (await gt(page)).length).toBe(count);
    await official(page,dialog);
    await expect(dialog.locator('#annStage .a9s-annotation[data-id]')).toHaveCount(count);
    const sample=await page.evaluate(()=>({time:performance.now(),heap:performance.memory?.usedJSHeapSize??null,
      officialShapes:document.querySelectorAll('#annStage .a9s-annotation[data-id]').length,totalNodes:document.querySelectorAll('#annStage *').length}));
    expect(sample.officialShapes).toBe(count);
    const start=Date.now();await dialog.getByRole('button',{name:'适应窗口',exact:true}).click();
    await expect(dialog.locator('svg.a9s-annotationlayer')).toBeVisible();
    samples.push({count,fitWallMs:Date.now()-start,...sample});
    await page.screenshot({path:testInfo.outputPath(`annotorious-${count}-boxes.png`)});
  }
  const performancePath=testInfo.outputPath('actual-browser-performance-samples.json');
  await writeFile(performancePath,JSON.stringify({scope:'whole-page browser heap samples; fit button wall time; not an isolated editor memory or leak measurement',samples},null,2));
  await testInfo.attach('actual-browser-performance-samples',{path:performancePath,contentType:'application/json'});
});

test('dirty previous next navigation saves the current GT before replacing the official editor',async({page,request})=>{
  const fx=await fixture(request,{count:2}),dialog=await open(page,fx,{batch:true});await official(page,dialog);
  await dialog.locator('[data-ann-mode="draw"]').click();await drag(page,[100,100],[220,200]);
  await expect.poll(async()=> (await gt(page)).length).toBe(1);const id=(await gt(page))[0].id;
  await page.keyboard.press('ArrowRight');await expect(dialog.locator('#ann420Filename')).toHaveText(fx.images[1].filename);
  await official(page,dialog);expect(await gt(page)).toEqual([]);
  expect((await (await request.get(annotationUrl(fx))).json()).boxes[0].id).toBe(id);
  await page.keyboard.press('ArrowLeft');await expect(dialog.locator('#ann420Filename')).toHaveText(fx.images[0].filename);
  await expect.poll(async()=> (await gt(page))[0]?.id).toBe(id);await official(page,dialog);
});

test('GT projection cannot mark a new editor ready before its actual image decodes',async({page,request})=>{
  const fx=await fixture(request,{count:2});
  const imagePath=new URL(fx.images[1].url,'http://localhost').pathname;
  let release;const gate=new Promise(resolve=>{release=resolve});
  await page.route(url=>url.pathname===imagePath,async route=>{
    const response=await route.fetch();await gate;await route.fulfill({response});
  });
  try {
    const dialog=await open(page,fx,{batch:true});await official(page,dialog);
    await dialog.locator('[data-ann-mode="select"]').click();
    await page.keyboard.press('ArrowRight');
    await expect(dialog.locator('#ann420Filename')).toHaveText(fx.images[1].filename);
    await expect(dialog.locator('[data-ann-editor-status]')).toBeVisible();
    await expect.poll(()=>page.evaluate(()=>!!state.annotationEditorFlight)).toBe(true);
    expect(await page.evaluate(()=>!!state.annotationEditor?.snapshot)).toBe(false);
    expect(await gt(page)).toEqual([]);
    release();await official(page,dialog);
    await page.keyboard.press('ArrowLeft');
    await expect(dialog.locator('#ann420Filename')).toHaveText(fx.images[0].filename);
    await official(page,dialog);
  } finally {release();}
});

test('twenty consecutive images each commit a real edit before keyboard navigation continues',async({page,request})=>{
  test.setTimeout(120_000);
  const fx=await fixture(request,{count:20,boxes:boxes(1)}),dialog=await open(page,fx,{batch:true});
  const vehicle=String(fx.labels.find(label=>label.code==='vehicle').class_id);
  for(let i=0;i<20;i++){
    await expect(dialog.locator('#ann420Filename')).toHaveText(fx.images[i].filename);
    await expect.poll(()=>page.evaluate(id=>!!state.annotationEditor&&String(state.annotationEditorIdentity).includes(`:${id}:`),fx.images[i].id)).toBe(true);
    await dialog.locator('#annBoxes select').first().selectOption(vehicle);
    await expect.poll(async()=> (await gt(page))[0]?.label).toBe('vehicle');
    await dialog.locator('[data-ann-mode="select"]').click();
    if(i<19)await page.keyboard.press('ArrowRight');else await dialog.getByRole('button',{name:'保存并继续',exact:true}).click();
    await expect.poll(async()=> (await (await request.get(annotationUrl(fx,i))).json()).boxes[0]?.label).toBe('vehicle');
    await expect(dialog.locator('#ann420Position')).toHaveText(`${Math.min(i+2,20)} / 20`);
  }
  await expect(dialog.locator('#annSaveState')).toHaveText(/^已保存/);
});

test('uncertain save first reads the authoritative version and never blindly repeats POST',async({page,request})=>{
  const fx=await fixture(request),dialog=await open(page,fx);await official(page,dialog);
  await dialog.locator('[data-ann-mode="draw"]').click();await drag(page,[100,100],[220,200]);
  await expect.poll(async()=> (await gt(page)).length).toBe(1);let posts=0,reads=0;
  await page.route(`**${annotationUrl(fx)}`,route=>{
    if(route.request().method()==='GET'){reads++;return route.continue();}
    posts++;return route.abort('failed');
  });
  await page.keyboard.press('Control+s');await expect.poll(()=>posts).toBe(1);
  await expect(dialog.locator('#ann414Save')).toBeEnabled();
  await expect(dialog.locator('#annSaveState')).toContainText('待核验');
  await page.keyboard.press('Control+s');await expect.poll(()=>reads).toBe(1);
  await expect(dialog.locator('#ann414Save')).toBeEnabled();expect(posts).toBe(1);
  expect(await page.evaluate(()=>state.annDirty)).toBe(true);expect(await gt(page)).toHaveLength(1);
});

test('five real open close cycles destroy the official layer and release editor keyboard ownership',async({page,request})=>{
  const fx=await fixture(request,{boxes:boxes(1)});let dialog=await open(page,fx);await official(page,dialog);
  for(let i=0;i<5;i++) {
    await page.evaluate(()=>{window.previousAnnotoriousEditor=state.annotationEditor;});
    await page.keyboard.press('Escape');
    await expect(dialog).toHaveCount(0);await expect(page.locator('svg.a9s-annotationlayer')).toHaveCount(0);
    expect(await page.evaluate(()=>previousAnnotoriousEditor.snapshot().destroyed)).toBe(true);
    for(const key of ['Delete','h','Control+z'])await page.keyboard.press(key);
    if(i<4) {
      await page.locator('.data412-card',{hasText:fx.images[0].filename}).getByRole('button',{name:/^(标注|编辑标注)$/}).click();
      dialog=page.getByRole('dialog',{name:'图片标注工作台',exact:true});await official(page,dialog);
      expect(await gt(page)).toHaveLength(1);
    }
  }
});

test('late first-image GET cannot replace the newer image or resurrect a closed official editor',async({page,request})=>{
  const fx=await fixture(request,{count:2});let seenResolve,release;
  const seen=new Promise(resolve=>seenResolve=resolve),gate=new Promise(resolve=>release=resolve);let delayed=false;
  await page.route(`**${annotationUrl(fx)}`,async route=>{
    if(route.request().method()==='GET'&&!delayed){delayed=true;seenResolve();await gate;}
    await route.continue();
  });
  // Start the actual batch-open interaction; the test deliberately does not
  // await open's ready assertion while the first GET is held.
  const opening=open(page,fx,{batch:true});await seen;
  const dialog=page.getByRole('dialog',{name:'图片标注工作台',exact:true});
  await expect(dialog.locator('#ann420Filename')).toHaveText(fx.images[0].filename);
  await dialog.locator('#ann420Next').click();await expect(dialog.locator('#ann420Filename')).toHaveText(fx.images[1].filename);
  await official(page,dialog);await opening;
  await dialog.locator('[data-ann-mode="select"]').click();
  await page.keyboard.press('Escape');await expect(dialog).toHaveCount(0);
  const late=page.waitForResponse(r=>r.request().method()==='GET'&&r.url().endsWith(annotationUrl(fx)));
  release();await late;await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  await expect(page.locator('svg.a9s-annotationlayer')).toHaveCount(0);
  expect(await page.evaluate(()=>state.annotationEditor?.snapshot()?.destroyed??true)).toBe(true);
});

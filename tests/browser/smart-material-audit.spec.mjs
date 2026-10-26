import {test,expect} from '@playwright/test';

async function setup(page,request,{enabled=true}={}) {
  const project=await(await request.post('/api/projects',{data:{name:`智能分析隔离-${Date.now()}`,labels:[{code:'object',display_name:'目标',color:'#2563eb'}]}})).json();
  await page.route('**/api/v53/bootstrap/snapshot**',route=>{const url=new URL(route.request().url());url.searchParams.set('preferred_project_id',project.id);return route.continue({url:String(url)});});
  await page.addInitScript(()=>localStorage.setItem('mc_train_ui_state_v34',JSON.stringify({page:'数据集'})));
  let creates=0,reviews=[],failCreate=false,task=null;
  const issue={issue_id:'issue-one',image_id:'image-one',related_image_id:null,issue_type:'suspected_annotation',review_token:'token-one',stale:false,review_valid:false,generation:1,evidence:{missing_count:1},inputs:{'image-one':{gt_boxes:[{id:'gt1',label:'object',class_id:0,x1:5,y1:5,x2:40,y2:40}],pred_boxes:[]}}};
  const pageResult={items:[issue],total:1,offset:0,limit:25,review_counts:{confirmed_issue:reviews.length},checks:{},generation:1};
  await page.route(`**/api/v62/projects/${project.id}/smart-material-audit**`,async route=>{
    const url=new URL(route.request().url()),path=url.pathname;
    if(path.endsWith('/status'))return route.fulfill({json:{enabled,max_images:1000,message:enabled?'隔离分析可用':'智能分析未启用，原业务不受影响'}});
    if(path.endsWith('/models'))return route.fulfill({json:{items:[],next_cursor:null}});
    if(path.endsWith('/estimate'))return route.fulfill({json:{count:120,selection_spec:{scope:'FILTERED',filters:{},repository_revision:1}}});
    if(path.endsWith('/review')){const body=route.request().postDataJSON();reviews.push(body);issue.review={...body,actor_id:'controlled-reviewer',reviewed_at:'2026-10-26T01:01:00Z'};issue.review_valid=true;return route.fulfill({json:issue});}
    if(path.endsWith('/findings/issue-one'))return route.fulfill({json:{...issue,generation:task?.attempt||1}});
    if(path.endsWith('/findings'))return route.fulfill({json:{...pageResult,generation:task?.attempt||1,review_counts:{confirmed_issue:reviews.length}}});
    if(route.request().method()==='POST'){creates++;if(failCreate)return route.fulfill({status:503,json:{detail:{message:'隔离引擎不可用'}}});task={task_id:'smart-browser',kind:'MATERIAL_BATCH',project_id:project.id,operation:'SMART_AUDIT',status:'SUCCEEDED',processed:120,total:120,attempt:1,result_ready:true,updated_at:'2026-10-26T01:00:00Z',smart_audit_summary:{checks:{visual_similarity:{status:'completed',checked:120},mistakenness:{status:'not_checked',reason:'无可信预测'}}}};return route.fulfill({status:202,json:task});}
    return route.fallback();
  });
  await page.route(`**/api/v62/projects/${project.id}/material-batches**`,route=>route.fulfill({json:route.request().url().includes('?')?{items:task?[task]:[],next_cursor:null}:task}));
  await page.route('**/materials/image-one/content',route=>route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="80"><rect width="100" height="80" fill="#e2e8f0"/></svg>'}));
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('/');await expect.poll(()=>page.evaluate(()=>Boolean(window.SmartMaterialAuditRuntime&&state.uiReady))).toBe(true);
  return {project,errors,issue,creates:()=>creates,reviews:()=>reviews,fail(){failCreate=true;},task:()=>task};
}

test('smart audit OFF has no startup requests and original material/label pages remain usable',async({page,request})=>{
  const calls=[];page.on('request',req=>{if(req.url().includes('/api/v62/')&&req.url().includes('/smart-material-audit'))calls.push(req.url());});
  const fixture=await setup(page,request,{enabled:false});expect(calls).toHaveLength(0);
  await page.getByRole('button',{name:'智能质量分析',exact:true}).click();
  const panel=page.locator('.smart-material-audit');await expect(panel.locator('[data-status]')).toContainText('未启用');
  await expect(panel.locator('[data-create]')).toBeDisabled();expect(fixture.creates()).toBe(0);
  await page.keyboard.press('Escape');await expect(panel).not.toBeVisible();
  await page.evaluate(()=>setPage('标签管理'));await expect(page.locator('#view')).toContainText('标签');expect(fixture.errors).toEqual([]);
});

test('smart audit retry invalidates delayed old details and second image retry preserves its identity',async({page,request})=>{
  const fixture=await setup(page,request);fixture.issue.related_image_id='image-two';fixture.issue.inputs['image-two']={gt_boxes:[],pred_boxes:[]};
  let secondLoads=0;
  await page.route('**/materials/image-two/content',route=>{secondLoads++;return secondLoads===1?route.fulfill({status:404}):route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="60" height="100"><rect width="60" height="100" fill="blue"/></svg>'});});
  await page.getByRole('button',{name:'智能质量分析',exact:true}).click();const panel=page.locator('.smart-material-audit');await expect(panel.locator('[data-create]')).toBeEnabled();page.once('dialog',dialog=>dialog.accept());await panel.locator('[data-create]').click();
  const failedImage=panel.locator('[data-detail] img').nth(1);await expect(failedImage).toHaveAttribute('alt','原图暂不可用；点击重试');await failedImage.click();await expect.poll(()=>secondLoads).toBe(2);await expect(failedImage).toHaveAttribute('src',/image-two\/content$/);
  let release;const pending=new Promise(resolve=>release=resolve);let started=false;
  await page.route('**/smart-material-audit/smart-browser/findings/issue-one',async route=>{started=true;await pending;await route.fulfill({json:{...fixture.issue,generation:1}});});
  await panel.locator('[data-issue]').click();await expect.poll(()=>started).toBe(true);
  // The original repository clears result_ref immediately, but increments attempt only on claim.
  await page.evaluate(task=>window.SmartMaterialAuditRuntime.onTask({...task,attempt:1,status:'QUEUED',result_ready:false,updated_at:'2026-10-26T02:00:00Z'}),fixture.task());
  release();await expect(panel.locator('[data-review]')).toBeEmpty();await expect(panel.locator('[data-detail]')).toBeEmpty();
  await page.evaluate(task=>window.SmartMaterialAuditRuntime.onTask({...task,task_id:'unselected-task',attempt:3,status:'SUCCEEDED',updated_at:'2026-10-26T03:00:00Z'}),fixture.task());
  await expect(panel.locator('[data-status]')).toContainText('排队中');
  await page.evaluate(task=>window.SmartMaterialAuditRuntime.onTask({...task,attempt:2,status:'RUNNING',result_ready:false,updated_at:'2026-10-26T04:00:00Z'}),fixture.task());
  await expect(panel.locator('[data-review]')).toBeEmpty();expect(fixture.reviews()).toHaveLength(0);expect(fixture.errors).toEqual([]);
});

test('smart audit ON uses original submission owner, real DOM pagination, readonly GT layers and review',async({page,request},testInfo)=>{
  await page.setViewportSize({width:1920,height:1080});const fixture=await setup(page,request);
  await page.getByRole('button',{name:'智能质量分析',exact:true}).click();const panel=page.locator('.smart-material-audit');
  await expect(panel.locator('[data-create]')).toBeEnabled();await panel.locator('[data-estimate]').click();await expect(panel.locator('[data-status]')).toContainText('120 张');
  page.once('dialog',dialog=>dialog.accept());await panel.locator('[data-create]').click();await expect(panel.locator('[data-issues]')).toContainText('疑似错标');expect(fixture.creates()).toBe(1);
  await expect(panel.locator('[data-checks]')).toContainText('未检查');await expect(panel.locator('[data-next]')).toBeDisabled();
  await expect(panel.locator('[data-cancel]')).not.toBeVisible();await expect(panel.locator('[data-retry]')).not.toBeVisible();
  await expect(panel.locator('.sma-world svg')).toHaveCount(1);await panel.getByRole('checkbox',{name:'GT',exact:true}).uncheck();await panel.getByRole('checkbox',{name:'GT',exact:true}).check();
  await panel.getByRole('button',{name:'放大',exact:true}).click();await panel.getByRole('button',{name:'适应窗口'}).click();
  await panel.getByRole('button',{name:'确认存在问题',exact:true}).click();await expect.poll(()=>fixture.reviews().length).toBe(1);expect(fixture.reviews()[0].expected_review_token).toBe('token-one');
  await expect(panel.locator('[data-review]')).toContainText('controlled-reviewer');
  await page.screenshot({path:testInfo.outputPath('smart-audit-1920.png'),fullPage:true});
  await page.setViewportSize({width:1366,height:768});expect(await panel.evaluate(el=>el.scrollWidth<=el.clientWidth+1)).toBe(true);
  await page.screenshot({path:testInfo.outputPath('smart-audit-1366.png'),fullPage:true});
  await page.keyboard.press('Escape');await expect(panel).not.toBeVisible();expect(fixture.errors).toEqual([]);
});

test('smart audit failed admission is recoverable and late status after close cannot reopen a modal',async({page,request})=>{
  const fixture=await setup(page,request);fixture.fail();await page.getByRole('button',{name:'智能质量分析',exact:true}).click();
  const panel=page.locator('.smart-material-audit');await expect(panel.locator('[data-create]')).toBeEnabled();
  await page.evaluate(()=>window.SmartMaterialAuditRuntime.onTask({task_id:'previous-view-task',project_id:state.project.id,operation:'SMART_AUDIT',attempt:1,status:'SUCCEEDED'}));
  await expect(panel.locator('[data-status]')).toContainText('隔离分析可用');
  page.once('dialog',dialog=>dialog.accept());await panel.locator('[data-create]').click();await expect(panel.locator('[data-status]')).toContainText('引擎不可用');await expect(panel.locator('[data-create]')).toBeEnabled();
  await page.keyboard.press('Escape');await expect(panel).not.toBeVisible();
  await page.evaluate(()=>{modal('其他业务','<button>仍可操作</button>');window.SmartMaterialAuditRuntime.onTask({task_id:'late',project_id:state.project.id,operation:'SMART_AUDIT',status:'SUCCEEDED'});});
  await expect(page.getByRole('button',{name:'仍可操作',exact:true})).toBeVisible();await expect(page.locator('.smart-material-audit')).toHaveCount(0);expect(fixture.errors).toEqual([]);
});

test('smart review enters the original annotation editor and records corrected only after its real GT save',async({page,request},testInfo)=>{
  const fixture=await setup(page,request);
  const width=100,height=80,row=300,buffer=Buffer.alloc(54+row*height);buffer.fill(140,54);buffer.write('BM');buffer.writeUInt32LE(buffer.length,2);buffer.writeUInt32LE(54,10);buffer.writeUInt32LE(40,14);buffer.writeInt32LE(width,18);buffer.writeInt32LE(height,22);buffer.writeUInt16LE(1,26);buffer.writeUInt16LE(24,28);buffer.writeUInt32LE(row*height,34);
  const uploaded=await request.post(`/api/projects/${fixture.project.id}/images`,{multipart:{dataset_id:'default',files:{name:'review-original.bmp',mimeType:'image/bmp',buffer}}});expect(uploaded.ok()).toBeTruthy();
  const image=(await uploaded.json()).uploaded[0];fixture.issue.image_id=image.id;fixture.issue.inputs={[image.id]:{gt_boxes:[],pred_boxes:[]}};
  await request.post(`/api/v52/projects/${fixture.project.id}/images/mark-ready`,{data:{image_ids:[image.id]}});
  await page.evaluate(async()=>{state.annotationQueue414=['prior-queue'];await setPage('标签管理');});
  await page.getByRole('button',{name:'智能质量建议与人工复核',exact:true}).click();const panel=page.locator('.smart-material-audit');await expect(panel.locator('[data-create]')).toBeEnabled();page.once('dialog',dialog=>dialog.accept());await panel.locator('[data-create]').click();
  await expect(page.locator('[data-smart-audit-label-summary]')).toContainText('待复核');
  await panel.getByRole('button',{name:'打开原标注工作台'}).click();const dialog=page.getByRole('dialog',{name:'图片标注工作台',exact:true});await expect(dialog).toBeVisible();
  await expect.poll(()=>page.evaluate(()=>Boolean(state.annotationEditor?.snapshot&&!state.annotationHydrating420&&!state.annotationEditor.snapshot().locked))).toBe(true);
  const rect=await dialog.locator('#annImg').boundingBox();await page.mouse.move(rect.x+rect.width*.2,rect.y+rect.height*.2);await page.mouse.down();await page.mouse.move(rect.x+rect.width*.65,rect.y+rect.height*.65,{steps:8});await page.mouse.up();
  await expect.poll(()=>page.evaluate(()=>state.ann.boxes.length)).toBe(1);await expect(dialog.locator('#annStage .a9s-annotation:is([data-id],.selected)')).toHaveCount(1);
  const saved=page.waitForResponse(res=>res.request().method()==='POST'&&res.url().endsWith(`/annotations/${image.id}`));await page.evaluate(()=>saveAnn(true));expect((await saved).ok()).toBeTruthy();
  await expect.poll(()=>fixture.reviews().some(r=>r.verdict==='corrected')).toBe(true);expect(fixture.reviews().at(-1).expected_generation).toBe(1);
  await page.evaluate(()=>closeModal());await expect(dialog).not.toBeVisible();expect(await page.evaluate(()=>state.annotationQueue414)).toEqual([]);
  await page.screenshot({path:testInfo.outputPath('smart-review-original-editor.png'),fullPage:true});expect(fixture.errors).toEqual([]);
});

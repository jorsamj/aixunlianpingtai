import {test,expect} from '@playwright/test';
import {writeFileSync} from 'node:fs';
test.use({hasTouch:true});
for(const width of [1920,1366,768])test(`审核工作台三栏与批选 ${width}`,async({page},info)=>{
 await page.setViewportSize({width,height:1000});await page.goto('/');await expect.poll(()=>page.evaluate(()=>typeof state!=='undefined'&&state.uiReady)).toBe(true);
 const url='data:image/svg+xml,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="960"><rect width="1280" height="960" fill="#dce5ed"/><rect x="100" y="200" width="200" height="500" fill="#6e8299"/><text x="420" y="480" font-size="48">ISOLATED TEST</text></svg>');
 await page.route('**/api/v60/projects/*/annotation-tasks/workbench-test/candidates**',route=>route.fulfill({json:{total:6,review_revision:1,summary:{remaining_reviewable:6,zero:3,with_boxes:3},items:Array.from({length:6},(_,i)=>({image_id:`img-${i}`,filename:`测试图片-${i}.png`,url,width:1280,height:960,status:i%2?'empty':'success',boxes:i%2?[]:[{label:'person',x1:100,y1:200,x2:300,y2:700}]}))}}));
 await page.evaluate(()=>window.reviewAiLabel427('workbench-test'));await expect(page.locator('.ai66-candidate-card')).toHaveCount(6);
 await page.getByRole('button',{name:'切换列表'}).click();await expect(page.locator('#ai60ReviewGrid')).toHaveClass(/ai-review-list/);await page.getByRole('button',{name:'切换网格'}).click();const first=page.locator('.ai66-candidate-card').first();const identity=await first.evaluate(node=>{node.dataset.identity='stable';return node.dataset.identity});await first.locator('input[type=checkbox]').check();await expect(page.locator('#ai60SelectionCount')).toContainText('选中 1 张');expect(await first.getAttribute('data-identity')).toBe(identity);
 await first.locator('.ai-candidate-stage').click();if(width>768)await expect(page.locator('#ai60ReviewInspector')).toContainText('测试图片-0');
 await expect(page.locator('#ai60ApproveRemaining')).toHaveText('通过剩余全部 6 张（整批结束）');expect(await page.locator('.ai-review-page-shell').evaluate(node=>node.scrollWidth<=node.clientWidth+2)).toBe(true);
 await first.locator('input[type=checkbox]').focus();await page.keyboard.press('Space');await expect(first.locator('input[type=checkbox]')).not.toBeChecked();await page.keyboard.press('Space');await expect(first.locator('input[type=checkbox]')).toBeChecked();if(width===768){await first.locator('input[type=checkbox]').tap();await expect(first.locator('input[type=checkbox]')).not.toBeChecked();await first.locator('input[type=checkbox]').tap();await expect(first.locator('input[type=checkbox]')).toBeChecked()}await page.emulateMedia({reducedMotion:'reduce'});await expect(first).toHaveCSS('transition-duration','0s');await page.screenshot({path:info.outputPath(`review-${width}.png`),fullPage:true});
});
test('两万候选任务只渲染当前页并记录交互基线',async({page},info)=>{
 await page.setViewportSize({width:1366,height:1000});await page.goto('/');await expect.poll(()=>page.evaluate(()=>typeof state!=='undefined'&&state.uiReady)).toBe(true);
 let reads=0;const url='data:image/svg+xml,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="960"><rect width="1280" height="960" fill="#dce5ed"/></svg>');
 await page.route('**/api/v60/projects/*/annotation-tasks/large-review/candidates**',route=>{reads++;return route.fulfill({json:{total:20000,review_revision:1,summary:{remaining_reviewable:20000,zero:20000},next_cursor:'24',items:Array.from({length:24},(_,i)=>({image_id:`large-${i}`,filename:`隔离-${i}.jpg`,url,width:1280,height:960,status:'empty',boxes:[]}))}})});
 await page.evaluate(()=>window.reviewAiLabel427('large-review'));await expect(page.locator('.ai66-candidate-card')).toHaveCount(24);expect(reads).toBe(1);
 const result=await page.evaluate(async()=>{const samples=[],heaps=[],longTasks=[],observer=new PerformanceObserver(list=>longTasks.push(...list.getEntries().map(e=>e.duration))),nodes=[...document.querySelectorAll('.ai66-candidate-card')];observer.observe({entryTypes:['longtask']});for(let i=0;i<20;i++){const t=performance.now();window.toggleAiSelection60(`large-${i}`,true);await new Promise(requestAnimationFrame);samples.push(performance.now()-t);if(performance.memory)heaps.push(performance.memory.usedJSHeapSize)}observer.disconnect();samples.sort((a,b)=>a-b);return {scope:'ISOLATED_20000_METADATA_24_RENDERED_NOT_PRODUCTION',input_to_next_frame_p50_ms:samples[10],input_to_next_frame_p95_ms:samples[18],js_heap_bytes:performance.memory?.usedJSHeapSize??null,js_heap_peak_observed_bytes:heaps.length?Math.max(...heaps):null,long_task_count:longTasks.length,max_long_task_ms:longTasks.length?Math.max(...longTasks):0,dom_identity_preserved:nodes.every((node,i)=>document.querySelectorAll('.ai66-candidate-card')[i]===node)}});
 expect(result.dom_identity_preserved).toBe(true);writeFileSync(info.outputPath('review-interaction-baseline.json'),JSON.stringify(result,null,2));await info.attach('review-interaction-baseline.json',{body:JSON.stringify(result,null,2),contentType:'application/json'});
});


test('有歧义筛选及同位置批量保留一个标签，确认直接入库',async({page})=>{
 await page.setViewportSize({width:1366,height:1000});await page.goto('/');
 await expect.poll(()=>page.evaluate(()=>typeof state!=='undefined'&&state.uiReady)).toBe(true);
 const img='data:image/svg+xml,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="960"/>');
 const box=(label,x1,y1,x2,y2)=>({label,x1,y1,x2,y2});
 const person=box('person',10,10,90,90),lying=box('tangzhe',10,10,90,90);
 const items=[
   {image_id:'overlap-1',filename:'重叠1.jpg',url:img,width:1280,height:960,status:'success',boxes:[person,lying,box('fire',200,200,270,270)],manual_review_required:true,review_conflicts:[{labels:['person','tangzhe'],iou:1}]},
   {image_id:'overlap-2',filename:'重叠2.jpg',url:img,width:1280,height:960,status:'success',boxes:[person,lying,box('smoke',300,300,390,390),box('fire',300,300,390,390)],manual_review_required:true,review_conflicts:[{labels:['person','tangzhe'],iou:1},{labels:['smoke','fire'],iou:1}]},
   {image_id:'clean',filename:'无歧义.jpg',url:img,width:1280,height:960,status:'success',boxes:[person]}
 ];
 const writes=[];
 await page.route('**/api/v60/projects/*/annotation-tasks/ambiguity-test/**',async route=>{
   const url=new URL(route.request().url()),method=route.request().method();
   if(method==='POST'&&url.pathname.endsWith('/decisions')){
     const payload=route.request().postDataJSON();writes.push(...payload.decisions);
     expect(payload.commit_selected).toBe(true);expect(payload.commit).toBe(true);
     return route.fulfill({json:{committed_selected:true,applied_images:payload.decisions.length,
       review_revision:2,summary:{remaining_reviewable:2}}});
   }
   const filtered=url.searchParams.get('filter')==='ambiguous'?items.slice(0,2)
     :url.searchParams.get('filter')==='clean_boxes'?items.slice(2):items;
   return route.fulfill({json:{total:filtered.length,review_revision:1,summary:{total:3,with_boxes:1,ambiguous:2},items:filtered}});
 });
 await page.evaluate(()=>{
   state.labels=[...(state.labels||[]).filter(row=>!['person','tangzhe','fire','smoke'].includes(row.code)),
     ...['person','tangzhe','fire','smoke'].map((code,class_id)=>({code,class_id,status:'active'}))];
   return window.reviewAiLabel427('ambiguity-test');
 });
 await page.getByRole('button',{name:/有框 · 无歧义/}).click();
 await expect(page.locator('.ai66-candidate-card')).toHaveCount(1);
 await page.getByRole('button',{name:/有歧义/}).click();
 await expect(page.locator('.ai66-candidate-card')).toHaveCount(2);
 await page.locator('#ai60AmbiguousKeep').selectOption('person');
 await page.getByRole('button',{name:'选择本页'}).click();
 await page.getByRole('button',{name:'预检全部已选图片'}).click();
 await expect(page.locator('.ai-review-ambiguity-preview')).toContainText('可处理 1 / 勾选 2 张');
 await expect(page.locator('.ai-review-ambiguity-preview')).toContainText('跳过 1 张');
 page.once('dialog',dialog=>dialog.accept());
 await page.getByRole('button',{name:'确认消歧并正式入库'}).click();
 await expect.poll(()=>writes.length).toBe(1);
 expect(writes[0].accepted).toBe(true);
 expect(writes[0].boxes.map(row=>row.label)).toEqual(['person','fire']);
 await expect(page.locator('.ai-review-ambiguity-feedback')).toContainText('正式入库 1 张');
});


test('歧义自动模式可填 IoU 阈值，优先置信度且无分数按顺序选框后人工确认入库',async({page})=>{
 await page.setViewportSize({width:1366,height:1000});await page.goto('/');
 await expect.poll(()=>page.evaluate(()=>typeof state!=='undefined'&&state.uiReady)).toBe(true);
 const img='data:image/svg+xml,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="960"/>');
 const box=(label,x1,y1,x2,y2,confidence)=>({label,x1,y1,x2,y2,...(confidence==null?{}:{confidence})});
 const items=[
   {image_id:'confident',filename:'有分数.jpg',url:img,width:1280,height:960,status:'success',manual_review_required:true,boxes:[box('person',0,0,100,100,.3),box('tangzhe',0,0,100,100,.9)]},
   {image_id:'no-score',filename:'无分数.jpg',url:img,width:1280,height:960,status:'success',manual_review_required:true,boxes:[box('person',0,0,100,100),box('tangzhe',15,0,115,100)]}
 ];
 const writes=[];
 await page.route('**/api/v60/projects/*/annotation-tasks/ambiguity-auto/**',route=>{
   const url=new URL(route.request().url());
   if(route.request().method()==='POST'&&url.pathname.endsWith('/decisions')){
     const payload=route.request().postDataJSON();
     expect(payload.commit_selected).toBe(true);expect(payload.commit).toBe(true);
     for(const body of payload.decisions)writes.push({id:body.image_id,body});
     return route.fulfill({json:{committed_selected:true,applied_images:payload.decisions.length,
       review_revision:2,summary:{remaining_reviewable:0}}});
   }
   return route.fulfill({json:{total:2,review_revision:1,summary:{ambiguous:2},items}});
 });
 await page.evaluate(()=>window.reviewAiLabel427('ambiguity-auto'));
 await page.getByRole('button',{name:/有歧义/}).click();
 await page.locator('#ai60AmbiguousMode').selectOption('auto');
 await page.getByRole('button',{name:'选择本页'}).click();
 await page.getByRole('button',{name:'预检全部已选图片'}).click();
 await expect(page.locator('.ai-review-ambiguity-preview')).toContainText('可处理 1 / 勾选 2 张');
 await page.locator('#ai60AmbiguousThreshold').fill('0.70');
 await page.locator('#ai60AmbiguousThreshold').blur();
 await page.getByRole('button',{name:'预检全部已选图片'}).click();
 await expect(page.locator('.ai-review-ambiguity-preview')).toContainText('可处理 2 / 勾选 2 张');
 await expect(page.locator('.ai-review-ambiguity-preview')).toContainText('1 组无可信置信度');
 page.once('dialog',dialog=>dialog.accept());
 await page.getByRole('button',{name:'确认消歧并正式入库'}).click();
 await expect.poll(()=>writes.length).toBe(2);
 expect(writes.every(row=>row.body.accepted===true)).toBe(true);
 expect(writes.find(row=>row.id==='confident').body.boxes.map(b=>b.label)).toEqual(['tangzhe']);
 expect(writes.find(row=>row.id==='no-score').body.boxes.map(b=>b.label)).toEqual(['person']);
 await expect(page.locator('.ai-review-ambiguity-feedback')).toContainText('正式入库 2 张');
});


test('有歧义全选跨页冻结范围，预检与批量正式入库覆盖所有筛选图片且勾选不重绘卡片',async({page})=>{
 await page.goto('/');await expect.poll(()=>page.evaluate(()=>Boolean(state.uiReady))).toBe(true);
 const img='data:image/svg+xml,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480"/>');
 const rows=Array.from({length:30},(_,i)=>({image_id:'amb-cross-'+i,filename:'歧义-'+i+'.jpg',
   url:img,width:640,height:480,status:'success',manual_review_required:true,
   boxes:[{label:'person',x1:20,y1:30,x2:100,y2:150},{label:'tangzhe',x1:20,y1:30,x2:100,y2:150}]}));
 const writes=[],reads=[];
 await page.route('**/api/v60/projects/*/annotation-tasks/cross-page-review/**',route=>{
   const u=new URL(route.request().url()),path=u.pathname,method=route.request().method();
   if(method==='POST'&&path.endsWith('/review-selection'))
     return route.fulfill({json:{selection_id:'a'.repeat(32),count:30,total:30,filter:'ambiguous',review_revision:1}});
   if(method==='GET'&&path.endsWith('/review-selection/'+'a'.repeat(32)+'/candidates')){
     const cursor=Number(u.searchParams.get('cursor')||0);reads.push(cursor);
     return route.fulfill({json:{items:rows.slice(cursor,cursor+20),total:30,filter:'ambiguous',
       review_revision:1,next_cursor:cursor+20<30?String(cursor+20):null}});
   }
   if(method==='POST'&&path.endsWith('/decisions')){
     const payload=route.request().postDataJSON();writes.push(...payload.decisions);
     expect(payload.commit_selected).toBe(true);expect(payload.commit).toBe(true);
     return route.fulfill({json:{committed_selected:true,applied_images:payload.decisions.length,
       review_revision:1+writes.length,summary:{ambiguous:Math.max(0,30-writes.length)}}});
   }
   if(method==='GET'&&path.endsWith('/candidates')){
     const offset=Number(u.searchParams.get('cursor')||0);
     return route.fulfill({json:{items:rows.slice(offset,offset+24),total:30,
       next_cursor:offset+24<30?String(offset+24):null,summary:{ambiguous:30,remaining_reviewable:30},
       review_revision:1}});
   }
   return route.abort();
 });
 await page.evaluate(()=>{
   state.labels=[...(state.labels||[]).filter(row=>!['person','tangzhe'].includes(row.code)),
     ...['person','tangzhe'].map((code,class_id)=>({code,class_id,status:'active'}))];
   return window.reviewAiLabel427('cross-page-review');
 });
 await page.getByRole('button',{name:/有歧义/}).click();
 await expect(page.locator('.ai66-candidate-card')).toHaveCount(24);
 const first=page.locator('.ai66-candidate-card').first();
 await first.evaluate(node=>node.dataset.preserveIdentity='yes');
 await first.locator('.ai-review-select').check();
 await expect(first).toHaveAttribute('data-preserve-identity','yes');
 await page.getByRole('button',{name:'选择全部筛选结果'}).click();
 await expect(page.locator('#ai60SelectionCount')).toContainText('选中 30 张');
 await expect(first).toHaveAttribute('data-preserve-identity','yes');
 await page.locator('#ai60AmbiguousKeep').selectOption('person');
 await page.getByRole('button',{name:'预检全部已选图片'}).click();
 await expect(page.locator('.ai-review-ambiguity-preview')).toContainText('可处理 30 / 勾选 30 张');
 expect(reads).toEqual([0,20]);
 page.once('dialog',dialog=>dialog.accept());
 await page.getByRole('button',{name:'确认消歧并正式入库'}).click();
 await expect.poll(()=>writes.length).toBe(30);
 expect(new Set(writes.map(row=>row.image_id)).size).toBe(30);
 expect(writes.every(row=>row.boxes.length===1&&row.boxes[0].label==='person')).toBe(true);
 await expect(page.locator('.ai-review-ambiguity-feedback')).toContainText('正式入库 30 张');
});

test('无歧义跨页选中二次确认后正式入库，未选中和歧义候选保持原状',async({page})=>{
 await page.goto('/');await expect.poll(()=>page.evaluate(()=>Boolean(state.uiReady))).toBe(true);
 const img='data:image/svg+xml,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480"/>');
 const clean=Array.from({length:3},(_,i)=>({image_id:'clean-scoped-'+i,filename:'无歧义-'+i+'.jpg',
   url:img,width:640,height:480,status:'success',manual_review_required:false,
   boxes:[{label:'person',x1:10,y1:15,x2:100,y2:160}]}));
 const ambiguous={image_id:'amb-not-selected',filename:'有歧义.jpg',url:img,width:640,height:480,
   status:'success',manual_review_required:true,boxes:[{label:'person',x1:10,y1:10,x2:50,y2:50},
     {label:'tangzhe',x1:10,y1:10,x2:50,y2:50}]};
 const decisions=[];
 await page.route('**/api/v60/projects/*/annotation-tasks/clean-scoped-review/**',route=>{
   const u=new URL(route.request().url()),path=u.pathname,method=route.request().method();
   if(method==='POST'&&path.endsWith('/review-selection'))
     return route.fulfill({json:{selection_id:'b'.repeat(32),count:3,total:3,filter:'clean_boxes',review_revision:1}});
   if(method==='GET'&&path.endsWith('/review-selection/'+'b'.repeat(32)+'/candidates'))
     return route.fulfill({json:{items:clean,filter:'clean_boxes',review_revision:1,total:3,next_cursor:null}});
   if(method==='POST'&&path.endsWith('/decisions')){
     const body=route.request().postDataJSON();decisions.push(body);
     return route.fulfill({json:{committed_selected:true,applied_images:body.decisions.length,review_revision:2,summary:{remaining_reviewable:1},task:{status:'AWAITING_CONFIRMATION'}}});
   }
   if(method==='GET'&&path.endsWith('/candidates')){
     const filter=u.searchParams.get('filter'),items=filter==='clean_boxes'?clean:[...clean,ambiguous];
     return route.fulfill({json:{items,total:items.length,review_revision:decisions.length?2:1,
       summary:{clean_boxes:3,ambiguous:1,remaining_reviewable:decisions.length?1:4}}});
   }
   return route.abort();
 });
 await page.evaluate(()=>window.reviewAiLabel427('clean-scoped-review'));
 await page.getByRole('button',{name:/有框 · 无歧义/}).click();
 await page.getByRole('button',{name:'选择全部筛选结果'}).click();
 await expect(page.locator('#ai60ApproveSelected')).toHaveText('确认入库已选 3 张');
 page.once('dialog',dialog=>dialog.accept());
 await page.locator('#ai60ApproveSelected').click();
 await expect.poll(()=>decisions.length).toBe(1);
 expect(decisions[0].decisions.map(row=>row.image_id)).toEqual(clean.map(row=>row.image_id));
 expect(decisions[0].commit).toBe(true);expect(decisions[0].commit_selected).toBe(true);
 expect(decisions[0].accept_unmentioned).toBe(false);
 expect(decisions[0].reject_unmentioned).toBe(false);
 expect(decisions[0].decisions.some(row=>row.image_id===ambiguous.image_id)).toBe(false);
 await expect(page.locator('#ai60SelectionStatus')).toContainText('其他图片仍可继续审核');
});

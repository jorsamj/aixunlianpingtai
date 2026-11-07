import {test,expect} from '@playwright/test';
import {mkdir} from 'node:fs/promises';

async function screenshot(page,name){await mkdir('test-results-pool559',{recursive:true});await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);const form=page.locator('#negativePoolMembers');const rect=await form.boundingBox();expect(rect.x).toBeGreaterThanOrEqual(0);expect(rect.x+rect.width).toBeLessThanOrEqual(page.viewportSize().width);await page.screenshot({path:`test-results-pool559/${name}.png`})}

function bitmap(index){const w=16,h=16,b=Buffer.alloc(54+w*h*3,index%200+30);b.fill(0,0,54);b.write('BM');b.writeUInt32LE(b.length,2);b.writeUInt32LE(54,10);b.writeUInt32LE(40,14);b.writeInt32LE(w,18);b.writeInt32LE(h,22);b.writeUInt16LE(1,26);b.writeUInt16LE(24,28);b.writeUInt32LE(index,54);return b}
async function fixture(page,request,count=201){
 const project=await(await request.post('/api/projects',{data:{name:`Pool members ${Date.now()}`,labels:[{code:'person'}]}})).json();
 const algorithm=(await(await request.post(`/api/v12/projects/${project.id}/algorithms`,{data:{name:'pool algorithm',algorithm_type:'yolo_ultralytics'}})).json()).algorithm;
 const ids=[];
 for(let i=0;i<count;i+=50){
  const form=new FormData();for(let n=i;n<Math.min(count,i+50);n++)form.append('files',new Blob([bitmap(n)],{type:'image/bmp'}),`member-${n}.bmp`);
  const encoded=new Response(form);
  const response=await request.post(`/api/projects/${project.id}/images`,{data:Buffer.from(await encoded.arrayBuffer()),headers:{'Content-Type':encoded.headers.get('content-type')}});
  expect(response.ok(),await response.text()).toBeTruthy();ids.push(...(await response.json()).uploaded.map(x=>x.id));
 }
 // Browser-only FormData serialization uses one consistent boundary.
 expect(ids).toHaveLength(count);
 await page.route('**/api/v53/bootstrap/snapshot**',route=>{const url=new URL(route.request().url());url.searchParams.set('preferred_project_id',project.id);return route.continue({url:String(url)})});
 await page.addInitScript(()=>localStorage.setItem('mc_train_ui_state_v34',JSON.stringify({page:'数据集'})));
 await page.goto('/');await expect.poll(()=>page.evaluate(()=>typeof state!=='undefined'&&state.uiReady&&Boolean(window.NegativePoolRuntime))).toBe(true);
 return {project,algorithm,ids};
}
async function start(page,f){
 await page.evaluate(ids=>window.NegativePoolRuntime.joinSelected(ids),f.ids);
 const form=page.locator('#negativePoolMembers');await form.locator('select').selectOption(f.algorithm.id);await form.locator('[name=confirmed]').check();await form.getByRole('button',{name:'确认',exact:true}).focus();await expect(form.getByRole('button',{name:'确认',exact:true})).toBeFocused();await page.keyboard.press('Enter');return form;
}
test('201 original members use two bounded requests, accurate duplicate counts and no per-image GT reads',async({page,request})=>{
 await page.setViewportSize({width:1920,height:1080});
 const f=await fixture(page,request);let annotationReads=0;const sizes=[];
 page.on('request',r=>{if(r.url().includes('/annotations/'))annotationReads++;if(r.url().endsWith('/negative-pool/members'))sizes.push(r.postDataJSON().image_ids.length)});
 let form=await start(page,f);await expect(form).toContainText('新增 201');expect(sizes).toEqual([200,1]);expect(annotationReads).toBe(0);
 await form.getByRole('button',{name:'关闭',exact:true}).click();form=await start(page,f);await expect(form).toContainText('已存在 201');await expect(form).toContainText('新增 0');await screenshot(page,'members-1920');
});
test('failed batch retries alone; committed timeout is verified without inventing original additions',async({page,request})=>{
 await page.setViewportSize({width:1366,height:900});await page.emulateMedia({reducedMotion:'reduce'});
 const f=await fixture(page,request);let tail=0;const sizes=[];
 await page.route('**/negative-pool/members',async route=>{const body=route.request().postDataJSON();sizes.push(body.image_ids.length);if(body.image_ids.length===1&&tail++===0)return route.fulfill({status:400,json:{detail:'isolated batch conflict'}});return route.continue()});
 const form=await start(page,f);await expect(form).toContainText('失败 1');await expect(form).toContainText('isolated batch conflict');
 await form.getByRole('button',{name:'重试失败 / 核验待确认批次'}).click();await expect(form).toContainText('新增 201');expect(sizes).toEqual([200,1,1]);
 await form.getByRole('button',{name:'关闭',exact:true}).click();await page.unroute('**/negative-pool/members');
 let lost=true;await page.route('**/negative-pool/members',async route=>{if(lost){lost=false;await route.fetch();return route.abort('failed')}return route.continue()});
 const again=await start(page,{...f,ids:[f.ids[0]]});await expect(again).toContainText('待核验 1');await again.getByRole('button',{name:'重试失败 / 核验待确认批次'}).click();await expect(again).toContainText('首次变更数量未提供或无法确认');await expect(again).toContainText('新增 未知');await expect(again).toContainText('已存在 未知');await screenshot(page,'members-1366');
});
test.describe('touch member cancellation',()=>{
test.use({viewport:{width:768,height:900},hasTouch:true});
test('leaving the page permanently stops subsequent member chunks and late refresh',async({page,request})=>{
 const f=await fixture(page,request);let release,started;const held=new Promise(r=>release=r),seen=new Promise(r=>started=r);let calls=0;
 await page.route('**/negative-pool/members',async route=>{calls++;started();await held;return route.continue()});
 const form=await start(page,f);await seen;await form.getByRole('button',{name:'停止后续批次'}).tap();await expect(form).toContainText('已停止后续批次');release();await expect(form).toContainText('新增 200');await expect(form).toContainText('未处理 1');await expect(form.locator('[type=submit]')).not.toBeVisible();expect(calls).toBe(1);await screenshot(page,'members-768');await form.getByRole('button',{name:'关闭',exact:true}).tap();
 let releaseNext,startedNext;const nextHeld=new Promise(r=>releaseNext=r),nextSeen=new Promise(r=>startedNext=r);await page.unroute('**/negative-pool/members');await page.route('**/negative-pool/members',async route=>{calls++;startedNext();await nextHeld;return route.continue()});
 await start(page,f);await nextSeen;await page.evaluate(async()=>{await setPage('算法列表');await setPage('数据集')});const oldText=await page.locator('#negativePoolMembers').textContent();releaseNext();await page.waitForTimeout(700);expect(calls).toBe(2);expect(await page.evaluate(()=>state.page)).toBe('数据集');expect(await page.locator('#negativePoolMembers').textContent()).toBe(oldText);
});
});

test('partial removal clears only committed selections; late upload cannot open a new member dialog',async({page,request},info)=>{
 await page.setViewportSize({width:1366,height:900});
 const f=await fixture(page,request);const base=`/api/v61/projects/${f.project.id}/negative-pool`;
 expect((await request.post(base+'/members',{data:{image_ids:f.ids,algorithm_id:f.algorithm.id}})).ok()).toBe(true);
 await page.evaluate(()=>window.NegativePoolRuntime.open());
 const filters=page.locator('[data-np-form=filters]');await filters.locator('[name=algorithm_id]').selectOption(f.algorithm.id);await filters.getByRole('button',{name:'筛选',exact:true}).click();
 await expect(page.locator('.negative-pool-card')).toHaveCount(48);
 const card=page.locator('.negative-pool-card').first();
 await card.getByText('来源与审核详情',{exact:true}).click();
 await expect(card.locator('.negative-pool-qualification')).toHaveText('待确认');
 await expect(card.locator('.negative-pool-detail')).toContainText('不代表本次目标已确认无目标');
 await page.screenshot({path:info.outputPath('pool-qualification-1366.png')});
 await expect(card.locator('.negative-pool-detail')).not.toContainText('资格：待确认');
 await page.getByRole('button',{name:'全选当前筛选结果',exact:true}).click();await expect(page.locator('#negativePoolSelection')).toContainText('201');
 let failedIds=[];await page.route('**/negative-pool/members',route=>{const body=route.request().postDataJSON();if(body.action==='remove'&&body.image_ids.length===1){failedIds=body.image_ids;return route.fulfill({status:400,json:{detail:'isolated removal failure'}})}return route.continue()});
 await page.locator('.negative-pool-more summary').click();await page.getByRole('button',{name:'移出负样本池',exact:true}).click();const members=page.locator('#negativePoolMembers');await members.getByRole('button',{name:'确认',exact:true}).click();await expect(members).toContainText('已移出 200');await expect(members).toContainText('失败 1');await expect.poll(()=>page.evaluate(()=>window.NegativePoolRuntime.getSelected())).toEqual(failedIds);await expect(page.locator('#negativePoolSelection')).toContainText('已选 1 张');
 await members.getByRole('button',{name:'关闭',exact:true}).click();await page.unroute('**/negative-pool/members');
 let release,started;const held=new Promise(r=>release=r),seen=new Promise(r=>started=r);await page.route(`**/api/projects/${f.project.id}/images`,async route=>{if(route.request().method()!=='POST')return route.continue();started();await held;return route.continue()});
 await page.getByRole('button',{name:'上传到负样本池',exact:true}).click();const upload=page.locator('#negativePoolDialog');await upload.locator('[name=files]').setInputFiles({name:'late.bmp',mimeType:'image/bmp',buffer:bitmap(990)});await upload.getByRole('button',{name:'确认',exact:true}).click();await seen;await upload.getByRole('button',{name:'取消',exact:true}).click();await page.evaluate(async()=>{await setPage('算法列表');await setPage('数据集')});release();await page.waitForTimeout(700);await expect(page.locator('#negativePoolMembers')).toHaveCount(0);
});

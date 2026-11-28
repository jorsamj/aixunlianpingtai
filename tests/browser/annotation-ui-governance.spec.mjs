import {test,expect} from '@playwright/test';

function bmp(w,h){const row=Math.ceil(w*3/4)*4,b=Buffer.alloc(54+row*h);b.fill(125,54);b.write('BM');b.writeUInt32LE(b.length,2);b.writeUInt32LE(54,10);b.writeUInt32LE(40,14);b.writeInt32LE(w,18);b.writeInt32LE(h,22);b.writeUInt16LE(1,26);b.writeUInt16LE(24,28);b.writeUInt32LE(row*h,34);return b;}
async function fixture(page,request){
 const created=await request.post('/api/projects',{data:{name:`ANN UI ${Date.now()} ${Math.random()}`,labels:[{code:'person',display_name:'人员',color:'#cf2345'},{code:'vehicle',display_name:'车辆',color:'#137faa'}]}});expect(created.ok()).toBeTruthy();const project=await created.json(),images=[];
 for(const [i,[w,h]]of [[900,450],[450,900],[640,640]].entries()){const r=await request.post(`/api/projects/${project.id}/images`,{multipart:{dataset_id:'default',files:{name:`ann-ui-${i}.bmp`,mimeType:'image/bmp',buffer:bmp(w,h)}}});expect(r.ok()).toBeTruthy();images.push((await r.json()).uploaded[0]);}
 expect((await request.post(`/api/v52/projects/${project.id}/images/mark-ready`,{data:{image_ids:images.map(i=>i.id)}})).ok()).toBeTruthy();
 await page.route('**/api/v53/bootstrap/snapshot**',route=>{const u=new URL(route.request().url());u.searchParams.set('preferred_project_id',project.id);return route.continue({url:u.toString()});});
 await page.addInitScript(()=>localStorage.setItem('mc_train_ui_state_v34',JSON.stringify({page:'数据集'})));await page.goto('/');await expect.poll(()=>page.evaluate(()=>state.uiReady)).toBe(true);await page.getByRole('button',{name:/已处理/}).click();
 const open=async i=>{await page.locator('.data412-card',{hasText:images[i].filename}).getByRole('button',{name:/^(标注|编辑标注)$/}).click();const dialog=page.getByRole('dialog',{name:'图片标注工作台',exact:true});await expect(dialog.locator('svg.a9s-annotationlayer')).toHaveCount(1);await expect.poll(()=>page.evaluate(()=>!state.annotationHydrating420&&!state.annotationEditorFlight&&!state.annotationEditor.snapshot().locked)).toBe(true);return dialog;};
 return {project,images,open,url:i=>`/api/projects/${project.id}/annotations/${images[i].id}`};
}
async function centered(page){
 // Wait for the original ResizeObserver fit, then sample both rectangles in
 // one layout frame. Separate CDP reads can straddle the native 6px modal entry animation.
 await expect.poll(()=>page.evaluate(()=>{const image=document.getElementById('annImg'),viewport=document.querySelector('.ann-canvas-wrap');return Math.abs(state.annotationEditor.snapshot().scale-Math.min(viewport.clientWidth/image.naturalWidth,viewport.clientHeight/image.naturalHeight));})).toBeLessThan(.0001);
 const offset=await page.evaluate(()=>{const image=document.getElementById('annImg').getBoundingClientRect(),viewport=document.querySelector('.ann-canvas-wrap').getBoundingClientRect();return {x:Math.abs(image.x+image.width/2-viewport.x-viewport.width/2),y:Math.abs(image.y+image.height/2-viewport.y-viewport.height/2)};});
 expect(offset.x).toBeLessThan(2);expect(offset.y).toBeLessThan(2);
}
test('ANN UI has one explicit right review owner and centered image across desktop viewports',async({page,request})=>{
 const fx=await fixture(page,request),dialog=await fx.open(0);const before=await dialog.locator('#ann420ConfirmEmpty').count();
 for(const viewport of [{width:1920,height:1080},{width:1440,height:900},{width:1366,height:768}]){await page.setViewportSize(viewport);await dialog.getByRole('button',{name:'适应窗口',exact:true}).click();await page.screenshot({path:`C:/tmp/annotation-ui-${before?'before':'after'}-${viewport.width}.png`});await centered(page);expect(await dialog.evaluate(el=>el.scrollWidth<=el.clientWidth)).toBe(true);}
 await expect(dialog.locator('#ann420ConfirmEmpty')).toHaveCount(0);await expect(dialog.locator('#ann420SaveReview')).toHaveText('确认本图无目标');await expect(dialog.locator('#ann420SaveReview')).toBeDisabled();
 await dialog.locator('#ann420ReviewPanel summary').click();await dialog.locator('#ann420PendingLabels input').first().check();await dialog.locator('#ann420SaveReview').click();await expect.poll(async()=>(await(await request.get(fx.url(0))).json()).annotation_state).toBe('confirmed_empty');await expect(dialog.locator('#ann420SaveReview')).toHaveText('✓ 已确认负样本');await dialog.getByRole('button',{name:'关闭',exact:true}).click();await fx.open(0);await expect(dialog.locator('#ann420SaveReview')).toHaveText('✓ 已确认负样本');
});
test('ANN landscape portrait square fit and manual viewport survive resize using original editor',async({page,request})=>{
 const fx=await fixture(page,request);for(let i=0;i<3;i++){const dialog=await fx.open(i);await centered(page);await dialog.getByRole('button',{name:'100%',exact:true}).click();await dialog.locator('[data-ann-mode="pan"]').click();const viewport=await dialog.locator('.ann-canvas-wrap').boundingBox();await page.mouse.move(viewport.x+100,viewport.y+100);await page.mouse.down();await page.mouse.move(viewport.x+125,viewport.y+120,{steps:4});await page.mouse.up();const transform=await dialog.locator('#annStage').getAttribute('style');const before=await page.evaluate(()=>state.annotationEditor.snapshot());await page.setViewportSize({width:1440+i*20,height:900});const after=await page.evaluate(()=>state.annotationEditor.snapshot());expect(after.scale).toBeCloseTo(before.scale,4);await expect(dialog.locator('#annStage')).toHaveAttribute('style',transform);await dialog.getByRole('button',{name:'适应窗口',exact:true}).click();await centered(page);await dialog.getByRole('button',{name:'关闭',exact:true}).click();}
});

test('ANN formal label color follows management edit in class list object and official projection',async({page,request})=>{
 const fx=await fixture(page,request),dialog=await fx.open(0),rect=await dialog.locator('#annImg').boundingBox();
 await page.mouse.move(rect.x+rect.width*.2,rect.y+rect.height*.2);await page.mouse.down();await page.mouse.move(rect.x+rect.width*.4,rect.y+rect.height*.4,{steps:6});await page.mouse.up();await expect.poll(()=>page.evaluate(()=>state.ann.boxes.length)).toBe(1);
 await expect(dialog.locator('[data-ann-label-code="person"] i')).toHaveCSS('background-color','rgb(207, 35, 69)');await expect(dialog.locator('#annBoxes i')).toHaveCSS('background-color','rgb(207, 35, 69)');
 const classId=await page.evaluate(()=>state.labels.find(l=>l.code==='person').class_id);await page.evaluate(id=>window.openLabel414(id),classId);const edit=page.getByRole('dialog',{name:'编辑标签',exact:true});await edit.locator('#label414Color').fill('#27a35c');await edit.getByRole('button',{name:'保存',exact:true}).click();await expect(edit).toHaveCount(0);
 await expect(dialog.locator('[data-ann-label-code="person"] i')).toHaveCSS('background-color','rgb(39, 163, 92)');await expect(dialog.locator('#annBoxes i')).toHaveCSS('background-color','rgb(39, 163, 92)');await expect(dialog.locator('.a9s-annotation .a9s-inner')).toHaveCSS('stroke','rgb(39, 163, 92)');
 await page.keyboard.press('Control+s');await dialog.getByRole('button',{name:'关闭',exact:true}).click();await fx.open(0);await expect(dialog.locator('#annBoxes i')).toHaveCSS('background-color','rgb(39, 163, 92)');
});

test('ANN broken source hides official boxes and retries the original image without GT writes',async({page,request})=>{
 const fx=await fixture(page,request),card=page.locator('.data412-card',{hasText:fx.images[0].filename});
 const original=(await(await request.get(fx.url(0))).json()).image.url,sourceUrl=new URL(original,page.url());sourceUrl.searchParams.set('ann-ui-broken','1');const source=sourceUrl.pathname+sourceUrl.search;let broken=true,posts=0;
 page.on('request',req=>{if(req.method()==='POST'&&req.url().endsWith(fx.url(0)))posts++;});
 // Only the image URL projection is controlled; formal GT GET/save stay real.
 await page.route(`**${fx.url(0)}`,async route=>{const response=await route.fetch(),body=await response.json();body.image.url=source;return route.fulfill({response,json:body});});
 await page.route(url=>url.pathname===sourceUrl.pathname&&url.searchParams.get('ann-ui-broken')==='1',route=>broken?route.fulfill({status:200,contentType:'image/bmp',body:Buffer.from('broken source bytes')}):route.continue());
 await card.getByRole('button',{name:/^(标注|编辑标注)$/}).click();const dialog=page.getByRole('dialog',{name:'图片标注工作台',exact:true});await expect(dialog.locator('[data-ann-editor-status]')).toContainText('读取失败');await expect(dialog.locator('.a9s-annotationlayer')).toHaveCount(0);broken=false;await dialog.locator('[data-ann-editor-retry]').click();await expect(dialog.locator('svg.a9s-annotationlayer')).toHaveCount(1);expect(posts).toBe(0);

});

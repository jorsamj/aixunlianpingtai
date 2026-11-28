// Run from frontend with the disposable tools/test_vue_ai_review_server.py on 8030.
// Real Chrome, auth, APIs, CandidateStore and offline Annotorious. No model execution.
import {chromium,expect} from '@playwright/test';
import {mkdir,writeFile} from 'node:fs/promises';
const base=process.env.MC_AI_ACCEPTANCE_ORIGIN||'http://127.0.0.1:8030',out='../test-results/p1or-real-entry';
await mkdir(out,{recursive:true});
const browser=await chromium.launch({channel:'chrome'}),page=await browser.newPage({viewport:{width:1920,height:1080}});
const errors=[],writes=[],assets=[],steps=[];let project;
page.on('pageerror',error=>errors.push(error.message));
page.on('request',request=>{if(request.url().includes('/api/')&&request.method()!=='GET'&&!request.url().includes('/auth/'))writes.push({method:request.method(),path:new URL(request.url()).pathname})});
page.on('response',response=>{if(response.url().includes('/static/vendor/annotorious/'))assets.push({path:new URL(response.url()).pathname,status:response.status()})});
const boxes=()=>page.evaluate(()=>structuredClone(state.ai60Edit?.boxes||[]));
async function drag(from,to,selector='.vue-annotation-editor .editor-world img'){
 const image=page.locator(selector),rect=await image.boundingBox(),size=await image.evaluate(img=>({w:img.naturalWidth,h:img.naturalHeight}));
 const point=([x,y])=>({x:rect.x+x*rect.width/size.w,y:rect.y+y*rect.height/size.h}),a=point(from),b=point(to);
 await page.mouse.move(a.x,a.y);await page.mouse.down();await page.mouse.move(b.x,b.y,{steps:8});await page.mouse.up();
}
async function ready(){await expect(page.locator('.vue-annotation-editor svg.a9s-annotationlayer')).toHaveCount(1);await expect.poll(()=>page.evaluate(()=>!!state.ai60Edit?.editor&&!state.ai60Edit?.pending)).toBe(true);await expect(page.getByRole('button',{name:'画框',exact:true})).toBeEnabled()}
async function screenshots(name){for(const [width,height] of [[1920,1080],[1366,768],[768,1024]]){await page.setViewportSize({width,height});await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:`${out}/${name}-${width}.png`,fullPage:true,animations:'disabled'})}await page.setViewportSize({width:1920,height:1080})}
try{
 await page.goto(base+'/');await expect(page).toHaveURL(/login/);await page.locator('#loginUsername').fill('vue-acceptance');await page.locator('#loginPassword').fill('isolated-test-only');await page.locator('#loginSubmit').click();await expect(page.locator('#authUsername')).toHaveText('vue-acceptance');
 await page.goto(base+'/?vue_ai_tasks=1&vue_ai_review=1');await expect.poll(()=>page.evaluate(()=>state.uiReady)).toBe(true);
 project=await page.evaluate(()=>state.project.id);const task='isolated-vue-ai-review',root=`${base}/api/v60/projects/${project}/annotation-tasks/${task}`;
 await page.evaluate(()=>window.setPage('AI标注任务正式浏览'));await expect(page.locator('.ai-tasks')).toContainText(task);await page.getByRole('button',{name:'详情',exact:true}).first().click();await expect(page.getByRole('dialog',{name:'AI 标注任务详情'})).toContainText('等待确认');await page.getByRole('button',{name:'审核原候选',exact:true}).click();await expect(page.locator('.candidate')).toHaveCount(3);steps.push('index-auth-task-detail-review');
 const initial=await (await page.request.get(root+'/candidates')).json();expect(initial.items.every(row=>!row.gt_committed)).toBe(true);
 await screenshots('review');await page.getByRole('button',{name:'编辑候选框',exact:true}).first().click();await ready();
 await page.getByRole('button',{name:'画框',exact:true}).click();await drag([300,100],[420,220]);await expect.poll(async()=>(await boxes()).length).toBe(2);
 const created=(await boxes())[1];await page.getByRole('button',{name:'选择 / 编辑',exact:true}).click();await drag([360,160],[360,160]);await expect.poll(()=>page.evaluate(()=>state.ai60Edit.editor.snapshot().selectedId)).toBe(created.id);
 await drag([360,160],[380,180]);await expect.poll(async()=>(await boxes())[1].x1).toBeCloseTo(320,0);
 await drag([440,240],[460,260]);await expect.poll(async()=>(await boxes())[1].x2).toBeCloseTo(460,0);await expect.poll(async()=>(await boxes())[1].y2).toBeCloseTo(260,0);
 await page.locator('.editor-objects article').nth(1).locator('select').selectOption('vehicle');await expect.poll(async()=>(await boxes())[1].label).toBe('vehicle');
 await page.getByRole('button',{name:'删除第2个框',exact:true}).click();await expect.poll(async()=>(await boxes()).length).toBe(1);await page.getByRole('button',{name:'撤销',exact:true}).click();await expect.poll(async()=>(await boxes()).length).toBe(2);
 await page.getByRole('button',{name:'放大',exact:true}).click();await page.getByRole('button',{name:'平移',exact:true}).click();await drag([50,350],[80,370]);await page.getByRole('button',{name:'适应窗口',exact:true}).click();steps.push('real-offline-draw-move-resize-reclass-delete-undo-zoom-pan');await screenshots('editor');
 const expected=await boxes();await page.getByRole('button',{name:'保存候选修改',exact:true}).click();await expect.poll(()=>page.evaluate(()=>state.ai60Review.seen.get('ai-review-material-000')?.draft_revision)).toBe(1);
 const saved=await (await page.request.get(root+'/candidates/ai-review-material-000')).json();expect(saved.item.boxes).toHaveLength(2);expect(saved.item.gt_committed).not.toBe(true);for(const key of ['x1','y1','x2','y2'])expect(saved.item.boxes[1][key]).toBeCloseTo(expected[1][key],1);
 const gtUrl=`${base}/api/projects/${project}/annotations/ai-review-material-000`,gtBefore=await (await page.request.get(gtUrl)).json();expect(gtBefore.boxes||gtBefore.annotation?.boxes||[]).toHaveLength(0);steps.push('draft-http-roundtrip-no-GT');
 await page.getByRole('button',{name:'返回审核列表',exact:true}).click();await expect(page.locator('svg.a9s-annotationlayer')).toHaveCount(0);await page.getByRole('button',{name:'编辑候选框',exact:true}).nth(1).click();await ready();await page.getByRole('button',{name:'返回审核列表',exact:true}).click();steps.push('switch-image-destroy');
 await page.reload();await expect.poll(()=>page.evaluate(()=>state.uiReady)).toBe(true);await expect(page.locator('.candidate')).toHaveCount(3);await page.getByRole('button',{name:'编辑候选框',exact:true}).first().click();await ready();expect((await boxes()).length).toBe(2);await page.getByRole('button',{name:'返回审核列表',exact:true}).click();steps.push('route-refresh-draft-restored');
 // Switch presentation through the original Owner; old official editor must still work.
 await page.getByRole('button',{name:'使用原工作台',exact:true}).click();await expect(page.locator('.ai66-candidate-card')).toHaveCount(3);await page.locator('.ai66-candidate-card .ai-candidate-stage').first().click();await page.locator('#ai60ReviewInspector').getByRole('button',{name:'编辑候选框',exact:true}).click();await expect(page.locator('#ai60EditStage svg.a9s-annotationlayer')).toHaveCount(1);await page.getByRole('button',{name:'画框',exact:true}).click();await drag([60,280],[150,360],'#ai60EditImg');await expect.poll(async()=>(await boxes()).length).toBe(3);await page.getByRole('button',{name:'保存候选修改',exact:true}).click();await expect(page.locator('#ai60EditStatus')).toContainText('版本 2');await page.getByRole('button',{name:'返回列表',exact:true}).click();steps.push('legacy-original-official-editor-saved');
 // Explicit isolated approval is the only step allowed to write fixture GT.
 page.on('dialog',dialog=>dialog.accept());await page.locator('.ai-review-select').first().check();await page.locator('#ai60ApproveSelected').click();await expect(page.locator('.ai66-candidate-card.gt-committed')).toHaveCount(1);const gtAfter=await (await page.request.get(gtUrl)).json();expect(gtAfter.boxes||gtAfter.annotation?.boxes||[]).toHaveLength(3);steps.push('original-explicit-approve-GT');
 expect(errors).toEqual([]);expect(assets.every(row=>row.status===200)).toBe(true);expect(await page.locator('script[src*="/static/vendor/annotorious/annotorious.js"]').count()).toBe(1);
 await writeFile(`${out}/receipt.json`,JSON.stringify({scope:'isolated synthetic CandidateStore/local JPEG, real index/auth/API/offline official plugin; lifespan/execution/SDK off',project,steps,errors,writes,assets},null,2));console.log(JSON.stringify({passed:true,steps,errors}));
}catch(error){await writeFile(`${out}/failure.json`,JSON.stringify({message:error.message,steps,errors,writes,assets},null,2));await page.screenshot({path:`${out}/failure.png`,fullPage:true,timeout:5000}).catch(()=>{});throw error}finally{await browser.close()}

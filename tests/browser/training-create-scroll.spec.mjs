import {test, expect} from '@playwright/test';

const viewports = [
  {width:1920,height:1080}, {width:1366,height:768}, {width:1280,height:720},
  {width:760,height:820}, {width:1093,height:614, equivalentZoom:'1366×768 / 125%'},
];

async function fixture(page, request) {
  const project = await (await request.post('/api/projects', {data:{name:`滚动回归-${Date.now()}`,labels:Array.from({length:60},(_,i)=>({code:`class_${i}`,display_name:`训练类别 ${i} 较长名称`}))}})).json();
  const result = await (await request.post(`/api/v12/projects/${project.id}/algorithms`, {data:{name:'弹窗滚轮隔离算法',industry:'测试',algorithm_type:'yolo_ultralytics'}})).json();
  await page.route('**/api/v53/bootstrap/snapshot**',async route=>{const url=new URL(route.request().url());url.searchParams.set('preferred_project_id',project.id);await route.fallback({url:String(url)});});
  await page.route('**/api/training_options**',route=>route.fulfill({json:{targets:[{id:'scroll-cpu',name:'隔离CPU',type:'local',framework:'ultralytics',status:'ready',algorithms:[{key:'yolo_detect',name:'Detect',base_model:'yolo11n.pt',default_epochs:1,default_imgsz:640,default_batch:1}],base_models:[{value:'yolo11n.pt',label:'YOLO11n',model_status:'FOUND'}]}]}}));
  await page.route('**/api/system/recommendation',route=>route.fulfill({json:{device:'cpu',batch:1,workers:0}}));
  await page.route('**/api/v62/training-devices',async route=>{await new Promise(resolve=>setTimeout(resolve,350));await route.fulfill({json:{recommended:'cpu',options:[{id:'cpu',label:'CPU',available:true}]}});});
  let creates=0;
  await page.route('**/train/start',route=>{creates++;return route.fulfill({status:409,json:{detail:'滚动验收禁止启动训练'}});});
  await page.addInitScript(()=>localStorage.setItem('mc_train_ui_state_v34',JSON.stringify({page:'算法列表'})));
  await page.goto('/');
  await expect.poll(()=>page.evaluate(()=>Boolean(window.TrainingLabelRuntime && state.uiReady))).toBe(true);
  const open=async()=>{
    await page.locator('.alg428-card',{hasText:'弹窗滚轮隔离算法'}).getByRole('button',{name:'训练',exact:true}).click();
    const dialog=page.getByRole('dialog',{name:/创建训练任务/});
    await expect(dialog.locator('[data-training-label-code]')).toHaveCount(60);
    return dialog;
  };
  return {open, creates:()=>creates,algorithmId:result.algorithm.id};
}

async function bounds(dialog) {
  return dialog.evaluate(node=>{
    const card=node.matches('.modal-card')?node:node.querySelector('.modal-card');
    const r=card.getBoundingClientRect(),head=card.querySelector('.modal-head').getBoundingClientRect(),foot=card.querySelector('.train428-footer').getBoundingClientRect(),layout=card.querySelector('.train-create-layout').getBoundingClientRect();
    return {left:r.left+28,right:r.right-28,top:Math.max(head.bottom+8,layout.top+2),bottom:Math.min(foot.top-8,r.bottom-10,layout.bottom-2)};
  });
}
async function wheel(page,dialog,delta,labels=false) {
  const b=await bounds(dialog);let x=b.left+8,y=b.top+12;
  if(labels){
    const r=await dialog.locator('#trainUiLabelSlot').boundingBox();
    if(r&&r.y<b.bottom&&r.y+r.height>b.top){x=Math.min(b.right-5,Math.max(b.left+5,r.x+r.width/2));y=(Math.max(b.top,r.y)+Math.min(b.bottom,r.y+r.height))/2;}
  }
  await page.mouse.move(x,y);await page.mouse.wheel(0,delta);
  await page.waitForTimeout(55); // Native compositor scroll must settle before measuring hit targets.
}
async function usable(dialog,target) {
  const r=await target.boundingBox();if(!r)return false;const b=await bounds(dialog);
  if(r.y<b.top||r.y+r.height>b.bottom)return false;
  return target.evaluate(node=>{const r=node.getBoundingClientRect();return node.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));});
}
async function reach(page,dialog,target,{labels=false}={}) {
  for(let i=0;i<45;i++){
    if(await usable(dialog,target))return;
    const r=await target.boundingBox(),b=await bounds(dialog);
    await wheel(page,dialog,r&&r.y<b.top?-220:220,labels);
  }
  expect(await usable(dialog,target),'actual wheel must expose an unobscured usable configuration').toBe(true);
}
async function top(page,dialog) {for(let i=0;i<4;i++)await wheel(page,dialog,-3000);}

for(const viewport of viewports)test(`training configuration wheel remains usable ${viewport.width}x${viewport.height}`,async({page,request},testInfo)=>{
  test.setTimeout(90_000);await page.setViewportSize({width:viewport.width,height:viewport.height});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const f=await fixture(page,request);let dialog=await f.open();
  await top(page,dialog);
  await reach(page,dialog,dialog.locator('[data-mode="custom"]'));
  await dialog.locator('[data-mode="custom"]').click();
  await top(page,dialog);
  const bottom=dialog.locator('.train-v3-all-settings');
  await reach(page,dialog,bottom,{labels:true});
  await dialog.screenshot({path:testInfo.outputPath('wheel-after-labels.png')});
  await reach(page,dialog,dialog.locator('[data-training-label-code="class_59"]').locator('..'),{labels:true});
  await reach(page,dialog,bottom);
  await bottom.click();
  const settings=page.getByRole('dialog',{name:/训练配置设置/});await expect(settings).toBeVisible();
  await settings.getByRole('button',{name:'应用配置',exact:true}).click();
  for(const mode of ['quick','full','complex','custom']){
    await top(page,dialog);await reach(page,dialog,dialog.locator(`[data-mode="${mode}"]`));await dialog.locator(`[data-mode="${mode}"]`).click();
    const details=dialog.locator('.train-create-split-details');await reach(page,dialog,details.locator('summary'));await details.locator('summary').click();
    await reach(page,dialog,dialog.locator('#trV3Validation'));await expect(dialog.locator('#trV3Validation')).toBeEditable();
    await reach(page,dialog,details.locator('summary'));await details.locator('summary').click();
    await reach(page,dialog,mode==='custom'?bottom:dialog.locator('.train-v3-mode-brief'));
    await expect(dialog.locator('.train-ui-submit')).toBeInViewport();
    await expect(dialog.locator('.modal-head')).toBeInViewport();
    for(const selector of ['.modal-head','.train428-footer']){const r=await dialog.locator(selector).boundingBox();expect(r.y).toBeGreaterThanOrEqual(0);expect(r.y+r.height).toBeLessThanOrEqual(page.viewportSize().height);}
  }
  await dialog.locator('.train-ui-cancel').click();dialog=await f.open();await top(page,dialog);
  await reach(page,dialog,dialog.locator('[data-mode="custom"]'));await dialog.locator('[data-mode="custom"]').click();
  await page.setViewportSize({width:Math.max(720,viewport.width-80),height:Math.max(550,viewport.height-90)});
  await reach(page,dialog,dialog.locator('.train-v3-all-settings'),{labels:true});
  const owners=await dialog.evaluate(node=>[...node.querySelectorAll('*')].filter(el=>['auto','scroll'].includes(getComputedStyle(el).overflowY)&&el.scrollHeight>el.clientHeight+2).map(el=>el.className));
  expect(owners).toEqual(['train-create-layout']);
  expect(f.creates()).toBe(0);expect(errors).toEqual([]);
});

import {test, expect} from '@playwright/test';

test('report and evaluation use bounded dialogs at desktop and mobile sizes', async ({page}) => {
  await page.goto('/');
  await expect.poll(() => page.evaluate(() => state.uiReady)).toBe(true);
  for (const [width,height] of [[1920,1080],[1440,900],[1366,768],[375,812]]) {
    await page.setViewportSize({width,height});
    for (const kind of ['training-report-workspace','evaluation429']) {
      await page.evaluate(kind => window.modal('真实布局验收', `<section class="quality-workspace ${kind}"><button class="icon" aria-label="下载报告">↓</button><div style="height:1400px">报告正文</div></section>`,true),kind);
      const card=page.locator('#modal .modal-card');
      const box=await card.boundingBox();
      expect(box.width).toBeLessThanOrEqual(Math.min(1120,width-24));
      expect(box.height).toBeLessThanOrEqual(height*.86+1);
      expect(box.x).toBeGreaterThanOrEqual(12);
      expect(box.y).toBeGreaterThanOrEqual(12);
      const close=page.locator('#modal .modal-head .icon');
      await expect(close).toBeVisible();
      await expect(close).toBeFocused();
      await page.keyboard.press('Shift+Tab');
      await expect(page.locator('#modalBody button')).toBeFocused();
      await page.keyboard.press('Tab');
      await expect(close).toBeFocused();
      await page.keyboard.press('Escape');
      await expect(page.locator('#modal')).toBeHidden();
    }
  }
});

test('one accessible icon tooltip follows the pointer and clears on Escape and dialog close', async ({page}) => {
  await page.goto('/');
  await expect.poll(() => page.evaluate(() => state.uiReady)).toBe(true);
  await page.evaluate(() => window.modal('提示验收','<section class="quality-workspace"><button class="icon" aria-label="下载报告">↓</button></section>',true));
  const icon=page.locator('#modalBody button');
  await icon.hover();
  const tip=page.getByRole('tooltip');
  await expect(tip).toBeVisible();
  await expect(tip).toHaveText('下载报告');
  const start=await tip.boundingBox();
  const anchor=await icon.boundingBox();
  await page.mouse.move(anchor.x+anchor.width/2+4,anchor.y+anchor.height/2+2);
  await expect.poll(async () => (await tip.boundingBox())?.x).not.toBe(start.x);
  await page.keyboard.press('Escape');
  await expect(tip).toBeHidden();
  await page.evaluate(() => window.modal('键盘提示验收','<section class="quality-workspace"><button class="icon" aria-label="下载报告">↓</button></section>',true));
  await icon.focus();
  await expect(tip).toBeVisible();
  await page.evaluate(() => closeModal());
  await expect(tip).toBeHidden();
  await expect(page.locator('[role="tooltip"]')).toHaveCount(1);
});

test('core snapshot paints while background bootstrap status is pending and records ten refreshes', async ({page},testInfo) => {
  await page.route('**/api/v53/bootstrap/status', route => route.fulfill({json:{status:'running',stage:'隔离后台恢复',progress:30}}));
  await page.addInitScript(() => {
    window.__snapshotParsing=[];
    const original=Response.prototype.json;
    Response.prototype.json=async function(...args){if(!this.url.includes('/api/v53/bootstrap/snapshot'))return original.apply(this,args);const text=await this.text();const start=performance.now();try{return JSON.parse(text)}finally{window.__snapshotParsing.push(performance.now()-start)}};
  });
  const rows=[];
  for(let index=0;index<10;index++){
    const started=Date.now();
    await page.goto('/');
    await expect.poll(() => page.evaluate(() => state.uiReady)).toBe(true);
    const interactiveMs=Date.now()-started;
    rows.push(await page.evaluate(({index,interactiveMs})=>{
      const entry=performance.getEntriesByType('resource').find(x=>x.name.includes('/api/v53/bootstrap/snapshot'));
      return {index,interactiveMs,url:entry?.name,ttfbMs:entry?.responseStart-entry?.requestStart,downloadMs:entry?.responseEnd-entry?.responseStart,durationMs:entry?.duration,bytes:entry?.encodedBodySize,decodedBytes:entry?.decodedBodySize,jsonParseMs:window.__snapshotParsing[0],serverTiming:entry?.serverTiming?.map(x=>({name:x.name,duration:x.duration})),snapshotRequests:performance.getEntriesByType('resource').filter(x=>x.name.includes('/api/v53/bootstrap/snapshot')).length};
    },{index,interactiveMs}));
    expect(rows.at(-1).snapshotRequests).toBe(1);
  }
  console.log('[startup-measurements]',JSON.stringify(rows));
  await testInfo.attach('startup-measurements.json',{body:JSON.stringify(rows,null,2),contentType:'application/json'});
});

test('task completion invalidates both snapshot and recent algorithm owner counts',async({page})=>{
  await page.goto('/');await expect.poll(()=>page.evaluate(()=>state.uiReady)).toBe(true);
  await expect.poll(()=>page.evaluate(()=>window.AlgorithmListRuntime.state().inflight)).toBe(false);
  let successes=1,requests=0;
  await page.route('**/api/v12/projects/*/algorithms',route=>{requests++;return route.fulfill({json:{items:[{id:'count-algorithm',name:'成功次数验收',successful_training_count:successes,versions:[]}]}})});
  await page.route('**/api/projects/*/jobs',route=>route.fulfill({json:[{id:'count-job',asset_algorithm_id:'count-algorithm',task_status:successes===1?'RUNNING':'SUCCEEDED',status:successes===1?'running':'done'}]}));
  await page.evaluate(()=>window.AlgorithmListRuntime.refresh({render:true}));
  expect(await page.evaluate(()=>state.algorithms[0].successful_training_count)).toBe(1);
  successes=2;
  await page.evaluate(async()=>{window.setPage('训练任务');await window.TrainingTaskRuntime.refresh({render:false,force:true});});
  const before=requests;
  await page.evaluate(()=>window.setPage('算法列表'));
  await expect.poll(()=>page.evaluate(()=>state.algorithms[0]?.successful_training_count)).toBe(2);
  expect(requests).toBeGreaterThan(before);
});

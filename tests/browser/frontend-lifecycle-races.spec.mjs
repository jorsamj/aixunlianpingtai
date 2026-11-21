import {test, expect} from '@playwright/test';

const viewports = [
  {width: 390, height: 844},
  {width: 1024, height: 768},
  {width: 1920, height: 1080},
];

for (const viewport of viewports) {
  test(`slow first snapshot has one startup owner at ${viewport.width}px`, async ({page}) => {
    await page.setViewportSize(viewport);
    let snapshots = 0;
    await page.route('**/api/v53/bootstrap/snapshot**', async route => {
      snapshots++;
      // Real browser timing, without replacing server snapshot with fake data.
      await new Promise(resolve => setTimeout(resolve, 5000));
      await route.continue();
    });
    await page.goto('/');
    await expect(page.locator('#view [data-boot-card="1"]')).toBeVisible();
    await page.waitForTimeout(3200); // intentionally crosses the old 3s timer
    await expect(page.locator('#view [data-boot-card="1"]')).toHaveCount(1);
    await expect.poll(() => page.evaluate(() => state.uiReady), {timeout: 20000}).toBe(true);
    await expect(page.locator('#view [data-boot-card="1"]')).toHaveCount(0);
    await page.waitForTimeout(7200); // intentionally crosses the old 10s timer
    await expect(page.locator('#view [data-boot-card="1"]')).toHaveCount(0);
    expect(snapshots).toBe(1);
  });
}

test('failed first core snapshot leaves the retry screen in charge of #view', async ({page}) => {
  await page.route('**/api/v53/bootstrap/snapshot**', route => route.fulfill({
    status: 500,
    contentType: 'application/json',
    body: JSON.stringify({detail: '隔离测试：核心接口失败'}),
  }));
  await page.goto('/');
  await expect(page.locator('#view .boot413-card.error')).toContainText('平台核心页面暂不可用');
  await expect(page.locator('#view button')).toContainText(['重新加载', '刷新页面']);
  await expect.poll(() => page.evaluate(() => state.uiReady)).toBe(false);
  await page.waitForTimeout(1100);
  await expect(page.locator('#view [data-algorithm-list-owner]')).toHaveCount(0);
  await expect(page.locator('#view .boot413-card.error')).toBeVisible();
});

test('old page refresh cannot destroy B form after navigation or A→B→A', async ({page}) => {
  await page.goto('/');
  await expect.poll(() => page.evaluate(() => state.uiReady), {timeout: 20000}).toBe(true);
  let release;
  const held = new Promise(resolve => {release = resolve;});
  let started;
  const requested = new Promise(resolve => {started = resolve;});
  await page.route(/\/api\/v53\/bootstrap\/snapshot(?:\?.*)?$/, async route => {
    if (new URL(route.request().url()).searchParams.get('refresh') !== 'true') return route.continue();
    started();
    await held;
    await route.continue();
  });
  // Algorithm/Training have their own focused refresh capture owners; model
  // configuration deliberately exercises the global authoritative button.
  await page.evaluate(() => window.setPage('模型配置'));
  expect(await page.evaluate(() => typeof document.getElementById('refreshBtn')?.onclick)).toBe('function');
  await page.locator('#refreshBtn').click();
  await expect.poll(() => page.locator('#refreshBtn').textContent(), {timeout: 2000}).toContain('刷新中');
  await Promise.race([requested, new Promise((_, reject) => setTimeout(() => reject(new Error('未触发权威刷新请求')), 10000))]);
  await page.evaluate(() => window.setPage('训练任务'));
  await page.evaluate(() => {
    const field = document.createElement('input');
    field.id = 'lifecycle-in-progress-input';
    field.value = '用户未提交的输入';
    document.getElementById('view').appendChild(field);
  });
  release();
  await expect.poll(() => page.evaluate(() => state.page)).toBe('训练任务');
  await expect(page.locator('#lifecycle-in-progress-input')).toHaveValue('用户未提交的输入');
  await page.evaluate(() => window.setPage('模型配置'));
  await expect.poll(() => page.evaluate(() => state.page)).toBe('模型配置');
  await expect(page.locator('#view')).not.toContainText('正在读取核心页面');
});

test('closing a pending task-detail opener cannot resurrect it above a newer modal', async ({page}) => {
  await page.goto('/');
  await expect.poll(() => page.evaluate(() => state.uiReady), {timeout: 20000}).toBe(true);
  const taskId = 'lifecycle-race-only';
  let started;
  const requested = new Promise(resolve => {started = resolve;});
  let release;
  const held = new Promise(resolve => {release = resolve;});
  await page.route(/\/api\/v47\/projects\/[^/]+\/clean-tasks$/, async route => {
    started();
    await held;
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({items: [{id: taskId, status: 'running'}]})});
  });
  await page.evaluate(() => {void window.showCleanTaskProgress429('lifecycle-race-only');});
  await requested;
  await page.evaluate(() => window.modal('新业务窗口 B', '<input id="new-window-input" value="保留草稿">'));
  release();
  await expect(page.locator('.modal:not(.hidden) .modal-title').last()).toHaveText('新业务窗口 B');
  await expect(page.locator('#new-window-input')).toHaveValue('保留草稿');
  await expect(page.locator('[data-clean-progress-task="lifecycle-race-only"]')).toHaveCount(0);
});


test('malformed startup snapshot retry restores the original extras owner once',async({page})=>{
 let reads=0;
 await page.route('**/api/v53/bootstrap/snapshot**',route=>{reads++;if(reads===1)return route.fulfill({contentType:'application/json',body:'{broken'});return route.continue()});
 await page.goto('/');
 await expect(page.locator('#view .boot413-card.error')).toContainText('BOOTSTRAP_JSON_INVALID');
 await page.locator('#view button').filter({hasText:'重新加载'}).click();
 await expect.poll(()=>page.evaluate(()=>state.uiReady)).toBe(true);
 await expect.poll(()=>page.evaluate(()=>Number(state.__startupExtrasOwner)>0)).toBe(true);
 expect(reads).toBeLessThanOrEqual(3);
 await expect(page.locator('#view .boot413-card.error')).toHaveCount(0);
 expect(await page.evaluate(()=>window.__startupDiagnostics413.jsonParseMs)).toBeGreaterThanOrEqual(0);
});


test('ready core reports read parse and render stages across three viewport sizes',async({browser},testInfo)=>{
 const contexts=await Promise.all([{width:1920,height:1080},{width:1024,height:768},{width:390,height:844}].map(viewport=>browser.newContext({viewport})));
 try{
  const measurements=await Promise.all(contexts.map(async(context,index)=>{
   const page=await context.newPage(),started=Date.now();await page.goto('http://127.0.0.1:8011/');
   await expect.poll(()=>page.evaluate(()=>state.uiReady)).toBe(true);
   const metrics=await page.evaluate(()=>({diagnostics:window.__startupDiagnostics413,materials:state.materialSummary61?.total,algorithms:state.algorithmsTotal,requests:performance.getEntriesByType('resource').filter(e=>e.name.includes('/api/v53/bootstrap/snapshot')).length}));
   expect(metrics.diagnostics.phase).toBe('interactive');expect(metrics.diagnostics.jsonParseMs).toBeGreaterThanOrEqual(0);expect(metrics.requests).toBeLessThanOrEqual(2);
   return {viewport:page.viewportSize(),interactiveMs:Date.now()-started,...metrics};
  }));
  await testInfo.attach('core-stage-measurements.json',{body:JSON.stringify(measurements,null,2),contentType:'application/json'});
 }finally{await Promise.all(contexts.map(context=>context.close()))}
});

test('model configuration failure stays local and can retry after core is interactive',async({page})=>{
 let reads=0;let failures=true;
 await page.route('**/api/v35/model-configs',route=>{reads++;return failures?route.fulfill({status:503,json:{message:'隔离模型配置读取故障'}}):route.continue()});
 await page.goto('/');await expect.poll(()=>page.evaluate(()=>state.uiReady)).toBe(true);
 await page.evaluate(()=>window.setPage('模型配置'));
 await expect(page.locator('[data-model-config-panel]')).toContainText('模型配置读取失败');
 expect(await page.evaluate(()=>state.uiReady)).toBe(true);
 failures=false;await page.locator('[data-model-config-panel]').getByRole('button',{name:'重试',exact:true}).click();
 await expect(page.locator('[data-model-config-panel]')).not.toContainText('模型配置读取失败');
 expect(reads).toBe(2);
 await page.evaluate(()=>window.setPage('算法列表'));
 await expect(page.locator('#view .boot413-card.error')).toHaveCount(0);
});


test('overview marks deferred training truth without pretending there are no jobs',async({page})=>{
 await page.addInitScript(()=>localStorage.setItem('mc_train_ui_state_v34',JSON.stringify({page:'总览'})));
 await page.goto('/');await expect.poll(()=>page.evaluate(()=>state.uiReady)).toBe(true);
 await expect(page.locator('.ops422-kpi').filter({hasText:'正在训练'})).toContainText('任务状态按需读取');
 await expect(page.locator('.ops422-recent')).toContainText('训练状态按需读取');
 await expect(page.locator('.ops422-trend')).toContainText('尚未读取训练历史');
});


test('core HTTP deadline offers retry and a retired response cannot repaint the page',async({page})=>{
 let first=true,release;const held=new Promise(resolve=>release=resolve);
 await page.route('**/api/v53/bootstrap/snapshot**',async route=>{if(first){first=false;await held}try{await route.continue()}catch{}});
 await page.goto('/');
 await expect(page.locator('#view .boot413-card.error')).toContainText('BOOTSTRAP_REQUEST_TIMEOUT',{timeout:24000});
 expect(await page.evaluate(()=>state.uiReady)).toBe(false);
 await page.locator('#view button').filter({hasText:'重新加载'}).click();
 await expect.poll(()=>page.evaluate(()=>state.uiReady)).toBe(true);
 release();await page.waitForTimeout(300);
 await expect(page.locator('#view .boot413-card.error')).toHaveCount(0);
 expect(await page.evaluate(()=>window.__startupDiagnostics413.phase)).toBe('interactive');
});

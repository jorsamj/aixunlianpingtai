import {test, expect} from '@playwright/test';

async function ready(page) {
  await page.addInitScript(() => localStorage.setItem('cl_v427_advanced', '1'));
  await page.goto('/');
  await expect.poll(() => page.evaluate(() => Boolean(window.state?.uiReady || (typeof state !== 'undefined' && state.uiReady)))).toBe(true);
}

test('four advanced menus retain existing owners, sections, forms and refresh state', async ({page}, info) => {
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({width:1920,height:1080});
  await ready(page);
  await page.waitForTimeout(180);
  await page.screenshot({path:info.outputPath('advanced-before-or-after.png'),fullPage:true});
  const group=page.locator('#nav .nav-group').filter({has:page.locator('.nav-group-title',{hasText:/^高级功能$/})});
  await expect(group.locator('.nav-btn b')).toHaveText(['算力与节点','模型转换环境','AI 辅助配置','存储管理']);
  await group.getByRole('button',{name:/算力与节点/}).click();
  await expect(page.locator('#title')).toHaveText('算力与节点');
  await expect(page.locator('#crumb')).toContainText('高级功能');
  await expect.poll(()=>page.evaluate(()=>state.page)).toBe('服务节点');
  await page.waitForTimeout(180);
  await page.screenshot({path:info.outputPath('nodes-1920.png'),fullPage:true});
  const tabs=page.locator('#advancedPageTabs');
  await page.route('**/api/ultralytics_env',async route=>{await new Promise(resolve=>setTimeout(resolve,900));await route.fulfill({json:{}});});
  await tabs.getByRole('tab',{name:'训练环境',exact:true}).click();
  await expect(page.locator('#uroot')).toBeVisible();
  await page.waitForTimeout(180);
  await page.screenshot({path:info.outputPath('training-environment-1920.png'),fullPage:true});
  await expect.poll(()=>page.evaluate(()=>state.page)).toBe('训练资源');
  await page.locator('#nav .nav-advanced427 button').click();
  await expect(page.locator('#title')).toHaveText('算力与节点');
  await expect(page.locator('#uroot')).toBeVisible();
  await page.locator('#nav .nav-advanced427 button').click();
  await group.getByRole('button',{name:/AI 辅助配置/}).click();
  await expect(page.locator('[data-model-config-panel]')).toBeVisible();
  await page.waitForTimeout(950);
  await expect(page.locator('#toast')).not.toContainText('page-navigation');
  await page.waitForTimeout(180);
  await page.screenshot({path:info.outputPath('ai-models-1920.png'),fullPage:true});
  await tabs.getByRole('tab',{name:'提示词模板',exact:true}).click();
  await expect(page.locator('[data-model-prompt-panel]')).toBeVisible();
  await expect(page.locator('[data-model-config-panel]')).toBeHidden();
  await page.reload();
  await expect(page.locator('[data-model-prompt-panel]')).toBeVisible();
  await page.getByRole('button',{name:'新增提示词',exact:true}).click();
  await expect(page.locator('#modal')).toBeVisible();
  await page.evaluate(()=>closeModal());
  await group.getByRole('button',{name:/存储管理/}).click();
  await expect(page.locator('.storage61-table').first()).toBeVisible();
  await tabs.getByRole('tab',{name:'空间与缓存',exact:true}).click();
  await expect(page.locator('#storageLifecycleStatus61')).toBeVisible();
  await page.waitForTimeout(180);
  await page.screenshot({path:info.outputPath('storage-cache-1920.png'),fullPage:true});
  await tabs.getByRole('tab',{name:'旧素材兼容迁移',exact:true}).click();
  await expect(page.locator('[data-compat-scan]')).toBeVisible();
  await group.getByRole('button',{name:/模型转换环境/}).click();
  await expect(page.locator('.deploy-resource-grid')).toBeVisible();
  await page.locator('.advanced-tool-help>summary').click();
  await expect(page.locator('.advanced-tool-note')).toBeVisible();
  await page.waitForTimeout(180);
  await page.screenshot({path:info.outputPath('conversion-resources-1920.png'),fullPage:true});
  await tabs.getByRole('tab',{name:'厂商与芯片字典',exact:true}).click();
  await expect(page.locator('#conversion-catalog-host')).toBeVisible();
  for(const size of [{width:1920,height:1080},{width:1440,height:900},{width:1366,height:768},{width:1093,height:614}]) {
    await page.setViewportSize(size);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
    await page.waitForTimeout(180);
  await page.screenshot({path:info.outputPath(`advanced-${size.width}.png`),fullPage:true});
  }
  await page.evaluate(()=>setPage('模型配置'));
  await expect(page.locator('#title')).toHaveText('AI 辅助配置');
  await expect(group.getByRole('button',{name:/AI 辅助配置/})).toHaveClass(/active/);
  expect(errors).toEqual([]);
});

test('diagnostic task resumes through original route and viewing integration never writes', async ({page}) => {
  let polls=0; const writes=[];
  const scan={id:'advanced-scan',status:'running',progress:25,items:[],total:4,done:1};
  await page.route('**/api/v40/system/components/latest',route=>route.fulfill({json:scan}));
  await page.route('**/api/v40/system/components/scan/advanced-scan',route=>{polls++;return route.fulfill({json:{...scan,status:polls>1?'done':'running',progress:polls>1?100:50}});});
  page.on('request',request=>{if(/external-algorithm-platform|changlian-data/.test(request.url()) && !['GET','HEAD'].includes(request.method()))writes.push(request.url());});
  await ready(page);
  await page.route('**/api/advanced-navigation-slow-probe',async route=>{await new Promise(resolve=>setTimeout(resolve,350));await route.fulfill({json:{ok:true}});});
  const cancellation=await page.evaluate(async()=>{
    const {PageRequestScope,isPageNavigationCancelled}=await import('/static/modules/page-request-scope.js?v=20261031-p0');
    const native=window.fetch.__pageRequestScopeOriginal || window.fetch;
    const scope=new PageRequestScope({page:'训练资源',fetchImpl:(url,options)=>native.call(window,url,options)});
    let finalized=false;
    const request=scope.fetch('/api/advanced-navigation-slow-probe').finally(()=>{finalized=true});
    await new Promise(resolve=>setTimeout(resolve,30));scope.navigate('模型配置');
    const outcome=await Promise.race([
      request.then(()=>'settled',error=>isPageNavigationCancelled(error)?'navigation-cancelled':'other-error'),
      new Promise(resolve=>setTimeout(()=>resolve('pending'),80))
    ]);
    return {outcome,finalized,abortedRequests:scope.abortedRequests};
  });
  expect(cancellation).toEqual({outcome:'navigation-cancelled',finalized:true,abortedRequests:1});
  await page.evaluate(()=>setPage('组件检测'));
  await expect(page.locator('#advancedPageTabs [aria-selected="true"]')).toHaveText('环境诊断');
  await expect.poll(()=>polls).toBeGreaterThan(0);
  await page.locator('#advancedPageTabs').getByRole('tab',{name:'服务节点',exact:true}).click();
  await expect.poll(()=>page.evaluate(()=>state.page)).toBe('服务节点');
  const stopped=polls; await page.waitForTimeout(850); expect(polls).toBe(stopped);
  await page.locator('#advancedPageTabs').getByRole('tab',{name:'环境诊断',exact:true}).click();
  await expect(page.locator('#componentScanBtn')).toBeEnabled();
  for(const name of ['平台对接','畅联云数据']) {
    await page.evaluate(name=>setPage(name),name);
    await expect(page.locator('#advancedPageTabs')).toBeHidden();
    await expect(page.locator('#view')).not.toContainText('当前页面不存在');
  }
  expect(writes).toEqual([]);
});


test('advanced tabs use scoped underline styling across four groups and narrow screens',async({page})=>{
  await ready(page);
  for(const owner of ['服务节点','部署资源','模型配置','存储配置']) {
    await page.evaluate(owner=>setPage(owner),owner);
    const tabs=page.locator('#advancedPageTabs');
    await expect(tabs).toBeVisible();
    for(const width of [1440,760,375]) {
      await page.setViewportSize({width,height:820});
      const selected=tabs.locator('[aria-selected="true"]');
      await expect(selected).toHaveCount(1);
      const style=await selected.evaluate(el=>{const s=getComputedStyle(el);return {background:s.backgroundColor,radius:s.borderRadius,font:s.fontSize,weight:s.fontWeight,line:s.borderBottomWidth,wrap:getComputedStyle(el.parentElement).flexWrap};});
      expect(style).toEqual({background:'rgba(0, 0, 0, 0)',radius:'0px',font:'14px',weight:'600',line:'3px',wrap:'nowrap'});
      expect(await tabs.evaluate(el=>el.getBoundingClientRect().right<=innerWidth+1)).toBe(true);
    }
    const last=tabs.getByRole('tab').nth(1);
    await last.click();await expect(last).toHaveAttribute('aria-selected','true');
    await last.hover();await last.focus();await page.keyboard.press('Tab');await page.keyboard.press('Shift+Tab');
    expect(await last.evaluate(el=>getComputedStyle(el).outlineStyle)).not.toBe('none');
    const label=await last.textContent();
    await page.reload();
    await expect(tabs.locator('[aria-selected="true"]')).toHaveText(label);
  }
});

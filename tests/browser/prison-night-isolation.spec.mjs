import {test,expect} from '@playwright/test';
test('independent night inspection menu and iframe cannot replace training platform owner',async({page})=>{
  const parentErrors=[];
  page.on('pageerror',error=>parentErrors.push(error.message));
  await page.setViewportSize({width:1366,height:768});
  await page.goto('/');
  await expect.poll(()=>page.evaluate(()=>Boolean(state.uiReady)),{timeout:20000}).toBe(true);
  const menu=page.locator('#nav .nav-night-isolated-btn');
  await expect(menu).toBeVisible();
  await expect(menu).toContainText('AI算法底座');
  await expect(page.locator('#nav .nav-advanced427')).toBeVisible();
  await menu.click();
  await expect(page.locator('#nightInspectionIsolated iframe')).toHaveCount(1);
  await expect(page.locator('body')).toHaveClass(/sidebar-collapsed/);
  const expand=page.getByRole('button',{name:'展开或收起平台菜单'});
  await expect(expand).toBeVisible();
  await expand.click();
  await expect(page.locator('body')).not.toHaveClass(/sidebar-collapsed/);
  await expand.click();
  await expect(page.locator('body')).toHaveClass(/sidebar-collapsed/);
  const frame=page.locator('#nightInspectionIsolated iframe');
  await expect(frame).toHaveAttribute('sandbox','allow-scripts allow-modals');
  await expect(frame).toHaveAttribute('title','AI算法底座（独立演示）');
  await expect(page.frameLocator('#nightInspectionIsolated iframe').getByText('夜间离床风险智能研判大屏').first()).toBeVisible();

  const iframeTimeBefore=await page.frameLocator('#nightInspectionIsolated iframe').locator('body').evaluate(()=>performance.timeOrigin);
  await page.frameLocator('#nightInspectionIsolated iframe').locator('body').evaluate(()=>{
    const record=(kind,event)=>{document.documentElement.dataset['aiProbe'+kind]=String(event.target?.outerHTML||event.target?.nodeName||'').slice(0,160)};
    window.addEventListener('pointerdown',event=>record('Pointer',event),true);
    window.addEventListener('click',event=>record('WindowClick',event),true);
    document.addEventListener('click',event=>record('DocumentClick',event),true);
  });
  const frameNavEvents=[];
  const onFrameNavigated=frame=>{if(frame.parentFrame())frameNavEvents.push(frame.url())};
  page.on('framenavigated',onFrameNavigated);
    await page.frameLocator('#nightInspectionIsolated iframe').locator('[data-page="events"]').first().click();
  page.off('framenavigated',onFrameNavigated);
  const navDebug=await page.frameLocator('#nightInspectionIsolated iframe').locator('body').evaluate(()=>{
    const button=document.querySelector('.sidebar .nav button[data-page="events"]');
    const target=document.getElementById('events');
    return {owner:Boolean(document.getElementById('ai-foundation-sandbox-navigation-owner')),
      showPage:typeof window.showPage,
      activePages:[...document.querySelectorAll('.page.active')].map(node=>node.id),
      buttonActive:button?.classList.contains('active'),
      targetClass:target?.className,targetDisplay:target&&getComputedStyle(target).display,
      bodyClass:document.body.className,ownerScripts:document.querySelectorAll('script').length,timeOrigin:performance.timeOrigin,
      probePointer:document.documentElement.dataset.aiProbePointer,probeWindowClick:document.documentElement.dataset.aiProbeWindowClick,probeDocumentClick:document.documentElement.dataset.aiProbeDocumentClick,
      hitTest:(()=>{const rect=button?.getBoundingClientRect();if(!rect)return null;const x=rect.left+rect.width/2,y=rect.top+rect.height/2;const hit=document.elementFromPoint(x,y);return {x,y,hit:hit?.outerHTML?.slice(0,160),withinButton:button.contains(hit),rect:rect.toJSON()};})(),observed:document.documentElement.dataset.aiNavObserved,after:document.documentElement.dataset.aiNavAfter,init:document.documentElement.dataset.aiNavInitialized,captured:document.documentElement.dataset.aiNavCaptured,firstNode:document.querySelector('[data-page="events"]')?.outerHTML?.slice(0,180),navCount:document.querySelectorAll('.sidebar .nav button[data-page="events"]').length};
  });
  console.log('[ai-foundation-nav-diagnostic]',JSON.stringify({...navDebug,iframeTimeBefore,frameNavEvents}));
  await expect(page.frameLocator('#nightInspectionIsolated iframe').locator('#events')).toBeVisible();
  for(const pageId of ['deviceAccess','channelView','taskConfig','modelConfig','algoList','workflowConfig','dictTags','templateConfig']){
    await page.frameLocator('#nightInspectionIsolated iframe').locator(`.nav button[data-page="${pageId}"]`).first().click();
    await expect(page.frameLocator('#nightInspectionIsolated iframe').locator(`#${pageId}`)).toBeVisible();
  }
  await page.evaluate(()=>window.setPage('算法列表'));
  await expect(page.locator('#nightInspectionIsolated')).toHaveCount(0);
  await expect(page.locator('#nav .nav-night-isolated-btn')).toBeVisible();
  await page.evaluate(()=>window.setPage('总览'));
  await expect(page.locator('[data-overview-tabs]')).toBeVisible();
  await expect(page.locator('#nightInspectionIsolated')).toHaveCount(0);
  expect(parentErrors).toEqual([]);
});

import {test,expect} from '@playwright/test';
test('independent night inspection menu and iframe cannot replace training platform owner',async({page})=>{
  const parentErrors=[];
  page.on('pageerror',error=>parentErrors.push(error.message));
  await page.setViewportSize({width:1366,height:768});
  await page.goto('/');
  await expect.poll(()=>page.evaluate(()=>Boolean(state.uiReady)),{timeout:20000}).toBe(true);
  const menu=page.locator('#nav .nav-night-isolated-btn');
  await expect(menu).toBeVisible();
  await expect(page.locator('#nav .nav-advanced427')).toBeVisible();
  await menu.click();
  await expect(page.locator('#nightInspectionIsolated iframe')).toHaveCount(1);
  const frame=page.locator('#nightInspectionIsolated iframe');
  await expect(frame).toHaveAttribute('sandbox','allow-scripts allow-modals');
  await expect(page.frameLocator('#nightInspectionIsolated iframe').getByText('监所夜间离床风险智能研判系统').first()).toBeVisible();
  await page.frameLocator('#nightInspectionIsolated iframe').locator('[data-page="events"]').first().click();
  await expect(page.frameLocator('#nightInspectionIsolated iframe').locator('#events')).toBeVisible();
  for(const pageId of ['taskConfig','modelConfig','algoList','workflowConfig','dictTags','templateConfig']){
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

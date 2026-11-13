import {test,expect} from '@playwright/test';

test('training resource cards render, patch, and refresh without adding a second owner',async({page})=>{
  const pageErrors=[];
  page.on('pageerror',error=>pageErrors.push(error.message));
  await page.goto('/');
  await expect.poll(()=>page.evaluate(()=>Boolean(state.uiReady)),{timeout:20000}).toBe(true);
  await page.evaluate(()=>{
    state.page='训练资源';
    state.targets=[
      {id:'server:gpu-1',name:'测试GPU服务器',framework:'ultralytics',type:'server',server_id:'server-1',status:'ready',algorithms:[{},{}],base_models:[{}]},
      {id:'local_paddle',name:'测试Paddle',framework:'paddle',type:'local',status:'offline',scan:{families:{YOLO:3}},algorithms:[],base_models:[]},
    ];
    window.renderResourceBasePage();
  });
  await expect(page.locator('#view .resource-grid .res-card')).toHaveCount(2);
  await expect(page.locator('#view .resource-grid')).toContainText('测试GPU服务器');
  await expect(page.locator('#view .resource-grid')).toContainText('YOLO 3');
  await expect(page.locator('#view .resource-grid .res-card.ready')).toHaveCount(1);
  await page.evaluate(()=>{
    state.targets[0].status='offline';
    window.patchTrainingResourceCardsV3();
  });
  await expect(page.locator('#view .resource-grid .res-card.ready')).toHaveCount(0);
  await expect(page.locator('#view .resource-grid .res-card.warn')).toHaveCount(2);
  await page.evaluate(()=>{
    window.__testResourceRefreshCalls=0;
    window.refreshTrainingResourcePageV3=()=>{window.__testResourceRefreshCalls++};
  });
  await page.locator('#view .resource-layout .panel-head button').first().click();
  await expect.poll(()=>page.evaluate(()=>window.__testResourceRefreshCalls)).toBe(1);
  await page.evaluate(()=>window.renderResourceBasePage());
  await expect(page.locator('#view .resource-grid')).toHaveCount(1);
  await expect(page.locator('#view .resource-grid .res-card')).toHaveCount(2);
  expect(pageErrors).toEqual([]);
});

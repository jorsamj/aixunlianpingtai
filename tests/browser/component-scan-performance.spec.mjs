import {test, expect} from '@playwright/test';

test('component scan keeps progress DOM stable and stops polling after leaving the page', async ({page}) => {
  const pageErrors=[];
  page.on('pageerror',error=>pageErrors.push(error));

  let progress=10;
  let stage='检测 Python 运行时';
  const scan=()=>({
    id:'component-perf-1',
    status:'running',
    stage,
    progress,
    summary:{ready:1,warning:0,missing:0,total:6},
    capabilities:[{name:'训练',status:'ready',remote:false,ready:1,total:1}],
    components:[{name:'Python',status:'ready',version:'3.12'}],
  });

  await page.route('**/api/v40/system/components/latest',async route=>{
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(scan())});
  });
  await page.route('**/api/v40/system/components/scan/component-perf-1',async route=>{
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(scan())});
  });

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout:15_000});
  await page.evaluate(()=>window.setPage('组件检测'));
  await expect(page.locator('[data-component-progress-bar]')).toHaveAttribute('data-progress','10.00');

  await page.evaluate(()=>{
    window.__componentBody=document.getElementById('componentBody');
    window.__componentBar=document.querySelector('[data-component-progress-bar]');
    window.__componentCapabilities=document.querySelector('[data-component-capabilities]');
  });

  progress=58;
  stage='检测部署工具链';
  await page.evaluate(()=>window.pollComponentScanV40('component-perf-1'));

  await expect(page.locator('[data-component-progress-bar]')).toHaveAttribute('data-progress','58.00');
  await expect(page.locator('[data-component-stage]')).toHaveText('检测部署工具链');
  await expect(page.locator('[data-component-percent]')).toHaveText('58%');
  expect(await page.evaluate(()=>({
    body:window.__componentBody===document.getElementById('componentBody'),
    bar:window.__componentBar===document.querySelector('[data-component-progress-bar]'),
    capabilities:window.__componentCapabilities===document.querySelector('[data-component-capabilities]'),
  }))).toEqual({body:true,bar:true,capabilities:true});

  await expect.poll(()=>page.evaluate(()=>window.PollRegistryRuntime?.snapshot?.().some(row=>row.key==='component-scan-v40')||false)).toBe(true);
  await page.evaluate(()=>window.setPage('工作台'));
  await expect.poll(()=>page.evaluate(()=>window.PollRegistryRuntime?.snapshot?.().some(row=>row.key==='component-scan-v40')||false)).toBe(false);
  expect(pageErrors).toEqual([]);
});


test('component page revisit reuses terminal scan snapshot without starting another scan', async ({page}) => {
  let latestGets = 0;
  let scanPosts = 0;
  await page.route('**/api/v40/system/components/latest', async route => {
    if (route.request().method() !== 'GET') return route.continue();
    latestGets += 1;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id:'component-cache-1',
        status:'done',
        stage:'检测完成',
        progress:100,
        summary:{ready:1,warning:0,missing:0,total:1},
        capabilities:[],
        components:[{name:'Python',status:'ready',version:'3.12'}],
      }),
    });
  });
  await page.route('**/api/v40/system/components/scan', async route => {
    if (route.request().method() !== 'POST') return route.continue();
    scanPosts += 1;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({id:'unexpected-scan',status:'queued',progress:0}),
    });
  });

  await page.goto('/');
  await expect.poll(async () => page.evaluate(() => state.uiReady === true)).toBe(true);
  await page.evaluate(() => window.setPage('组件检测'));
  await expect(page.locator('#componentBody')).toContainText('Python', {timeout: 10_000});
  await expect.poll(() => latestGets).toBe(1);
  expect(scanPosts).toBe(0);

  await page.evaluate(() => window.setPage('工作台'));
  await expect(page.locator('#title')).toContainText('总览');
  await page.evaluate(() => window.setPage('组件检测'));
  await expect(page.locator('#componentBody')).toContainText('Python');
  await page.waitForTimeout(150);
  expect(latestGets).toBe(1);
  expect(scanPosts).toBe(0);
});

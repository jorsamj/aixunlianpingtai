import {test,expect} from '@playwright/test';

test('quality detection downloads on first detect tab, reuses module and respects tab leave',async({page})=>{
  test.setTimeout(60_000);
  const errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  let moduleLoads=0;
  await page.route(/\/static\/modules\/quality-detection-workbench\.js\?/,async route=>{
    moduleLoads++;
    await route.continue();
  });
  await page.goto('/');
  await expect.poll(()=>page.evaluate(()=>Boolean(state.uiReady)),{timeout:15_000}).toBe(true);
  expect(moduleLoads).toBe(0);
  await page.evaluate(()=>window.setPage('质量中心'));
  await expect(page.getByRole('button',{name:'质量概览'})).toBeVisible();
  expect(moduleLoads).toBe(0);
  await page.getByRole('button',{name:'场景算法实测',exact:true}).click();
  await expect(page.locator('[data-quality-detection-shell="1"]')).toBeVisible({timeout:15_000});
  expect(moduleLoads).toBe(1);
  await page.getByRole('button',{name:'质量概览'}).click();
  await expect(page.locator('[data-quality-detection-shell="1"]')).toHaveCount(0);
  await page.getByRole('button',{name:'场景算法实测',exact:true}).click();
  await expect(page.locator('[data-quality-detection-shell="1"]')).toBeVisible();
  expect(moduleLoads).toBe(1);
  expect(errors).toEqual([]);
});

test('delayed quality bench import cannot repaint after navigation leaves quality center',async({page})=>{
  test.setTimeout(60_000);
  let release;
  const gate=new Promise(resolve=>{release=resolve});
  let seen;
  const intercepted=new Promise(resolve=>{seen=resolve});
  await page.route(/\/static\/modules\/quality-detection-workbench\.js\?/,async route=>{
    seen();
    await gate;
    try {await route.continue()} catch (_) { /* navigation may retire pending fetch */ }
  });
  try {
    await page.goto('/');
    await expect.poll(()=>page.evaluate(()=>Boolean(state.uiReady)),{timeout:15_000}).toBe(true);
    await page.evaluate(()=>window.setPage('质量中心'));
    await page.getByRole('button',{name:'场景算法实测',exact:true}).click();
    await Promise.race([intercepted,new Promise((_,reject)=>setTimeout(()=>reject(new Error('lazy module not requested')),10000))]);
    await page.evaluate(()=>window.setPage('训练任务'));
    await expect(page.locator('.train428-page')).toBeVisible();
    release();
    await page.waitForTimeout(300);
    await expect(page.locator('#title')).toHaveText('训练任务');
    await expect(page.locator('[data-quality-detection-shell="1"]')).toHaveCount(0);
  } finally {release?.()}
});

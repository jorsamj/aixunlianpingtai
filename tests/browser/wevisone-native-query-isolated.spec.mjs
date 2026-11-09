import {test,expect} from '@playwright/test';
import {readFileSync} from 'node:fs';

test('WeVisOne native editor sends separate person and tangzhe descriptions without altering the generic editor',async({page})=>{
  const source=readFileSync(new URL('../../static/app.js',import.meta.url),'utf8').replace(/\r\n/g,'\n');
  const start=source.indexOf('(()=>{\n  const providerNames={volcengine_ark:');
  const end=source.indexOf('  window.testModelConfigM4=async function',start);
  expect(start).toBeGreaterThan(0);
  expect(end).toBeGreaterThan(start);
  await page.route('http://wevisone-editor.test/**',route=>route.fulfill({contentType:'text/html',body:'<!doctype html><meta charset="utf-8"><style>.hidden{display:none!important}</style><div id="modal"></div>'}));
  await page.goto('http://wevisone-editor.test/');
  await page.evaluate(()=>{
    window.esc=x=>String(x??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
    window.modal=(_title,html)=>document.getElementById('modal').innerHTML=html;
    window.closeModal=()=>{};
    window.toast=message=>{window.lastToast=message};
    window.renderModelConfigPageV35=()=>{};
    window.state={page:'模型配置',modelConfigs:[]};
    window.api=async(_url,options)=>{window.savedBody=JSON.parse(options.body);return{...window.savedBody,id:'new-dorm',wevisone_label_queries:window.savedBody.wevisone_label_queries}};
  });
  await page.addScriptTag({content:source.slice(start,end)+'\n})();'});
  await page.evaluate(()=>openModelConfigM4());
  await expect(page.locator('#mcWevisoneQueries')).toBeHidden();
  await page.locator('#mcProviderAdapter').selectOption('wevisone_vl');
  await expect(page.locator('#mcWevisoneQueries')).toBeVisible();
  // Native providers keep the same editable coordinate choices as generic
  // providers; the backend/adapter validates them against the actual wire.
  await expect(page.locator('.model-m4-advanced')).not.toHaveClass(/hidden/);
  await page.locator('.model-m4-advanced > summary').click();
  await page.locator('#mcCoordinateSpace').selectOption('normalized_01');
  await page.locator('#mcCoordinateOrder').selectOption('yxyx');
  await page.locator('#mcCoordinateOrigin').selectOption('bottom_left');
  await page.getByRole('button',{name:'填入宿舍示例'}).click();
  await expect(page.locator('[data-query-code]')).toHaveCount(2);
  await expect(page.locator('[data-query-text]').first()).toHaveValue(/standing or walking/);
  await expect(page.locator('[data-query-text]').nth(1)).toHaveValue(/lying or reclining/);
  await expect(page.locator('#mcAnnPrompt')).toBeHidden();
  await page.locator('#mcName').fill('Dorm 2B');
  await page.locator('#mcModel').fill('wevisone-vl-2b');
  await page.locator('#mcUrl').fill('http://127.0.0.1:18000');
  await page.getByRole('button',{name:'保存配置'}).click();
  await expect.poll(()=>page.evaluate(()=>window.savedBody?.wevisone_label_queries?.tangzhe)).toContain('lying or reclining');
  expect(await page.evaluate(()=>window.savedBody?.wevisone_label_queries?.person)).toContain('standing or walking');
  expect(await page.evaluate(()=>[window.savedBody?.coordinate_space,window.savedBody?.coordinate_order,window.savedBody?.coordinate_origin])).toEqual(['normalized_01','yxyx','bottom_left']);
  await page.locator('#mcProviderAdapter').selectOption('local_openai');
  await expect(page.locator('#mcWevisoneQueries')).toBeHidden();
  await expect(page.locator('#mcAnnPrompt')).toBeVisible();
});

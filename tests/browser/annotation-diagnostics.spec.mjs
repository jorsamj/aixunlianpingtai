import {test,expect} from '@playwright/test';
import {readFileSync} from 'node:fs';
test('isolated annotation diagnostics compares stages without formal annotation writes',async({page},testInfo)=>{
 const module=readFileSync(new URL('../../static/modules/annotation-diagnostics.js',import.meta.url),'utf8');
 await page.route('http://diagnostics.test/**',route=>route.request().url().endsWith('diagnostics.js')?route.fulfill({contentType:'text/javascript',body:module}):route.fulfill({contentType:'text/html',body:'<!doctype html><html lang="zh"><meta charset="utf-8"><style>body{font:14px sans-serif;margin:24px;max-width:700px}button{padding:8px;margin:4px}dt{color:#666}table{width:100%}</style><h1>隔离诊断夹具 · 非生产验收</h1><section id="details"></section></html>'}));
 await page.goto('http://diagnostics.test/');
 await page.evaluate(async()=>{
  const {mountAnnotationDiagnostics}=await import('/diagnostics.js');
  const svg='<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080"><rect width="1920" height="1080" fill="#f2f3f5"/><text x="400" y="500" font-size="70">ISOLATED TEST FIXTURE</text></svg>';
  mountAnnotationDiagnostics(document.getElementById('details'),{status:'UNVERIFIED_CONTRACT',model_name:'isolated fixture',contract:{coordinate_space:'normalized_1000',coordinate_order:'xyxy'},geometry:{original_width:1920,original_height:1080,inference_width:1920,inference_height:1080,exif_orientation:1,mapping:'identity_original_bytes'},raw_candidates:[{label:'person',x1:100,y1:200,x2:300,y2:600}],converted_boxes:[{label:'person',x1:192,y1:216,x2:576,y2:648}],counts:{raw:1,invalid:0,threshold_filtered:0,nms_filtered:0,final:1}}, {imageUrl:'data:image/svg+xml,'+encodeURIComponent(svg),finalBoxes:[{label:'person',x1:192,y1:216,x2:576,y2:648}]});
 });
 await expect(page.getByRole('button',{name:'最终结果'})).toHaveAttribute('aria-pressed','true');
 await page.getByRole('button',{name:'原始位置'}).click();
 await expect(page.locator('span[title="person"]')).toHaveCSS('left','64px');
 await page.getByRole('button',{name:'还原位置'}).click();
 await expect(page.getByRole('button',{name:'还原位置'})).toHaveAttribute('aria-pressed','true');
 await page.screenshot({path:testInfo.outputPath('annotation-diagnostics-isolated.png'),fullPage:true});
 await page.getByRole('button',{name:'收起'}).click();await expect(page.locator('#details')).toHaveCount(0);
});

test('real review page loads one diagnostic on demand and drops stale responses',async({page},testInfo)=>{
 await page.goto('/');
 await expect.poll(()=>page.evaluate(()=>typeof state!=='undefined'&&state.uiReady)).toBe(true);
 const imageUrl='data:image/svg+xml,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080"><rect width="1920" height="1080" fill="#e5e6eb"/><text x="250" y="500" font-size="90">ISOLATED TEST</text></svg>');
 const box={label:'person',x1:192,y1:216,x2:576,y2:648};
 const diagnostics={model:'isolated fixture',provider:'test-only',latency_ms:42,status:'UNVERIFIED_CONTRACT',contract:{coordinate_space:'normalized_1000',coordinate_order:'xyxy'},geometry:{original_width:1920,original_height:1080,inference_width:1920,inference_height:1080,exif_orientation:1,mapping:'identity_original_bytes',model_internal_geometry:'unknown_provider_managed'},raw_candidates:[{label:'person',x1:100,y1:200,x2:300,y2:600}],converted_boxes:[box],counts:{raw:1,invalid:0,threshold_filtered:0,nms_filtered:0,final:1}};
 const candidates={total:1,items:[{image_id:'isolated',filename:'ISOLATED TEST — NOT PRODUCTION.svg',url:imageUrl,width:1920,height:1080,status:'completed',boxes:[box]}],label_summary:[{label:'person',images:1,boxes:1}]};
 let reads=0,hold=false,release;
 await page.route('**/api/v60/projects/*/annotation-tasks/diagnostic-review/candidates**',async route=>{
  if(route.request().url().endsWith('/diagnostics')){reads++;if(hold)await new Promise(resolve=>release=resolve);return route.fulfill({json:{image_id:'isolated',diagnostics}})}
  return route.fulfill({json:candidates});
 });
 await page.evaluate(()=>window.reviewAiLabel427('diagnostic-review'));
 await expect(page.locator('.ai66-candidate-card')).toHaveCount(1);expect(reads).toBe(0);
 await page.locator('.ai-candidate-stage').first().click();await page.getByRole('button',{name:'查看诊断',exact:true}).click();
 const details=page.locator('[data-ai-diagnostics]');await expect(details).toContainText('unknown_provider_managed');expect(reads).toBe(1);
 await details.getByRole('button',{name:'原始位置',exact:true}).click();await expect(details.getByRole('button',{name:'原始位置',exact:true})).toHaveAttribute('aria-pressed','true');
 await details.getByRole('button',{name:'还原位置',exact:true}).click();
 await page.locator('.ai66-label-tools').evaluate(node=>node.open=false);
 for(const viewport of [{width:1440,height:1000},{width:390,height:844}]){
  await page.setViewportSize(viewport);
  if(viewport.width===390)await page.evaluate(()=>document.querySelector('.side-collapse').click());
  await details.scrollIntoViewIfNeeded();
  expect(await details.evaluate(node=>node.scrollWidth<=node.clientWidth+2)).toBe(true);
  await expect(details).toBeInViewport();
  expect(await page.locator('#ai60ReviewGrid').evaluate(node=>node.clientHeight)).toBeGreaterThan(100);
  await page.screenshot({path:testInfo.outputPath(`annotation-review-diagnostics-${viewport.width}.png`),fullPage:true});
 }
 expect(reads).toBe(1);await details.getByRole('button',{name:'收起',exact:true}).click();
 hold=true;await page.locator('.ai-candidate-stage').first().click();await page.getByRole('button',{name:'查看诊断',exact:true}).click();await expect.poll(()=>reads).toBe(2);
 await page.evaluate(()=>window.setAiReviewFilter60('failed'));await expect(page.locator('.ai66-candidate-card')).toHaveCount(0);
 release();await page.waitForTimeout(150);await expect(page.locator('[data-ai-diagnostics]')).toHaveCount(0);
});

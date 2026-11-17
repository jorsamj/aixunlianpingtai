import {test,expect} from '@playwright/test';

test('a cancelled page chunk never mounts or reads its API; unrelated pages stay unloaded',async({page})=>{
 await page.route('**/lazy-fixture',route=>route.fulfill({contentType:'text/html',body:'<!doctype html><body></body>'}));
 await page.goto('/lazy-fixture');
 const requested:string[]=[];
 page.on('request',request=>requested.push(new URL(request.url()).pathname));
 let release!:()=>void;
 const gate=new Promise<void>(resolve=>{release=resolve});
 await page.route('**/chunks/TrainingTasks-*.js',async route=>{await gate;await route.continue()});
 await page.evaluate(async()=>{
  const module=await import('/static/vue-catalog/catalog-preview.js');
  const host=document.createElement('div');host.id='lazy-cancel-host';document.body.append(host);
  const controller=new AbortController();
  (window as any).cancelLazy=()=>controller.abort();
  (window as any).lazyDone=module.mountTrainingTasks(host,{signal:controller.signal,projectId:'isolated',memory:{},get:()=>{throw new Error('Cancelled page must not read')}});
 });
 await expect.poll(()=>requested.some(path=>/chunks\/TrainingTasks-/.test(path))).toBe(true);
 await page.evaluate(()=>(window as any).cancelLazy());release();
 await page.evaluate(async()=>{const unmount=await (window as any).lazyDone;unmount()});
 await expect(page.locator('#lazy-cancel-host')).toBeEmpty();
 expect(requested.some(path=>/chunks\/(AiReviewWorkbench|MaterialLibrary|TrainingReport|ModelAssets)-/.test(path))).toBe(false);
 expect(requested.some(path=>path.startsWith('/api/'))).toBe(false);
});

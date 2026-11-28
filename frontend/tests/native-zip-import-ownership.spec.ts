import {expect,test,type Page} from '@playwright/test';
import {resolve} from 'node:path';

async function assets(page:Page){
 await page.route('**/app/**',route=>{
  const name=new URL(route.request().url()).pathname.slice('/app/'.length)||'index.html';
  return route.fulfill({path:resolve('../static/vue-app',name),contentType:name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':'text/html'});
 });
}
const job=(overrides:Record<string,unknown>={})=>({id:'up-1',file_name:'raw-dataset.zip',status:'running',stage:'extracting',
 progress:40,zip_display_progress:{phase_label:'正在解压与入库',message:'后台正在处理 ZIP 数据。',overall_progress:40},
 queue_position:null,upload_id:'up-1',created_at:'2026-11-24T09:30:00',updated_at:'2026-11-24T09:30:05',
 report:{imported_images:0,annotated_images:0,failed:0},...overrides});

test('native ZIP page mirrors the single durable runtime owner and stops its polling on unmount',async({page})=>{
 const listCalls:string[]=[];
 let current=job();
 await assets(page);
 await page.route('**/api/**',async route=>{
  const url=new URL(route.request().url()),path=url.pathname,method=route.request().method();
  if(path==='/api/auth/session')return route.fulfill({json:{authenticated:true,user:{username:'隔离用户'}}});
  if(path==='/api/projects')return route.fulfill({json:[{id:'p',name:'项目 P'}]});
  if(path==='/api/projects/p')return route.fulfill({json:{id:'p',labels:[{code:'fire',display_name:'明火'}]}});
  if(path==='/api/v19/projects/p/import/jobs'&&method==='GET'){
   listCalls.push(url.search);
   return route.fulfill({json:{ok:true,items:[current]}});
  }
  return route.fulfill({status:404,json:{detail:'unexpected '+path}});
 });
 await page.goto('/app/#/projects/p/materials/zip');
 await expect(page.getByRole('heading',{level:2,name:'ZIP 数据集导入',exact:true})).toBeVisible();
 await expect(page.getByRole('row').filter({hasText:'raw-dataset.zip'})).toBeVisible();
 await expect(page.getByText('正在解压与入库').first()).toBeVisible();
 // The durable runtime keeps polling the one existing v19 list endpoint.
 await expect.poll(()=>listCalls.length,{timeout:4000}).toBeGreaterThanOrEqual(2);
 // The page reads the runtime's in-memory snapshot; it has no separate list owner.
 const snapshot=await page.evaluate(()=>(window as unknown as {ZipImportRuntime?:{snapshot?:()=>{jobs:unknown[]}}}).ZipImportRuntime?.snapshot?.());
 expect(snapshot?.jobs?.length).toBe(1);
 await expect(page.getByRole('link',{name:'原 ZIP 上传入口',exact:true})).toHaveAttribute('href',/action=material-zip/);
 // Manual refresh goes through runtime.reconcile, not a second fetch implementation.
 const before=listCalls.length;
 await page.getByRole('button',{name:'刷新任务',exact:true}).click();
 await expect.poll(()=>listCalls.length).toBeGreaterThan(before);
 current=job({status:'done',stage:'done',progress:100,report:{imported_images:2,annotated_images:0,failed:0}});
 await expect(page.getByText('导入完成').first()).toBeVisible({timeout:8000});
 await expect(page.getByText('已入库 2 张',{exact:true})).toBeVisible();
});

test('leaving the native ZIP page destroys the runtime poller and stops list requests',async({page})=>{
 const listCalls:string[]=[];
 await assets(page);
 await page.route('**/api/**',async route=>{
  const url=new URL(route.request().url()),path=url.pathname;
  if(path==='/api/auth/session')return route.fulfill({json:{authenticated:true,user:{username:'隔离用户'}}});
  if(path==='/api/projects')return route.fulfill({json:[{id:'p',name:'项目 P'}]});
  if(path==='/api/projects/p')return route.fulfill({json:{id:'p',labels:[]}});
  if(path==='/api/v19/projects/p/import/jobs'){listCalls.push(path);return route.fulfill({json:{ok:true,items:[job()]}})}
  return route.fulfill({status:404,json:{detail:'unexpected '+path}});
 });
 await page.goto('/app/#/projects/p/materials/zip');
 await expect(page.getByRole('row').filter({hasText:'raw-dataset.zip'})).toBeVisible();
 await expect.poll(()=>listCalls.length,{timeout:4000}).toBeGreaterThanOrEqual(2);
 await page.goto('/app/#/projects/p/nodes');
 await expect(page.locator('.catalog-preview h1')).toHaveText('服务节点与算力');
 const frozen=listCalls.length;
 await page.waitForTimeout(1600);
 expect(listCalls.length).toBe(frozen);
 const runtime=await page.evaluate(()=>Boolean((window as unknown as {ZipImportRuntime?:unknown}).ZipImportRuntime));
 expect(runtime).toBe(false);
});

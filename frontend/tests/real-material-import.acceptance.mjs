// Original index/auth/Uppy/image upload in fresh fixture DATA_DIR. No ZIP import,
// cleaning, annotations, SDK, external publishing or production services execute.
import {chromium,expect} from '@playwright/test';
import {mkdir,writeFile} from 'node:fs/promises';
const base=process.env.MC_IMPORT_ORIGIN||'http://127.0.0.1:8037',out='../test-results/p1w-material-import';await mkdir(out,{recursive:true});
const browser=await chromium.launch({channel:'chrome'}),page=await browser.newPage({viewport:{width:1600,height:1000}}),requests=[],vendors=[],errors=[];
page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{const u=new URL(r.url());if(u.pathname.includes('/vendor/uppy/'))vendors.push(u.pathname);if(r.method()!=='GET')requests.push({method:r.method(),path:u.pathname})});
await page.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():route.abort());
await page.route('**/api/v60/projects/*/annotation-tasks',route=>route.request().method()==='POST'?route.abort():route.continue());
await page.route('**/api/v62/projects/*/material-batches/tasks',route=>route.request().method()==='POST'?route.abort():route.continue());
const view=()=>page.getByRole('region',{name:'素材接入与治理',exact:true});let project;
try{
 await page.goto(base+'/');await expect(page).toHaveURL(/login/);await page.locator('#loginUsername').fill('vue-acceptance');await page.locator('#loginPassword').fill('isolated-test-only');await page.locator('#loginSubmit').click();await expect(page.locator('#authUsername')).toHaveText('vue-acceptance');
 await page.goto(base+'/?vue_material_library=1&vue_material_import=1');await expect.poll(()=>page.evaluate(()=>state.uiReady&&!!window.MaterialImportVueRuntime)).toBe(true);project=await page.evaluate(()=>state.project.id);
 await page.evaluate(()=>window.setPage('素材库正式浏览'));await page.getByRole('button',{name:'上传与治理',exact:true}).click();await expect(view()).toBeVisible();expect(vendors).toHaveLength(0);
 await view().getByRole('button',{name:'选择图片上传',exact:true}).click();await expect(page.locator('[data-image-uppy-view] .uppy-Dashboard')).toBeVisible();
 const data=Buffer.alloc(78);data.write('BM');data.writeUInt32LE(78,2);data.writeUInt32LE(54,10);data.writeUInt32LE(40,14);data.writeInt32LE(3,18);data.writeInt32LE(2,22);data.writeUInt16LE(1,26);data.writeUInt16LE(24,28);data.fill(117,54);
 await page.locator('[data-image-uppy-view] input[type=file]').first().setInputFiles({name:'p1w-isolated-upload.bmp',mimeType:'image/bmp',buffer:data});
 await page.locator('[data-image-uppy-view]').getByRole('button',{name:/上传.*1/}).click();await expect(page.locator('[data-upload-confirmation]')).toBeVisible({timeout:45000});
 await expect(page.locator('[data-upload-confirmation]')).toContainText('成功入库 1 张');
 await page.evaluate(()=>window.setPage('素材上传与治理'));await expect(view()).toBeVisible();await expect(view()).toContainText('图片上传');await expect(view()).toContainText('已完成');
 await view().getByRole('button',{name:'选择 ZIP 导入',exact:true}).click();await expect(page.locator('[data-uppy-zip-view] .uppy-Dashboard')).toBeVisible();await page.getByRole('button',{name:'关闭 · 后台继续',exact:true}).click();await expect(page.locator('.uppy-Dashboard')).toHaveCount(0);
 const viewports=[[1920,1080],[1600,1000],[1440,900],[1366,768],[1024,900],[768,1024]],layouts=[];
 for(const[width,height]of viewports){await page.setViewportSize({width,height});const layout=await page.evaluate(()=>({width:innerWidth,document:document.documentElement.scrollWidth,table:[...document.querySelectorAll('.material-import-governance .el-scrollbar__wrap')].map(x=>({client:x.clientWidth,scroll:x.scrollWidth}))}));expect(layout.document).toBeLessThanOrEqual(width);layouts.push(layout);await page.screenshot({path:`${out}/uploaded-${width}.png`,fullPage:true,animations:'disabled'})}
 await view().getByRole('button',{name:'进入素材与使用证据',exact:true}).click();await expect(page.getByRole('region',{name:'素材库只读浏览',exact:true})).toBeVisible();await page.getByRole('button',{name:'上传与治理',exact:true}).click();await expect(view()).toContainText('已完成');
 await page.evaluate(()=>window.setPage('素材接入'));await expect(page.locator('#src422Q')).toBeVisible();await page.evaluate(()=>window.setPage('数据集'));await expect(page.locator('#view')).toBeVisible();
 expect(vendors).toContain('/static/vendor/uppy/uppy.min.mjs');expect(requests.filter(r=>r.path===`/api/projects/${project}/images`)).toHaveLength(1);expect(requests.filter(r=>/annotation-tasks|material-batches\/tasks|import\/uploads/.test(r.path))).toEqual([]);expect(errors).toEqual([]);
 await writeFile(`${out}/receipt.json`,JSON.stringify({scope:'Actual isolated index/login/original Uppy image upload 1; ZIP real offline UI only, no ZIP upload/import/GT/cleaning',project,requests,vendors,errors,layouts,viewports},null,2));console.log('P1W real-entry PASS; real image POST1, ZIP/clean/AI/GT POST0');
}catch(e){await writeFile(`${out}/failure.json`,JSON.stringify({message:e.message,requests,vendors,errors},null,2));await page.screenshot({path:`${out}/failure.png`,fullPage:true}).catch(()=>{});throw e}finally{await browser.close()}

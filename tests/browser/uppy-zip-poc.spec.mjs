import {test,expect} from '@playwright/test';
import os from 'node:os';
import path from 'node:path';
import {archive,setup,open,add,upload,watch,successes,jobs,gateParts,cleanupInputs} from './helpers/uppy-zip.mjs';
test.afterEach(()=>cleanupInputs());

test('UP-01 UP-05 Chinese local lazy Dashboard DOM selection reaches original mapping and real imported JPEG GT',async({page,request})=>{
 const external=[],vendor=[];page.on('request',r=>{const u=new URL(r.url());if(!['127.0.0.1','localhost'].includes(u.hostname))external.push(r.url());if(u.pathname.includes('/vendor/uppy/'))vendor.push(u.pathname);});
 await page.route(/^https?:\/\/(?!127\.0\.0\.1|localhost)/,r=>r.abort());
 const project=await setup(page,request);expect(vendor).toEqual([]);await open(page);await watch(page);
 await expect(page.locator('.uppy-Dashboard')).toContainText('浏览文件');
 await add(page,[{name:'real-gt.zip',buffer:archive()}]);await upload(page);const [event]=await successes(page,1);expect(event.jobId).toBeTruthy();
 expect(vendor).toContain('/static/vendor/uppy/uppy.min.mjs');expect(external).toEqual([]);
 await expect.poll(async()=>(await jobs(request,project.id)).find(j=>j.file_name==='real-gt.zip')?.status,{timeout:30000}).toBe('selecting');const rows=await jobs(request,project.id);const job=rows.find(j=>j.file_name==='real-gt.zip');expect(job.status).toBe('selecting');
 await page.evaluate(id=>window.ZipImportRuntime.openTask(id),job.id);
 const dialog=page.getByRole('dialog',{name:'ZIP 数据导入'});await expect(dialog.locator('[data-zip-target]')).toHaveValue('object');
 await dialog.getByRole('button',{name:'确认标签并导入'}).click();
 await expect.poll(async()=>(await jobs(request,project.id)).find(j=>j.id===job.id)?.status,{timeout:60000}).toBe('done');
 const material=await (await request.get(`/api/v61/projects/${project.id}/materials`)).json();expect(material.items[0].annotation_origin).toBe('imported');
 expect(material.items).toHaveLength(1);const gt=await (await request.get(`/api/projects/${project.id}/annotations/${material.items[0].id}`)).json();expect(gt.boxes).toHaveLength(1);
});

test('UP-02 UP-03 three archives use two global slots and at most four actual parts each with real progress',async({page,request})=>{
 const project=await setup(page,request);await open(page);await watch(page);const g=gateParts(page);await g.install;
 try{await add(page,[0,1,2].map(i=>({name:`slots-${i}.zip`,buffer:archive(`slots${i}`,33*1024*1024)})));await upload(page);
 await expect.poll(()=>g.urls.length,{timeout:30000}).toBe(8);const ids=g.urls.map(u=>u.split('/uploads/')[1].split('/')[0]);expect(new Set(ids).size).toBe(2);for(const id of new Set(ids))expect(ids.filter(x=>x===id)).toHaveLength(4);
 await expect(page.locator('.uppy-Dashboard-Item')).toHaveCount(3);
 }finally{g.release();}
 await successes(page,3);const ev=await page.evaluate(()=>window.__zipEvents);for(const name of ['slots-0.zip','slots-1.zip','slots-2.zip']){const progress=ev.filter(e=>e.name===name&&e.type==='progress');expect(progress.some(e=>e.loaded>0&&e.loaded<e.total)).toBeTruthy();expect(progress.some(e=>e.loaded===e.total)).toBeTruthy();}
 expect((await jobs(request,project.id)).filter(j=>j.file_name.startsWith('slots-'))).toHaveLength(3);
});

test('UP-06 close destroys official instance while original multipart continues and same task opens original mapping',async({page,request})=>{
 const project=await setup(page,request);await open(page);await watch(page);const g=gateParts(page);await g.install;
 try{await add(page,[{name:'close-background.zip',buffer:archive()}]);await upload(page);await expect.poll(()=>g.urls.length).toBe(1);
 await page.evaluate(()=>{const u=window.ZipUppyView.uppy;const original=u.destroy.bind(u);window.__destroyCount=0;u.destroy=()=>{window.__destroyCount++;return original();};});
 await page.getByRole('button',{name:'关闭 · 后台继续'}).click();await expect.poll(()=>page.evaluate(()=>window.__destroyCount)).toBe(1);await expect(page.locator('.uppy-Dashboard')).toHaveCount(0);
 }finally{g.release();}
 await successes(page,1);await expect.poll(async()=>(await jobs(request,project.id)).find(j=>j.file_name==='close-background.zip')?.status,{timeout:30000}).toBe('selecting');const j=(await jobs(request,project.id)).find(j=>j.file_name==='close-background.zip');expect(j.status).toBe('selecting');await page.evaluate(id=>window.ZipImportRuntime.openTask(id),j.id);await expect(page.locator('.zip-label-workspace')).toBeVisible();
});

test('UP-04 dropped complete response reads durable original upload identity without duplicate completion',async({page,request})=>{
 const project=await setup(page,request);await open(page);await watch(page);let posts=0,reads=0,uploadId='';
 page.on('request',r=>{if(uploadId&&r.method()==='GET'&&r.url().endsWith('/import/jobs/'+uploadId))reads++;});
 await page.route('**/import/uploads/*/complete',async route=>{posts++;uploadId=route.request().url().split('/uploads/')[1].split('/')[0];await route.fetch();await route.abort('connectionreset');});
 await add(page,[{name:'lost-response.zip',buffer:archive()}]);await upload(page);const [e]=await successes(page,1);expect(posts).toBe(1);expect(reads).toBeGreaterThan(0);expect(e.uploadId).toBe(uploadId);expect((await jobs(request,project.id)).filter(j=>j.file_name==='lost-response.zip')).toHaveLength(1);
});

test('UP-06 local bundle failure automatically exposes original upload fallback that still imports',async({page,request})=>{
 const project=await setup(page,request);await page.route('**/static/vendor/uppy/uppy.min.mjs',r=>r.abort('failed'));
 await page.evaluate(async()=>{await (await import('/static/modules/uppy-zip-view.js')).openUppyZipView({poc:true});});
 await expect(page.locator('[data-uppy-legacy]')).toBeVisible();await page.locator('[data-uppy-legacy-input]').setInputFiles({name:'fallback.zip',mimeType:'application/zip',buffer:archive()});await page.locator('[data-uppy-legacy-submit]').click();
 await expect.poll(async()=>(await jobs(request,project.id)).some(j=>j.file_name==='fallback.zip'&&j.status==='selecting'),{timeout:30000}).toBe(true);
});

test('UP-06 manual fallback uses the original owner and only one real upload',async({page,request})=>{
 const project=await setup(page,request);await open(page);await page.getByRole('button',{name:'使用原上传界面'}).click();await expect(page.locator('[data-uppy-legacy]')).toBeVisible();await expect(page.locator('.uppy-Dashboard')).toHaveCount(0);
 await page.locator('[data-uppy-legacy-input]').setInputFiles({name:'manual-fallback.zip',mimeType:'application/zip',buffer:archive()});await page.locator('[data-uppy-legacy-submit]').click();await expect.poll(async()=>(await jobs(request,project.id)).filter(j=>j.file_name==='manual-fallback.zip').length,{timeout:30000}).toBe(1);
});

test('UP-03 official pause resumes same upload without retransmitting confirmed part',async({page,request})=>{
 const project=await setup(page,request);await open(page);await watch(page);let release;const gate=new Promise(r=>release=r);const puts=[];let confirmed=false;
 page.on('response',r=>{if(r.request().method()==='PUT'&&r.url().endsWith('/parts/0')&&r.ok())confirmed=true;});
 const handler=async route=>{puts.push(route.request().url());if(!route.request().url().endsWith('/parts/0'))await gate;await route.continue().catch(()=>{});};await page.route('**/import/uploads/*/parts/*',handler);
 try{await add(page,[{name:'pause-same.zip',buffer:archive('pause',17*1024*1024)}]);await upload(page);await expect.poll(()=>confirmed,{timeout:30000}).toBe(true);
 await page.evaluate(()=>{const u=window.ZipUppyView.uppy;u.pauseResume(u.getFiles()[0].id);});await expect.poll(()=>page.evaluate(()=>window.__zipEvents.some(e=>e.type==='paused'))).toBe(true);
 const before=await jobs(request,project.id);expect(before).toHaveLength(1);expect(before[0].status).toBe('paused');
 release();await page.unroute('**/import/uploads/*/parts/*',handler);
 page.on('request',r=>{if(r.method()==='PUT')puts.push(r.url());});
 await page.evaluate(()=>{const u=window.ZipUppyView.uppy;u.pauseResume(u.getFiles()[0].id);});const [event]=await successes(page,1);expect(event.uploadId).toBe(before[0].id);expect(puts.filter(u=>u.endsWith('/parts/0'))).toHaveLength(1);expect(await jobs(request,project.id)).toHaveLength(1);
 }finally{release();}
});

test('UP-04 offline part failure official retry reuses same upload and single task',async({page,request})=>{
 const project=await setup(page,request);await open(page);await watch(page);let offline=true;const ids=[];
 await page.route('**/import/uploads/*/parts/*',async r=>{ids.push(r.request().url().split('/uploads/')[1].split('/')[0]);if(offline)await r.abort('internetdisconnected');else await r.continue();});
 await add(page,[{name:'offline-retry.zip',buffer:archive()}]);await upload(page);await expect.poll(()=>page.evaluate(()=>window.__zipEvents.some(e=>e.type==='error')),{timeout:30000}).toBe(true);
 offline=false;await page.evaluate(()=>window.ZipUppyView.uppy.retryAll());await successes(page,1);expect(new Set(ids).size).toBe(1);expect((await jobs(request,project.id)).filter(j=>j.file_name==='offline-retry.zip')).toHaveLength(1);
});

test('UP-04 reload reselect identical File fingerprint resumes original upload and skips completed part',async({page,request})=>{
 const project=await setup(page,request);await open(page);await watch(page);let release;const gate=new Promise(r=>release=r);let confirmed=false;const puts=[];
 page.on('response',r=>{if(r.request().method()==='PUT'&&r.url().endsWith('/parts/0')&&r.ok())confirmed=true;});
 const handler=async route=>{puts.push(route.request().url());if(!route.request().url().endsWith('/parts/0'))await gate;await route.continue().catch(()=>{});};await page.route('**/import/uploads/*/parts/*',handler);
 let identity;
 try{await add(page,[{name:'refresh-identical.zip',buffer:archive('refresh',17*1024*1024)}]);identity=await page.evaluate(()=>{const f=window.ZipUppyView.uppy.getFiles()[0].data;return {name:f.name,lastModified:f.lastModified};});await upload(page);await expect.poll(()=>confirmed,{timeout:30000}).toBe(true);await page.reload();}finally{release();}
 await page.unroute('**/import/uploads/*/parts/*',handler);const original=(await jobs(request,project.id)).find(j=>j.file_name===identity.name);expect(original).toBeTruthy();
 await expect.poll(()=>page.evaluate(id=>Boolean(state.uiReady && window.ZipImportRuntime?.getProjectId()===id),project.id)).toBe(true);await open(page);await watch(page);
 await add(page,[{name:identity.name,buffer:archive('refresh',17*1024*1024)}]);await page.evaluate(meta=>{const u=window.ZipUppyView.uppy,f=u.getFiles()[0];u.setFileState(f.id,{data:new File([f.data],meta.name,{type:'application/zip',lastModified:meta.lastModified})});},identity);
 page.on('request',r=>{if(r.method()==='PUT')puts.push(r.url());});await upload(page);const [event]=await successes(page,1);expect(event.uploadId).toBe(original.id);expect(puts.filter(u=>u.endsWith('/parts/0'))).toHaveLength(1);expect(await jobs(request,project.id)).toHaveLength(1);
});

test('UP-06 late local module completion after close cannot mount or reopen stale view',async({page,request})=>{
 await setup(page,request);let release;const gate=new Promise(r=>release=r);let requested=false;
 await page.route('**/static/vendor/uppy/uppy.min.mjs',async r=>{requested=true;await gate;await r.continue();});
 await page.evaluate(()=>{window.__opening=import('/static/modules/uppy-zip-view.js').then(m=>m.openUppyZipView({poc:true}));});await expect.poll(()=>requested).toBe(true);await page.getByRole('button',{name:'关闭 · 后台继续'}).click();release();await page.evaluate(()=>window.__opening);await expect(page.locator('.uppy-Dashboard')).toHaveCount(0);await expect(page.locator('[data-uppy-legacy]:visible')).toHaveCount(0);
});

test('UP-02 original task center cancels queued sibling without sending its parts',async({page,request})=>{
 const project=await setup(page,request);await open(page);await watch(page);const g=gateParts(page);await g.install;
 try{await add(page,[0,1,2].map(i=>({name:`cancel-queue-${i}.zip`,buffer:archive(`cancel${i}`)})));await upload(page);await expect.poll(()=>g.urls.length).toBe(2);
 const toggle=page.locator('#uploadTaskCenter [data-utc-toggle]');if(await toggle.getAttribute('aria-expanded')!=='true')await toggle.click();const row=page.locator('#uploadTaskCenter .utc-row',{hasText:'cancel-queue-2.zip'});await row.getByRole('button',{name:'取消',exact:true}).click();await expect(row).toContainText('已取消');
 }finally{g.release();}
 await successes(page,2);expect(g.urls).toHaveLength(2);expect((await jobs(request,project.id)).filter(j=>j.file_name==='cancel-queue-2.zip')).toHaveLength(0);
});

test('UP-07 Chinese Dashboard remains operable in four real Chrome viewports',async({page,request})=>{
 await setup(page,request);
 for(const [width,height] of [[1920,1080],[1440,900],[1366,768],[375,812]]){await page.setViewportSize({width,height});await open(page);await expect(page.locator('.uppy-Dashboard')).toBeVisible();await expect(page.getByRole('button',{name:'关闭 · 后台继续'})).toBeInViewport();await page.screenshot({path:path.join(os.tmpdir(),`uppy-chrome-${width}x${height}.png`),fullPage:true});await page.getByRole('button',{name:'关闭 · 后台继续'}).click();await expect(page.locator('.uppy-Dashboard')).toHaveCount(0);}
});

test('UP-05 external label is manually mapped by original review into canonical GT',async({page,request})=>{
 const project=await setup(page,request);await open(page);await watch(page);await add(page,[{name:'manual-label.zip',buffer:archive('manual',0,'helmet')}]);await upload(page);await successes(page,1);
 await expect.poll(async()=>(await jobs(request,project.id)).find(j=>j.file_name==='manual-label.zip')?.status,{timeout:30000}).toBe('selecting');const job=(await jobs(request,project.id)).find(j=>j.file_name==='manual-label.zip');await page.evaluate(id=>window.ZipImportRuntime.openTask(id),job.id);
 const dialog=page.getByRole('dialog',{name:'ZIP 数据导入'});await expect(dialog.locator('[data-zip-target]')).toHaveValue('');await dialog.locator('[data-zip-target]').selectOption('object');await dialog.getByRole('button',{name:'确认标签并导入'}).click();await expect.poll(async()=>(await jobs(request,project.id)).find(j=>j.id===job.id)?.status,{timeout:30000}).toBe('done');const material=await (await request.get(`/api/v61/projects/${project.id}/materials`)).json();expect(material.items[0].annotation_preview[0].label).toBe('object');
});

test('UP-04 unknown completion and unavailable query preserves single durable task without repost',async({page,request})=>{
 const project=await setup(page,request);await open(page);await watch(page);let posts=0,uploadId='';
 await page.route('**/import/uploads/*/complete',async r=>{posts++;uploadId=r.request().url().split('/uploads/')[1].split('/')[0];await r.fetch();await r.abort('connectionreset');});
 await page.route('**/import/jobs/*',async r=>{if(r.request().method()==='GET'&&uploadId&&r.request().url().endsWith('/'+uploadId))await r.abort('internetdisconnected');else await r.continue();});
 await add(page,[{name:'unknown-complete.zip',buffer:archive()}]);await upload(page);await expect.poll(()=>page.evaluate(()=>window.__zipEvents.some(e=>e.type==='error')),{timeout:30000}).toBe(true);expect(posts).toBe(1);const rows=await jobs(request,project.id);expect(rows.filter(j=>j.file_name==='unknown-complete.zip')).toHaveLength(1);expect(rows.find(j=>j.file_name==='unknown-complete.zip').id).toBe(uploadId);
});

test('UP-08 formal dataset upload button opens official Uppy and preserves explicit original fallback',async({page,request})=>{
 const project=await setup(page,request);await page.getByRole('button',{name:/数据集/}).click();await page.getByRole('button',{name:'上传',exact:true}).click();await page.getByRole('button',{name:/上传 ZIP/}).click();
 const dialog=page.getByRole('dialog',{name:'上传 ZIP',exact:true});await expect(dialog.locator('.uppy-Dashboard')).toBeVisible();await expect(dialog.locator('[data-uppy-zip-target] > .loading')).toHaveCount(0);await watch(page);await add(page,[{name:'formal-uppy.zip',buffer:archive('formal')}]);await upload(page);await successes(page,1);
 await dialog.getByRole('button',{name:'使用原上传界面'}).click();await expect(dialog.locator('.uppy-Dashboard')).toHaveCount(0);await expect(dialog.locator('[data-uppy-legacy]')).toBeVisible();await dialog.locator('[data-uppy-legacy-input]').setInputFiles({name:'formal-fallback.zip',mimeType:'application/zip',buffer:archive('fallback')});await dialog.locator('[data-uppy-legacy-submit]').click();await expect.poll(async()=>{const rows=await jobs(request,project.id);return ['formal-uppy.zip','formal-fallback.zip'].filter(name=>rows.some(j=>j.file_name===name&&j.status==='selecting')).length;},{timeout:30000}).toBe(2);
});

import {test,expect} from '@playwright/test';
import {archive,setup,open,add,upload,watch,successes,jobs,cleanupInputs} from './helpers/uppy-zip.mjs';

test.afterEach(()=>cleanupInputs());
async function uploadOne(page,request,name='automatic.zip'){
 const project=await setup(page,request);await open(page);await watch(page);
 await add(page,[{name,buffer:archive(name)}]);await upload(page);const [event]=await successes(page,1);
 await expect.poll(async()=>(await jobs(request,project.id)).find(j=>j.id===event.jobId)?.status,{timeout:30000}).toBe('selecting');
 return {project,id:event.jobId};
}
const review=page=>page.locator('.zip-label-confirm[data-review-key]');
async function confirm(page){await review(page).locator('[data-zip-target]').selectOption('object');await review(page).locator('[data-zip-confirm-button]').click();}

test('ZIP foreground scan automatically opens the original review without a task-center click',async({page,request})=>{
 const {id}=await uploadOne(page,request);
 await expect(review(page)).toHaveAttribute('data-review-key',id);
});

test('confirmed ZIP closes its own window and cannot reopen or POST start twice from stale selecting lists',async({page,request})=>{
 const {project,id}=await uploadOne(page,request,'close-once.zip');
 await page.evaluate(id=>window.ZipImportRuntime.openTask(id),id);
 const stale=(await jobs(request,project.id)).find(j=>j.id===id);let posts=0;
 page.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith(`/import/jobs/${id}/start`))posts++;});
 await page.route(`**/api/v19/projects/${project.id}/import/jobs`,r=>r.fulfill({json:{items:[stale]}}));
 await confirm(page);
 await expect(page.locator('.modal:not(.hidden):has(.zip411)')).toHaveCount(0);
 for(let i=0;i<4;i++)await page.evaluate(()=>window.ZipImportRuntime.reconcile('test-stale-list'));
 await page.evaluate(id=>window.ZipImportRuntime.confirmLabels(id),id);
 expect(posts).toBe(1);await expect(review(page)).toHaveCount(0);
 await expect.poll(async()=>{const r=await request.get(`/api/v19/projects/${project.id}/import/jobs/${id}`);return (await r.json()).status;},{timeout:60000}).toBe('done');
 await page.unroute(`**/api/v19/projects/${project.id}/import/jobs`);
 await page.evaluate(()=>window.ZipImportRuntime.reconcile('completion'));await page.waitForTimeout(350);
 await expect(page.locator('.modal:not(.hidden)')).toHaveCount(0);
 const materials=await(await request.get(`/api/v61/projects/${project.id}/materials`)).json();expect(materials.items).toHaveLength(1);
});


test('network 100 percent still scanning does not open review and another business modal defers presentation',async({page,request})=>{
 const project=await setup(page,request);let scanning=true;
 await page.route(`**/api/v19/projects/${project.id}/import/jobs`,async route=>{
  const response=await route.fetch();const data=await response.json();
  if(scanning)data.items=data.items.map(j=>({...j,status:'scanning',label_confirmation_required:false}));
  await route.fulfill({response,json:data});
 });
 await open(page);await watch(page);await add(page,[{name:'scan-gate.zip',buffer:archive('scan')}]);await upload(page);await successes(page,1);
 await expect(review(page)).toHaveCount(0);
 await page.evaluate(()=>window.modal('其他业务','<button id="other-business">其他操作</button>'));
 scanning=false;await page.evaluate(()=>window.ZipImportRuntime.reconcile('scan-ready'));
 await expect(page.locator('#other-business')).toBeVisible();await expect(review(page)).toHaveCount(0);
 await page.evaluate(()=>window.closeModal());await page.evaluate(()=>window.ZipImportRuntime.reconcile('business-closed'));
 await expect(review(page)).toHaveCount(1);
});

test('dismissed review does not reopen on polling or refresh and task center manually recovers same job',async({page,request})=>{
 const {project,id}=await uploadOne(page,request,'later.zip');await expect(review(page)).toHaveAttribute('data-review-key',id);
 await page.evaluate(()=>window.closeModal());
 for(let i=0;i<3;i++)await page.evaluate(()=>window.ZipImportRuntime.reconcile('dismissed-poll'));
 await expect(review(page)).toHaveCount(0);await page.reload();
 await expect.poll(()=>page.evaluate(()=>Boolean(state.uiReady&&window.ZipImportRuntime))).toBe(true);
 await page.evaluate(()=>window.ZipImportRuntime.reconcile('reloaded'));
 await expect(review(page)).toHaveCount(0);
 await page.evaluate(id=>window.ZipImportRuntime.openTask('zip:'+id),id);
 await expect(review(page)).toHaveAttribute('data-review-key',id);
 expect((await jobs(request,project.id)).find(j=>j.id===id).status).toBe('selecting');
});

test('three concurrent ZIPs keep distinct ordered reviews and each imports exactly once',async({page,request})=>{
 const project=await setup(page,request);await open(page);await watch(page);const starts=new Map();
 page.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith('/start')){const id=r.url().split('/jobs/')[1].split('/')[0];starts.set(id,(starts.get(id)||0)+1)}});
 await add(page,[0,1,2].map(i=>({name:`ordered-${i}.zip`,buffer:archive(`image-${i}`)})));await upload(page);const events=await successes(page,3);
 const seen=new Set();
 for(let i=0;i<3;i++){
  await page.evaluate(()=>window.ZipImportRuntime.reconcile('next-review'));
  await expect(review(page)).toHaveCount(1);const id=await review(page).getAttribute('data-review-key');expect(seen.has(id)).toBe(false);seen.add(id);
  const job=(await jobs(request,project.id)).find(j=>j.id===id);await expect(review(page)).toContainText(job.file_name);await expect(review(page).locator('[data-zip-review-order]')).toContainText(id);
  await confirm(page);await expect.poll(()=>starts.get(id)||0).toBe(1);
  await expect(page.locator(`.zip-label-confirm[data-review-key="${id}"]`)).toHaveCount(0);
 }
 expect(seen).toEqual(new Set(events.map(e=>e.jobId)));
 await expect.poll(async()=>(await jobs(request,project.id)).filter(j=>j.status==='done').length,{timeout:60000}).toBe(3);
 await page.evaluate(()=>window.ZipImportRuntime.reconcile('all-completed'));
 await expect(review(page)).toHaveCount(0);const materials=await(await request.get(`/api/v61/projects/${project.id}/materials`)).json();expect(materials.items).toHaveLength(3);expect([...starts.values()]).toEqual([1,1,1]);
});

test('late accepted start cannot close a newer business modal',async({page,request})=>{
 const {project,id}=await uploadOne(page,request,'late-start.zip');await expect(review(page)).toHaveAttribute('data-review-key',id);
 let release,received=false;const gate=new Promise(r=>release=r);
 await page.route(`**/import/jobs/${id}/start`,async route=>{const response=await route.fetch();received=true;await gate;await route.fulfill({response});});
 try{
  await confirm(page);await expect.poll(()=>received).toBe(true);
  await page.evaluate(()=>{window.closeModal();window.modal('新业务窗口','<button id="new-business">保持打开</button>')});
  release();await expect(page.locator('#new-business')).toBeVisible();
  await expect.poll(()=>page.evaluate(({project,id})=>localStorage.getItem(`mc_zip_import_start_v1:${project.id}:${id}`),{project,id})).toBe('submitted');
  await page.evaluate(()=>window.ZipImportRuntime.reconcile('late-start'));
  await expect(page.locator('#new-business')).toBeVisible();await expect(review(page)).toHaveCount(0);
 }finally{release();}
});

test('original upload fallback automatically reaches same server label review',async({page,request})=>{
 const project=await setup(page,request);await open(page);await page.getByRole('button',{name:'使用原上传界面'}).click();
 await page.locator('[data-uppy-legacy-input]').setInputFiles({name:'original-entry.zip',mimeType:'application/zip',buffer:archive('original')});await page.locator('[data-uppy-legacy-submit]').click();
 await expect(review(page)).toHaveCount(1);const id=await review(page).getAttribute('data-review-key');expect((await jobs(request,project.id)).find(j=>j.id===id).label_confirmation_required).toBe(true);
});


test('classic ZIP entry uses the same automatic label confirmation owner',async({page,request})=>{
 const project=await setup(page,request);await page.evaluate(()=>window.importData());
 await page.locator('#importFile').setInputFiles({name:'classic.zip',mimeType:'application/zip',buffer:archive('classic')});
 await page.evaluate(()=>{void window.doImportUploadV19()});
 await expect(review(page)).toHaveCount(1);const id=await review(page).getAttribute('data-review-key');
 expect((await jobs(request,project.id)).find(j=>j.id===id).label_confirmation_required).toBe(true);await confirm(page);
 await expect(page.locator('.modal:not(.hidden)')).toHaveCount(0);
});

test('server refusal leaves label review recoverable without claiming confirmation',async({page,request})=>{
 const {project,id}=await uploadOne(page,request,'refused.zip');await expect(review(page)).toHaveAttribute('data-review-key',id);
 await page.route(`**/import/jobs/${id}/start`,route=>route.fulfill({status:409,json:{detail:'隔离测试：请重新核验映射'}}));
 await confirm(page);await expect(review(page).locator('[data-zip-confirm-status]')).toContainText('隔离测试');
 await expect(review(page).locator('[data-zip-confirm-button]')).toBeEnabled();
 expect((await jobs(request,project.id)).find(j=>j.id===id).status).toBe('selecting');
 await page.unroute(`**/import/jobs/${id}/start`);await confirm(page);await expect(review(page)).toHaveCount(0);
});

import {test, expect} from '@playwright/test';
import {archive,setup} from './helpers/uppy-zip.mjs';

test('confirmed missing ZIP survives refresh without polling, shows stale evidence and recovers only on manual reconcile',async({page,request})=>{
  const p=await (await request.post('/api/projects',{data:{name:'ZIP-record-missing-'+Date.now(),labels:[]}})).json();
  const old={id:'zip:missing-fixture',kind:'zip',title:'isolated-missing.zip',status:'RUNNING',progress:72.7,
    stage:'解析图片与标注',updatedAt:'2026-10-26T03:00:00Z',createdAt:'2026-10-26T02:00:00Z',
    pollOwner:'zip-import-runtime',serverUrl:`/api/v19/projects/${p.id}/import/jobs/missing-fixture`};
  await page.route('**/api/v53/bootstrap/snapshot**',async route=>{
    const url=new URL(route.request().url());url.searchParams.set('preferred_project_id',p.id);await route.continue({url:String(url)});
  });
  let lookups=0,starts=0,restored=false;
  const running={id:'other-fixture',status:'running',phase:'ANNOTATION_PARSE',file_name:'other.zip',progress:81,updated_at:'2026-10-26T04:00:00Z'};
  // Only the isolated test project's ZIP API is controlled. No production data.
  await page.route(`**/api/v19/projects/${p.id}/import/jobs**`,async route=>{
    const url=new URL(route.request().url());
    if(route.request().method()==='POST'){starts++;return route.fulfill({status:409,json:{detail:'no duplicate start'}})}
    if(url.pathname.endsWith('/jobs'))return route.fulfill({json:{items:[running,...(restored?[{id:'missing-fixture',status:'done',phase:'DONE',progress:100,file_name:old.title,report:{imported_images:2}}]:[])]}});
    if(url.pathname.endsWith('/missing-fixture')){lookups++;return restored?route.fulfill({json:{id:'missing-fixture',status:'done',phase:'DONE',progress:100,file_name:old.title,report:{imported_images:2}}}):route.fulfill({status:404,json:{detail:'导入任务不存在'}})}
    return route.fulfill({json:running});
  });
  await page.addInitScript(({p,old})=>{
    localStorage.setItem('mc_train_ui_state_v34',JSON.stringify({page:'数据集'}));
    if(!localStorage.getItem('zip-record-fixture-seeded')){
      localStorage.setItem('mc_upload_task_center_v1:'+p.id,JSON.stringify([old]));
      localStorage.setItem('zip-record-fixture-seeded','1');
    }
  },{p,old});
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.goto('/');
  await expect.poll(()=>page.evaluate(()=>Boolean(window.UploadTaskCenterRuntime&&window.ZipImportRuntime&&state.uiReady)) ).toBe(true);
  await expect.poll(()=>lookups).toBe(1);
  await page.locator('[data-utc-toggle]').click();
  const row=page.locator('[data-utc-id="zip:missing-fixture"]');
  // A confirmed 404 becomes an explicitly invalid historical display record,
  // not a live UNKNOWN task that keeps its old polling cadence.
  await expect(row).toContainText('历史记录已失效');
  await expect(row).toContainText('最后记录 72.7%');
  await expect(row).toContainText('服务器未找到该任务记录');
  await expect(page.locator('[data-utc-id="zip:other-fixture"] .utc-pill')).toHaveText('进行中');
  await page.evaluate(async()=>{for(let n=0;n<6;n++)await window.ZipImportRuntime.reconcile('poll')});
  expect(lookups).toBe(1);
  await expect(row).toContainText('任务 zip:missing-fixture');
  await expect(row.getByRole('button',{name:'移除展示记录'})).toBeVisible();
  // An invalid server reference is not reopened by an implicit detail GET.
  await expect(row.getByRole('button',{name:'查看任务'})).toHaveCount(0);
  expect(starts).toBe(0);
  await page.reload();
  await expect.poll(()=>page.evaluate(()=>window.UploadTaskCenterRuntime?.list().find(x=>x.id==='zip:missing-fixture')?.status)).toBe('UNKNOWN');
  // A confirmed missing record stops automatic polling even across F5.
  expect(lookups).toBe(1);
  restored=true;
  await page.evaluate(()=>window.ZipImportRuntime.reconcile('manual'));
  await expect.poll(()=>page.evaluate(()=>window.UploadTaskCenterRuntime.list().find(x=>x.id==='zip:missing-fixture')?.status)).toBe('DONE');
  expect(starts).toBe(0);
  expect(errors).toEqual([]);
});

test('another tab can clear completed history without stranding a stale RUNNING row or erasing import evidence',async({page,request})=>{
  const p=await setup(page,request);
  const created=await request.post(`/api/v19/projects/${p.id}/datasets/default/import/jobs`,{
    multipart:{file:{name:'real-evidence.zip',mimeType:'application/zip',buffer:archive('real-evidence')}}});
  expect(created.ok()).toBeTruthy();const job=await created.json();
  await page.evaluate(()=>window.ZipImportRuntime.reconcile('manual'));
  const started=await request.post(`/api/v19/projects/${p.id}/import/jobs/${job.id}/start`,{data:{selected_paths:[],label_mapping:{'0':'object'}}});
  expect(started.ok()).toBeTruthy();
  await expect.poll(async()=> (await (await request.get(`/api/v19/projects/${p.id}/import/jobs/${job.id}`)).json()).status).toBe('done');
  const reviewUrl=`/api/v52/projects/${p.id}/import/jobs/${job.id}/review`;
  const before=await (await request.get(reviewUrl)).json();
  expect(before.report.imported_images).toBe(1);expect(before.report.boxes).toBe(1);
  await page.evaluate(job=>window.UploadTaskCenterRuntime.upsert({id:'zip:'+job.id,kind:'zip',title:job.file_name,status:'RUNNING',progress:88.9,pollOwner:'zip-import-runtime',localOnly:false}),job);
  const clear=await request.delete(`/api/v19/projects/${p.id}/import/jobs/${job.id}`);
  expect(clear.ok()).toBeTruthy();expect((await clear.json()).evidence_retained).toBe(true);
  await page.evaluate(()=>window.ZipImportRuntime.reconcile('manual'));
  await expect.poll(()=>page.evaluate(id=>window.UploadTaskCenterRuntime.list().find(row=>row.id==='zip:'+id)?.status,job.id)).toBe('DONE');
  const after=await (await request.get(reviewUrl)).json();
  expect(after.report.imported_images).toBe(1);expect(after.report.boxes).toBe(1);
  expect(after.image_ids).toEqual(before.image_ids);
  await page.evaluate(()=>window.UploadTaskCenterRuntime.clearCompleted());
  expect(await page.evaluate(id=>window.UploadTaskCenterRuntime.list().some(row=>row.id==='zip:'+id),job.id)).toBe(false);
});

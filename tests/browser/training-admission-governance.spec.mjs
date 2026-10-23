import {test,expect} from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {execFileSync} from 'node:child_process';

function runWorker(projectId,taskId,{driftImageId='',status='SUCCEEDED'}={}){
  const roots=fs.readdirSync(os.tmpdir()).filter(name=>name.startsWith('xjalgo-browser-')).map(name=>path.join(os.tmpdir(),name)).filter(root=>fs.existsSync(path.join(root,'projects',projectId)));
  expect(roots).toHaveLength(1);
  return execFileSync('python',['-c',`import os,json,app
from contextlib import closing
from platform_core.task_runtime import Scheduler,TaskKind
from platform_core.material_batches import MaterialBatchHandler
r=app.shared_task_repository(); target=${JSON.stringify(taskId)}; capability='test.gov.'+target
with closing(r._connect()) as db:
 db.execute('BEGIN IMMEDIATE'); row=db.execute('SELECT project_id,status,required_capabilities FROM tasks WHERE task_id=?',(target,)).fetchone()
 assert row['project_id']==${JSON.stringify(projectId)} and row['status']=='QUEUED'
 assert json.loads(row['required_capabilities'])==['materials.batch']
 db.execute('UPDATE tasks SET required_capabilities=? WHERE task_id=?',(json.dumps([capability]),target));db.commit()
drift=${JSON.stringify(driftImageId)}
if drift:
 m=app.material_store(${JSON.stringify(projectId)}); row=m.get(drift);m.upsert({**row,'content_sha256':'f'*64})
s=Scheduler(r,app.shared_task_artifacts(),'gov-browser-worker',{TaskKind.MATERIAL_BATCH:MaterialBatchHandler(app.DATA_DIR)},{capability})
assert s.run_once()
assert r.get(target).status.value==${JSON.stringify(status)}, r.get(target)
`],{encoding:'utf8',env:{...process.env,MC_TRAIN_DATA_DIR:roots[0],MC_PLATFORM_VERSION:'browser-test'}});
}

function bmp(index){
  const w=16,h=16,b=Buffer.alloc(54+w*h*3,index+30);b.fill(0,0,54);b.write('BM');b.writeUInt32LE(b.length,2);b.writeUInt32LE(54,10);b.writeUInt32LE(40,14);b.writeInt32LE(w,18);b.writeInt32LE(h,22);b.writeUInt16LE(1,26);b.writeUInt16LE(24,28);return b;
}
async function fixture(page,request,{hold=false}={}){
  const project=await(await request.post('/api/projects',{data:{name:`准入治理-${Date.now()}-${Math.random()}`,labels:[{code:'smoke',display_name:'香烟'}]}})).json();
  const asset=await(await request.post(`/api/v12/projects/${project.id}/algorithms`,{data:{name:'香烟准入治理隔离算法',industry:'测试',algorithm_type:'yolo_ultralytics'}})).json();
  const images=[];
  for(let i=0;i<40;i++){
    const response=await request.post(`/api/projects/${project.id}/images`,{multipart:{dataset_id:'default',files:{name:`gov-${i}.bmp`,mimeType:'image/bmp',buffer:bmp(i)}}});
    expect(response.ok()).toBeTruthy();const image=(await response.json()).uploaded[0];images.push(image);
    if(i>=38){const ann=await request.post(`/api/projects/${project.id}/annotations/${image.id}`,{data:{boxes:[{id:`good-${i}`,class_id:0,label:'smoke',x1:1,y1:1,x2:8,y2:8}],annotation_state:'annotated',reviewed_label_codes:['smoke'],expected_version:image.annotation_version,source_content_sha256:image.content_sha256}});expect(ann.ok()).toBeTruthy();}
  }
  const ready=await request.post(`/api/v52/projects/${project.id}/images/mark-ready`,{data:{image_ids:images.map(x=>x.id)}});expect(ready.ok()).toBeTruthy();
  await page.route('**/api/v53/bootstrap/snapshot**',async route=>{const url=new URL(route.request().url());url.searchParams.set('preferred_project_id',project.id);await route.fallback({url:String(url)});});
  let release;const gate=new Promise(resolve=>{release=resolve});
  await page.route(`**/api/v62/projects/${project.id}/training-materials/compatibility`,async route=>{await gate;await route.continue();});
  await page.route('**/api/training_options**',route=>route.fulfill({json:{targets:[{id:'gov-cpu',scheduler_owned:true,framework:'ultralytics',algorithms:[{key:'yolo_detect'}],base_models:[{value:'yolo11n.pt',model_status:'FOUND'}]}]}}));
  await page.goto('/');await expect.poll(()=>page.evaluate(()=>state.uiReady)).toBe(true);
  await page.evaluate(({id,ids})=>window.TrainingDraftRuntime.update({algorithmId:id,materialIds:ids,testMaterialIds:[],newLabelCodes:[],config:{model:'yolo11n.pt'}}),{id:asset.algorithm.id,ids:images.map(x=>x.id)});
  await expect.poll(()=>page.evaluate(()=>window.TrainingMaterialSummaryRuntime.summaryReadyFor())).toBe(true);
  await page.evaluate(({id,ids})=>{
    window.TrainingDraftRuntime.update({algorithmId:id,materialIds:ids,testMaterialIds:[],newLabelCodes:[],config:{model:'yolo11n.pt'}});
    state.targets=[{id:'gov-cpu',scheduler_owned:true,framework:'ultralytics',algorithms:[{key:'yolo_detect'}],base_models:[{value:'yolo11n.pt',model_status:'FOUND'}]}];
    window.modal('创建训练任务',`<div class="train429-create"><input id="tr429TaskId" value="train_aaaaaaaaaaaaaaaaaaaa"><select id="tr429Target"><option value="gov-cpu">隔离调度资源</option></select><select id="tr429Alg"><option value="yolo_detect">测试引擎</option></select><div class="train429-data-summary"></div><div class="train428-footer"><button class="btn primary" onclick="void window.submitTrain429()">开始训练</button></div></div>`,true);
    window.TrainingSubmitRuntime.updateReadiness();
  },{id:asset.algorithm.id,ids:images.map(x=>x.id)});
  await page.locator('[data-training-label-code="smoke"]').check();
  if(!hold)release();
  await page.getByRole('dialog',{name:'创建训练任务',exact:true}).getByRole('button',{name:'开始训练',exact:true}).click();
  return {project,images,asset:asset.algorithm,release};
}

test('38 real incompatible materials diagnose only after start and preserve the original draft',async({page,request})=>{
  const fx=await fixture(page,request);
  const diagnostic=page.getByRole('dialog',{name:'训练暂不可开始',exact:true});
  await expect(diagnostic).toBeVisible();
  await expect(diagnostic).toContainText('38 张');
  await expect(diagnostic).toContainText('缺少正式标注');
  const training=page.getByRole('dialog',{name:'创建训练任务',exact:true});await expect(training).toBeVisible();
  expect(await page.evaluate(()=>window.TrainingDraftRuntime.current().materialIds.length)).toBe(40);
  await diagnostic.getByRole('button',{name:'返回训练配置',exact:true}).click();
  await page.evaluate(()=>{for(let i=0;i<5;i++)window.TrainingSubmitRuntime.updateReadiness()});
  await expect(diagnostic).toHaveCount(0);
  await expect(training.getByRole('button',{name:'查看不能训练的原因',exact:true})).toBeVisible();
  expect(await page.evaluate(()=>window.TrainingDraftRuntime.current().materialIds)).toEqual(fx.images.map(x=>x.id));
});

test('unfinished compatibility is loading and a closed training session cannot receive its late diagnostic',async({page,request})=>{
  const fx=await fixture(page,request,{hold:true});
  await expect.poll(()=>page.evaluate(()=>window.TrainingMaterialSummaryRuntime.compatibilityFor().loading)).toBe(true);
  await expect(page.getByRole('dialog',{name:'训练暂不可开始',exact:true})).toHaveCount(0);
  await page.getByRole('dialog',{name:'创建训练任务',exact:true}).getByRole('button',{name:'关闭',exact:true}).click();
  fx.release();
  await expect.poll(()=>page.evaluate(()=>window.TrainingMaterialSummaryRuntime.compatibilityFor().loading)).toBe(false);
  await expect(page.getByRole('dialog',{name:'训练暂不可开始',exact:true})).toHaveCount(0);
});

test('all 38 real issues can be excluded together without deleting GT or losing the training configuration',async({page,request})=>{
  const fx=await fixture(page,request);
  await page.getByRole('dialog',{name:'训练暂不可开始',exact:true}).getByRole('button',{name:'查看全部问题 · 批量处理'}).click();
  const issues=page.locator('[data-training-compatibility-dialog]');
  await expect(issues).toContainText('38 张素材 · 38 条训练问题');
  await issues.getByRole('button',{name:'全选全部训练问题',exact:true}).click();
  await expect(issues.locator('[data-governance-selected]')).toContainText('已选 38 张');
  page.once('dialog',dialog=>dialog.accept());
  await issues.getByRole('button',{name:'批量排除本次训练',exact:true}).click();
  await expect.poll(()=>page.evaluate(()=>window.TrainingDraftRuntime.current().materialIds.length)).toBe(2);
  expect(await page.evaluate(()=>window.TrainingDraftRuntime.current().algorithmId)).toBe(fx.asset.id);
  expect(await page.evaluate(()=>window.TrainingDraftRuntime.current().config.model)).toBe('yolo11n.pt');
  const summary=await(await request.post(`/api/v62/projects/${fx.project.id}/training-materials/selection-summary`,{data:{image_ids:fx.images.map(x=>x.id)}})).json();
  expect(summary.matched_count).toBe(40);
  await expect.poll(()=>page.evaluate(()=>window.TrainingMaterialSummaryRuntime.compatibilityFor().compatible)).toBe(true);
  await expect(page.getByRole('dialog',{name:'创建训练任务',exact:true})).toBeVisible();
});

test('real DELETE_INDEX worker completion removes only returned successful IDs and invalidates the draft check',async({page,request})=>{
  const fx=await fixture(page,request);
  await expect(page.getByRole('dialog',{name:'训练暂不可开始',exact:true})).toBeVisible();
  page.once('dialog',dialog=>dialog.accept());
  const task=await page.evaluate(ids=>window.runMaterialBatch62('DELETE_INDEX',{scope:'SELECTED',imageIds:ids}),fx.images.slice(0,38).map(x=>x.id));
  expect(task.task_id).toBeTruthy();expect(task.status).toBe('QUEUED');
  expect(await page.evaluate(()=>window.TrainingDraftRuntime.current().materialIds.length)).toBe(40);
  runWorker(fx.project.id,task.task_id);
  await expect.poll(()=>page.evaluate(()=>window.TrainingDraftRuntime.current().materialIds.length)).toBe(2);
  await expect.poll(()=>page.evaluate(()=>window.TrainingMaterialSummaryRuntime.compatibilityFor().ready)).toBe(false);
  const results=await(await request.get(`/api/v62/projects/${fx.project.id}/material-batches/${task.task_id}/results`)).json();
  expect(results.items).toHaveLength(38);expect(results.items.every(item=>item.logical_removed&&item.physical_retained&&item.reclaimed_bytes===0)).toBe(true);
  const summary=await(await request.post(`/api/v62/projects/${fx.project.id}/training-materials/selection-summary`,{data:{image_ids:fx.images.map(x=>x.id)}})).json();
  expect(summary.matched_count).toBe(2);
  await expect(page.getByRole('dialog',{name:'创建训练任务',exact:true})).toBeVisible();
});

test('project clear requires its exact name and a frozen impact confirmation before the real worker deletes current records',async({page,request})=>{
  const fx=await fixture(page,request);
  await expect(page.getByRole('dialog',{name:'训练暂不可开始',exact:true})).toBeVisible();
  const dialogs=[];page.on('dialog',async dialog=>{dialogs.push(dialog.message());await dialog.accept(dialog.type()==='prompt'?fx.project.name:undefined)});
  const task=await page.evaluate(()=>window.runMaterialBatch62('DELETE_INDEX',{scope:'PROJECT'}));
  expect(task.task_id).toBeTruthy();expect(dialogs).toHaveLength(2);expect(dialogs[0]).toContain(fx.project.name);expect(dialogs[1]).toContain('整个项目');expect(dialogs[1]).toContain('释放空间 0 字节');
  // Worker completion precedes the browser's scheduled poll and paged results
  // fetch. Observe both real responses before asserting the draft projection.
  const taskPath=`/api/v62/projects/${fx.project.id}/material-batches/${task.task_id}`;
  const terminalResponse=page.waitForResponse(async response=>
    new URL(response.url()).pathname===taskPath&&response.ok()&&(await response.json()).status==='SUCCEEDED');
  const resultsResponse=page.waitForResponse(response=>
    new URL(response.url()).pathname===`${taskPath}/results`&&response.ok());
  runWorker(fx.project.id,task.task_id);
  await Promise.all([terminalResponse,resultsResponse]);
  await expect.poll(()=>page.evaluate(()=>window.TrainingDraftRuntime.current().materialIds.length)).toBe(0);
  expect((await(await request.post(`/api/v62/projects/${fx.project.id}/training-materials/selection-summary`,{data:{image_ids:fx.images.map(x=>x.id)}})).json()).matched_count).toBe(0);
  await expect(page.getByRole('dialog',{name:'创建训练任务',exact:true}).locator('.train428-footer .btn.primary')).toBeEnabled();
  expect(await page.evaluate(()=>window.TrainingSubmitRuntime.state().readiness.ready)).toBe(false);
});

test('a real partial delete keeps the failed material in the draft and never unlocks admission by arithmetic',async({page,request})=>{
  const fx=await fixture(page,request);
  await expect(page.getByRole('dialog',{name:'训练暂不可开始',exact:true})).toBeVisible();
  page.once('dialog',dialog=>dialog.accept());
  const task=await page.evaluate(ids=>window.runMaterialBatch62('DELETE_INDEX',{scope:'SELECTED',imageIds:ids}),fx.images.slice(0,38).map(x=>x.id));
  runWorker(fx.project.id,task.task_id,{driftImageId:fx.images[0].id,status:'PARTIAL_SUCCESS'});
  await expect.poll(()=>page.evaluate(()=>window.TrainingDraftRuntime.current().materialIds.length)).toBe(3);
  expect(await page.evaluate(()=>window.TrainingDraftRuntime.current().materialIds)).toContain(fx.images[0].id);
  await expect.poll(()=>page.evaluate(()=>window.TrainingMaterialSummaryRuntime.compatibilityFor().ready)).toBe(false);
  await page.getByRole('dialog',{name:'训练暂不可开始',exact:true}).getByRole('button',{name:'返回训练配置',exact:true}).click();
  let posts=0;page.on('request',r=>{if(r.url().endsWith('/train/start')&&r.method()==='POST')posts++});
  await page.getByRole('dialog',{name:'创建训练任务',exact:true}).getByRole('button',{name:'开始训练',exact:true}).click();
  await expect(page.getByRole('dialog',{name:'训练暂不可开始',exact:true})).toBeVisible();
  await expect.poll(()=>page.evaluate(()=>window.TrainingMaterialSummaryRuntime.compatibilityFor().ready)).toBe(true);
  expect(posts).toBe(0);
  expect(await page.evaluate(()=>window.TrainingMaterialSummaryRuntime.compatibilityFor().compatible)).toBe(false);
  await expect(page.getByRole('dialog',{name:'创建训练任务',exact:true}).locator('.train428-footer .btn.primary')).toBeEnabled();
  expect(await page.evaluate(()=>window.TrainingSubmitRuntime.state().readiness.ready)).toBe(false);
  const results=await(await request.get(`/api/v62/projects/${fx.project.id}/material-batches/${task.task_id}/results`)).json();
  expect(results.succeeded_image_ids).toHaveLength(37);expect(results.items.filter(item=>item.item_state==='failed').map(item=>item.image_id)).toEqual([fx.images[0].id]);
});

test('the normal dataset bulk toolbar exposes project clear without any administrator role',async({page,request})=>{
  await fixture(page,request);
  await page.getByRole('dialog',{name:'训练暂不可开始',exact:true}).getByRole('button',{name:'返回训练配置',exact:true}).click();
  await page.getByRole('dialog',{name:'创建训练任务',exact:true}).getByRole('button',{name:'关闭',exact:true}).click();
  await page.getByRole('button',{name:/数据集/}).click();
  await page.getByRole('button',{name:'批量操作',exact:true}).click();
  await expect(page.getByRole('button',{name:'清空项目素材库',exact:true})).toBeVisible();
});

test('a late accepted deletion never attaches its result to a replacement training draft',async({page,request})=>{
  const fx=await fixture(page,request);
  await expect(page.getByRole('dialog',{name:'训练暂不可开始',exact:true})).toBeVisible();
  let release,entered;
  const gate=new Promise(resolve=>{release=resolve}),started=new Promise(resolve=>{entered=resolve});
  await page.route(`**/api/v62/projects/${fx.project.id}/material-batches`,async route=>{
    if(route.request().method()!=='POST')return route.fallback();
    const response=await route.fetch();entered();await gate;await route.fulfill({response});
  });
  page.once('dialog',dialog=>dialog.accept());
  await page.evaluate(ids=>{window.pendingOldDeletion=window.runMaterialBatch62('DELETE_INDEX',{scope:'SELECTED',imageIds:ids})},fx.images.slice(0,38).map(x=>x.id));
  await started;
  const replacement=[fx.images[0].id,fx.images[38].id,fx.images[39].id];
  await page.evaluate(ids=>{
    const html=document.querySelector('.train429-create').outerHTML.replaceAll('train_aaaaaaaaaaaaaaaaaaaa','train_bbbbbbbbbbbbbbbbbbbb');
    while(document.querySelector('.modal:not(.hidden)'))window.closeModal();
    window.TrainingDraftRuntime.update({materialIds:ids});window.modal('后续训练配置',html,true);window.TrainingSubmitRuntime.updateReadiness();
    const complete=window.TrainingMaterialSummaryRuntime.onMaterialBatchCompleted;
    window.TrainingMaterialSummaryRuntime.onMaterialBatchCompleted=async task=>{const result=await complete(task);window.oldDeletionSettled=task.task_id;return result};
  },replacement);
  release();const task=await page.evaluate(()=>window.pendingOldDeletion);
  runWorker(fx.project.id,task.task_id);
  await expect.poll(()=>page.evaluate(()=>window.oldDeletionSettled)).toBe(task.task_id);
  expect(await page.evaluate(()=>window.TrainingDraftRuntime.current().materialIds)).toEqual(replacement);
  await expect(page.getByRole('dialog',{name:'后续训练配置',exact:true})).toBeVisible();
});

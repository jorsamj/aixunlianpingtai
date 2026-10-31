import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {test, expect} from '@playwright/test';

function isolatedPython(projectId, source) {
  const roots=fs.readdirSync(os.tmpdir()).filter(name=>name.startsWith('xjalgo-browser-')).map(name=>path.join(os.tmpdir(),name)).filter(root=>fs.existsSync(path.join(root,'projects',projectId)));
  expect(roots).toHaveLength(1);
  return execFileSync('python',['-c',source],{encoding:'utf8',env:{...process.env,MC_TRAIN_DATA_DIR:roots[0],MC_PLATFORM_VERSION:'browser-test',YOLO_CONFIG_DIR:path.join(roots[0],'ultralytics'),INTEGRITY_TEST_PROJECT:projectId}}).trim();
}

async function fixture(request) {
  const response=await request.post('/api/projects',{data:{name:`训练重复闭环-${Date.now()}`,labels:[{code:'person',display_name:'人员'},{code:'vehicle',display_name:'车辆'}]}});
  expect(response.ok()).toBeTruthy();const project=await response.json();
  const algorithm=await (await request.post(`/api/v12/projects/${project.id}/algorithms`,{data:{name:'真实冲突回归',algorithm_type:'yolo_ultralytics'}})).json();
  const ids=[];
  for(let i=0;i<7;i++){
    const buffer=execFileSync('python',['-c',`from PIL import Image; import io,sys; b=io.BytesIO(); Image.new('RGB',(160,90),(${40+i*20},120,210)).save(b,format='PNG'); sys.stdout.buffer.write(b.getvalue())`]);
    const upload=await request.post(`/api/projects/${project.id}/images`,{multipart:{files:{name:`sample-${i}.png`,mimeType:'image/png',buffer},dataset_id:'default'}});
    expect(upload.ok()).toBeTruthy();ids.push((await upload.json()).uploaded[0].id);
  }
  const result=JSON.parse(isolatedPython(project.id,`import os,json,app
from platform_core.annotation_repository import AnnotationRepository
from platform_core.task_runtime import TaskRecord,TaskKind,TaskStatus
from dataclasses import replace
p=os.environ['INTEGRITY_TEST_PROJECT']; m=app.material_store(p); ids=${JSON.stringify(ids)}
import sys
from contextlib import redirect_stdout
with redirect_stdout(sys.stderr):
 from ultralytics import YOLO
 model_dir=m.project_path/'models'; model_dir.mkdir(exist_ok=True)
 YOLO('yolo11n.yaml').save(str(model_dir/'yolo11n.pt'))
first=m.get(ids[0]); copy={k:v for k,v in first.items() if not k.startswith('annotation_')}; copy.update(id='duplicate-copy',filename='duplicate-copy.png'); m.upsert(copy); ids.append(copy['id'])
m.patch({i:{'processing_status':'processed'} for i in ids})
a=AnnotationRepository(m.project_path)
for i in ids:
 boxes=[{'label':'vehicle' if i=='duplicate-copy' else 'person','class_id':1 if i=='duplicate-copy' else 0,'x1':16,'y1':9,'x2':80,'y2':45}]
 if i not in (ids[0],'duplicate-copy'): boxes.append({'label':'vehicle','class_id':1,'x1':90,'y1':10,'x2':140,'y2':60})
 a.upsert(i,boxes,annotation_state='annotated',annotation_scope=['person','vehicle'])
payload={'algorithm_asset_id':${JSON.stringify(algorithm.algorithm.id)},'train_image_ids':ids,'train_labels':['person','vehicle'],'split_mode':'random_test_from_training_pool','experiment_percent':20,'validation_percent':20}
r=app.shared_task_repository(); artifacts=app.shared_task_artifacts(); task='train_browser_old_'+p
artifacts.atomic_write_json(task,'payload.json',payload)
r.create(replace(TaskRecord.new(task,p,TaskKind.TRAINING,'payload.json','isolated-history'),status=TaskStatus.FAILED,error='DUPLICATE_ANNOTATION_CONFLICT: original GT differs'),artifacts=artifacts)
from platform_core.remote_material_lifecycle import RemoteExecutionStagingLifecycle
def no_provider(project_id,reference):
 raise AssertionError('request-only cleanup must not access storage')
assert RemoteExecutionStagingLifecycle(r,artifacts,no_provider).cleanup_task(r.get(task))['status']=='NO_OBJECTS'
print(json.dumps({'ids':ids,'sha':first['content_sha256'],'oldTask':task,'history':payload}))
`));
  return {project,algorithmId:algorithm.algorithm.id,...result};
}

async function openDraft(page,f) {
  await page.route('**/api/v53/bootstrap/snapshot**',async route=>{const url=new URL(route.request().url());url.searchParams.set('preferred_project_id',f.project.id);await route.fallback({url:url.toString()})});
  // Only resource discovery is substituted; compatibility, GT, content and admission stay real.
  await page.route('**/api/training_options**',route=>route.fulfill({json:{targets:[{id:'duplicate-cpu',name:'隔离 CPU',type:'local',framework:'ultralytics',status:'ready',algorithms:[{key:'yolo_detect',name:'Detect',base_model:'yolo11n.pt',default_epochs:1,default_imgsz:640,default_batch:1}],base_models:[{value:'yolo11n.pt',label:'YOLO11n',model_status:'FOUND'}]}]}}));
  await page.route('**/api/system/recommendation',route=>route.fulfill({json:{device:'cpu',batch:1,workers:0}}));
  await page.route('**/api/v62/training-devices',route=>route.fulfill({json:{recommended:'cpu',options:[{id:'cpu',label:'CPU',available:true}]}}));
  await page.addInitScript(()=>localStorage.setItem('mc_train_ui_state_v34',JSON.stringify({page:'算法列表'})));
  await page.setViewportSize({width:1366,height:768});await page.goto('/');
  await expect.poll(()=>page.evaluate(()=>state.uiReady===true)).toBe(true);
  await page.locator('[data-algorithm-card]',{hasText:'真实冲突回归'}).getByRole('button',{name:'训练',exact:true}).click();
  await expect(page.getByRole('dialog',{name:/创建训练任务/})).toBeVisible();
  await page.evaluate(f=>{window.TrainingDraftRuntime.update({algorithmId:f.algorithmId,newLabelCodes:['person','vehicle'],materialIds:f.ids,splitMode:'random_test_from_training_pool',experimentPercent:20,validationPercent:20});},f);
  await page.getByRole('dialog',{name:'创建训练任务',exact:true}).locator('button[data-training-step="3"]').click();
  await page.getByRole('button',{name:'开始训练',exact:true}).click();
  await expect.poll(()=>page.evaluate(()=>window.TrainingMaterialSummaryRuntime.compatibilityFor().issue_count)).toBe(2);
  await page.getByRole('dialog',{name:'训练暂不可开始',exact:true}).getByRole('button',{name:'返回训练配置',exact:true}).click();
}

async function evidence(page,testInfo,name){await page.screenshot({path:testInfo.outputPath(`${name}.png`)});}

function runIsolatedBatch(projectId,taskId,expectedStatus='SUCCEEDED'){
  isolatedPython(projectId,`import app,json
from contextlib import closing
from platform_core.task_runtime import Scheduler,TaskKind
from platform_core.material_batches import MaterialBatchHandler
r=app.shared_task_repository(); target=${JSON.stringify(taskId)}; capability='test.training-governance.'+target
with closing(r._connect()) as database:
 row=database.execute('SELECT project_id,status,required_capabilities FROM tasks WHERE task_id=?',(target,)).fetchone()
 assert row['project_id']==${JSON.stringify(projectId)} and row['status']=='QUEUED' and json.loads(row['required_capabilities'])==['materials.batch']
 database.execute('UPDATE tasks SET required_capabilities=? WHERE task_id=?',(json.dumps([capability]),target));database.commit()
s=Scheduler(r,app.shared_task_artifacts(),'training-governance-browser',{TaskKind.MATERIAL_BATCH:MaterialBatchHandler(app.DATA_DIR)},{capability},lease_seconds=60)
assert s.run_once()
assert r.get(target).status.value==${JSON.stringify(expectedStatus)}`);
}

test('training conflict selection uses shared safe preview, keeps selection on failure, and completes real deletion', async({page,request},testInfo)=>{
  const f=await fixture(request);await openDraft(page,f);
  await page.evaluate(()=>window.TrainingMaterialSummaryRuntime.openCompatibilityIssues());
  const root=page.locator('[data-training-compatibility-dialog]');
  await expect(root.getByRole('button',{name:'全选当前页',exact:true})).toBeVisible();
  await root.getByRole('button',{name:'全选当前页',exact:true}).click();
  await expect(root.locator('[data-governance-selected]')).toContainText('已选 2 张');
  await root.getByRole('button',{name:'全选当前筛选结果',exact:true}).click();
  await root.locator('[data-governance-check="duplicate-copy"]').uncheck();
  await expect(root.locator('[data-governance-selected]')).toContainText('已选 1 张');
  await root.getByRole('button',{name:'取消全选',exact:true}).click();
  await root.locator('[data-duplicate-compare]').first().click();
  await page.locator(`[data-conflict-keeper="${f.ids[0]}"]`).click();
  await page.locator('[data-comparison-back]').click();
  await page.locator('#trainingCompatibilityQuery').fill('duplicate-copy');
  await page.getByRole('button',{name:'筛选',exact:true}).click();
  await expect(page.locator('[data-governance-check]')).toHaveCount(1);
  await page.locator('[data-governance-check="duplicate-copy"]').check();
  const audit=await request.post(`/api/v62/projects/${f.project.id}/material-integrity/audits`);
  const auditId=(await audit.json()).task_id;
  runIsolatedBatch(f.project.id,auditId);
  await page.route('**/training-plans',async route=>route.fulfill({status:503,json:{detail:{message:'隔离模拟预检失败：选择应保留'}}}),{times:1});
  await page.getByRole('button',{name:'删除已选 · 安全预览',exact:true}).click();
  await expect(page.locator('[data-governance-error]')).toContainText('选择应保留');
  await expect(page.locator('[data-governance-check="duplicate-copy"]')).toBeChecked();
  await page.getByRole('button',{name:'删除已选 · 安全预览',exact:true}).click();
  await expect(page.locator('.material-integrity47-plan')).toContainText('计划删索引');
  await expect(page.getByRole('button',{name:'确认删除 1 条索引',exact:true})).toBeVisible();
  await evidence(page,testInfo,'training-shared-deletion-preview');
  await page.getByRole('button',{name:'返回选择 · 保留勾选',exact:true}).click();
  await expect(page.locator('#trainingCompatibilityQuery')).toHaveValue('duplicate-copy');
  await expect(page.locator('[data-governance-check="duplicate-copy"]')).toBeChecked();
  await page.getByRole('button',{name:'删除已选 · 安全预览',exact:true}).click();
  await expect(page.getByRole('button',{name:'确认删除 1 条索引',exact:true})).toBeVisible();
  await page.setViewportSize({width:375,height:812});await evidence(page,testInfo,'training-shared-deletion-mobile');
  await page.getByRole('button',{name:'确认删除 1 条索引',exact:true}).click();
  await expect(page.locator('#materialIntegrityTask47')).toContainText('排队中');
  const taskId=await page.evaluate(()=>state.materialIntegrityTask47.task_id);
  await evidence(page,testInfo,'training-shared-deletion-queued');
  runIsolatedBatch(f.project.id,taskId);
  await expect(page.locator('#materialIntegrityTask47')).toContainText('实际删除索引 1');
  await evidence(page,testInfo,'training-shared-deletion-completed');
  await page.getByRole('button',{name:'返回训练冲突 · 重新检查当前数据',exact:true}).click();
  await expect(page.locator('[data-training-compatibility-dialog]')).toContainText('当前筛选没有问题素材');
  const history=JSON.parse(isolatedPython(f.project.id,`import json,app; print(json.dumps(app.shared_task_artifacts().read_json(${JSON.stringify(f.oldTask)},'payload.json')))`));
  expect(history).toEqual(f.history);
});

test('historical 99-page governance selection stays server-side and survives paging',async({page,request},testInfo)=>{
  const f=await fixture(request);await openDraft(page,f);
  isolatedPython(f.project.id,`import app,json
from platform_core.annotation_repository import AnnotationRepository
m=app.material_store(${JSON.stringify(f.project.id)}); source=m.get(${JSON.stringify(f.ids[0])}); a=AnnotationRepository(m.project_path)
extra=[f'page-copy-{i:04}' for i in range(2374)]
m.upsert_many([{**{k:v for k,v in source.items() if not k.startswith('annotation_')},'id':i,'filename':i+'.png'} for i in extra])
for offset in range(0,len(extra),500):
 a.upsert_many([{'image_id':i,'annotation_state':'annotated','annotation_scope':['person','vehicle'],'boxes':[{'label':'vehicle','class_id':1,'x1':16,'y1':9,'x2':80,'y2':45}]} for i in extra[offset:offset+500]])
artifacts=app.shared_task_artifacts(); old=artifacts.read_json(${JSON.stringify(f.oldTask)},'payload.json');old['train_image_ids']+=extra;artifacts.atomic_write_json(${JSON.stringify(f.oldTask)},'payload.json',old)`);
  await page.evaluate(task=>window.TrainingMaterialSummaryRuntime.openTaskDiagnosis(task),f.oldTask);
  const root=page.locator('[data-training-compatibility-dialog]');
  await expect(root).toContainText('第 1 / 99 页');
  const first=await root.locator('[data-governance-check]').first().getAttribute('data-governance-check');
  await root.locator('[data-governance-check]').first().check();
  await root.getByRole('button',{name:'下一页问题',exact:true}).click();
  await root.locator('[data-governance-check]').first().check();
  await expect(root.locator('[data-governance-selected]')).toContainText('已选 2 张');
  await root.getByRole('button',{name:'上一页问题',exact:true}).click();
  await expect(root.locator(`[data-governance-check="${first}"]`)).toBeChecked();
  await root.getByRole('button',{name:'全选当前筛选结果',exact:true}).click();
  await expect(root.locator('[data-governance-selected]')).toContainText('已选 2376 张');
  await root.locator(`[data-governance-check="${first}"]`).uncheck();
  await expect(root.locator('[data-governance-selected]')).toContainText('已选 2375 张');
  await evidence(page,testInfo,'training-cross-99-page-selection');
  const audit=await request.post(`/api/v62/projects/${f.project.id}/material-integrity/audits`);
  runIsolatedBatch(f.project.id,(await audit.json()).task_id);
  const result=page.waitForResponse(r=>r.url().endsWith('/training-plans'));
  await root.getByRole('button',{name:'删除已选 · 安全预览',exact:true}).click();
  const response=await result;expect(response.status()).toBe(201);
  const selection=response.request().postDataJSON();
  expect(selection.all_filtered).toBe(true);expect(selection.image_ids).toEqual([]);expect(selection.excluded_image_ids).toEqual([first]);
  expect(JSON.stringify(selection).length).toBeLessThan(2000);
  const plan=await response.json();expect(plan.selected_count).toBe(2375);expect(plan.delete_count).toBe(2375);expect(plan.manual_required_count).toBe(0);
  await expect(page.getByRole('button',{name:'确认删除 2375 条索引',exact:true})).toBeVisible();
});

test('a late real GT comparison cannot reopen over a newer business modal',async({page,request})=>{
  const f=await fixture(request);await openDraft(page,f);
  await page.evaluate(()=>window.TrainingMaterialSummaryRuntime.openCompatibilityIssues());
  let release,entered;
  const gate=new Promise(resolve=>{release=resolve}),started=new Promise(resolve=>{entered=resolve});
  await page.route('**/material-integrity/gt-comparison',async route=>{const response=await route.fetch();entered();await gate;await route.fulfill({response})});
  await page.locator('[data-duplicate-compare]').first().click();await started;
  await page.evaluate(()=>window.modal('其他业务窗口','<div data-new-business>新窗口内容保持</div>',true));
  const settled=page.waitForResponse(response=>response.url().endsWith('/gt-comparison'));release();await settled;
  await expect(page.getByRole('dialog',{name:'其他业务窗口',exact:true})).toContainText('新窗口内容保持');
  await expect(page.locator('.training-duplicate-comparison')).toHaveCount(0);
  expect(await page.evaluate(()=>[...document.querySelectorAll('.modal:not(.hidden)')].at(-1).querySelector('.modal-title').textContent)).toBe('其他业务窗口');
});

test('changed GT invalidates prior manual keeper and cross-role conflicts still allow visual review',async({page,request})=>{
  const f=await fixture(request);await openDraft(page,f);
  await page.evaluate(()=>window.TrainingMaterialSummaryRuntime.openCompatibilityIssues());
  await page.locator('[data-duplicate-compare]').first().click();
  await page.locator(`[data-conflict-keeper="${f.ids[0]}"]`).click();
  await page.locator('[data-comparison-back]').click();
  isolatedPython(f.project.id,`import app
from platform_core.annotation_repository import AnnotationRepository
a=AnnotationRepository(app.project_dir(${JSON.stringify(f.project.id)}));a.upsert('duplicate-copy',[{'label':'vehicle','class_id':1,'x1':17,'y1':9,'x2':80,'y2':45}],annotation_state='annotated',annotation_scope=['person','vehicle'])`);
  await page.locator('[data-training-recheck]').click();
  await page.locator('[data-governance-check="duplicate-copy"]').check();
  await page.locator('[data-governance-delete-mode]').selectOption('KEEP_ONE');
  const audit=await request.post(`/api/v62/projects/${f.project.id}/material-integrity/audits`);runIsolatedBatch(f.project.id,(await audit.json()).task_id);
  const preview=page.waitForResponse(r=>r.url().endsWith('/training-plans'));
  await page.getByRole('button',{name:'删除已选 · 安全预览',exact:true}).click();
  const result=await(await preview).json();expect(result.delete_count).toBe(0);expect(result.manual_required_count).toBe(1);
  await expect(page.locator('.material-integrity47-zero-delete')).toContainText('没有可安全删除的素材');
  await page.getByRole('button',{name:'返回选择 · 保留勾选',exact:true}).click();
  await page.evaluate(f=>{window.TrainingDraftRuntime.update({materialIds:f.ids.filter(id=>id!=='duplicate-copy'),testMaterialIds:['duplicate-copy'],splitMode:'independent_test_set',experimentPercent:null});},f);
  await page.evaluate(async()=>{await window.TrainingMaterialSummaryRuntime.refreshCompatibility({force:true});window.TrainingMaterialSummaryRuntime.openCompatibilityIssues()});
  await expect(page.locator('[data-conflict-exclude]').first()).toBeEnabled();
  await expect(page.locator('[data-duplicate-compare]').first()).toBeEnabled();
  await page.locator('[data-duplicate-compare]').first().click();
  await expect(page.locator('.training-duplicate-comparison .material-integrity47-grid img')).toHaveCount(2);
  await expect(page.locator('.training-duplicate-comparison [data-gt-overlay] img')).toHaveCount(1);
  for(const button of await page.locator('.training-duplicate-comparison [data-conflict-exclude]').all())await expect(button).toBeEnabled();
  await page.locator('[data-comparison-back]').click();
  await page.getByRole('button',{name:'全选当前页',exact:true}).click();
  let release,entered;
  const gate=new Promise(resolve=>{release=resolve}),started=new Promise(resolve=>{entered=resolve});
  await page.route('**/training-plans',async route=>{const response=await route.fetch();entered();await gate;await route.fulfill({response})},{times:1});
  await page.getByRole('button',{name:'删除已选 · 安全预览',exact:true}).click();await started;
  await page.locator('[data-conflict-review]').first().click();
  const workbench=page.getByRole('dialog',{name:'图片标注工作台',exact:true});await expect(workbench).toBeVisible();
  const settled=page.waitForResponse(r=>r.url().endsWith('/training-plans'));release();await settled;
  await expect(workbench).toBeVisible();await expect(page.locator('.material-integrity47-plan')).toHaveCount(0);
});

test('partial deletion preserves failed server-frozen selection and requires a fresh frozen preview',async({page,request},testInfo)=>{
  const f=await fixture(request);await openDraft(page,f);
  isolatedPython(f.project.id,`import app
from platform_core.annotation_repository import AnnotationRepository
m=app.material_store(${JSON.stringify(f.project.id)});a=AnnotationRepository(m.project_path);source=m.get('duplicate-copy')
m.upsert({**{k:v for k,v in source.items() if not k.startswith('annotation_')},'id':'duplicate-second','filename':'duplicate-second.png'})
a.upsert('duplicate-second',[{'label':'vehicle','class_id':1,'x1':16,'y1':9,'x2':80,'y2':45}],annotation_state='annotated',annotation_scope=['person','vehicle'])`);
  await page.evaluate(async()=>{
    const draft=window.TrainingDraftRuntime.current();window.TrainingDraftRuntime.update({materialIds:[...draft.materialIds,'duplicate-second']});
    await window.TrainingMaterialSummaryRuntime.refreshCompatibility({force:true});window.TrainingMaterialSummaryRuntime.openCompatibilityIssues();
  });
  await page.locator('[data-duplicate-compare]').first().click();
  const keeper=await page.locator('[data-conflict-keeper]').first().getAttribute('data-conflict-keeper');
  await page.locator('[data-conflict-keeper]').first().click();await page.locator('[data-comparison-back]').click();
  await page.getByRole('button',{name:'全选当前筛选结果',exact:true}).click();
  await page.locator('[data-governance-delete-mode]').selectOption('KEEP_ONE');
  const audit=await request.post(`/api/v62/projects/${f.project.id}/material-integrity/audits`);runIsolatedBatch(f.project.id,(await audit.json()).task_id);
  await page.getByRole('button',{name:'删除已选 · 安全预览',exact:true}).click();
  await page.getByRole('button',{name:'确认删除 2 条索引',exact:true}).click();
  await expect(page.locator('#materialIntegrityTask47')).toContainText('排队中');
  const taskId=await page.evaluate(()=>state.materialIntegrityTask47.task_id);
  const failedId=keeper===f.ids[0]?'duplicate-second':f.ids[0];
  isolatedPython(f.project.id,`import app
from platform_core.annotation_repository import AnnotationRepository
a=AnnotationRepository(app.project_dir(${JSON.stringify(f.project.id)}));a.upsert(${JSON.stringify(failedId)},[{'label':'person','class_id':0,'x1':19,'y1':9,'x2':80,'y2':45}],annotation_state='annotated',annotation_scope=['person','vehicle'])`);
  runIsolatedBatch(f.project.id,taskId,'PARTIAL_SUCCESS');
  await expect(page.locator('#materialIntegrityTask47')).toContainText('部分成功');
  await expect(page.locator('#materialIntegrityTask47')).toContainText('实际删除索引 1');
  await evidence(page,testInfo,'training-shared-deletion-partial');
  await page.getByRole('button',{name:'返回训练冲突 · 重新检查当前数据',exact:true}).click();
  await expect(page.locator('[data-governance-selected]')).toContainText('原任务未删除 1 张');
  const freshAudit=await request.post(`/api/v62/projects/${f.project.id}/material-integrity/audits`);runIsolatedBatch(f.project.id,(await freshAudit.json()).task_id);
  const response=page.waitForResponse(r=>r.url().endsWith('/training-plans'));
  await page.getByRole('button',{name:'删除已选 · 安全预览',exact:true}).click();
  const reply=await response;expect(reply.request().postDataJSON().previous_execution_task_id).toBe(taskId);
  const plan=await reply.json();expect(plan.selected_count).toBe(1);expect(plan.delete_count).toBe(1);expect(plan.manual_required_count).toBe(0);
});

test('real duplicate GT comparison edits the original annotation and rechecks before admission',async({page,request},testInfo)=>{
  const f=await fixture(request);await openDraft(page,f);
  const trainPosts=[];page.on('request',r=>{if(r.url().endsWith('/train/start')&&r.method()==='POST')trainPosts.push(r.postDataJSON())});
  await expect(page.getByRole('button',{name:'开始训练',exact:true})).toBeEnabled();
  await page.evaluate(()=>window.TrainingMaterialSummaryRuntime.openCompatibilityIssues());
  await page.locator('[data-duplicate-compare]').first().click();
  const comparison=page.locator('.training-duplicate-comparison');await expect(comparison.locator('.material-integrity47-grid > article')).toHaveCount(2);
  await expect(comparison).toContainText(f.sha);await expect(comparison.locator('.material-integrity47-grid svg')).toHaveCount(2);
  await expect(comparison.locator('[data-gt-overlay] svg')).toHaveCount(1);
  for(const img of await comparison.locator('img').all())await expect.poll(()=>img.evaluate(el=>el.complete&&el.naturalWidth)).toBe(160);
  await evidence(page,testInfo,'comparison-desktop');await page.setViewportSize({width:375,height:812});await evidence(page,testInfo,'comparison-mobile');await page.setViewportSize({width:1366,height:768});
  await comparison.locator('[data-conflict-review="duplicate-copy"]').click();
  const workbench=page.getByRole('dialog',{name:'图片标注工作台',exact:true});await expect(workbench.locator('#annSaveState')).toHaveText('已保存');
  await expect(workbench.locator('#annBoxes select')).toHaveValue('1');await evidence(page,testInfo,'annotation-before');
  await workbench.locator('#annBoxes select').selectOption('0');await workbench.getByRole('button',{name:'保存并继续',exact:true}).click();
  await expect(workbench.locator('#annSaveState')).toHaveText('已保存 · 1框');await evidence(page,testInfo,'annotation-after');
  const saved=await (await request.get(`/api/projects/${f.project.id}/annotations/duplicate-copy`)).json();expect(saved.boxes[0].label).toBe('person');expect(saved.boxes[0].x1).toBe(16);
  await workbench.getByRole('button',{name:'关闭',exact:true}).click();
  await expect.poll(()=>page.evaluate(()=>window.TrainingMaterialSummaryRuntime.compatibilityFor().compatible)).toBe(true);
  await evidence(page,testInfo,'precheck-resolved');expect(trainPosts).toHaveLength(0);
  await page.getByRole('button',{name:'返回训练配置 · 保留草稿',exact:true}).click();
  const accepted=page.waitForResponse(r=>r.url().endsWith('/train/start')&&r.request().method()==='POST');
  await page.getByRole('dialog',{name:'创建训练任务',exact:true}).locator('button[data-training-step="3"]').click();
  await page.getByRole('button',{name:'开始训练',exact:true}).click();
  // Corrected duplicate GT leaves two single-category positives. The final
  // sample-coverage review is required, but no negative receipt is created.
  const confirmation=page.getByRole('dialog',{name:'确认本次训练样本',exact:true});
  await expect(confirmation).toContainText('部分类别覆盖');
  await confirmation.getByRole('button',{name:'确认并创建',exact:true}).click();
  const admission=await accepted;expect(admission.ok(),await admission.text()).toBeTruthy();expect(trainPosts).toHaveLength(1);
  const history=JSON.parse(isolatedPython(f.project.id,`import json,app; print(json.dumps(app.shared_task_artifacts().read_json(${JSON.stringify(f.oldTask)},'payload.json')))`));expect(history).toEqual(f.history);
});

test('explicit exclusion remains auditable, stale revisions reject admission, and failed history stays distinct',async({page,request},testInfo)=>{
  const f=await fixture(request);await openDraft(page,f);
  const before=await (await request.get(`/api/projects/${f.project.id}/annotations/duplicate-copy`)).json();
  await page.evaluate(()=>window.TrainingMaterialSummaryRuntime.openCompatibilityIssues());page.once('dialog',dialog=>dialog.accept());await page.locator('[data-conflict-exclude="duplicate-copy"]').click();
  await expect.poll(()=>page.evaluate(()=>window.TrainingMaterialSummaryRuntime.compatibilityFor().compatible)).toBe(true);
  const draft=await page.evaluate(()=>window.TrainingDraftRuntime.current());expect(draft.duplicateReview.excluded_image_ids).toEqual(['duplicate-copy']);expect(draft.duplicateReview.original_train_image_ids).toEqual(f.ids);
  const payload={algorithm_asset_id:f.algorithmId,framework:'ultralytics',model:'yolo11n.pt',train_labels:['person','vehicle'],train_image_ids:draft.materialIds,split_mode:draft.splitMode,experiment_percent:20,validation_percent:20,duplicate_review:draft.duplicateReview,device:'cpu'};
  const accepted=await request.post(`/api/v12/projects/${f.project.id}/train/start`,{data:payload});expect(accepted.ok(),await accepted.text()).toBeTruthy();
  const admitted=await accepted.json();const taskId=admitted.task_id||admitted.task?.task_id;
  const stored=JSON.parse(isolatedPython(f.project.id,`import json,app; print(json.dumps(app.shared_task_artifacts().read_json(${JSON.stringify(taskId)},'payload.json')))`));expect(stored.duplicate_review.excluded_image_ids).toEqual(['duplicate-copy']);
  expect(await (await request.get(`/api/projects/${f.project.id}/annotations/duplicate-copy`)).json()).toEqual(before);
  isolatedPython(f.project.id,`import os,app; from platform_core.annotation_repository import AnnotationRepository; a=AnnotationRepository(app.project_dir(os.environ['INTEGRITY_TEST_PROJECT'])); a.upsert('duplicate-copy',[{'label':'vehicle','class_id':1,'x1':17,'y1':9,'x2':80,'y2':45}],annotation_state='annotated',annotation_scope=['person','vehicle'])`);
  const stale=await request.post(`/api/v12/projects/${f.project.id}/train/start`,{data:payload});expect(stale.status()).toBe(409);expect(await stale.text()).toMatch(/revision/i);
  const diagnosis=await request.get(`/api/v62/projects/${f.project.id}/training-tasks/${f.oldTask}/input-diagnosis`);expect(diagnosis.ok(),await diagnosis.text()).toBeTruthy();expect((await diagnosis.json()).historical_evidence.status).toBe('insufficient_no_input_freeze');
  await page.evaluate(task=>window.TrainingMaterialSummaryRuntime.openTaskDiagnosis(task),f.oldTask);await expect(page.locator('[data-training-compatibility-dialog]')).toContainText('insufficient_no_input_freeze');
  await evidence(page,testInfo,'failed-task-diagnosis-desktop');await page.setViewportSize({width:375,height:812});await evidence(page,testInfo,'failed-task-diagnosis-mobile');
  const cross=await request.post(`/api/v62/projects/${f.project.id}/training-materials/compatibility`,{data:{...payload,duplicate_review:undefined,train_image_ids:f.ids.filter(id=>id!=='duplicate-copy'),test_image_ids:['duplicate-copy'],split_mode:'independent_test_set'}});expect(cross.ok()).toBeTruthy();expect((await cross.json()).items.some(item=>item.issue_type==='content_hash_leakage')).toBe(true);
});
test('verified import GT review shares comparison, freezes source scope and removes only reviewed conflicts',async({page,request},testInfo)=>{
  const f=await fixture(request);
  isolatedPython(f.project.id,`import app,json
from dataclasses import replace
from platform_core.task_runtime import TaskRecord,TaskKind,TaskStatus
from platform_core.storage.import_candidates import ImportCandidateStore
from platform_core.annotation_repository import AnnotationRepository
p=${JSON.stringify(f.project.id)};m=app.material_store(p);a=AnnotationRepository(m.project_path);r=app.shared_task_repository();art=app.shared_task_artifacts()
for image_id,task_id,target in [(${JSON.stringify(f.ids[0])},'review-approved','person'),('duplicate-copy','review-other','vehicle')]:
 gt=a.get(image_id);row=m.get(image_id);box=gt['boxes'][0]
 box.update(source_task_id=task_id,import_batch_id=task_id,source_class_id='0',canonical_label_id=target,canonical_project_class_id=0 if target=='person' else 1)
 a.upsert(image_id,[box],annotation_state='annotated',annotation_scope=['person','vehicle'])
 art.atomic_write_json(task_id,'payload.json',{})
 r.create(replace(TaskRecord.new(task_id,p,TaskKind.MATERIAL_IMPORT,'payload.json','isolated-import'),status=TaskStatus.SUCCEEDED),artifacts=art)
 details={'label_mapping':{'0':target,'1':'vehicle' if target=='person' else 'person'},'external_classes':[{'class_id':'0','name':'source-object'},{'class_id':'1','name':'source-other'}]}
 store=ImportCandidateStore(art.artifact_path(task_id,'scan/candidates.sqlite3'));store.upsert_many([{**row,'object_key':'source.png','filename':'source.png','status':'IMPORTABLE'}])
 store.manifest_many([{'object_key':'source.png','split':'train','yaml_key':'data.yaml'}])
 store.annotation_batch([], [{'object_key':'source.png','line_number':1,'class_id':0,'cx':48/160,'cy':27/90,'w':64/160,'h':36/90}], [])
 store.confirm(['source.png'],details=details);store.bind_index_batch([{'object_key':'source.png','image_id':image_id}]);store.mark_indexed([{'object_key':'source.png'}])
 art.atomic_write_json(task_id,'scan/confirmation.json',{**details,'accepted':True})
`);
  const keeperBefore=await (await request.get(`/api/projects/${f.project.id}/annotations/${f.ids[0]}`)).json();
  const auditId=(await (await request.post(`/api/v62/projects/${f.project.id}/material-integrity/audits`)).json()).task_id;
  runIsolatedBatch(f.project.id,auditId);
  await openDraft(page,f);await page.evaluate(()=>window.TrainingMaterialSummaryRuntime.openCompatibilityIssues());
  let releaseReview;const reviewGate=new Promise(resolve=>{releaseReview=resolve});
  let reviewIntercepted;const reviewStarted=new Promise(resolve=>{reviewIntercepted=resolve});
  await page.route('**/conflict-review?*',async route=>{const response=await route.fetch();reviewIntercepted();await reviewGate;await route.fulfill({response})},{times:1});
  await page.locator('[data-project-gt-review]').click();
  await reviewStarted;await page.evaluate(()=>closeModal());
  const lateReview=page.waitForResponse(response=>response.url().includes('/conflict-review?'));releaseReview();await lateReview;
  await page.waitForTimeout(100);await expect(page.locator('.gt-review-workbench')).toHaveCount(0);
  await page.evaluate(async()=>{await openMaterialIntegrityAudit47();await openGtConflictReview47()});
  let review=page.locator('.gt-review-workbench');await expect(review).toContainText('已证实映射差异');
  await expect(review.locator('[data-gt-review-group]')).toHaveCount(1);
  await review.locator('#gtReviewBatch47').selectOption('review-approved');await review.locator('[data-gt-review-filter]').click();
  await expect(review.locator('#gtReviewBatch47')).toHaveValue('review-approved');
  for(const [width,height] of [[1920,1080],[1440,900],[1366,768],[375,812]]){
    await page.setViewportSize({width,height});await expect(review).toBeVisible();
    expect(await review.evaluate(el=>el.scrollWidth<=el.clientWidth+1)).toBe(true);
    await evidence(page,testInfo,`gt-review-${width}`);
  }
  await page.setViewportSize({width:1366,height:768});
  await review.locator('[data-gt-review-open]').click();
  await expect(page.locator('[data-gt-evidence]')).toContainText('已核验导入确认映射不同');
  await expect(page.locator('[data-gt-overlay] img')).toBeVisible();
  const overlayLabels=page.locator('[data-gt-overlay] svg text');await expect(overlayLabels).toHaveCount(2);
  expect(await overlayLabels.nth(0).getAttribute('y')).not.toBe(await overlayLabels.nth(1).getAttribute('y'));
  await evidence(page,testInfo,'gt-overlay-source-comparison');
  await page.getByRole('button',{name:'返回批量审核 · 保留选择',exact:true}).click();
  review=page.locator('.gt-review-workbench');await review.locator('[data-gt-source-confirm]').check();
  await review.locator('[data-gt-review-source]').click();
  await expect(page.getByRole('button',{name:'确认删除 1 条索引',exact:true})).toBeVisible();
  await evidence(page,testInfo,'gt-source-review-frozen-preview');
  await page.getByRole('button',{name:'确认删除 1 条索引',exact:true}).click();
  await expect(page.locator('#materialIntegrityTask47')).toContainText('排队中');
  const taskId=await page.evaluate(()=>state.materialIntegrityTask47.task_id);runIsolatedBatch(f.project.id,taskId);
  await expect(page.locator('#materialIntegrityTask47')).toContainText('实际删除索引 1');
  expect(await (await request.get(`/api/projects/${f.project.id}/annotations/${f.ids[0]}`)).json()).toEqual(keeperBefore);
  const clean=await request.post(`/api/v62/projects/${f.project.id}/training-materials/compatibility`,{data:{algorithm_asset_id:f.algorithmId,
    train_image_ids:f.ids.filter(id=>id!=='duplicate-copy'),train_labels:['person','vehicle'],split_mode:'random_test_from_training_pool',experiment_percent:20,validation_percent:20}});
  expect(clean.ok(),await clean.text()).toBeTruthy();expect((await clean.json()).items.some(item=>item.issue_type==='duplicate_annotation_conflict')).toBe(false);
  const freshId=(await (await request.post(`/api/v62/projects/${f.project.id}/material-integrity/audits`)).json()).task_id;runIsolatedBatch(f.project.id,freshId);
  const result=await request.get(`/api/v62/projects/${f.project.id}/material-integrity/audits/${freshId}/conflict-review`);
  expect(result.ok()).toBeTruthy();expect((await result.json()).total_groups).toBe(0);
});


test('GT review can explicitly discard all unprotected conflict identities through existing frozen Worker',async({page,request})=>{
  const f=await fixture(request);
  const audit=await request.post(`/api/v62/projects/${f.project.id}/material-integrity/audits`);
  expect(audit.status()).toBe(202);
  const auditId=(await audit.json()).task_id;
  runIsolatedBatch(f.project.id,auditId);
  await openDraft(page,f);
  await page.evaluate(()=>closeModal());
  await page.evaluate(async()=>await window.openMaterialIntegrityAudit47());
  await page.locator('[data-gt-bulk-review]').click();
  const review=page.locator('.modal:not(.hidden) .gt-review-workbench');
  await expect(review.locator('[data-gt-review-discard]')).toHaveCount(1);
  await review.locator('[data-gt-review-discard]').check();
  await expect(review.locator('[data-gt-review-count]')).toContainText('已选批量放弃 1 组');
  page.once('dialog',dialog=>dialog.accept());
  await review.locator('[data-gt-review-discard-selected]').click();
  await expect.poll(()=>page.evaluate(()=>state.materialIntegrityPlan47?.discard_mode)).toBe(true);
  const plan=await page.evaluate(()=>state.materialIntegrityPlan47);
  expect(plan.discard_mode).toBe(true);
  expect(plan.delete_count).toBe(2);
  expect(plan.preview_groups[0].keeper_image_id).toBe('');
  const execute=page.getByRole('button',{name:'确认删除 2 条索引',exact:true});
  await expect(execute).toBeVisible();
  await execute.click();
  await expect(page.locator('#materialIntegrityTask47')).toContainText('排队中');
  const taskId=await page.evaluate(()=>state.materialIntegrityTask47.task_id);
  runIsolatedBatch(f.project.id,taskId);
  await expect(page.locator('#materialIntegrityTask47')).toContainText('实际删除索引 2');
  const remaining=JSON.parse(isolatedPython(f.project.id,`import app,json
m=app.material_store(${JSON.stringify(f.project.id)})
print(json.dumps([m.get(${JSON.stringify(f.ids[0])}) is None,m.get('duplicate-copy') is None]))`));
  expect(remaining).toEqual([true,true]);
});

test('late GT group response cannot replace the review after returning',async({page,request})=>{
  const f=await fixture(request);
  const task=(await (await request.post(`/api/v62/projects/${f.project.id}/material-integrity/audits`)).json()).task_id;
  runIsolatedBatch(f.project.id,task);
  await openDraft(page,f);
  await page.evaluate(()=>closeModal());
  await page.evaluate(()=>{void window.openMaterialIntegrityAudit47()});
  const reviewButton=page.locator('.modal:not(.hidden) [data-gt-bulk-review]');
  await expect(reviewButton).toBeVisible();
  await reviewButton.click();
  const review=page.locator('.modal:not(.hidden) .gt-review-workbench');
  await expect(review.locator('[data-gt-review-open]')).toHaveCount(1);
  const key=await review.locator('[data-gt-review-open]').first().getAttribute('data-gt-review-open');
  let releaseRequest,signalRequest;
  const requestGate=new Promise(resolve=>{releaseRequest=resolve});
  const requestStarted=new Promise(resolve=>{signalRequest=resolve});
  await page.route('**/material-integrity/audits/*/groups/*/items?*',async route=>{
    signalRequest();
    await requestGate;
    await route.continue();
  });
  await page.evaluate(args=>{
    window.__integrityDelayedGroup=window.openMaterialIntegrityGroup47(encodeURIComponent(args.task),encodeURIComponent(args.key));
  },{task,key});
  await requestStarted;
  await expect(page.locator('.modal:not(.hidden) [data-integrity-group-loading]')).toBeVisible();
  await page.evaluate(()=>{void window.openGtConflictReview47()});
  await expect(review.locator('[data-gt-review-open]')).toHaveCount(1);
  releaseRequest();
  await page.evaluate(()=>window.__integrityDelayedGroup);
  await expect(review).toBeVisible();
  await expect(page.locator('.modal:not(.hidden) .material-integrity47-group')).toHaveCount(0);
});

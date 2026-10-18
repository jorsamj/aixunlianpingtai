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
  await expect.poll(()=>page.evaluate(()=>window.TrainingMaterialSummaryRuntime.compatibilityFor().issue_count)).toBe(2);
}

async function evidence(page,testInfo,name){await page.screenshot({path:testInfo.outputPath(`${name}.png`)});}

test('real duplicate GT comparison edits the original annotation and rechecks before admission',async({page,request},testInfo)=>{
  const f=await fixture(request);await openDraft(page,f);
  const trainPosts=[];page.on('request',r=>{if(r.url().endsWith('/train/start')&&r.method()==='POST')trainPosts.push(r.postDataJSON())});
  await expect(page.getByRole('button',{name:'创建训练任务',exact:true})).toBeDisabled();
  await page.evaluate(()=>window.TrainingMaterialSummaryRuntime.openCompatibilityIssues());
  await page.locator('[data-duplicate-compare]').first().click();
  const comparison=page.locator('.training-duplicate-comparison');await expect(comparison.locator('.material-integrity47-grid > article')).toHaveCount(2);
  await expect(comparison).toContainText(f.sha);await expect(comparison.locator('svg')).toHaveCount(2);
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
  await page.getByRole('button',{name:'创建训练任务',exact:true}).click();const admission=await accepted;expect(admission.ok(),await admission.text()).toBeTruthy();expect(trainPosts).toHaveLength(1);
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

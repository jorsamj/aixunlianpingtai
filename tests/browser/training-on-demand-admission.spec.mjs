import {test, expect} from '@playwright/test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {execFileSync} from 'node:child_process';

const compatible={compatible:true,issue_count:0,affected_image_count:0,items:[],issue_counts:{},material_revision:1,annotation_revision:1};
const blocked={...compatible,compatible:false,issue_count:2,affected_image_count:2,issue_counts:{missing_annotation:1,duplicate_annotation_conflict:1}};
const training=page=>page.getByRole('dialog',{name:/创建训练任务/});
const diagnostic=page=>page.getByRole('dialog',{name:'训练暂不可开始',exact:true});
const start=page=>training(page).locator('.train428-footer .btn.primary');
const reason=page=>training(page).getByRole('button',{name:'查看不能训练的原因',exact:true});
function gate(){let resolve;const promise=new Promise(r=>resolve=r);return {promise,release:()=>resolve()};}

function isolatedPython(projectId,source){
  const roots=fs.readdirSync(os.tmpdir()).filter(name=>name.startsWith('xjalgo-browser-')).map(name=>path.join(os.tmpdir(),name)).filter(root=>fs.existsSync(path.join(root,'projects',projectId)));
  expect(roots).toHaveLength(1);
  return execFileSync('python',['-c',source],{encoding:'utf8',env:{...process.env,MC_TRAIN_DATA_DIR:roots[0],MC_PLATFORM_VERSION:'browser-test',YOLO_CONFIG_DIR:path.join(roots[0],'ultralytics')}}).trim();
}
function bmp(index){const b=Buffer.alloc(54+16*16*3,40+index*30);b.fill(0,0,54);b.write('BM');b.writeUInt32LE(b.length,2);b.writeUInt32LE(54,10);b.writeUInt32LE(40,14);b.writeInt32LE(16,18);b.writeInt32LE(16,22);b.writeUInt16LE(1,26);b.writeUInt16LE(24,28);return b;}

// Every scenario uses the formal algorithm-card entry, canonical Modal and real
// isolated project/GT records. Resource discovery is controlled (no GPU work).
// Lifecycle scenarios explicitly substitute compatibility / creation replies;
// the real-GT case below never substitutes the compatibility endpoint.
async function fixture(page,request,{realCompatibility=false,empty=false,conflict=false}={}){
  const project=await(await request.post('/api/projects',{data:{name:`按需准入-${Date.now()}-${Math.random()}`,labels:[{code:'smoke',display_name:'烟雾'}]}})).json();
  const created=await(await request.post(`/api/v12/projects/${project.id}/algorithms`,{data:{name:'按需准入隔离算法',algorithm_type:'yolo_ultralytics',industry:'测试'}})).json();
  const images=[];
  for(let i=0;i<3;i++){
    const response=await request.post(`/api/projects/${project.id}/images`,{multipart:{dataset_id:'default',files:{name:`demand-${i}.bmp`,mimeType:'image/bmp',buffer:bmp(i)}}});
    expect(response.ok()).toBeTruthy();const image=(await response.json()).uploaded[0];images.push(image);
    const annotation=await request.post(`/api/projects/${project.id}/annotations/${image.id}`,{data:{boxes:[{class_id:0,label:'smoke',x1:1,y1:1,x2:8,y2:8}],annotation_state:'annotated',reviewed_label_codes:['smoke'],expected_version:image.annotation_version,source_content_sha256:image.content_sha256}});
    expect(annotation.ok()).toBeTruthy();
  }
  const ids=images.map(row=>row.id);
  if(conflict){
    isolatedPython(project.id,`import app\nfrom platform_core.annotation_repository import AnnotationRepository\nm=app.material_store(${JSON.stringify(project.id)})\nrow={k:v for k,v in m.get(${JSON.stringify(ids[0])}).items() if not k.startswith('annotation_')}\nrow.update(id='demand-duplicate',filename='demand-duplicate.bmp');m.upsert(row)\na=AnnotationRepository(m.project_path)\na.upsert('demand-duplicate',[{'class_id':0,'label':'smoke','x1':2,'y1':2,'x2':12,'y2':12}],annotation_state='annotated',annotation_scope=['smoke'])\nm.patch({i:{'processing_status':'processed'} for i in ${JSON.stringify([...ids,'demand-duplicate'])}})`);
    ids.push('demand-duplicate');
  }
  await request.post(`/api/v52/projects/${project.id}/images/mark-ready`,{data:{image_ids:ids}});
  await page.route('**/api/v53/bootstrap/snapshot**',async route=>{const url=new URL(route.request().url());url.searchParams.set('preferred_project_id',project.id);await route.fallback({url:String(url)});});
  await page.route('**/api/training_options**',route=>route.fulfill({json:{targets:[{id:'demand-cpu',name:'隔离调度资源',scheduler_owned:true,type:'local',framework:'ultralytics',status:'ready',algorithms:[{key:'yolo_detect',name:'Detect',base_model:'yolo11n.pt',default_epochs:1,default_imgsz:640,default_batch:1}],base_models:[{value:'yolo11n.pt',label:'YOLO11n',model_status:'FOUND'}]}]}}));
  await page.route('**/api/system/recommendation',route=>route.fulfill({json:{device:'cpu',batch:1,workers:0}}));
  await page.route('**/api/v62/training-devices',route=>route.fulfill({json:{recommended:'cpu',options:[{id:'cpu',label:'CPU',available:true}]}}));
  const calls={checks:[],posts:[],lookups:[]};
  let check=route=>route.fulfill({json:compatible});
  let create=route=>route.fulfill({status:409,json:{detail:'隔离场景未授权创建'}});
  await page.route(`**/api/v62/projects/${project.id}/training-materials/compatibility`,async route=>{calls.checks.push(route.request().postDataJSON());if(realCompatibility)return route.continue();return check(route);});
  await page.route(`**/api/v12/projects/${project.id}/train/start`,async route=>{calls.posts.push(route.request().postDataJSON());return create(route);});
  await page.route(`**/api/v62/projects/${project.id}/tasks/*`,route=>{calls.lookups.push(route.request().url());return route.fulfill({status:404,json:{detail:'isolated unknown outcome'}});});
  await page.addInitScript(()=>localStorage.setItem('mc_train_ui_state_v34',JSON.stringify({page:'算法列表'})));
  await page.goto('/');await expect.poll(()=>page.evaluate(()=>state.uiReady===true)).toBe(true);
  await page.locator('[data-algorithm-card]',{hasText:'按需准入隔离算法'}).getByRole('button',{name:'训练',exact:true}).click();
  await expect(training(page)).toBeVisible();
  if(!empty){
    await page.evaluate(({algorithmId,ids})=>window.TrainingDraftRuntime.update({algorithmId,materialIds:ids,newLabelCodes:['smoke'],config:{model:'yolo11n.pt'}}),{algorithmId:created.algorithm.id,ids});
    await expect.poll(()=>page.evaluate(()=>window.TrainingMaterialSummaryRuntime.summaryReadyFor())).toBe(true);
    const label=training(page).locator('[data-training-label-code="smoke"]');if(await label.count())await label.check();
  }
  return {project,ids,algorithmId:created.algorithm.id,calls,setCheck:fn=>{check=fn;},setCreate:fn=>{create=fn;}};
}
async function assertQuiet(page,calls){
  await page.evaluate(()=>{for(let i=0;i<3;i++)window.TrainingSubmitRuntime.updateReadiness();});
  await page.waitForTimeout(180);
  expect(calls.checks).toHaveLength(0);expect(calls.posts).toHaveLength(0);
  await expect(diagnostic(page)).toHaveCount(0);await expect(reason(page)).toBeHidden();
}

test('formal first open and ordinary editing stay quiet even without selected materials',async({page,request},testInfo)=>{
  const f=await fixture(page,request,{empty:true});
  await assertQuiet(page,f.calls);
  await training(page).locator('[data-mode="quick"]').click();
  await expect(training(page).locator('[data-mode="quick"]')).toHaveAttribute('aria-pressed','true');
  await assertQuiet(page,f.calls);await expect(start(page)).toBeEnabled();await expect(start(page)).toHaveText('开始训练');
  await page.screenshot({path:testInfo.outputPath('quiet-formal-first-open.png')});
});

test('one click checks real GT, shows busy stages and creates exactly one durable task (controlled timing only)',async({page,request},testInfo)=>{
  const f=await fixture(page,request);await assertQuiet(page,f.calls);
  // Build local untrained weights from packaged architecture; never download,
  // claim a Worker lease, or execute training. Only real queued creation is tested.
  isolatedPython(f.project.id,`import app,sys\nfrom contextlib import redirect_stdout\nwith redirect_stdout(sys.stderr):\n from ultralytics import YOLO\n root=app.material_store(${JSON.stringify(f.project.id)}).project_path/'models';root.mkdir(exist_ok=True)\n YOLO('yolo11n.yaml').save(str(root/'yolo11n.pt'))`);
  const checkGate=gate(),postGate=gate();
  f.setCheck(async route=>{await checkGate.promise;await route.continue();});
  f.setCreate(async route=>{await postGate.promise;await route.continue();});
  await start(page).click();
  await expect(start(page)).toHaveText('正在检查训练条件…');await expect(start(page)).toBeDisabled();await expect(start(page)).toHaveAttribute('aria-busy','true');
  await expect(training(page).locator('[data-training-submit-feedback]')).toBeVisible();
  await expect(training(page).locator('[data-training-submit-feedback]')).toHaveCSS('opacity','1');
  await expect(training(page).locator('[data-training-submit-feedback]')).not.toContainText(/\d+%/);
  await page.screenshot({path:testInfo.outputPath('real-admission-checking.png')});
  await expect(reason(page)).toBeHidden();
  await page.evaluate(()=>{window.TrainingSubmitRuntime.submit();window.TrainingSubmitRuntime.submit();});
  await expect.poll(()=>f.calls.checks.length).toBe(1);expect(f.calls.posts).toHaveLength(0);
  checkGate.release();await expect.poll(()=>f.calls.posts.length).toBe(1);
  await expect(start(page)).toHaveText('正在创建训练任务…');await expect(start(page)).toBeDisabled();await expect(reason(page)).toBeHidden();
  postGate.release();await expect(training(page)).toHaveCount(0);
  expect(f.calls.posts).toHaveLength(1);expect(f.calls.posts[0].expected_material_revision).toBeDefined();
  await expect(diagnostic(page)).toHaveCount(0);
  expect(await page.evaluate(id=>(state.jobs||[]).filter(row=>String(row.task_id||row.id)===id).length,f.calls.posts[0].task_id)).toBe(1);
  const durable=JSON.parse(isolatedPython(f.project.id,`import json,app\nfrom contextlib import closing\nr=app.shared_task_repository();task=r.get(${JSON.stringify(f.calls.posts[0].task_id)})\nwith closing(r._connect()) as db:\n count=db.execute('SELECT count(*) FROM tasks WHERE project_id=? AND kind=?',(${JSON.stringify(f.project.id)},'TRAINING')).fetchone()[0]\nprint(json.dumps({'task_id':task.task_id,'status':task.status.value,'count':count,'project_id':task.project_id}))`));
  expect(durable).toEqual({task_id:f.calls.posts[0].task_id,status:'QUEUED',count:1,project_id:f.project.id});
  await testInfo.attach('real-durable-creation.json',{body:Buffer.from(JSON.stringify({durable,compatibilityRequests:f.calls.checks,creationRequests:f.calls.posts},null,2)),contentType:'application/json'});
});

test('real differing GT is fully diagnosed only after start and closing details preserves the draft',async({page,request},testInfo)=>{
  const f=await fixture(page,request,{realCompatibility:true,conflict:true});await assertQuiet(page,f.calls);
  const before=await page.evaluate(()=>window.TrainingDraftRuntime.current());
  await start(page).click();await expect(diagnostic(page)).toBeVisible();
  await expect(diagnostic(page)).toContainText('同图不同GT冲突');await expect(diagnostic(page)).toContainText('2');
  expect(f.calls.posts).toHaveLength(0);
  const truth=await page.evaluate(()=>window.TrainingMaterialSummaryRuntime.compatibilityFor());
  expect(truth.issue_counts.duplicate_annotation_conflict).toBe(2);
  await page.screenshot({path:testInfo.outputPath('real-gt-blockers.png')});
  await testInfo.attach('real-gt-compatibility.json',{body:Buffer.from(JSON.stringify(truth,null,2)),contentType:'application/json'});
  await diagnostic(page).getByRole('button',{name:'返回训练配置',exact:true}).click();
  expect(await page.evaluate(()=>window.TrainingDraftRuntime.current())).toEqual(before);
  await expect(reason(page)).toBeVisible();await reason(page).click();await expect(diagnostic(page)).toBeVisible();
});

test('all confirmed blockers appear together; edit expires the reason and next click rechecks (controlled API truth)',async({page,request})=>{
  const f=await fixture(page,request);f.setCheck(route=>route.fulfill({json:blocked}));
  await start(page).click();await expect(diagnostic(page)).toContainText('缺少正式标注');await expect(diagnostic(page)).toContainText('同图不同GT冲突');
  await diagnostic(page).getByRole('button',{name:'返回训练配置',exact:true}).click();await expect(reason(page)).toBeVisible();
  await training(page).locator('[data-mode="quick"]').click();await expect(reason(page)).toBeHidden();
  const checks=f.calls.checks.length;await page.waitForTimeout(150);expect(f.calls.checks).toHaveLength(checks);
  await start(page).click();await expect.poll(()=>f.calls.checks.length).toBe(checks+1);await expect(diagnostic(page)).toBeVisible();expect(f.calls.posts).toHaveLength(0);
});

for(const fault of ['HTTP 500','network disconnect','timeout']){
  test(`check ${fault} ends busy state and offers safe retry without business diagnosis (controlled fault)`,async({page,request})=>{
    const f=await fixture(page,request);const pending=gate();
    f.setCheck(async route=>{if(fault==='HTTP 500')return route.fulfill({status:500,json:{detail:'isolated check service unavailable'}});if(fault==='network disconnect')return route.abort('internetdisconnected');await pending.promise;await route.fulfill({json:compatible}).catch(()=>{});});
    if(fault==='timeout')await page.clock.install();
    await start(page).click();await expect.poll(()=>f.calls.checks.length).toBe(1);
    if(fault==='timeout')await page.clock.fastForward(30001);
    await expect(start(page)).toBeEnabled();await expect(start(page)).toHaveText('重新检查');await expect(start(page)).toHaveAttribute('aria-busy','false');await expect(diagnostic(page)).toHaveCount(0);await expect(reason(page)).toBeHidden();
    await expect(training(page)).toContainText(/失败|超时|重新检查/);expect(f.calls.posts).toHaveLength(0);
    f.setCheck(route=>route.fulfill({json:blocked}));pending.release();
    await start(page).click();await expect.poll(()=>f.calls.checks.length).toBe(2);await expect(diagnostic(page)).toBeVisible();expect(f.calls.posts).toHaveLength(0);
  });
}

for(const change of ['close','draft','project']){
  test(`late successful check after ${change} cannot create or reopen a modal (controlled delayed reply)`,async({page,request})=>{
    const f=await fixture(page,request);const pending=gate();let delivered=false;
    f.setCheck(async route=>{await pending.promise;await route.fulfill({json:compatible}).catch(()=>{});delivered=true;});
    await start(page).click();await expect.poll(()=>f.calls.checks.length).toBe(1);
    if(change==='close')await training(page).getByRole('button',{name:'关闭',exact:true}).click();
    if(change==='draft')await page.evaluate(()=>window.TrainingDraftRuntime.update({trainingMode:'quick',materialIds:[]}));
    if(change==='project'){
      const other=await(await request.post('/api/projects',{data:{name:`迟到隔离-${Date.now()}`}})).json();
      // Isolate project identity from the separate close scenario: leave the
      // original DOM alive so only the project guard can reject this reply.
      await page.evaluate(project=>{state.project=project;},other);
    }
    pending.release();await expect.poll(()=>delivered).toBe(true);await page.waitForTimeout(180);
    expect(f.calls.posts).toHaveLength(0);await expect(diagnostic(page)).toHaveCount(0);
    if(change==='close')await expect(training(page)).toHaveCount(0);
  });
}

test('backend rechecks after a passed frontend check and rejection never becomes success (controlled rejection)',async({page,request})=>{
  const f=await fixture(page,request);f.setCreate(route=>route.fulfill({status:409,json:{code:'DUPLICATE_ANNOTATION_CONFLICT',detail:'正式创建二次核验：GT 已变化'}}));
  await start(page).click();await expect.poll(()=>f.calls.posts.length).toBe(1);
  await expect(training(page)).toBeVisible();await expect(page.locator('body')).toContainText('GT 已变化');
  expect(await page.evaluate(id=>(state.jobs||[]).some(row=>String(row.task_id||row.id)===id),f.calls.posts[0].task_id)).toBe(false);
  await expect(page.locator('body')).not.toContainText('训练任务创建成功');
});

test('uncertain creation retains its task identity and blocks blind duplicate creation (controlled lost response)',async({page,request})=>{
  const f=await fixture(page,request);f.setCreate(route=>route.abort('failed'));
  const taskId=await training(page).locator('#tr429TaskId').inputValue();
  await start(page).click();await expect.poll(()=>f.calls.lookups.length).toBe(1);
  await expect(training(page)).toBeVisible();await expect(training(page)).toContainText(/创建结果尚未确认|核对创建结果/);
  await page.evaluate(()=>window.TrainingSubmitRuntime.submit());expect(f.calls.posts).toHaveLength(1);
  expect(f.calls.posts[0].task_id).toBe(taskId);await expect(training(page).locator('#tr429TaskId')).toHaveValue(taskId);
  await expect(reason(page)).toBeHidden();
});

test('a late backend rejection cannot attach old blockers to an edited draft in the same formal modal (controlled delayed 409)',async({page,request})=>{
  const f=await fixture(page,request);const pending=gate();let delivered=false;
  const staleMessage='隔离旧请求拒绝：GT 已变化，不得污染新配置';
  f.setCreate(async route=>{
    await pending.promise;
    await route.fulfill({status:409,json:{code:'DUPLICATE_ANNOTATION_CONFLICT',detail:staleMessage}});
    delivered=true;
  });
  await start(page).click();await expect.poll(()=>f.calls.posts.length).toBe(1);
  await expect(start(page)).toHaveText('正在创建训练任务…');
  await page.evaluate(()=>{window.originalPostingRoot=document.querySelector('.train429-create');});
  // Simulate a canonical configuration update while the original POST is in flight;
  // the visible submit overlay correctly prevents ordinary pointer edits.
  await page.evaluate(()=>window.TrainingDraftRuntime.update({trainingMode:'quick'}));
  expect(await page.evaluate(()=>window.TrainingDraftRuntime.current().trainingMode)).toBe('quick');
  pending.release();await expect.poll(()=>delivered).toBe(true);
  await expect(start(page)).toHaveAttribute('aria-busy','false');
  await expect(training(page)).toBeVisible();await expect(diagnostic(page)).toHaveCount(0);await expect(reason(page)).toBeHidden();
  await expect(training(page)).not.toContainText(staleMessage);
  expect(await page.evaluate(()=>window.originalPostingRoot===document.querySelector('.train429-create'))).toBe(true);
  expect(await page.evaluate(()=>window.TrainingDraftRuntime.current().trainingMode)).toBe('quick');
  expect(f.calls.posts).toHaveLength(1);
});

test('a confirmed unavailable fixed Benchmark is a business blocker without an invalid compatibility request',async({page,request})=>{
  const f=await fixture(page,request);
  const benchmarkReason='隔离固定 Benchmark 已撤销，请重新评测';
  // Simulate an already-selected benchmark becoming unavailable after initial
  // configuration. Its confirmed local truth must survive precheck ordering.
  await page.evaluate(({algorithmId,benchmarkReason})=>{
    state.trainingBenchmarkReuse={algorithm_id:algorithmId,available:false,loading:false,load_error:false,reason:benchmarkReason};
    window.TrainingDraftRuntime.update({benchmarkReuseEnabled:true});
  },{algorithmId:f.algorithmId,benchmarkReason});
  f.setCheck(route=>route.fulfill({status:500,json:{detail:'invalid fixed-Benchmark selection must not be sent'}}));
  await expect(reason(page)).toBeHidden();await start(page).click();
  await expect(diagnostic(page)).toBeVisible();
  await expect(diagnostic(page).locator('[data-admission-code="fixed-test-benchmark"]')).toContainText(benchmarkReason);
  await expect(diagnostic(page)).not.toContainText('检查失败');
  expect(f.calls.checks).toHaveLength(0);expect(f.calls.posts).toHaveLength(0);
  await diagnostic(page).getByRole('button',{name:'返回训练配置',exact:true}).click();
  await expect(reason(page)).toBeVisible();await expect(start(page)).toBeEnabled();
});

for (const recovered of [false,true]) test(`late ${recovered?'lookup-recovered':'direct'} creation success keeps the accepted task but cannot mark an edited form successful (controlled valid receipt)`,async({page,request})=>{
  const f=await fixture(page,request),pending=gate();
  await page.evaluate(()=>{const owner=window.TrainingTaskRuntime,accept=owner.acceptCreatedTask;window.acceptedDemandTasks=[];owner.acceptCreatedTask=function(task,...args){window.acceptedDemandTasks.push(task.task_id);return accept.call(this,task,...args);};});
  const task=()=>({task_id:f.calls.posts[0].task_id,kind:'TRAINING',task_type:'TRAINING',status:'QUEUED',persisted_status:'QUEUED',project_id:f.project.id,algorithm_id:f.algorithmId});
  f.setCreate(async route=>{await pending.promise;if(recovered)return route.abort('failed');return route.fulfill({json:{ok:true,task:task()}});});
  if(recovered)await page.route(`**/api/v62/projects/${f.project.id}/tasks/*`,route=>route.fulfill({json:{task:task()}}));
  await start(page).click();await expect.poll(()=>f.calls.posts.length).toBe(1);
  // Simulate a canonical configuration update while the original POST is in flight;
  // the visible submit overlay correctly prevents ordinary pointer edits.
  await page.evaluate(()=>window.TrainingDraftRuntime.update({trainingMode:'quick'}));
  pending.release();await expect(start(page)).toHaveAttribute('aria-busy','false');
  await expect(training(page)).toBeVisible();await expect(start(page)).toHaveText('开始训练');
  expect(await page.evaluate(()=>window.TrainingSubmitRuntime.state().lastStage)).toBe('idle');
  await expect(training(page).locator('[data-training-submit-feedback]')).not.toContainText('训练任务创建成功');
  expect(await page.evaluate(()=>window.acceptedDemandTasks)).toEqual([f.calls.posts[0].task_id]);
  expect(f.calls.posts).toHaveLength(1);await expect(reason(page)).toBeHidden();
});

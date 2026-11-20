import {test,expect} from '@playwright/test';
import {spawn,execFileSync} from 'node:child_process';
import {mkdtempSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createServer} from 'node:net';

test('原生单图决定按真实回执恢复，保留逐图范围、候选隔离和正式 GT',async({page,request})=>{
  test.setTimeout(90000);
  const data=mkdtempSync(join(tmpdir(),'ai-review-native-decision-'));
  const env={...process.env,MC_TRAIN_DATA_DIR:data,MC_PLATFORM_VERSION:'browser-test',
    MC_ALLOW_MULTIPLE_PROJECTS_FOR_TESTS:'1',YOLO_CONFIG_DIR:join(data,'ultralytics')};
  const socket=createServer();
  await new Promise(resolve=>socket.listen(0,'127.0.0.1',resolve));
  const port=socket.address().port;
  await new Promise(resolve=>socket.close(resolve));
  const origin='http://127.0.0.1:'+port;
  const server=spawn('python',['-m','uvicorn','app:app','--host','127.0.0.1','--port',String(port)],{env,windowsHide:true,stdio:'ignore'});
  try{
    await expect.poll(async()=>{try{return (await request.get(origin+'/api/health')).status()}catch{return 0}},{timeout:30000}).toBe(200);
    const projectResponse=await request.post(origin+'/api/projects',{data:{name:'原生单图审核隔离项目',labels:[
      {code:'fire',display_name:'明火'},{code:'smoke',display_name:'烟雾'},
    ]}});
    expect(projectResponse.ok()).toBeTruthy();
    const project=(await projectResponse.json()).id;
    const names=['decision-first.jpg','decision-ambiguous.jpg','decision-untouched.jpg'];
    const ids=[];
    for(const [index,name] of names.entries()){
      const buffer=execFileSync('python',['-c',"from PIL import Image;import io,sys;b=io.BytesIO();Image.new('RGB',(320,240),(int(sys.argv[1]),100,150)).save(b,format='JPEG');sys.stdout.buffer.write(b.getvalue())",String(50+70*index)]);
      const upload=await request.post(origin+'/api/projects/'+project+'/images',{multipart:{
        files:{name,mimeType:'image/jpeg',buffer},dataset_id:'default',
      }});
      expect(upload.ok()).toBeTruthy();
      ids.push((await upload.json()).uploaded[0].id);
    }
    const task='native-decision';
    const seed=[
      'import app, sys',
      'from platform_core.task_runtime import TaskRecord, TaskKind, TaskStatus',
      'from platform_core.annotation_candidates import CandidateStore',
      'project, task, *ids = sys.argv[1:]',
      'repository = app.shared_task_repository(); artifacts = app.shared_task_artifacts()',
      'materials = {id: app.material_store(project).get(id) for id in ids}',
      'labels = ["fire", "smoke"]; policy = "per_image_required"',
      'artifacts.atomic_write_json(task, "request.json", dict(labels=labels, review_scope_policy=policy, per_image_missing_review_scopes={id: labels for id in ids}, per_image_annotation_versions={id: int(app.read_annotation(project,id).get("version") or 0) for id in ids}, per_image_source_hashes={id: row["content_sha256"] for id, row in materials.items()}))',
      'repository.create(TaskRecord.new(task, project, TaskKind.AI_ANNOTATION, "request.json", "isolated"))',
      'store = CandidateStore(artifacts, task_id=task); store.initialize(labels=labels, total_images=len(ids))',
      'box = {"id":"f","label":"fire","x1":20,"y1":30,"x2":100,"y2":120}',
      'store.append_items([dict(image_id=id, filename=row["filename"], status="success", width=320, height=240, source_content_sha256=row["content_sha256"], review_scope_policy=policy, missing_review_scope=labels, manual_review_required=id == ids[1], boxes=[box] if id != ids[1] else [box, {**box, "id":"s", "label":"smoke"}]) for id,row in materials.items()])',
      'lease = repository.claim_next("fixture", {TaskKind.AI_ANNOTATION}, set())',
      'repository.finish(task, lease.lease_token, TaskStatus.AWAITING_CONFIRMATION, "candidates/manifest.json")',
    ].join('\n');
    execFileSync('python',['-c',seed,project,task,...ids],{env});
    const base=origin+'/api/v60/projects/'+project+'/annotation-tasks/'+task;
    const decisions=base+'/decisions',candidate=id=>base+'/candidates/'+id;
    const read=async url=>{
      const response=await request.get(url);
      expect(response.ok()).toBeTruthy();
      return response.json();
    };
    const gt=()=>Promise.all(ids.map(id=>read(origin+'/api/projects/'+project+'/annotations/'+id)));
    const initialGt=await gt(),untouched=(await read(candidate(ids[2]))).item;
    const payloads=[],receiptIds=[];
    let failDetail=false,receiptChecks=0;
    await page.route(candidate(ids[0]),route=>{
      if(!failDetail)return route.continue();
      failDetail=false;
      return route.fulfill({status:503,json:{detail:'隔离读取失败'}});
    });
    await page.route(decisions+'/by-request/*',route=>{
      const identity=route.request().url().split('/').at(-1);
      receiptIds.push(identity);
      if(identity===payloads[0].request_id){
        if(++receiptChecks===1)return route.fulfill({status:404,json:{detail:'尚无回执'}});
        if(receiptChecks===2)return route.fulfill({status:202,json:{status:'pending',request_id:identity}});
        failDetail=true;
      }
      return route.continue();
    });
    await page.route(decisions,async route=>{
      const body=route.request().postDataJSON();
      payloads.push(body);
      if(payloads.length===2){
        const response=await request.post(decisions,{data:{...payloads[0],
          review_revision:body.review_revision,request_id:'other-reviewer-decision',decisions:[{image_id:ids[0],accepted:false}],
        }});
        expect(response.ok()).toBeTruthy();
      }
      const response=await route.fetch();
      if(payloads.length===1){
        expect(response.ok(),await response.text()).toBeTruthy();
        return route.abort('failed');
      }
      if(payloads.length===2)expect(response.status()).toBe(409);
      if(payloads.length===3){
        expect(response.ok()).toBeTruthy();
        return route.fulfill({status:202,json:{status:'pending',request_id:body.request_id}});
      }
      return route.fulfill({response});
    });

    const inspector=page.getByRole('complementary',{name:'当前图片检查'});
    const adopt=inspector.getByRole('button',{name:'采用候选',exact:true});
    const reject=inspector.getByRole('button',{name:'拒绝候选',exact:true});
    const verify=inspector.getByRole('button',{name:'核验原操作'});
    const select=name=>page.getByRole('button',{name,exact:true}).click();
    const heading=inspector.getByRole('heading',{level:4});
    await page.setViewportSize({width:1366,height:768});
    await page.goto(origin+'/app/#/projects/'+project+'/ai/tasks/'+task+'/review');
    await select(names[0]);
    await expect(reject).toBeEnabled();
    await expect(adopt).toBeDisabled();
    await inspector.getByRole('checkbox',{name:'fire',exact:true}).check();
    const initialRevision=(await read(candidate(ids[0]))).review_revision;
    await adopt.click();
    await expect(verify).toBeVisible();
    expect(payloads[0]).toEqual({single_candidate:true,request_id:expect.stringMatching(/^[A-Za-z0-9_-]{12,80}$/),
      review_revision:initialRevision,commit:false,commit_selected:false,accept_unmentioned:false,reject_unmentioned:false,
      label_mapping:{},decisions:[{image_id:ids[0],accepted:true,review_scope:['fire']}],
    });
    await page.reload();
    await select(names[0]);
    await verify.click();
    await expect(inspector.getByText('暂未查到原审核回执')).toBeVisible();
    await verify.click();
    await expect(heading).toContainText('审核结果待核验');
    await verify.click();
    await expect(inspector.getByText('审核已完成，候选或统计刷新失败。')).toBeVisible();
    await expect(adopt).toBeDisabled();
    await inspector.getByRole('button',{name:'重读候选和统计'}).click();
    await expect(heading).toContainText('已采用候选');
    expect(receiptIds).toEqual(Array(3).fill(payloads[0].request_id));
    expect(payloads).toHaveLength(1);
    expect((await read(candidate(ids[0]))).item).toMatchObject({accepted:true,review_scope:['fire'],gt_committed:false});

    await page.setViewportSize({width:768,height:1024});
    await inspector.getByRole('button',{name:'关闭检查'}).click();
    await page.getByText('更多筛选',{exact:true}).click();
    const unreviewed=page.getByRole('button',{name:/^未审核/});
    await unreviewed.click();
    await expect(unreviewed).toHaveAttribute('aria-pressed','true');
    await expect(page.getByRole('heading',{name:'候选图片 2 张'})).toBeVisible();
    const untouchedCard=page.getByRole('button',{name:names[2],exact:true});
    await untouchedCard.evaluate(node=>{node.dataset.preserveIdentity='true'});
    await select(names[1]);
    await expect(heading).toContainText('待消歧');
    await expect(adopt).toBeDisabled();
    await reject.click();
    await expect(inspector.getByText('审核状态已变化，请核对当前候选后重新决定。')).toBeVisible();
    await expect(reject).toBeEnabled();
    expect((await read(candidate(ids[1]))).item.accepted).toBeNull();
    await reject.click();
    await expect(heading).toContainText('审核结果待核验');
    await expect(reject).toBeDisabled();
    await verify.click();
    await expect(heading).toContainText('已拒绝候选');
    await expect(inspector.getByText('当前图片已不在本页筛选结果中。')).toBeVisible();
    await expect(page.getByRole('heading',{name:'候选图片 1 张'})).toBeVisible();
    await expect(unreviewed).toHaveAttribute('aria-pressed','true');
    await expect(untouchedCard).toHaveAttribute('data-preserve-identity','true');
    expect(payloads).toHaveLength(3);
    expect(payloads[1].request_id).not.toBe(payloads[2].request_id);
    expect(payloads[2].decisions).toEqual([{image_id:ids[1],accepted:false}]);
    expect(receiptIds.at(-1)).toBe(payloads[2].request_id);
    expect((await read(candidate(ids[1]))).item).toMatchObject({accepted:false,gt_committed:false});
    expect((await read(candidate(ids[2]))).item).toEqual(untouched);
    expect(await gt()).toEqual(initialGt);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(768);

    const pagingTask='native-decision-last-page';
    execFileSync('python',['-c',[
      'import app, sys',
      'from platform_core.task_runtime import TaskRecord, TaskKind, TaskStatus',
      'from platform_core.annotation_candidates import CandidateStore',
      'project, task, last_id = sys.argv[1:]',
      'repository = app.shared_task_repository(); artifacts = app.shared_task_artifacts()',
      'artifacts.atomic_write_json(task, "request.json", {"labels": ["fire"]})',
      'repository.create(TaskRecord.new(task, project, TaskKind.AI_ANNOTATION, "request.json", "isolated"))',
      'store = CandidateStore(artifacts, task_id=task); store.initialize(labels=["fire"], total_images=25)',
      'store.append_items([dict(image_id=f"first-page-{i}", filename=f"first-page-{i}.jpg", status="empty", width=320, height=240) for i in range(24)])',
      'material = app.material_store(project).get(last_id)',
      'store.append_items([dict(image_id=last_id, filename=material["filename"], status="empty", width=320, height=240, source_content_sha256=material["content_sha256"])])',
      'lease = repository.claim_next("fixture", {TaskKind.AI_ANNOTATION}, set())',
      'repository.finish(task, lease.lease_token, TaskStatus.AWAITING_CONFIRMATION, "candidates/manifest.json")',
    ].join('\n'),project,pagingTask,ids[2]],{env});
    const pagingBase=origin+'/api/v60/projects/'+project+'/annotation-tasks/'+pagingTask;
    const postBodies=[];
    await page.route(pagingBase+'/decisions',route=>{
      postBodies.push(route.request().postDataJSON());
      return route.continue();
    });
    await page.goto(origin+'/app/#/projects/'+project+'/ai/tasks/'+pagingTask+'/review');
    await page.getByText('更多筛选',{exact:true}).click();
    await unreviewed.click();
    await expect(page.getByRole('heading',{name:'候选图片 25 张'})).toBeVisible();
    await page.getByRole('button',{name:'下一页'}).click();
    await expect(page.getByText('第 2 页 · 每页 24 张')).toBeVisible();
    await expect(page.locator('.review-candidate')).toHaveCount(1);

    const otherScope={actorKey:JSON.stringify(['test','isolated-test-runtime']),projectId:project,taskId:pagingTask,imageId:'first-page-0'};
    const otherKey='ai-review-decision:v1:'+JSON.stringify(Object.values(otherScope));
    const otherPacket=JSON.stringify({scope:otherScope,status:'pending',
      body:{...payloads[2],request_id:'untouched-other-pending',decisions:[{image_id:otherScope.imageId,accepted:false}]}});
    await page.evaluate(([key,packet])=>sessionStorage.setItem(key,packet),[otherKey,otherPacket]);

    await select(names[2]);
    const emptyRead=page.waitForResponse(response=>response.ok()
      &&response.url().startsWith(pagingBase+'/candidates?')
      &&new URL(response.url()).searchParams.get('cursor')==='24');
    await adopt.click();
    const empty=await (await emptyRead).json();
    expect(empty).toMatchObject({items:[],total:24,summary:{unreviewed:24}});
    await expect(heading).toContainText('已采用候选');
    await expect(page.getByText('第 1 页 · 每页 24 张')).toBeVisible();
    await expect(page.locator('.review-candidate')).toHaveCount(24);
    await expect(page.getByRole('button',{name:'上一页'})).toBeDisabled();
    await expect(page.getByRole('button',{name:'下一页'})).toBeDisabled();
    await expect(unreviewed).toHaveAttribute('aria-pressed','true');
    await expect(unreviewed).toContainText('24');
    expect(postBodies).toHaveLength(1);
    expect(await page.evaluate(key=>sessionStorage.getItem(key),otherKey)).toBe(otherPacket);
    expect(await gt()).toEqual(initialGt);

    const append=script=>execFileSync('python',['-c',[
      'import app, sys',
      'from platform_core.annotation_candidates import CandidateStore',
      'store = CandidateStore(app.shared_task_artifacts(), task_id=sys.argv[1])',
      script,
    ].join('\n'),pagingTask],{env});
    append('store.append_items([dict(image_id="failed-page", filename="failed-page.jpg", status="failed"),dict(image_id="ambiguous-page", filename="ambiguous-page.jpg", status="success", manual_review_required=True)])');

    const freezeRequests=[],boundedReads=[],forbidden=[];
    page.on('request',req=>{
      const url=new URL(req.url());
      if(req.method()==='POST'&&req.url()===pagingBase+'/review-selection')freezeRequests.push(req.postDataJSON());
      if(req.method()==='GET'&&req.url().startsWith(pagingBase+'/candidates?')&&url.searchParams.has('selection_id'))
        boundedReads.push(url.searchParams);
      if(url.pathname.includes('/negative-transfer')||url.pathname.includes('/review-selection/')||
        (req.method()!=='GET'&&(/annotations\//.test(url.pathname)||req.postDataJSON()?.commit)))forbidden.push(url.pathname);
    });
    const selection=page.getByRole('region',{name:'候选选择'});
    const countSelected=n=>expect(selection.locator('p[aria-live]').filter({hasText:new RegExp('已选 '+n+' 张')})).toBeVisible();
    const lastBox=page.getByRole('checkbox',{name:'选择 '+names[2],exact:true});
    const freezeButton=selection.getByRole('button',{name:'选择全部筛选结果'});
    const selectCurrent=selection.getByRole('button',{name:'选择本页'});
    const previous=page.getByRole('button',{name:'上一页'});
    const next=page.getByRole('button',{name:'下一页'});
    await page.reload();
    await selectCurrent.click();
    await countSelected(24);
    await next.click();
    await lastBox.check();
    await countSelected(25);
    const failed=page.getByRole('checkbox',{name:'选择 failed-page.jpg',exact:true});
    await expect(failed).toBeDisabled();
    await lastBox.evaluate(node=>{node.dataset.preserveIdentity='true'});
    const frozenResponse=page.waitForResponse(r=>r.ok()&&r.url()===pagingBase+'/review-selection'&&r.request().method()==='POST');
    const membership=page.waitForResponse(r=>r.ok()&&r.url().startsWith(pagingBase+'/candidates?')&&r.url().includes('selection_id'));
    await freezeButton.click();
    const frozen=await (await frozenResponse).json();
    expect(frozen).toMatchObject({purpose:'gt',filter:'all',filtered_total:27,count:25,reasons:{failed:1,requires_review:1}});
    expect(frozen).not.toHaveProperty('image_ids');
    expect((await (await membership).json()).items.map(row=>row.selection_member)).toEqual([true,false,false]);
    await expect(lastBox).toHaveAttribute('data-preserve-identity','true');
    await expect(selection.getByRole('button',{name:/^正式入库已选/})).toBeDisabled();
    await expect(selection).toContainText('生成失败或未生成 1 张');
    await expect(selection).toContainText('待人工消歧 1 张');
    await lastBox.uncheck();
    await countSelected(24);
    await previous.click();
    await countSelected(24);
    await expect(page.getByRole('checkbox',{name:'选择 first-page-0.jpg',exact:true})).toBeChecked();
    await next.click();
    await expect(lastBox).not.toBeChecked();
    await lastBox.check();
    await countSelected(25);
    await expect(failed).toBeDisabled();
    expect(freezeRequests).toEqual([{filter:'all',purpose:'gt',review_revision:frozen.review_revision}]);
    expect(boundedReads.length).toBeGreaterThanOrEqual(3);
    expect(boundedReads.every(query=>query.get('limit')==='24'&&query.get('selection_id')===frozen.selection_id)).toBe(true);
    const wrongTask=await request.get(base+'/candidates?limit=24&selection_id='+frozen.selection_id);
    expect(wrongTask.status()).toBe(404);

    append('store.append_items([dict(image_id="new-revision", filename="new-revision.jpg", status="empty")])');
    const stale=page.waitForResponse(r=>r.ok()&&r.url().includes('selection_id='+frozen.selection_id));
    await previous.click();
    expect(await (await stale).json()).toMatchObject({selection_stale:true});
    await expect(selection).toContainText('筛选快照已失效，请重新选择');
    await countSelected(0);
    expect(freezeRequests).toHaveLength(1);
    expect(postBodies).toHaveLength(1);
    expect(forbidden).toEqual([]);
    expect(await page.evaluate(key=>sessionStorage.getItem(key),otherKey)).toBe(otherPacket);
    await select('first-page-0.jpg');
    await expect(heading).toContainText('审核结果待核验');
    await expect(adopt).toBeDisabled();
    await inspector.getByRole('button',{name:'关闭检查'}).click();
    await page.getByRole('button',{name:/^失败/}).click();
    await expect(page.locator('.review-candidate')).toHaveCount(1);
    await freezeButton.click();
    await expect(selection).toContainText('可操作 0 张');
    await countSelected(0);
    await expect(failed).toBeDisabled();
    await expect(selection.getByRole('button',{name:'清空选择'})).toBeEnabled();
    await page.goto(origin+'/app/#/projects/'+project+'/ai/tasks/'+task+'/review');
    await countSelected(0);
    await expect(selection.getByText('可操作 0 张',{exact:false})).toHaveCount(0);
    await expect(selection.getByRole('button',{name:'清空选择'})).toBeDisabled();
    expect(await page.evaluate(key=>sessionStorage.getItem(key),otherKey)).toBe(otherPacket);
    expect(await gt()).toEqual(initialGt);

    const formalTask='native-formal-selection';
    execFileSync('python',['-c',[
      'import app, sys',
      'from platform_core.task_runtime import TaskRecord, TaskKind, TaskStatus',
      'from platform_core.annotation_candidates import CandidateStore, CandidateDecision',
      'project, task, first, rejected, last = sys.argv[1:]',
      'repo = app.shared_task_repository(); artifacts = app.shared_task_artifacts()',
      'artifacts.atomic_write_json(task, "request.json", {"labels":["fire"]})',
      'repo.create(TaskRecord.new(task, project, TaskKind.AI_ANNOTATION, "request.json", "isolated"))',
      'store = CandidateStore(artifacts, task_id=task); store.initialize(labels=["fire"], total_images=25)',
      'materials = {id:app.material_store(project).get(id) for id in (first,last)}',
      'store.append_items([dict(image_id=first, filename=materials[first]["filename"], status="success", source_content_sha256=materials[first]["content_sha256"], boxes=[dict(id="gt-box",label="fire",x1=20,y1=30,x2=100,y2=120)])])',
      'store.append_items([dict(image_id=rejected, filename=app.material_store(project).get(rejected)["filename"], status="empty", source_content_sha256="0"*64)])',
      'store.apply_decisions([CandidateDecision(rejected, True)])',
      'store.append_items([dict(image_id=f"formal-filler-{i}", filename=f"formal-filler-{i}.jpg", status="empty") for i in range(22)])',
      'store.append_items([dict(image_id=last, filename=materials[last]["filename"], status="empty", source_content_sha256=materials[last]["content_sha256"])])',
      'lease = repo.claim_next("fixture", {TaskKind.AI_ANNOTATION}, set())',
      'repo.finish(task, lease.lease_token, TaskStatus.AWAITING_CONFIRMATION, "candidates/manifest.json")',
    ].join('\n'),project,formalTask,...ids],{env});
    const formalBase=origin+'/api/v60/projects/'+project+'/annotation-tasks/'+formalTask;
    const formalUrl=origin+'/app/#/projects/'+project+'/ai/tasks/'+formalTask+'/review';
    const formalPosts=[],formalLookups=[];
    const untouchedFormal=(await read(formalBase+'/candidates/formal-filler-0')).item;
    let failFormalPage=false;
    await page.route(formalBase+'/candidates?*',route=>{
      if(!failFormalPage)return route.continue();
      failFormalPage=false;
      return route.fulfill({status:503,json:{detail:'刷新中断'}});
    });
    await page.route(formalBase+'/decisions',async route=>{
      formalPosts.push(route.request().postDataJSON());
      const response=await route.fetch();
      if(formalPosts.length>1){
        expect(response.status(),await response.text()).toBe(409);
        return route.fulfill({response});
      }
      expect(response.ok(),await response.text()).toBeTruthy();
      return route.abort('failed');
    });
    await page.route(formalBase+'/decisions/by-request/*',route=>{
      const requestId=route.request().url().split('/').at(-1);
      formalLookups.push(requestId);
      if(formalLookups.length===1)return route.fulfill({status:202,json:{status:'pending',request_id:requestId}});
      if(formalLookups.length===2)return route.fulfill({status:404,json:{detail:'暂不可见'}});
      if(formalLookups.length===3)failFormalPage=true;
      return route.continue();
    });
    await page.goto(formalUrl);
    await page.getByRole('checkbox',{name:'选择 '+names[0],exact:true}).check();
    await next.click();
    await lastBox.check();
    await selection.getByRole('button',{name:'正式入库已选 2 张'}).click();
    const dialog=page.getByRole('dialog',{name:'确认正式 GT 入库'});
    await expect(dialog).toContainText(/有框 1 张.*零框 1 张/s);
    expect(formalPosts).toHaveLength(0);
    await dialog.getByRole('button',{name:'确认写入正式 GT'}).click();
    await expect(selection.getByText('正式入库结果待核验',{exact:true})).toBeVisible();
    await expect.poll(async()=> (await gt())[0].version).toBe(initialGt[0].version+1);
    expect(formalPosts).toHaveLength(1);
    expect(formalPosts[0]).toMatchObject({commit:true,commit_selected:true,single_candidate:false,
      accept_unmentioned:false,reject_unmentioned:false,label_mapping:{},
      decisions:[{image_id:ids[0],accepted:true},{image_id:ids[2],accepted:true}]});
    await page.goto(origin+'/app/#/projects/'+project+'/ai/tasks/'+task+'/review');
    await expect(selection.getByText('正式入库结果待核验',{exact:true})).toHaveCount(0);
    await page.goto(formalUrl);
    const lookupFormal=selection.getByRole('button',{name:'核验原入库请求'});
    await lookupFormal.click();
    await expect(lookupFormal).toBeEnabled();
    await lookupFormal.click();
    await expect(selection).toContainText('暂未查到原回执');
    await lookupFormal.click();
    await expect(selection).toContainText('正式入库完成，候选或统计刷新失败');
    await selection.getByRole('button',{name:'重新读取候选与 GT'}).click();
    await expect(selection).toContainText('正式入库完成 · 2 张');
    expect(formalPosts).toHaveLength(1);
    expect(formalLookups).toEqual(Array(3).fill(formalPosts[0].request_id));
    const formalGt=await gt();
    expect(formalGt[0]).toMatchObject({version:initialGt[0].version+1,boxes:[{label:'fire',source_task_id:formalTask}]});
    expect(formalGt[1]).toEqual(initialGt[1]);
    expect(formalGt[2]).toMatchObject({version:initialGt[2].version+1,annotation_state:'confirmed_empty',boxes:[]});
    expect((await read(formalBase+'/candidates/formal-filler-0')).item).toEqual(untouchedFormal);

    await page.getByRole('checkbox',{name:'选择 '+names[1],exact:true}).check();
    await selection.getByRole('button',{name:'正式入库已选 1 张'}).click();
    await dialog.getByRole('button',{name:'确认写入正式 GT'}).click();
    await expect(selection).toContainText('原操作未写入正式 GT。候选已采用 1/1 张');
    expect(formalPosts).toHaveLength(2);
    expect(formalLookups.at(-1)).toBe(formalPosts[1].request_id);
    expect((await read(formalBase+'/candidates/'+ids[1])).item).toMatchObject({accepted:true,gt_committed:false});
    expect(await gt()).toEqual(formalGt);
  }finally{
    server.kill();
  }
});

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
  }finally{
    server.kill();
  }
});

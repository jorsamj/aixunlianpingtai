import {test,expect} from '@playwright/test';
import {spawn,execFileSync} from 'node:child_process';
import {mkdtempSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createServer} from 'node:net';

test('原生 Annotorious 保存、原请求恢复及冲突保护使用真实草稿 API',async({page,request})=>{
  test.setTimeout(90000);
  const data=mkdtempSync(join(tmpdir(),'ai-review-native-draft-'));
  const env={...process.env,MC_TRAIN_DATA_DIR:data,MC_PLATFORM_VERSION:'browser-test',MC_ALLOW_MULTIPLE_PROJECTS_FOR_TESTS:'1',YOLO_CONFIG_DIR:join(data,'ultralytics')};
  const socket=createServer();
  await new Promise(resolve=>socket.listen(0,'127.0.0.1',resolve));
  const port=socket.address().port;
  await new Promise(resolve=>socket.close(resolve));
  const origin='http://127.0.0.1:'+port;
  const server=spawn('python',['-m','uvicorn','app:app','--host','127.0.0.1','--port',String(port)],{env,windowsHide:true,stdio:'ignore'});
  try{
    await expect.poll(async()=>{try{return (await request.get(origin+'/api/health')).status()}catch{return 0}},{timeout:30000}).toBe(200);
    const created=await request.post(origin+'/api/projects',{data:{name:'原生编辑隔离项目',labels:[
      {code:'fire',display_name:'明火'},{code:'smoke',display_name:'烟雾'},
    ]}});
    expect(created.ok()).toBeTruthy();
    const project=(await created.json()).id;
    const image=execFileSync('python',['-c',"from PIL import Image;import io,sys;b=io.BytesIO();Image.new('RGB',(1280,960),'#dde5ed').save(b,format='JPEG');sys.stdout.buffer.write(b.getvalue())"]);
    const upload=await request.post(origin+'/api/projects/'+project+'/images',{multipart:{
      files:{name:'native-draft.jpg',mimeType:'image/jpeg',buffer:image},dataset_id:'default',
    }});
    expect(upload.ok()).toBeTruthy();
    const row=(await upload.json()).uploaded[0];
    const rotated=execFileSync('python',['-c',"from PIL import Image;import io,sys;b=io.BytesIO();im=Image.new('RGB',(1280,960));ex=Image.Exif();ex[274]=6;im.save(b,format='JPEG',exif=ex);sys.stdout.buffer.write(b.getvalue())"]);
    const rotatedUpload=await request.post(origin+'/api/projects/'+project+'/images',{multipart:{
      files:{name:'rotated-draft.jpg',mimeType:'image/jpeg',buffer:rotated},dataset_id:'default',
    }});
    expect(rotatedUpload.ok()).toBeTruthy();
    const rotatedRow=(await rotatedUpload.json()).uploaded[0];
    const seed=[
      'import app, sys',
      'from platform_core.task_runtime import TaskRecord, TaskKind, TaskStatus',
      'from platform_core.annotation_candidates import CandidateStore',
      'project, image, rotated = sys.argv[1:]; task = "native-draft"',
      'repository = app.shared_task_repository(); artifacts = app.shared_task_artifacts()',
      'artifacts.atomic_write_json(task, "request.json", {"labels": ["fire", "smoke"]})',
      'repository.create(TaskRecord.new(task, project, TaskKind.AI_ANNOTATION, "request.json", "isolated"))',
      'store = CandidateStore(artifacts, task_id=task); store.initialize(labels=["fire", "smoke"], total_images=2)',
      'material = app.material_store(project).get(image)',
      'store.append_items([{"image_id": image, "filename": material["filename"], "status": "success", "width": 1280, "height": 960, "source_content_sha256": material["content_sha256"], "boxes": [{"id": "seed-box", "label": "fire", "x1": 100, "y1": 120, "x2": 300, "y2": 340}]}])',
      'rotated_material = app.material_store(project).get(rotated)',
      'store.append_items([{"image_id": rotated, "filename": rotated_material["filename"], "status": "empty", "width": rotated_material["width"], "height": rotated_material["height"], "source_content_sha256": rotated_material["content_sha256"], "boxes": []}])',
      'lease = repository.claim_next("fixture", {TaskKind.AI_ANNOTATION}, set())',
      'repository.finish(task, lease.lease_token, TaskStatus.AWAITING_CONFIRMATION, "candidates/manifest.json")',
    ].join('\n');
    execFileSync('python',['-c',seed,project,row.id,rotatedRow.id],{env});
    const base=origin+'/api/v60/projects/'+project+'/annotation-tasks/native-draft';
    const candidate=base+'/candidates/'+row.id,draft=candidate+'/draft';
    const gt=origin+'/api/projects/'+project+'/annotations/'+row.id;
    const originalGt=await (await request.get(gt)).json();
    const latest=async()=> (await (await request.get(candidate)).json()).item;
    const payloads=[];
    let failConfirmedRead=false;
    await page.route(candidate,route=>{
      if(failConfirmedRead){
        failConfirmedRead=false;
        return route.fulfill({status:503,json:{detail:'隔离读取失败'}});
      }
      return route.continue();
    });
    await page.route(draft,async route=>{
      payloads.push(route.request().postDataJSON());
      if(payloads.length===1){
        const response=await route.fetch();
        expect(response.ok()).toBeTruthy();
        return route.abort('failed');
      }
      if(payloads.length===2){
        const response=await route.fetch();
        expect(response.ok()).toBeTruthy();
        failConfirmedRead=true;
        return route.fulfill({response});
      }
      return route.continue();
    });
    const open=async()=>{
      await page.getByRole('button',{name:'native-draft.jpg',exact:true}).click();
      await page.getByRole('button',{name:'编辑候选',exact:true}).click();
      await expect(page.locator('svg.a9s-annotationlayer')).toHaveCount(1);
    };
    const scope=page.getByRole('region',{name:'AI候选标注编辑'});
    const save=scope.getByRole('button',{name:'保存候选修改'});
    await page.setViewportSize({width:1366,height:768});
    await page.goto(origin+'/app/#/projects/'+project+'/ai/tasks/native-draft/review');
    await open();
    const img=scope.locator('.editor-world img');
    const rect=await img.boundingBox();
    expect(rect.width/rect.height).toBeCloseTo(1280/960,3);
    const point=(x,y)=>[rect.x+x*rect.width/1280,rect.y+y*rect.height/960];
    await scope.getByRole('button',{name:'画框',exact:true}).click();
    await page.mouse.move(...point(460,300));await page.mouse.down();
    await page.mouse.move(...point(700,600),{steps:8});await page.mouse.up();
    await expect(scope.getByRole('heading',{name:'候选对象 · 2'})).toBeVisible();
    await scope.getByRole('button',{name:'撤销',exact:true}).click();
    await expect(scope.getByRole('heading',{name:'候选对象 · 1'})).toBeVisible();
    await scope.getByRole('button',{name:'重做',exact:true}).click();
    await expect(scope.getByRole('heading',{name:'候选对象 · 2'})).toBeVisible();
    await scope.locator('.editor-objects article').nth(1).locator('select').selectOption('smoke');
    await save.click();
    await expect(scope.getByRole('button',{name:'核验原保存请求'})).toBeEnabled();
    const first=await latest();
    expect(first.draft_revision).toBe(1);
    expect(first.boxes[1].label).toBe('smoke');
    expect(first.boxes[1].x1).toBeCloseTo(460,0);
    expect(first.boxes[1].y2).toBeCloseTo(600,0);

    await page.setViewportSize({width:768,height:1024});
    page.once('dialog',dialog=>dialog.accept());
    await page.reload();
    await open();
    await scope.getByRole('button',{name:'核验原保存请求'}).click();
    await expect(scope.getByText('草稿已保存，最新草稿读取失败。请重新载入。')).toBeVisible();
    const reload=scope.getByRole('button',{name:'重新载入草稿'});
    await expect(reload).toBeEnabled();
    await expect(save).toBeDisabled();
    const stay=page.waitForEvent('dialog');
    await Promise.all([stay.then(async dialog=>{
      expect(dialog.message()).toContain('保存已确认');
      await dialog.dismiss();
    }),scope.getByRole('button',{name:'返回审核列表'}).click()]);
    await expect(scope).toBeVisible();
    page.on('dialog',async dialog=>{await dialog.accept()});
    await reload.click();
    await expect(scope.getByText('已保存草稿 · 版本 1')).toBeVisible();
    page.removeAllListeners('dialog');
    expect(payloads).toHaveLength(2);
    expect(payloads[0]).toEqual(payloads[1]);
    expect((await latest()).draft_revision).toBe(1);
    const narrow=await img.boundingBox();
    expect(narrow.width/narrow.height).toBeCloseTo(1280/960,3);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);

    await scope.getByRole('button',{name:'删除第2个框'}).click();
    await expect(scope.getByRole('heading',{name:'候选对象 · 1'})).toBeVisible();
    const external=await request.put(draft,{data:{boxes:first.boxes,revision:1,request_id:'external-edit-0001',
      source_content_sha256:first.source_content_sha256}});
    expect(external.ok()).toBeTruthy();
    await save.click();
    await expect(scope.getByText(/草稿版本、任务或源素材已变化/)).toBeVisible();
    await expect(scope.getByRole('heading',{name:'候选对象 · 1'})).toBeVisible();
    await expect(save).toBeDisabled();
    expect((await latest()).draft_revision).toBe(2);
    expect((await latest()).boxes).toEqual(first.boxes);
    page.once('dialog',dialog=>dialog.accept());
    await scope.getByRole('button',{name:'重新载入草稿'}).click();
    await expect(scope.getByRole('heading',{name:'候选对象 · 2'})).toBeVisible();
    expect(await (await request.get(gt)).json()).toEqual(originalGt);
    await scope.getByRole('button',{name:'返回审核列表'}).click();
    await expect(page.getByRole('button',{name:'采用候选',exact:true})).toBeEnabled();
    await page.getByRole('button',{name:'rotated-draft.jpg',exact:true}).click();
    await page.getByRole('button',{name:'编辑候选',exact:true}).click();
    await expect(scope.getByText('原图方向或尺寸与服务端候选不一致，已阻止编辑。')).toBeVisible();
    await expect(save).toBeDisabled();
    await scope.getByRole('button',{name:'返回审核列表'}).click();

    const current=await latest();
    const actorKey=JSON.stringify(['test','isolated-test-runtime']);
    const identity={actorKey,projectId:project,taskId:'native-draft',imageId:row.id};
    const key='ai-candidate-draft:v1:'+JSON.stringify([actorKey,project,identity.taskId,row.id]);
    const seedRecovery=scope=>page.evaluate(([storageKey,value])=>sessionStorage.setItem(storageKey,JSON.stringify(value)),[
      key,{scope,draft:{boxes:current.boxes,revision:1,request_id:'external-edit-0001'}},
    ]);
    await seedRecovery(identity);
    await open();
    await expect(scope.getByText('候选草稿',{exact:true})).toBeVisible();
    await expect(scope.getByRole('button',{name:'核验原保存请求'})).toBeEnabled();
    const pendingDialog=page.waitForEvent('dialog');
    await Promise.all([pendingDialog.then(async dialog=>{
      expect(dialog.message()).toContain('原保存结果待核验');
      await dialog.dismiss();
    }),scope.getByRole('button',{name:'返回审核列表'}).click()]);
    await expect(scope).toBeVisible();
    page.once('dialog',dialog=>dialog.accept());
    await scope.getByRole('button',{name:'返回审核列表'}).click();

    await expect(page.getByText('请先在候选编辑器核验原草稿保存。')).toBeVisible();
    await expect(page.getByRole('button',{name:'采用候选',exact:true})).toBeDisabled();
    await expect(page.getByRole('button',{name:'拒绝候选',exact:true})).toBeDisabled();

    await seedRecovery({...identity,imageId:rotatedRow.id});
    await page.getByRole('button',{name:'native-draft.jpg',exact:true}).click();
    await page.getByRole('button',{name:'编辑候选',exact:true}).click();
    await expect(page.getByRole('alert')).toContainText('原草稿恢复记录无法安全读取');
    await expect(scope).toHaveCount(0);
    expect(payloads).toHaveLength(3);
  }finally{
    server.kill();
  }
});

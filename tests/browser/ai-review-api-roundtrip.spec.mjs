import {test,expect} from '@playwright/test';
import {spawn,execFileSync} from 'node:child_process';
import {mkdtempSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createServer} from 'node:net';

test('真实API草稿刷新与转池撤销闭环（隔离候选，非模型实测）',async({page,request},info)=>{
 test.setTimeout(90000);
 const data=mkdtempSync(join(tmpdir(),'xjalgo-browser-review-'));
 const env={...process.env,MC_TRAIN_DATA_DIR:data,MC_PLATFORM_VERSION:'browser-test',MC_ALLOW_MULTIPLE_PROJECTS_FOR_TESTS:'1',YOLO_CONFIG_DIR:join(data,'ultralytics')};
 const socket=createServer();await new Promise(resolve=>socket.listen(0,'127.0.0.1',resolve));const port=socket.address().port;await new Promise(resolve=>socket.close(resolve));
 const child=spawn('python',['-m','uvicorn','app:app','--host','127.0.0.1','--port',String(port),'--log-level','info'],{env,stdio:['ignore','pipe','pipe'],windowsHide:true});
 const ready=new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error('isolated server startup timeout')),30000);child.once('exit',code=>{clearTimeout(timer);reject(new Error(`isolated server exited ${code}`))});const onData=data=>{if(String(data).includes('Uvicorn running on')){clearTimeout(timer);resolve()}};child.stdout.on('data',onData);child.stderr.on('data',onData)});
 const origin=`http://127.0.0.1:${port}`;
 try{
  await ready;
  await expect.poll(async()=>{try{return (await request.get(origin+'/api/health')).status()}catch{return 0}},{timeout:30000}).toBe(200);
  const created=await request.post(origin+'/api/projects',{data:{name:'隔离审核闭环',labels:[{code:'fire',display_name:'明火'}]}});expect(created.ok()).toBeTruthy();const project=await created.json();
  const image=execFileSync('python',['-c',"from PIL import Image;import io,sys;b=io.BytesIO();Image.new('RGB',(1280,960),'#dde5ed').save(b,format='JPEG');sys.stdout.buffer.write(b.getvalue())"]);
  const upload=await request.post(`${origin}/api/projects/${project.id}/images`,{multipart:{files:{name:'isolated-review.jpg',mimeType:'image/jpeg',buffer:image},dataset_id:'default'}});expect(upload.ok()).toBeTruthy();const row=(await upload.json()).uploaded[0];
  const seed=`import app\nfrom platform_core.task_runtime import TaskRecord,TaskKind,TaskStatus\nfrom platform_core.annotation_candidates import CandidateStore\nr=app.shared_task_repository();a=app.shared_task_artifacts();a.atomic_write_json('browser-review-real','request.json',{'image_ids':['${row.id}'],'labels':['fire']});r.create(TaskRecord.new('browser-review-real','${project.id}',TaskKind.AI_ANNOTATION,'request.json','isolated'));s=CandidateStore(a,task_id='browser-review-real');s.initialize(labels=['fire'],total_images=1);s.append_items([{'image_id':'${row.id}','status':'success','boxes':[{'id':'box-1','label':'fire','x1':100,'y1':200,'x2':400,'y2':700}],'width':1280,'height':960,'source_content_sha256':'${row.content_sha256}'}]);l=r.claim_next('fixture',{TaskKind.AI_ANNOTATION},set());r.finish(l.task.task_id,l.lease_token,TaskStatus.AWAITING_CONFIRMATION,'candidates/manifest.json');a.atomic_write_json('browser-review-failed','request.json',{'image_ids':['${row.id}'],'labels':['fire']});r.create(TaskRecord.new('browser-review-failed','${project.id}',TaskKind.AI_ANNOTATION,'request.json','isolated-failed'));f=CandidateStore(a,task_id='browser-review-failed');f.initialize(labels=['fire'],total_images=1);f.append_items([{'image_id':'${row.id}','status':'failed','boxes':[],'error':'隔离请求合同错误','error_code':'MODEL_REQUEST_CONTRACT_INVALID','error_stage':'model_request','http_status':422,'request_id':'isolated-request','attempt_count':1,'retry_suggestion':'检查query字段'}]);l=r.claim_next('fixture',{TaskKind.AI_ANNOTATION},set());r.finish(l.task.task_id,l.lease_token,TaskStatus.FAILED,'candidates/manifest.json')`;
  execFileSync('python',['-c',seed],{env});
  const cat=await request.post(`${origin}/api/v61/projects/${project.id}/negative-pool/categories`,{data:{name:'隔离人工审核'}});expect(cat.ok()).toBeTruthy();
  await page.goto(origin);await expect.poll(()=>page.evaluate(()=>typeof state!=='undefined'&&state.uiReady)).toBe(true);
  await page.evaluate(p=>{state.project=p;return window.reviewAiLabel427('browser-review-real')},project);await expect(page.locator('.ai66-candidate-card')).toHaveCount(1);
  await page.locator('.ai-candidate-stage').first().click();await page.locator('#ai60ReviewInspector').getByRole('button',{name:'编辑候选框',exact:true}).click();
  await expect(page.locator('#ai60EditStatus')).toContainText('候选草稿');await page.evaluate(()=>window.updateAiCandidateBox60(0,'x1','120'));await page.getByRole('button',{name:'保存候选修改',exact:true}).click();await expect(page.locator('#ai60EditStatus')).toContainText('版本 1');
  await page.reload();await expect.poll(()=>page.evaluate(()=>typeof state!=='undefined'&&state.uiReady)).toBe(true);await page.evaluate(p=>{state.project=p;return window.reviewAiLabel427('browser-review-real')},project);
  const base=`${origin}/api/v60/projects/${project.id}/annotation-tasks/browser-review-real`;
  const persisted=await (await request.get(base+'/candidates')).json();expect(persisted.items[0].draft_revision).toBe(1);expect(persisted.items[0].boxes[0].x1).toBe(120);expect(persisted.items[0].original_boxes[0].x1).toBe(100);
  await page.locator('.ai-review-select').check();await page.getByRole('button',{name:'转入负样本池',exact:true}).click();await page.getByRole('button',{name:'预检影响范围'}).click();await expect(page.locator('#ai60TransferResult')).toContainText('弃用 1 个候选框');await page.getByRole('button',{name:'确认转入可用 1 张'}).click();await expect(page.locator('#ai60TransferResult')).toContainText('已转入 1 张');await expect(page.locator('#ai60ApproveRemaining')).toHaveText('通过剩余全部 0 张（整批结束）');
  await page.locator('#ai60TransferPanel').evaluate(node=>node.hidden=true);
  // Transferred candidates are a low-frequency filter in the immersive workbench.
  // Exercise the actual visible "更多筛选" entry instead of clicking a closed details child.
  await page.locator('.ai-review-filter-more > summary').click();
  await expect(page.locator('[data-ai66-filter="transferred"]')).toBeVisible();
  await page.locator('[data-ai66-filter="transferred"]').click();
  await expect(page.locator('.ai66-candidate-card')).toHaveCount(1);
  await page.locator('.ai-candidate-stage').first().click();
  await page.getByRole('button',{name:'查看转出记录',exact:true}).click();
  await expect(page.locator('#ai60TransferPanel')).toContainText('范围 1 张，已记录 1 张');
  await expect(page.locator('#ai60TransferPanel')).toContainText('isolated-review.jpg');
  await page.getByRole('button',{name:'撤销本次转出'}).click();await expect(page.locator('#ai60ApproveRemaining')).toHaveText('通过剩余全部 1 张（整批结束）');await page.locator('#ai60TransferPanel').getByRole('button',{name:'关闭',exact:true}).click();await page.locator('[data-ai66-filter="all"]').click();
  await page.screenshot({path:info.outputPath('real-api-review-transfer.png'),fullPage:true});
  // The confirmed GT result is durable, visible, and cannot be selected again.
  page.on('dialog',dialog=>dialog.accept());
  await page.locator('.ai-review-select').check();
  await page.locator('#ai60ApproveSelected').click();
  await expect(page.locator('.ai66-candidate-card.gt-committed')).toHaveCount(1);
  await expect(page.locator('.ai-review-committed-mark')).toContainText('已同意 · 正式入库');
  await expect(page.locator('.ai-review-select')).toBeDisabled();
  await expect(page.locator('#ai60ReviewSummary')).toContainText('已正式入库 1 张');
  await page.locator('#ai60SelectFiltered').click();
  await expect(page.locator('#ai60SelectionCount')).toContainText('选中 0 张');
  await expect(page.locator('#ai60SelectionStatus')).toContainText('没有可选的未入库素材');
  const committedResult=await (await request.get(base+'/candidates?filter=committed')).json();
  expect(committedResult.total).toBe(1);
  expect(committedResult.items[0].gt_committed).toBe(true);
  await page.reload();
  await expect.poll(()=>page.evaluate(()=>typeof state!=='undefined'&&state.uiReady)).toBe(true);
  await page.evaluate(p=>{state.project=p;return window.reviewAiLabel427('browser-review-real')},project);
  await expect(page.locator('.ai66-candidate-card.gt-committed')).toHaveCount(1);
  await expect(page.locator('.ai-review-select')).toBeDisabled();
  await page.locator('.ai-review-filter-more > summary').click();
  await page.locator('[data-ai66-filter="committed"]').click();
  await expect(page.locator('.ai66-candidate-card.gt-committed')).toHaveCount(1);
  await expect(page.locator('#ai60SelectFiltered')).toBeDisabled();
  await page.evaluate(()=>window.showAiTask60('browser-review-failed'));await expect(page.locator('[data-ai-failure-details]')).toContainText('HTTP 422');const download=page.waitForEvent('download');await page.locator('[data-ai-export-format="csv"]').click();expect((await download).suggestedFilename()).toBe('annotation-errors-browser-review-failed-1.csv');
 }finally{child.kill();}
});

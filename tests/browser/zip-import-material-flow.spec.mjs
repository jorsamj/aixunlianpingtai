import {test,expect} from '@playwright/test';
import {spawn,execFileSync} from 'node:child_process';
import {mkdtempSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createServer} from 'node:net';

test('真实ZIP原图/带标注/损坏/压缩错误及四动作（隔离API）',async({page,request},info)=>{
 test.setTimeout(180000);
 const data=mkdtempSync(join(tmpdir(),'xjalgo-browser-review-'));
 const env={...process.env,MC_TRAIN_DATA_DIR:data,MC_PLATFORM_VERSION:'browser-test',MC_ALLOW_MULTIPLE_PROJECTS_FOR_TESTS:'1',YOLO_CONFIG_DIR:join(data,'ultralytics')};
 const socket=createServer();await new Promise(resolve=>socket.listen(0,'127.0.0.1',resolve));const port=socket.address().port;await new Promise(resolve=>socket.close(resolve));
 const child=spawn('python',['-m','uvicorn','app:app','--host','127.0.0.1','--port',String(port),'--log-level','info'],{env,stdio:['ignore','pipe','pipe'],windowsHide:true});
 const ready=new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error('isolated server startup timeout')),30000);child.once('exit',code=>{clearTimeout(timer);reject(new Error(`isolated server exited ${code}`))});const onData=data=>{if(String(data).includes('Uvicorn running on')){clearTimeout(timer);resolve()}};child.stdout.on('data',onData);child.stderr.on('data',onData)});
 const origin=`http://127.0.0.1:${port}`;
 try{
  await ready;
  await expect.poll(async()=>{try{return (await request.get(origin+'/api/health')).status()}catch{return 0}},{timeout:30000}).toBe(200);
  const created=await request.post(origin+'/api/projects',{data:{name:'ZIP独立闭环',labels:[{code:'fire',display_name:'明火'}]}});expect(created.ok()).toBeTruthy();const project=await created.json();
  const make=(mode)=>execFileSync('python',['-c',`from PIL import Image;import io,sys,zipfile,struct
b=io.BytesIO();Image.new('RGB',(660,440),'#8da5b5').save(b,format='JPEG');z=io.BytesIO()
with zipfile.ZipFile(z,'w',compression=${mode==='deflate'?'zipfile.ZIP_DEFLATED':'zipfile.ZIP_STORED'}) as a:
 a.writestr('images/${mode}.jpg',b.getvalue())
 if '${mode}'=='annotated':a.writestr('labels/annotated.txt','0 .5 .5 .4 .6');a.writestr('classes.txt','fire')
v=bytearray(z.getvalue())
if '${mode}'=='unsupported':
 for sig,off in [(bytes.fromhex('504b0304'),8),(bytes.fromhex('504b0102'),10)]:
  at=v.find(sig)
  if at>=0:struct.pack_into('<H',v,at+off,9)
if '${mode}'=='corrupt':v=bytearray(b'not-a-zip-archive')
sys.stdout.buffer.write(v)`]);
  const base=`${origin}/api/v19/projects/${project.id}`;
  async function upload(mode){const buffer=make(mode);const session=await request.post(base+'/datasets/default/import/uploads',{data:{file_name:mode+'.zip',file_size:buffer.length,fingerprint:mode}});expect(session.ok()).toBeTruthy();const id=(await session.json()).upload_id;
   expect((await request.put(base+`/import/uploads/${id}/parts/0`,{data:buffer,headers:{'Content-Type':'application/octet-stream'}})).ok()).toBeTruthy();expect((await request.post(base+`/import/uploads/${id}/complete`)).status()).toBe(202);
   await expect.poll(async()=> (await(await request.get(base+`/import/jobs/${id}`)).json()).status,{timeout:30000}).toMatch(/selecting|failed/);return await(await request.get(base+`/import/jobs/${id}`)).json();}
  const raw=await upload('stored');expect(raw.scan_kind).toBe('RAW_UNANNOTATED');expect((await request.post(base+`/import/jobs/${raw.id}/start`,{data:{}})).ok()).toBeTruthy();
  await expect.poll(async()=> (await(await request.get(base+`/import/jobs/${raw.id}`)).json()).status,{timeout:30000}).toBe('done');const done=await(await request.get(base+`/import/jobs/${raw.id}`)).json();expect(done.report.warnings).toEqual([]);expect(done.report.boxes).toBe(0);
  const deflate=await upload('deflate');expect(deflate.status).toBe('selecting');expect((await request.post(base+`/import/jobs/${deflate.id}/start`,{data:{}})).ok()).toBeTruthy();await expect.poll(async()=> (await(await request.get(base+`/import/jobs/${deflate.id}`)).json()).status,{timeout:30000}).toBe('done');
  const ann=await upload('annotated');expect(ann.status).toBe('selecting');const start=await request.post(base+`/import/jobs/${ann.id}/start`,{data:{sample_type:'positive',intended_label_codes:['fire'],label_mapping:{'0':'fire'}}});expect(start.ok(),await start.text()).toBeTruthy();await expect.poll(async()=> (await(await request.get(base+`/import/jobs/${ann.id}`)).json()).status,{timeout:30000}).toBe('done');
  const annotated=await(await request.get(base+`/import/jobs/${ann.id}`)).json();expect(annotated.report.boxes).toBe(1);
  for(const mode of ['corrupt','unsupported']){const failure=await upload(mode);expect(failure.status).toBe('failed');expect(failure.error).toBeTruthy();if(mode==='unsupported')expect(failure.error).toMatch(/9|Deflate64/);expect((await request.get(base+`/import/jobs/${failure.id}`)).status()).toBe(200);}
  const rawMaterials=await(await request.get(`${origin}/api/v61/projects/${project.id}/materials?source_batch_id=${raw.id}`)).json();expect(rawMaterials.items).toHaveLength(1);expect(rawMaterials.items[0].annotation_state).toBe('unannotated');expect(rawMaterials.items[0].processing_status).toBe('pending_decision');
  await page.goto(origin);await expect.poll(()=>page.evaluate(()=>typeof state!=='undefined'&&state.uiReady&&!!window.ZipImportRuntime)).toBe(true);await page.evaluate(p=>{state.project=p},project);
  for(const width of [1920,1366,768]){await page.setViewportSize({width,height:1000});await page.evaluate(async id=>{await window.ZipImportRuntime.reconcile('isolated-test');await window.ZipImportRuntime.openTask(id)},raw.id);await expect(page.locator('#zip411Result')).toContainText('已成功入库 1 张原图，等待标注');await expect(page.locator('.zip-next-action')).toHaveCount(4);await page.mouse.move(0,0);await page.screenshot({path:info.outputPath(`zip-${width}.png`),fullPage:true});await page.evaluate(()=>window.closeModal());}
  await page.evaluate(id=>window.ZipImportRuntime.openTask(id),raw.id);await page.getByRole('button',{name:'暂存素材库',exact:false}).click();await expect(page.locator('.material-workspace412')).toBeVisible();expect(await page.evaluate(()=>state.materialBatchFilter61)).toBe(raw.id);
  await page.evaluate(id=>window.ZipImportRuntime.openTask(id),raw.id);await page.getByRole('button',{name:'直接 AI 预标注',exact:false}).click();await expect(page.locator('.ai-create-workbench')).toBeVisible();expect(await page.evaluate(()=>state.ai429Create?.sourceBatchId)).toBe(raw.id);await page.evaluate(()=>window.closeModal());
  await page.evaluate(id=>window.ZipImportRuntime.openTask(id),raw.id);await page.getByRole('button',{name:'质量检查（可选）',exact:false}).click();await expect(page.locator('.import412-decision')).toBeVisible();await page.evaluate(()=>window.closeModal());
  await page.evaluate(id=>window.ZipImportRuntime.openTask(id),raw.id);await page.getByRole('button',{name:'人工标注',exact:false}).click();await expect(page.locator('#annImg')).toBeVisible({timeout:10000});
 }finally{child.kill();}
});

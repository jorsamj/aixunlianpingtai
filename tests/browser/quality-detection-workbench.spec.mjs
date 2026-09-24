import {test, expect} from '@playwright/test';
import {promises as fs} from 'node:fs';
import os from 'node:os';
import path from 'node:path';

async function selectIsolatedTestProject(page, projectId) {
  await page.route('**/api/v53/bootstrap/snapshot**', async route => {
    const url = new URL(route.request().url());
    url.searchParams.set('preferred_project_id', projectId);
    await route.continue({url: url.toString()});
  });
}

function bmp(width=96,height=72,rgb=[80,130,190]) {
  const rowBytes=Math.ceil(width*3/4)*4;
  const buffer=Buffer.alloc(54+rowBytes*height);
  buffer.write('BM',0,'ascii');buffer.writeUInt32LE(buffer.length,2);buffer.writeUInt32LE(54,10);
  buffer.writeUInt32LE(40,14);buffer.writeInt32LE(width,18);buffer.writeInt32LE(height,22);
  buffer.writeUInt16LE(1,26);buffer.writeUInt16LE(24,28);buffer.writeUInt32LE(rowBytes*height,34);
  for(let y=0;y<height;y+=1){
    for(let x=0;x<width;x+=1){
      const offset=54+y*rowBytes+x*3;
      buffer[offset]=rgb[2];buffer[offset+1]=rgb[1];buffer[offset+2]=rgb[0];
    }
  }
  return buffer;
}

async function createAlgorithm(request, projectId, name) {
  const response=await request.post(`/api/v12/projects/${projectId}/algorithms`,{data:{
    name,industry:'浏览器验收',algorithm_type:'yolo_ultralytics',remark:'',
  }});
  expect(response.ok()).toBeTruthy();
  return (await response.json()).algorithm;
}

test('quality detection Real Chrome UI contract drives durable tasks for compare A-only and B-only without claiming production inference E2E', async ({page,request})=>{
  const project=await (await request.post('/api/projects',{data:{
    name:`质量检测浏览器-${Date.now()}`,labels:[{code:'object',display_name:'目标'}],
  }})).json();
  const smoke=await createAlgorithm(request,project.id,'烟雾识别');
  const helmet=await createAlgorithm(request,project.id,'安全帽识别');
  const encoded=encodeURIComponent(project.id);

  const models=[
    {label:'原始模型：YOLO11n 官方预训练',model_name:'yolo11n.pt',model_source:'builtin',framework:'ultralytics',path:'yolo11n.pt'},
    {label:'算法版本：烟雾识别 / v2（当前）',model_source:'algorithm_version',algorithm_id:smoke.id,version_id:'smoke-v2',is_current_version:true,framework:'ultralytics',path:'/models/smoke-v2.pt'},
    {label:'算法版本：安全帽识别 / v7',model_source:'algorithm_version',algorithm_id:helmet.id,version_id:'helmet-v7',framework:'ultralytics',path:'/models/helmet-v7.pt'},
  ];
  const creates=[];
  const reviews=[];
  let taskSeq=0;
  let modelLoads=0;
  let envLoads=0;

  await selectIsolatedTestProject(page,project.id);
  await page.route(`**/api/v12/projects/${encoded}/test_models**`,route=>{
    modelLoads+=1;
    return route.fulfill({
      status:200,contentType:'application/json',body:JSON.stringify({ok:true,items:models}),
    });
  });
  await page.route('**/api/v16/inference_envs',route=>{
    envLoads+=1;
    return route.fulfill({
      status:200,contentType:'application/json',
      body:JSON.stringify({items:[{id:'quality-env',name:'质量验收环境',framework:'ultralytics',status:'ready',python_path:'/opt/yolo/bin/python'}]}),
    });
  });
  await page.route(`**/api/v61/projects/${encoded}/deployment-tests`,async route=>{
    const raw=(route.request().postDataBuffer()||Buffer.alloc(0)).toString('utf8');
    const id=`quality-task-${++taskSeq}`;
    creates.push({id,raw});
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({
      id,task_id:id,kind:'DEPLOYMENT_TEST',status:'QUEUED',progress_percent:0,
    })});
  });
  await page.route(`**/api/v62/projects/${encoded}/tasks/*`,route=>{
    const id=new URL(route.request().url()).pathname.split('/').at(-1);
    return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({
      id,kind:'DEPLOYMENT_TEST',status:'SUCCEEDED',progress_percent:100,phase:'completed',
    })});
  });
  await page.route(`**/api/v61/projects/${encoded}/deployment-tests/*`,route=>{
    const id=new URL(route.request().url()).pathname.split('/').at(-1);
    return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({
      id,status:'SUCCEEDED',result:{
        detections:[{label:'object',confidence:0.91,x1:10,y1:8,x2:52,y2:44}],
        input_image_url:'/placeholder.jpg',result_image_url:'/placeholder.jpg',
        preprocess_ms:1.2,inference_ms:4.8,postprocess_ms:0.9,total_elapsed_ms:7.3,
      },
    })});
  });
  await page.route(`**/api/v64/projects/${encoded}/detection-batches**`,async route=>{
    const req=route.request(),url=new URL(req.url()),path=url.pathname;
    if(req.method()==='POST'&&/\/items\/\d+\/review$/.test(path)){
      reviews.push(req.postDataJSON());
      return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({ok:true})});
    }
    if(req.method()==='GET'&&path.endsWith('/detection-batches/history-batch')){
      return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({batch:{
        batch_id:'history-batch',created_at:'2026-09-23T00:00:00Z',total:1,completed_items:1,failed_items:0,
        items:[{index:0,original_filename:'history.bmp',review:{review:'correct',note:''},models:{
          A:{status:'SUCCEEDED',task_id:'history-a',model_source:'algorithm_version',algorithm_id:smoke.id,version_id:'smoke-v2',label:'算法版本：烟雾识别 / v2',detections:[],input_image_url:'/placeholder.jpg',result_image_url:'/placeholder.jpg'},
        }}],
      }})});
    }
    if(req.method()==='GET'&&path.endsWith('/detection-batches')){
      return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({items:[{
        batch_id:'history-batch',created_at:'2026-09-23T00:00:00Z',total:1,created_items:1,completed_items:1,failed_items:0,
      }]})});
    }
    return route.continue();
  });

  await page.addInitScript(()=>localStorage.setItem('mc_train_ui_state_v34',JSON.stringify({page:'总览'})));
  await page.goto('/');
  await page.evaluate(()=>window.setPage('质量中心'));
  await page.getByRole('button',{name:'模型检测',exact:true}).click();
  await expect.poll(()=>modelLoads).toBe(1);
  await expect.poll(()=>envLoads).toBe(1);

  await page.getByRole('button',{name:'质量概览',exact:true}).click();
  await page.getByRole('button',{name:'模型检测',exact:true}).click();
  await expect.poll(()=>modelLoads).toBe(1);
  await expect.poll(()=>envLoads).toBe(1);

  await page.getByRole('button',{name:'刷新模型',exact:true}).click();
  await expect.poll(()=>modelLoads).toBe(2);
  await expect.poll(()=>envLoads).toBe(2);
  const a=page.locator('#benchModelA'),b=page.locator('#benchModelB');
  await expect(a).toBeVisible();
  await expect(b).toBeVisible();
  await expect(a.locator('optgroup').first()).toHaveAttribute('label', /原始 \/ 基础模型/, {timeout:10_000});
  await expect(a.locator(`optgroup[label="算法 · 烟雾识别"]`)).toHaveCount(1);
  await expect(b.locator(`optgroup[label="算法 · 安全帽识别"]`)).toHaveCount(1);

  await page.locator('#benchModelSearchB').fill('安全帽');
  await expect(b.locator('option')).toHaveCount(1);
  await expect(b.locator('option')).toContainText('安全帽识别 / v7');
  await page.locator('#benchModelSearchB').fill('');

  await a.selectOption('1');
  await b.selectOption('2');
  await page.locator('#benchConf').fill('0.42');
  await expect(page.locator('#benchMode64').locator('option')).toHaveText(['同图 A / B 对比','只测 A 模型','只测 B 模型']);
  expect(await page.locator('#benchFolder64').evaluate(el=>el.hasAttribute('webkitdirectory'))).toBeTruthy();

  await page.locator('#benchFiles64').setInputFiles([
    {name:'compare.bmp',mimeType:'image/bmp',buffer:bmp()},
    {name:'ignored.txt',mimeType:'text/plain',buffer:Buffer.from('not an image')},
  ]);
  await expect(page.locator('#benchFileCount64')).toHaveText('已选择 1 张图片');
  await page.locator('#benchMode64').selectOption('compare');
  await page.locator('#benchRun64').click();
  await expect(page.locator('#benchBatchList64 .bench64-result-row.done')).toHaveCount(1);
  await expect.poll(()=>creates.length).toBe(2);
  expect(creates[0].raw).toContain('name="detection_side"');
  expect(creates[0].raw).toContain('\r\n\r\nA\r\n');
  expect(creates[1].raw).toContain('\r\n\r\nB\r\n');
  expect(creates[0].raw).toContain('name="detection_item_total"');
  expect(creates[0].raw).toContain('\r\n\r\n1\r\n');
  expect(creates[0].raw).toContain('name="conf"');
  expect(creates[0].raw).toContain('\r\n\r\n0.42\r\n');

  await page.locator('#benchBatchList64').getByRole('button',{name:'查看详情'}).click();
  const detail=page.getByRole('dialog',{name:'检测详情'});
  await expect(detail).toBeVisible();
  await detail.getByRole('button',{name:'正确',exact:true}).click();
  await expect.poll(()=>reviews.length).toBe(1);
  expect(reviews[0].review).toBe('correct');
  await page.evaluate(()=>window.closeModal());

  await page.evaluate(()=>window.clearBenchFiles64());
  await page.locator('#benchFiles64').setInputFiles({name:'a-only.bmp',mimeType:'image/bmp',buffer:bmp(96,72,[120,80,180])});
  await page.locator('#benchMode64').selectOption('a');
  await page.locator('#benchRun64').click();
  await expect.poll(()=>creates.length).toBe(3);
  expect(creates[2].raw).toContain('\r\n\r\nA\r\n');

  await page.evaluate(()=>window.clearBenchFiles64());
  await page.locator('#benchFiles64').setInputFiles({name:'b-only.bmp',mimeType:'image/bmp',buffer:bmp(96,72,[180,100,70])});
  await page.locator('#benchMode64').selectOption('b');
  await page.locator('#benchRun64').click();
  await expect.poll(()=>creates.length).toBe(4);
  expect(creates[3].raw).toContain('\r\n\r\nB\r\n');

  const folder=await fs.mkdtemp(path.join(os.tmpdir(),'quality-folder-'));
  try{
    const nested=path.join(folder,'nested');
    await fs.mkdir(nested,{recursive:true});
    await fs.writeFile(path.join(folder,'folder-one.bmp'),bmp(96,72,[90,150,190]));
    await fs.writeFile(path.join(nested,'folder-two.bmp'),bmp(96,72,[190,150,90]));
    await fs.writeFile(path.join(folder,'ignore.txt'),Buffer.from('not an image'));

    await page.evaluate(()=>window.clearBenchFiles64());
    await page.locator('#benchFolder64').setInputFiles(folder);
    await expect(page.locator('#benchFileCount64')).toHaveText('已选择 2 张图片');
    await expect(page.locator('#benchFileList64')).toContainText('folder-one.bmp');
    await expect(page.locator('#benchFileList64')).toContainText('folder-two.bmp');
    await expect(page.locator('#benchFileList64')).not.toContainText('ignore.txt');

    await page.locator('#benchMode64').selectOption('compare');
    await page.locator('#benchRun64').click();
    await expect(page.locator('#benchBatchList64 .bench64-result-row.done')).toHaveCount(2);
    await expect.poll(()=>creates.length).toBe(8);
    for(const task of creates.slice(4)){
      expect(task.raw).toContain('name="detection_item_total"');
      expect(task.raw).toContain('\r\n\r\n2\r\n');
    }
  }finally{
    await fs.rm(folder,{recursive:true,force:true});
  }

  const history=page.locator('.bench64-history-row',{hasText:'history-batch'});
  await expect(history).toBeVisible();
  await history.click();
  await expect(page.locator('#benchBatchList64')).toContainText('history.bmp');
  await expect(page.locator('#benchBatchList64')).toContainText('正确');
});

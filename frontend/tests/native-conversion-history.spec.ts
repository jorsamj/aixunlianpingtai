import {expect,test,type Page} from '@playwright/test';
import {resolve} from 'node:path';
import {createHash} from 'node:crypto';

async function assets(page:Page){
 await page.route('**/app/**',route=>{
  const name=new URL(route.request().url()).pathname.slice('/app/'.length)||'index.html';
  return route.fulfill({path:resolve('../static/vue-app',name),contentType:name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':'text/html'});
 });
}
const deployment={id:'job-1',target:'rknn',target_name:'RKNN',status:'done',stage:'finished',progress:100,
 task_id:'conv-task',task_status:'SUCCEEDED',durable_status:'SUCCEEDED',conversion_status:'completed',
 validation_status:'passed',numeric_status:'matched',publication_status:'recorded',runtime_verified:true,hardware_verified:true,
 source_name:'版本 V1',resource_name:'隔离转换资源',worker_id:'worker-1',
 created_at:'2026-11-24T08:00:00',started_at:'2026-11-24T08:01:00',finished_at:'2026-11-24T08:05:00',
 source_identity:{source_id:'source-1',sha256:'a'.repeat(64),algorithm_id:'a',version_id:'v'},
 params:{chip:'rk3588',precision:'fp16',sdk_version:'2.3.0',csc:'0'},
 requested_params:{chip:'rk3588',precision:'int8'},execution_evidence:{node_id:'node-1'},hardware_verification:{status:'verified',verified:true,chip:'rk3588'},
 outputs:[{file_name:'model.rknn',exists:true,sha256:'b'.repeat(64),size_mb:1.5,size_bytes:1572864,validation_status:'passed'}],
 outputs_truncated:false,error:null,message:null,resource_wait_reason:null};
const historyPage={ok:true,project_id:'p',algorithm_id:'a',version_id:'v',version:{id:'v',version_name:'版本 V1'},
 total:1,page:1,page_size:20,complete:true,filter_options:{status:['done'],target:['rknn'],chip:['rk3588'],precision:['fp16'],csc:['0']},
 diagnostics:[],items:[deployment]};

test('native conversion detail reads bound numeric history without creating validation',async({page})=>{
 await assets(page);
 const endpoint='/api/v39/projects/p/deploy/jobs/job-1';
 const recent={id:'nv_previous',conversion_job_id:'job-1',task:{task_id:'nv_previous',project_id:'p',kind:'MODEL_CONVERSION',status:'SUCCEEDED'},result:{verdict:'consistent',sample_count:3}};
 let historyReads=0;
 await page.route('**/api/**',route=>{
  const path=new URL(route.request().url()).pathname;
  expect(route.request().method()).toBe('GET');
  if(path==='/api/auth/session')return route.fulfill({json:{authenticated:true}});
  if(path==='/api/projects')return route.fulfill({json:[{id:'p',name:'项目 P'}]});
  if(path===endpoint)return route.fulfill({json:{...deployment,project_id:'p',source_trace:deployment.source_identity}});
  if(path===endpoint+'/log')return route.fulfill({contentType:'text/plain',body:'转换完成'});
  if(path===endpoint+'/numeric-validations'){
   historyReads++;
   return route.fulfill({json:{ok:true,items:[historyReads===1?recent:{...recent,conversion_job_id:'other'}]}});
  }
  return route.fulfill({status:404,json:{detail:'unexpected '+path}});
 });
 await page.goto('/app/#/projects/p/conversions/job-1');
 await expect(page.getByRole('heading',{name:'源模型身份'})).toBeVisible();
 await expect(page.getByText('a'.repeat(64),{exact:true})).toBeVisible();
 expect(historyReads).toBe(0);
 await page.getByRole('button',{name:'读取数值验证历史'}).click();
 await expect(page.getByRole('row').filter({hasText:'nv_previous'})).toContainText('consistent');
 await page.getByRole('button',{name:'刷新数值验证历史'}).click();
 await expect(page.getByText('数值验证历史响应身份不一致',{exact:true})).toBeVisible();
 await expect(page.getByRole('row').filter({hasText:'nv_previous'})).toHaveCount(0);
});

test('native numeric validation sends the original multipart contract and verifies a lost receipt by ID',async({page})=>{
 await assets(page);
 const endpoint='/api/v39/projects/p/deploy/jobs/job-1';
 let writes=0;
 let verificationId='';
 await page.route('**/api/**',route=>{
  const request=route.request();
  const path=new URL(request.url()).pathname;
  if(path==='/api/auth/session')return route.fulfill({json:{authenticated:true}});
  if(path==='/api/projects')return route.fulfill({json:[{id:'p',name:'项目 P'}]});
  if(path===endpoint)return route.fulfill({json:{...deployment,project_id:'p',source_name:'frozen.pt',outputs:[{rel:'artifacts/model.onnx'}]}});
  if(path===endpoint+'/log')return route.fulfill({contentType:'text/plain',body:'转换完成'});
  if(path===endpoint+'/numeric-validations'&&request.method()==='POST'){
   expect(request.headers()['content-type']).toContain('multipart/form-data');
   expect(request.postData()).toContain('filename="sample.png"');
   expect(request.postData()).toContain('name="request_id"');
   expect(request.postData()).toContain('name="confidence"');
   expect(request.postData()).toContain('name="nms_iou"');
   const requestId=/name="request_id"\r\n\r\n([A-Za-z0-9_-]+)/.exec(request.postData()||'')?.[1];
   expect(requestId).toBeTruthy();
   verificationId='nv_'+createHash('sha256').update(`p:job-1:${requestId}`).digest('hex').slice(0,24);
   writes++;
   return route.abort();
  }
  if(path.startsWith(endpoint+'/numeric-validations/')&&request.method()==='GET'){
   expect(path.split('/').at(-1)).toBe(verificationId);
   return route.fulfill({json:{ok:true,id:verificationId,conversion_job_id:'job-1',
    task:{task_id:verificationId,project_id:'p',kind:'MODEL_CONVERSION',status:'SUCCEEDED'},
    result:{verdict:'consistent',raw_verdict:'consistent',detection_status:'unavailable',sample_count:1}}});
  }
  return route.fulfill({status:404,json:{detail:'unexpected '+path}});
 });
 await page.goto('/app/#/projects/p/conversions/job-1');
 await page.getByLabel('验证图片').setInputFiles({name:'sample.png',mimeType:'image/png',buffer:Buffer.from('fixture')});
 await page.getByRole('button',{name:'开始数值验证'}).click();
 expect(writes).toBe(0);
 await page.getByRole('button',{name:'确认发起验证'}).click();
 await expect(page.getByText('数值验证提交回执未知。')).toBeVisible();
 await page.getByRole('button',{name:'核对原验证请求'}).click();
 await expect(page.getByRole('button',{name:'刷新验证报告'})).toBeVisible();
 await expect(page.getByText('unavailable',{exact:true})).toBeVisible();
 expect(verificationId).toMatch(/^nv_[a-f0-9]{24}$/);
 expect(writes).toBe(1);
});

test('native conversion stop requires confirmation and reads server state after a lost response',async({page})=>{
 await assets(page);
 const endpoint='/api/v39/projects/p/deploy/jobs/job-1';
 let stops=0;
 let stopped=false;
 await page.route('**/api/**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path==='/api/auth/session')return route.fulfill({json:{authenticated:true}});
  if(path==='/api/projects')return route.fulfill({json:[{id:'p',name:'项目 P'}]});
  if(path===endpoint+'/stop'){
   expect(route.request().method()).toBe('POST');
   stops++;
   return route.abort();
  }
  expect(route.request().method()).toBe('GET');
  if(path===endpoint)return route.fulfill({json:{...deployment,project_id:'p',source_id:'source-1',status:stopped?'stopped':'running'}});
  if(path===endpoint+'/log')return route.fulfill({contentType:'text/plain',body:'转换日志'});
  return route.fulfill({status:404,json:{detail:'unexpected '+path}});
 });
 await page.goto('/app/#/projects/p/conversions/job-1');
 await page.getByRole('button',{name:'停止转换',exact:true}).click();
 const confirm=page.getByRole('dialog',{name:'停止转换'});
 await expect(confirm).toContainText('job-1');
 expect(stops).toBe(0);
 await confirm.getByRole('button',{name:'确认停止转换'}).click();
 await expect(page.getByText('停止回执未知。请刷新并核对当前任务状态。',{exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:'停止转换',exact:true})).toHaveCount(0);
 stopped=true;
 await page.getByRole('button',{name:'刷新',exact:true}).click();
 await expect(page.getByText('转换任务已停止',{exact:true})).toBeVisible();
 expect(stops).toBe(1);
});

test('native conversion history reuses the pilot read-only view against the v42 asset projection',async({page})=>{
 const writes:string[]=[];page.on('request',r=>{if(!['GET','HEAD'].includes(r.method()))writes.push(r.method()+' '+new URL(r.url()).pathname)});
 await assets(page);
 await page.route('**/api/**',route=>{
  const url=new URL(route.request().url()),path=url.pathname;
  if(path==='/api/auth/session')return route.fulfill({json:{authenticated:true,user:{username:'隔离用户'}}});
  if(path==='/api/projects')return route.fulfill({json:[{id:'p',name:'项目 P'}]});
  if(path==='/api/v42/projects/p/algorithms/a/versions/v/deployments'){
   expect(url.searchParams.get('asset_view')).toBe('true');
   expect(url.searchParams.get('page')).toBe('1');
   expect(url.searchParams.get('page_size')).toBe('20');
   return route.fulfill({json:historyPage});
  }
  return route.fulfill({status:404,json:{detail:'unexpected '+path}});
 });
 await page.goto('/app/#/projects/p/algorithms/a/versions/v/conversions?algorithm_name='+encodeURIComponent('算法 A')+'&version_name='+encodeURIComponent('版本 V1'));
 await expect(page.locator('.catalog-preview h1')).toHaveText('转换记录与诊断');
 await expect(page.getByText('算法 A',{exact:true})).toBeVisible();
 await expect(page.getByRole('row').filter({hasText:'job-1'})).toBeVisible();
 await expect(page.getByRole('row').filter({hasText:'job-1'})).toContainText('RKNN');
 await expect(page.getByText('共 1 条 · 当前版本范围',{exact:true})).toBeVisible();
 // T2-C: creation is native now; the read-only pilot list still owns the records.
 await expect(page.getByRole('button',{name:'创建版本转换',exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:'原版本转换 / 验证',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'查看转换job-1详情',exact:true}).click();
 const drawer=page.getByRole('dialog',{name:'转换任务诊断与证据'});
 await expect(drawer).toBeVisible();
 await expect(drawer).toContainText('数值一致性状态');
 await expect(drawer).toContainText('matched');
 await expect(drawer).toContainText('model.rknn');
 await expect(drawer).toContainText('2.3.0');
 await expect(drawer.getByRole('button',{name:'原生任务详情',exact:true})).toBeVisible();
 await drawer.getByRole('button',{name:'返回当前记录列表',exact:true}).click();
 await expect(drawer).toBeHidden();
 expect(writes).toEqual([]);
});

test('algorithm library keeps the old conversion entry and adds the native conversion-history link',async({page})=>{
 await assets(page);
 const algorithm={id:'a',name:'算法 A',algorithm_type:'yolo_ultralytics',source_type:'local',trainable:true,version_count:1,current_version_id:'v',current_version:{id:'v',version_name:'版本 V1'},editable:true};
 const version={id:'v',algorithm_id:'a',version_name:'版本 V1',training_status:'SUCCEEDED',framework:'ultralytics',has_model:true};
 await page.route('**/api/**',route=>{
  const url=new URL(route.request().url()),path=url.pathname;
  if(path==='/api/auth/session')return route.fulfill({json:{authenticated:true,user:{username:'隔离用户'}}});
  if(path==='/api/projects')return route.fulfill({json:[{id:'p',name:'项目 P'}]});
  if(path==='/api/v12/projects/p/algorithms')return route.fulfill({json:{ok:true,project_id:'p',items:[algorithm],total:1,page:1,page_size:10,filter_options:{algorithm_type:['yolo_ultralytics'],industry:[]}}});
  if(path==='/api/v12/projects/p/algorithms/a')return route.fulfill({json:{ok:true,project_id:'p',algorithm,items:[version],total:1,page:1,page_size:20,versions_deferred:false}});
  if(path==='/api/v42/projects/p/algorithms/a/versions/v/deployments')return route.fulfill({json:historyPage});
  return route.fulfill({status:404,json:{detail:'unexpected '+path}});
 });
 await page.goto('/app/#/projects/p/algorithms');
 await page.getByRole('button',{name:'算法 A',exact:true}).click();
 const nativeLink=page.getByRole('link',{name:'转换记录（原生）',exact:true});
 await expect(nativeLink).toBeVisible();
 await expect(nativeLink).toHaveAttribute('href',/#\/projects\/p\/algorithms\/a\/versions\/v\/conversions\?.*algorithm_name=/);
 await expect(page.getByRole('link',{name:'转换 · 原流程',exact:true})).toHaveAttribute('href',/algorithm_id=a&version_id=v&action=conversion/);
 await nativeLink.click();
 await expect(page).toHaveURL(/\/app\/#\/projects\/p\/algorithms\/a\/versions\/v\/conversions\?/);
 await expect(page.locator('.catalog-preview h1')).toHaveText('转换记录与诊断');
 await expect(page.getByRole('row').filter({hasText:'job-1'})).toBeVisible();
});

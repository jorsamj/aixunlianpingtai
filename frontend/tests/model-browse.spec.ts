import {test,expect,type Page} from '@playwright/test';
import {fixture} from './fixture';

async function setup(page:Page){
 const requests:{method:string;path:string;query:string}[]=[];let denied=false,hold=false;
 const algorithms=Array.from({length:23},(_,i)=>({id:`a${i}`,name:`算法 ${String(i).padStart(2,'0')}`,algorithm_type:'yolo_ultralytics',industry:'安全',source_type:'LOCAL',status:'active',versions_deferred:true,version_count:22,current_version_id:`v${i}-0`,current_version:{id:`v${i}-0`,version_name:'当前版本'},created_at:'2026-11-01'}));
 const versions=(aid:string)=>Array.from({length:22},(_,i)=>({id:`v${aid.slice(1)}-${i}`,algorithm_id:aid,version_name:i===0?'当前版本':`历史版本 ${i}`,training_status:'SUCCEEDED',framework:'ultralytics',artifact_verified:true,model_file:{file_name:'best.pt',extension:'pt',availability:'UNVERIFIED'},metrics:{map50:i===0?0:null},test_metrics:{map50:0.72}}));
 await page.route('**/model-fixture*',route=>route.fulfill({contentType:'text/html',body:fixture}));
 await page.route('**/api/**',async route=>{
  const url=new URL(route.request().url()),path=url.pathname;requests.push({method:route.request().method(),path,query:url.search});
  if(path==='/api/auth/session')return route.fulfill({json:{authenticated:true,user:{username:'原会话用户'}}});
  if(denied&&path.includes('/algorithms'))return route.fulfill({status:403,json:{code:'FORBIDDEN',message:'没有模型读取权限'}});
  const match=path.match(/^\/api\/(v12|v42)\/projects\/([^/]+)\/algorithms(?:\/([^/]+))?(?:\/versions\/([^/]+)\/deployments)?$/);
  if(match){
   const [,api,project,aid,vid]=match,index=Number(url.searchParams.get('page')||1),version=url.searchParams.get('version_id');
   if(hold&&version)await new Promise(resolve=>setTimeout(resolve,700));
   if(api==='v42'){
    const rows=Array.from({length:105},(_,i)=>({id:`j${i}`,status:i%2?'failed':'done',target:'onnx',target_name:'ONNX',stage:'任务结束',progress:i%2?null:100,created_at:'2026-11-15',params:{chip:'rk3568',precision:'fp16',csc_preset:'none'},source_identity:{algorithm_id:aid,version_id:vid,sha256:'immutable-source-sha'},outputs:[{file_name:'model.onnx',exists:false}],numeric_status:null,publication_status:null,hardware_verified:false,validation_status:'unverified',error:i%2?'编译依赖缺失':''}));
    return route.fulfill({json:{ok:true,project_id:project,algorithm_id:aid,version_id:vid,version:{id:vid,algorithm_id:aid},items:rows.slice((index-1)*20,index*20),total:105,page:index,page_size:20,complete:true,filter_options:{status:['done','failed'],target:['onnx'],chip:['rk3568'],precision:['fp16'],csc:['none']}}});
   }
   if(!aid){let rows=project==='q'?[{...algorithms[0],id:'q-alg',name:'新项目算法'}]:algorithms;const query=url.searchParams.get('query');if(query)rows=rows.filter(row=>row.name.includes(query));return route.fulfill({json:{ok:true,project_id:project,items:rows.slice((index-1)*20,index*20),total:rows.length,page:index,page_size:20,filter_options:{algorithm_type:['yolo_ultralytics'],industry:['安全'],source_type:['LOCAL'],status:['active']}}})}
   if(version){const row=versions(aid).find(row=>row.id===version);return route.fulfill({json:{ok:true,project_id:project,algorithm_id:aid,version:{...row,classes:['smoke'],class_count:1,training_job_id:'saved-task',training_parameters:{epochs:50,dynamic:false},training_lineage:{base_version_id:'base-stable'},model_metadata:{image_width:640,image_height:640},metrics:{map50:null},val_metrics:{map50:0},test_metrics:{map50:.72}},artifacts:{items:[{artifact_id:'original-artifact',artifact_kind:'original',file_name:'best.pt',storage_status:'PENDING'},{artifact_id:'converted-artifact',artifact_kind:'converted',file_name:'model.onnx',conversion_job_id:'j0',storage_status:'UPLOADED'}],total:2,truncated:false}}})}
   const rows=versions(aid);return route.fulfill({json:{ok:true,project_id:project,algorithm:algorithms.find(row=>row.id===aid)||{id:aid,name:'新项目算法'},items:rows.slice((index-1)*20,index*20),total:22,page:index,page_size:20,versions_deferred:false}});
  }
  return route.fulfill({json:{ok:true,items:[],page:1,page_size:10,total:0,revision:1,templates:[]}});
 });
 await page.goto('/model-fixture?vue_model_assets=1');await page.waitForFunction(()=>window.fixtureReady);await page.evaluate(()=>window.setPage('模型资产只读浏览'));await expect(page.getByRole('heading',{name:'模型资产与算法版本',exact:true})).toBeVisible();
 return {requests,setDenied:(v:boolean)=>denied=v,setHold:(v:boolean)=>hold=v};
}

test('summary, lazy versions and evidence details lead into paged version history with preserved context',async({page})=>{
 const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message));const h=await setup(page);
 await expect(page.getByText('尚未读取版本，请先选择算法',{exact:true})).toBeVisible();expect(h.requests.filter(row=>row.path.includes('/algorithms/')&&row.path.startsWith('/api/v12')).length).toBe(0);
 await page.getByRole('button',{name:'选择算法算法 00',exact:true}).click();await expect(page.getByRole('region',{name:'模型版本列表',exact:true}).getByText('当前版本',{exact:true})).toHaveCount(2);
 expect(h.requests.filter(row=>row.query.includes('version_id=')).length).toBe(0);
 await page.getByRole('button',{name:'查看版本v0-0详情',exact:true}).click();await expect(page.getByRole('heading',{name:'Val 指标',exact:true})).toBeVisible();const val=page.locator('.metric-group').filter({has:page.getByRole('heading',{name:'Val 指标',exact:true})});await expect(val.getByText('0',{exact:true})).toBeVisible();await expect(page.getByText('没有匹配的登记记录；未执行存储扫描。',{exact:true})).toHaveCount(0);await expect(page.getByText('converted-artifact',{exact:true})).toBeVisible();await expect(page.getByText('未核验，请使用原授权入口',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'查看转换历史',exact:true}).click();await expect(page.getByText('共 105 条 · 当前版本范围',{exact:true})).toBeVisible();expect(h.requests.filter(row=>row.path.endsWith('/deployments')).length).toBe(1);
 const list=page.getByRole('region',{name:'版本转换记录列表',exact:true});await list.locator('.btn-next').click();await expect(page.getByRole('button',{name:'查看转换j20详情',exact:true})).toBeVisible();await page.getByRole('button',{name:'查看转换j20详情',exact:true}).click();await expect(page.getByText('未提供数值验证证据',{exact:true})).toBeVisible();await expect(page.getByText('未提供发布证据',{exact:true})).toBeVisible();await expect(page.getByText('文件不存在',{exact:true})).toBeVisible();await expect(page.getByText('immutable-source-sha',{exact:true})).toBeVisible();await page.getByRole('button',{name:'返回当前记录列表',exact:true}).click();
 for(const width of [1366,768]){await page.setViewportSize({width,height:1000});await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:`../test-results/vue-catalog/conversion-history-${width}.png`,fullPage:true,animations:'disabled'})}
 await page.getByRole('button',{name:'返回版本浏览',exact:true}).click();await page.getByRole('button',{name:'查看版本v0-0转换历史',exact:true}).click();await expect(page.getByRole('button',{name:'查看转换j20详情',exact:true})).toBeVisible();expect(h.requests.filter(row=>row.path.endsWith('/deployments')).at(-1)?.query).toContain('page=2');
 await page.getByRole('button',{name:'返回版本浏览',exact:true}).click();
 for(const width of [1366,768]){await page.setViewportSize({width,height:1000});await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:`../test-results/vue-catalog/model-assets-${width}.png`,fullPage:true,animations:'disabled'})}
 expect(h.requests.every(row=>row.method==='GET')).toBe(true);expect(h.requests.some(row=>row.path.startsWith('/api/v64')||row.path.includes('report'))).toBe(false);expect(errors).toEqual([]);
});

test('project switch cancels old version detail and does not reuse old project records; errors remain distinct',async({page})=>{
 const h=await setup(page);await page.getByRole('button',{name:'选择算法算法 00',exact:true}).click();await expect(page.getByRole('button',{name:'查看版本v0-0详情',exact:true})).toBeVisible();h.setHold(true);let aborted=false;page.on('requestfailed',request=>{if(request.url().includes('version_id='))aborted=true});await page.getByRole('button',{name:'查看版本v0-0详情',exact:true}).click();await page.evaluate(()=>{window.state.project={id:'q'};window.setPage('模型资产只读浏览')});await expect(page.getByRole('button',{name:'选择算法新项目算法',exact:true})).toBeVisible();await expect(page.getByText('尚未读取版本，请先选择算法',{exact:true})).toBeVisible();await expect.poll(()=>aborted).toBe(true);await expect(page.locator('.evidence-details')).toHaveCount(0);
 h.setDenied(true);await page.getByRole('button',{name:'刷新算法',exact:true}).click();await expect(page.getByText('没有模型读取权限',{exact:true})).toBeVisible();await expect(page.getByText('暂无匹配算法',{exact:true})).toHaveCount(0);
});

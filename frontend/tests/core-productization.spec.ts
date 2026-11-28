import {test,expect,type Page} from '@playwright/test';
import {fixture} from './fixture';
async function setup(page:Page){
 const writes:string[]=[];let saved:any=null,lost=false,deny=false;
 await page.route('**/core-fixture*',route=>route.fulfill({contentType:'text/html',body:fixture}));
 await page.route('**/api/**',async route=>{const req=route.request(),u=new URL(req.url()),p=u.pathname;
  if(p==='/api/auth/session')return route.fulfill({json:{authenticated:true,user:{username:'隔离用户'}}});
  if(req.method()!=='GET'){writes.push(req.method()+' '+p);saved={id:'new',...req.postDataJSON(),editable:true};if(lost)return route.fulfill({contentType:'application/json',body:'{broken'});return route.fulfill({json:{ok:true,algorithm:saved}})}
  if(p.includes('/algorithms')){
   const id=p.split('/algorithms/')[1];if(u.searchParams.has('basic_only'))return route.fulfill({json:{ok:true,project_id:'p',algorithm:id==='ext'?{id:'ext',name:'外部算法',remark:'远端主数据',industry:'安全',algorithm_type:'custom_python',editable:false}:saved||{id:'a',name:'已有算法',remark:'完整备注',industry:'安全',algorithm_type:'custom_python',editable:true}}});
   if(id)return route.fulfill({json:{ok:true,project_id:'p',algorithm:{id,name:id==='ext'?'外部算法':saved?.name||'已有算法',current_version_id:'v'},items:id==='ext'?[]:[{id:'v',algorithm_id:id,version_name:'正式版本',training_job_id:'t0',metrics:{map50:null}}],total:id==='ext'?0:1,page:1,page_size:20,versions_deferred:false}});
   return route.fulfill({json:{ok:true,project_id:'p',items:[{id:'a',name:'已有算法',version_count:1,versions_deferred:true},{id:'ext',name:'外部算法',source_type:'EXTERNAL',version_count:0},...(saved?[saved]:[])],total:saved?3:2,page:1,page_size:20,filter_options:{}}});
  }
  if(p.includes('/tasks')){
   if(deny)return route.fulfill({status:403,json:{message:'没有训练任务读取权限'}});
   const row=(i:number)=>({task_id:`t${i}`,project_id:'p',kind:'TRAINING',status:i%2?'WAITING_RESOURCE':'SUCCEEDED',persisted_status:i%2?'QUEUED':'SUCCEEDED',phase:i%2?'resource_waiting':'finished',progress_percent:i%2?0:100,report_job_id:`t${i}`,algorithm_id:'a',version_id:'v',worker_id:i%2?null:'saved-worker',resource_key:'training:auto',created_at:'2026-11-17'});
   const id=p.split('/tasks/')[1];if(id)return route.fulfill({json:{ok:true,project_id:'p',task:{...row(Number(id.slice(1))),configuration:{epochs:50,batch:4},execution:{node_id:'saved-node'},error:'已保存诊断'}}});
   const second=u.searchParams.get('cursor')==='second';return route.fulfill({json:{ok:true,project_id:'p',items:Array.from({length:second?3:20},(_,i)=>row(i+(second?20:0))),next_cursor:second?null:'second',filter_options:{status:['QUEUED','SUCCEEDED'],kind:['TRAINING','TRAINING_PREPARE']}}});
  }
  if(p.endsWith('/report'))return route.fulfill({json:{ok:true,project_id:'p',job_id:p.split('/jobs/')[1].split('/')[0],algorithm_id:'a',version_id:'v',state:'AVAILABLE',source:'DURABLE_FINALIZED',val_metrics:{precision:0,recall:null,map50:null,map50_95:.5},test_metrics:{map50:.72},test_status:'succeeded',configuration:{epochs:50},result:{status:'SUCCEEDED'},history:[{epoch:1,map50:0}],warnings:['已有趋势信号：先核查数据隔离']}});
  return route.fulfill({json:{ok:true,items:[],page:1,page_size:10,total:0,revision:1,templates:[]}});
 });
 await page.goto('/core-fixture?vue_algorithm_manage=1&vue_training_tasks=1&vue_training_report=1');await page.waitForFunction(()=>window.fixtureReady);await page.evaluate(()=>window.setPage('模型资产只读浏览'));await expect(page.getByRole('heading',{name:'算法管理与模型版本',exact:true})).toBeVisible();
 return {writes,lost:()=>lost=true,deny:()=>deny=true};
}
test('local algorithm create/edit reads back; external record remains protected',async({page})=>{
 const h=await setup(page);await page.getByRole('button',{name:'新增本地算法',exact:true}).click();await page.getByRole('textbox',{name:'算法名称',exact:true}).fill('新算法');await page.getByRole('textbox',{name:'算法备注',exact:true}).fill('真实备注');await page.getByRole('button',{name:'保存并核验',exact:true}).click();await expect(page.getByRole('button',{name:'选择算法新算法',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'算法详情 / 基本编辑',exact:true}).click();await expect(page.getByRole('textbox',{name:'算法备注',exact:true})).toHaveValue('真实备注');await page.getByRole('textbox',{name:'算法名称',exact:true}).fill('已编辑算法');await page.getByRole('button',{name:'保存并核验',exact:true}).click();await expect(page.getByRole('button',{name:'选择算法已编辑算法',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'选择算法外部算法',exact:true}).click();await page.getByRole('button',{name:'算法详情 / 基本编辑',exact:true}).click();await expect(page.getByRole('button',{name:'保存并核验',exact:true})).toBeDisabled();expect(h.writes).toEqual(['POST /api/v12/projects/p/algorithms','PUT /api/v12/projects/p/algorithms/new']);
});
test('task cursor page and report return preserve context; read errors stay distinct',async({page})=>{
 const h=await setup(page);await page.getByRole('button',{name:'训练任务中心',exact:true}).click();await page.getByRole('button',{name:'下一页',exact:true}).click();await page.getByRole('button',{name:'查看任务t20',exact:true}).click();await expect(page.getByText('saved-node',{exact:true})).toBeVisible();await page.getByRole('button',{name:'阅读训练报告',exact:true}).click();await expect(page.getByRole('heading',{name:'Val 指标',exact:true})).toBeVisible();await expect(page.getByText('DURABLE_FINALIZED',{exact:true})).toBeVisible();
 const val=page.locator('.report-metrics>section').first();await expect(val.getByText('未提供',{exact:true})).toHaveCount(2);await expect(val.getByText('0',{exact:true})).toBeVisible();
 for(const width of [1366,768]){await page.setViewportSize({width,height:1000});await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:`../test-results/vue-catalog/training-report-${width}.png`,fullPage:true,animations:'disabled'})}
 await page.getByRole('button',{name:'返回来源列表',exact:true}).click();await expect(page.getByRole('button',{name:'查看任务t20',exact:true})).toBeVisible();for(const width of [1366,768]){await page.setViewportSize({width,height:1000});await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:`../test-results/vue-catalog/training-tasks-${width}.png`,fullPage:true,animations:'disabled'})}
 h.deny();await page.getByRole('button',{name:'刷新任务',exact:true}).click();await expect(page.getByText('没有训练任务读取权限',{exact:true})).toBeVisible();expect(h.writes).toEqual([]);
});
test('unknown algorithm creation result blocks duplicate after leaving and reentering',async({page})=>{
 const h=await setup(page);h.lost();await page.getByRole('button',{name:'新增本地算法',exact:true}).click();await page.getByRole('textbox',{name:'算法名称',exact:true}).fill('未知结果');await page.getByRole('button',{name:'保存并核验',exact:true}).click();await expect(page.getByRole('button',{name:'保存并核验',exact:true})).toBeDisabled();await page.getByRole('button',{name:'关闭',exact:true}).last().click();await expect(page.getByRole('button',{name:'新增本地算法',exact:true})).toBeDisabled();await page.evaluate(()=>window.setPage('训练任务只读中心'));await page.evaluate(()=>window.setPage('模型资产只读浏览'));await expect(page.getByRole('button',{name:'新增本地算法',exact:true})).toBeDisabled();expect(h.writes.length).toBe(1);
});

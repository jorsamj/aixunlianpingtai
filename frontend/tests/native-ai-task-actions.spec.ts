import {expect,test,type Page} from '@playwright/test';
import {resolve} from 'node:path';

async function assets(page:Page){
 await page.route('**/app/**',route=>{
  const name=new URL(route.request().url()).pathname.slice('/app/'.length)||'index.html';
  return route.fulfill({path:resolve('../static/vue-app',name),contentType:name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':'text/html'});
 });
}
const counts={total:8,success:5,empty:1,failed:2,accepted:0,rejected:0,unreviewed:8,boxes:3,gt_committed:0};
const task=(id:string,overrides:Record<string,unknown>={})=>({id,project_id:'p',name:'任务 '+id,kind:'AI_ANNOTATION',
 status:'AWAITING_CONFIRMATION',phase:'awaiting_confirmation',progress_percent:100,created_at:'2026-11-24T09:30:00',
 statistics_known:true,total_count:8,completed_count:8,remaining_count:0,counts,accepted:null,
 requested_labels:['fire'],model_config_name:'模型 A',worker_id:'worker-1',...overrides});
const failed={image_id:'img-1',filename:'one.jpg',thumbnail_url:'/api/v61/projects/p/materials/img-1/content/thumbnail?edge=384',
 status:'failed',error:'模型服务连接中断',retry_suggestion:'检查模型服务后重试该图'};

test('native AI task detail shows real progress and writes through the existing v60 endpoints',async({page})=>{
 const writes:{method:string;path:string;body:string|null}[]=[];
 const listQueries:string[]=[];
 await assets(page);
 await page.route('**/api/**',async route=>{
  const url=new URL(route.request().url()),path=url.pathname,method=route.request().method();
  if(method!=='GET')writes.push({method,path,body:route.request().postData()});
  if(path==='/api/auth/session')return route.fulfill({json:{authenticated:true,user:{username:'隔离用户'}}});
  if(path==='/api/projects')return route.fulfill({json:[{id:'p',name:'项目 P'}]});
  if(path==='/api/v60/projects/p/annotation-tasks'&&method==='GET'){
   listQueries.push(url.search||'');
   return route.fulfill({json:{ok:true,project_id:'p',items:[
    task('task-running',{name:'运行中任务',status:'RUNNING',phase:'generation',progress_percent:40,completed_count:4}),
    task('task-failed',{name:'失败任务',status:'FAILED',phase:'generation',progress_percent:100}),
   ],next_cursor:null}});
  }
  if(path==='/api/v60/projects/p/annotation-tasks/task-running'&&method==='GET')
   return route.fulfill({json:{ok:true,project_id:'p',task:task('task-running',{name:'运行中任务',status:'RUNNING',phase:'generation',progress_percent:40,completed_count:4})}});
  if(path==='/api/v60/projects/p/annotation-tasks/task-failed'&&method==='GET')
   return route.fulfill({json:{ok:true,project_id:'p',task:task('task-failed',{name:'失败任务',status:'FAILED',phase:'generation',progress_percent:100})}});
  if(path.endsWith('/candidates')&&method==='GET')
   return route.fulfill({json:{ok:true,project_id:'p',task_id:path.includes('task-failed')?'task-failed':'task-running',
    items:[failed],next_cursor:null,total:1,review_revision:1}});
  if(path==='/api/v60/projects/p/annotation-tasks/task-running/cancel'&&method==='POST')
   return route.fulfill({json:task('task-running',{name:'运行中任务',status:'CANCEL_REQUESTED',phase:'cancelling',progress_percent:40})});
  if(path==='/api/v60/projects/p/annotation-tasks/task-failed/retry'&&method==='POST')
   return route.fulfill({json:task('task-failed',{name:'失败任务',status:'RUNNING',phase:'generation',progress_percent:10})});
  return route.fulfill({status:404,json:{detail:'unexpected '+path}});
 });
 await page.goto('/app/#/projects/p/ai/tasks');
 await expect(page.getByRole('heading',{level:2,name:'AI 标注任务',exact:true})).toBeVisible();
 expect(writes).toEqual([]);
 await page.getByRole('row').filter({hasText:'运行中任务'}).getByRole('button',{name:'查看进度',exact:true}).click();
 const drawer=page.getByRole('dialog',{name:'AI 标注任务：进度与写操作'});
 await expect(drawer).toBeVisible();
 await expect(drawer).toContainText('4 / 8');
 await expect(drawer).toContainText('40.0%');
 await expect(drawer).toContainText('worker-1');
 await expect(drawer.getByRole('button',{name:'取消任务',exact:true})).toBeVisible();
 await drawer.getByRole('button',{name:'取消任务',exact:true}).click();
 await expect(drawer.getByText('取消请求已由服务端受理')).toBeVisible();
 await expect.poll(()=>writes.filter(row=>row.path.endsWith('/cancel')).length).toBe(1);
 expect(writes.filter(row=>row.path.endsWith('/cancel'))[0]).toMatchObject({method:'POST',body:null});
 await drawer.getByRole('button',{name:'返回任务列表',exact:true}).click();
 await expect(drawer).toBeHidden();
 await page.getByRole('row').filter({hasText:'失败任务'}).getByRole('button',{name:'查看进度',exact:true}).click();
 await expect(drawer).toContainText('失败 / 未完成素材（1）');
 await expect(drawer).toContainText('one.jpg');
 await drawer.getByRole('button',{name:'继续任务（合法重试）',exact:true}).click();
 await expect.poll(()=>writes.filter(row=>row.path.endsWith('/retry')).length).toBe(1);
 expect(writes.filter(row=>row.path.endsWith('/retry'))[0]).toMatchObject({method:'POST',body:null});
 await expect(drawer.getByText('继续生成请求已受理')).toBeVisible();
 expect(listQueries.length).toBeGreaterThan(1);
});

test('native AI task writes never auto-repeat an unconfirmed receipt or accept a foreign receipt',async({page})=>{
 let cancels=0;
 await assets(page);
 await page.route('**/api/**',async route=>{
  const url=new URL(route.request().url()),path=url.pathname,method=route.request().method();
  if(path==='/api/auth/session')return route.fulfill({json:{authenticated:true,user:{username:'隔离用户'}}});
  if(path==='/api/projects')return route.fulfill({json:[{id:'p',name:'项目 P'}]});
  if(path==='/api/v60/projects/p/annotation-tasks'&&method==='GET')
   return route.fulfill({json:{ok:true,project_id:'p',items:[task('task-running',{status:'RUNNING',progress_percent:40})],next_cursor:null}});
  if(path.endsWith('/candidates')&&method==='GET')
   return route.fulfill({json:{ok:true,project_id:'p',task_id:'task-running',items:[],next_cursor:null,total:0,review_revision:0}});
  if(path.endsWith('/task-running')&&method==='GET')
   return route.fulfill({json:{ok:true,project_id:'p',task:task('task-running',{status:'RUNNING',progress_percent:40})}});
  if(path.endsWith('/cancel')&&method==='POST'){
   cancels+=1;
   return route.fulfill({status:500,json:{detail:'服务端暂时无法确认取消'}});
  }
  return route.fulfill({status:404,json:{detail:'unexpected '+path}});
 });
 await page.goto('/app/#/projects/p/ai/tasks?');
 await page.getByRole('row').filter({hasText:'task-running'}).getByRole('button',{name:'查看进度',exact:true}).click();
 const drawer=page.getByRole('dialog',{name:'AI 标注任务：进度与写操作'});
 await drawer.getByRole('button',{name:'取消任务',exact:true}).click();
 await expect(drawer.getByText(/结果待核验/)).toBeVisible();
 await page.waitForTimeout(1200);
 expect(cancels).toBe(1);
 await expect(drawer.getByRole('button',{name:'取消任务',exact:true})).toBeEnabled();
});

test('native AI task page keeps create on the legacy owner, links review back and locates materials',async({page})=>{
 const writes:string[]=[];
 await assets(page);
 await page.route('**/api/**',async route=>{
  const url=new URL(route.request().url()),path=url.pathname,method=route.request().method();
  if(method!=='GET')writes.push(method+' '+path);
  if(path==='/api/auth/session')return route.fulfill({json:{authenticated:true,user:{username:'隔离用户'}}});
  if(path==='/api/projects')return route.fulfill({json:[{id:'p',name:'项目 P'}]});
  if(path==='/api/v60/projects/p/annotation-tasks'&&method==='GET')
   return route.fulfill({json:{ok:true,project_id:'p',items:[task('task-await')],next_cursor:null}});
  if(path.includes('/annotation-tasks/task-await')&&method==='GET'&&!path.endsWith('/candidates'))
   return route.fulfill({json:{ok:true,project_id:'p',task:task('task-await')}});
  if(path.endsWith('/candidates')&&method==='GET')
   return route.fulfill({json:{ok:true,project_id:'p',task_id:'task-await',items:[failed],next_cursor:null,total:1,review_revision:1}});
  return route.fulfill({status:404,json:{detail:'unexpected '+path}});
 });
 await page.goto('/app/#/projects/p/ai/tasks');
 const create=page.getByRole('link',{name:'创建任务（原工作台）',exact:true});
 await expect(create).toBeVisible();
 await expect(create).toHaveAttribute('href',/page=%E8%87%AA%E5%8A%A8%E6%A0%87%E6%B3%A8/);
 await expect(create).toHaveAttribute('href',/action=material-ai/);
 await expect(page.getByRole('link',{name:'原完整自动标注',exact:true})).toHaveAttribute('href',/page=%E8%87%AA%E5%8A%A8%E6%A0%87%E6%B3%A8/);
 await page.getByRole('row').filter({hasText:'task-await'}).getByRole('button',{name:'查看进度',exact:true}).click();
 const drawer=page.getByRole('dialog',{name:'AI 标注任务：进度与写操作'});
 await expect(drawer.getByRole('button',{name:'进入审核',exact:true})).toBeVisible();
 await drawer.getByRole('button',{name:'在素材库定位',exact:true}).click();
 await expect(page).toHaveURL(/\/app\/#\/projects\/p\/materials\?detail=img-1/);
 expect(writes).toEqual([]);
});

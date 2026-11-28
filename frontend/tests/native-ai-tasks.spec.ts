import {expect,test,type Page} from '@playwright/test';
import {resolve} from 'node:path';

async function assets(page:Page){
 await page.route('**/app/**',route=>{
  const name=new URL(route.request().url()).pathname.slice('/app/'.length)||'index.html';
  return route.fulfill({path:resolve('../static/vue-app',name),contentType:name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':'text/html'});
 });
}
const counts={total:8,success:5,empty:1,failed:2,accepted:4,rejected:0,unreviewed:4,boxes:3,gt_committed:0};
const task=(id:string,overrides:Record<string,unknown>={})=>({id,project_id:'p',name:'任务 '+id,status:'AWAITING_CONFIRMATION',phase:'awaiting_confirmation',progress_percent:100,created_at:'2026-11-24T09:30:00',statistics_known:true,total_count:8,completed_count:8,remaining_count:0,counts,...overrides});
const reviewTask={id:'task-1',project_id:'p',name:'任务 task-1',status:'AWAITING_CONFIRMATION'};

test('native AI task list reads the existing v60 reader page with cursor paging and status filter',async({page})=>{
 const listQueries:URLSearchParams[]=[],paths:string[]=[];page.on('request',r=>paths.push(new URL(r.url()).pathname));
 await assets(page);
 await page.route('**/api/**',route=>{
  const url=new URL(route.request().url()),path=url.pathname;
  if(path==='/api/auth/session')return route.fulfill({json:{authenticated:true,user:{username:'隔离用户'}}});
  if(path==='/api/projects')return route.fulfill({json:[{id:'p',name:'项目 P'},{id:'q',name:'项目 Q'}]});
  if(path==='/api/v60/projects/p/annotation-tasks'){
   expect(route.request().method()).toBe('GET');
   listQueries.push(url.searchParams);
   expect(url.searchParams.get('reader_view')).toBe('true');
   expect(url.searchParams.get('limit')).toBe('20');
   const status=url.searchParams.get('status')||'',cursor=url.searchParams.get('cursor');
   if(status==='FAILED')return route.fulfill({json:{ok:true,project_id:'p',items:[task('task-failed',{status:'FAILED',name:'失败任务',progress_percent:null})],next_cursor:null}});
   if(cursor==='next-page')return route.fulfill({json:{ok:true,project_id:'p',items:[task('task-3',{status:'SUCCEEDED'})],next_cursor:null}});
   return route.fulfill({json:{ok:true,project_id:'p',items:[task('task-1'),task('task-2',{status:'FAILED',name:'失败任务二'})],next_cursor:'next-page',statistics_indexing:false}});
  }
  if(path==='/api/v60/projects/p/annotation-tasks/task-1'){
   expect(url.searchParams.get('reader_view')).toBe('true');
   return route.fulfill({json:{ok:true,project_id:'p',task:reviewTask}});
  }
  if(path==='/api/v60/projects/p/annotation-tasks/task-1/candidates')
   return route.fulfill({json:{items:[],total:0,next_cursor:null,review_revision:1,summary:{}}});
  return route.fulfill({status:404,json:{detail:'unexpected '+path}});
 });
 await page.goto('/app/#/projects/p/ai/tasks');
 await expect(page.getByRole('heading',{level:2,name:'AI 标注任务',exact:true})).toBeVisible();
 const firstRow=page.getByRole('row').filter({hasText:'task-1'});
 await expect(firstRow).toContainText('等待确认');
 await expect(firstRow).toContainText('100%');
 await expect(firstRow).toContainText('2026-11-24 09:30:00');
 await expect(firstRow.getByRole('cell').nth(3)).toHaveText('2');
 await expect(page.getByText('第 1 页 · 本页 2 条',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'下一页',exact:true}).click();
 await expect(page.getByRole('row').filter({hasText:'task-3'})).toBeVisible();
 expect(listQueries.at(-1)?.get('cursor')).toBe('next-page');
 await expect(page.getByText('第 2 页 · 本页 1 条',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'上一页',exact:true}).click();
 await expect(page.getByRole('row').filter({hasText:'task-1'})).toBeVisible();
 expect(listQueries.at(-1)?.get('cursor')).toBeNull();
 await page.getByRole('combobox',{name:'AI任务状态',exact:true}).focus();
 await page.getByRole('combobox',{name:'AI任务状态',exact:true}).press('ArrowDown');
 await page.getByRole('option',{name:'失败',exact:true}).click();
 await page.getByRole('button',{name:'查询',exact:true}).click();
 await expect(page.getByRole('row').filter({hasText:'失败任务'})).toBeVisible();
 expect(listQueries.at(-1)?.get('status')).toBe('FAILED');
 expect(listQueries.at(-1)?.get('cursor')).toBeNull();
 expect(paths).not.toContain('/static/app.js');
 expect(paths).not.toContain('/static/main.mjs');
});

test('native AI task list opens the existing review route and links back to the list',async({page})=>{
 await assets(page);
 await page.route('**/api/**',route=>{
  const url=new URL(route.request().url()),path=url.pathname;
  if(path==='/api/auth/session')return route.fulfill({json:{authenticated:true,user:{username:'隔离用户'}}});
  if(path==='/api/projects')return route.fulfill({json:[{id:'p',name:'项目 P'}]});
  if(path==='/api/v60/projects/p/annotation-tasks')return route.fulfill({json:{ok:true,project_id:'p',items:[task('task-1')],next_cursor:null}});
  if(path==='/api/v60/projects/p/annotation-tasks/task-1')return route.fulfill({json:{ok:true,project_id:'p',task:reviewTask}});
  if(path==='/api/v60/projects/p/annotation-tasks/task-1/candidates')
   return route.fulfill({json:{items:[],total:0,next_cursor:null,review_revision:0,summary:{}}});
  return route.fulfill({status:404,json:{detail:'unexpected '+path}});
 });
 await page.goto('/app/#/projects/p/ai/tasks');
 await page.getByRole('button',{name:'进入审核',exact:true}).first().click();
 await expect(page).toHaveURL(/\/app\/#\/projects\/p\/ai\/tasks\/task-1\/review$/);
 const back=page.getByRole('link',{name:'返回任务列表',exact:true});
 await expect(back).toHaveAttribute('href','#/projects/p/ai/tasks');
 await expect(page.getByRole('link',{name:'返回原工作台',exact:true})).toBeVisible();
 await back.click();
 await expect(page).toHaveURL(/\/app\/#\/projects\/p\/ai\/tasks$/);
 await expect(page.getByRole('heading',{level:2,name:'AI 标注任务',exact:true})).toBeVisible();
});

test('native AI task list rejects foreign project rows and shows an honest empty state',async({page})=>{
 let foreign=true;
 await assets(page);
 await page.route('**/api/**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path==='/api/auth/session')return route.fulfill({json:{authenticated:true,user:{username:'隔离用户'}}});
  if(path==='/api/projects')return route.fulfill({json:[{id:'p',name:'项目 P'}]});
  if(path==='/api/v60/projects/p/annotation-tasks')
   return route.fulfill({json:{ok:true,project_id:'p',items:foreign?[{...task('other'),project_id:'q'}]:[],next_cursor:null}});
  return route.fulfill({status:404,json:{detail:'unexpected '+path}});
 });
 await page.goto('/app/#/projects/p/ai/tasks');
 await expect(page.getByText('AI任务分页身份不一致',{exact:true})).toBeVisible();
 await expect(page.getByText('other',{exact:true})).toHaveCount(0);
 foreign=false;
 await page.getByRole('button',{name:'刷新',exact:true}).click();
 await expect(page.getByText('当前条件下没有 AI 标注任务',{exact:true})).toBeVisible();
});

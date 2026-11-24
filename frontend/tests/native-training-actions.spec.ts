import {expect,test,type Page} from '@playwright/test';
import {resolve} from 'node:path';

async function assets(page:Page){
 await page.route('**/app/**',route=>{
  const name=new URL(route.request().url()).pathname.slice('/app/'.length)||'index.html';
  return route.fulfill({path:resolve('../static/vue-app',name),contentType:name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':'text/html'});
 });
}
const base={project_id:'p',task_id:'t',kind:'TRAINING',progress_percent:40,created_at:'2026-11-24T09:00:00',
 algorithm_id:'a',algorithm_name:'算法 A',version_id:'v'};

function mockApi(page:Page,state:{task:Record<string,unknown>;writes:string[];pauseStatus?:number}){
 return page.route('**/api/**',async route=>{
  const url=new URL(route.request().url()),path=url.pathname,method=route.request().method();
  if(method!=='GET')state.writes.push(method+' '+path);
  if(path==='/api/auth/session')return route.fulfill({json:{authenticated:true,user:{username:'隔离用户'}}});
  if(path==='/api/projects')return route.fulfill({json:[{id:'p',name:'项目 P'}]});
  if(path==='/api/v62/projects/p/tasks'&&method==='GET')
   return route.fulfill({json:{ok:true,project_id:'p',items:[state.task],next_cursor:null,filter_options:{status:['RUNNING','PAUSED','QUEUED','SUCCEEDED'],kind:['TRAINING']}}});
  if(path==='/api/v62/projects/p/tasks/t'&&method==='GET')
   return route.fulfill({json:{ok:true,project_id:'p',task:state.task}});
  if(path==='/api/v62/projects/p/training-tasks/t/recovery'&&method==='GET')
   return route.fulfill({json:{ok:true,recovery:{task_id:'t',project_id:'p',task_status:String(state.task.status),
    available:false,recoverable:false,checkpoint_available:false,recovery_action:null}}});
  if(path==='/api/projects/p/jobs/t/log')return route.fulfill({contentType:'text/plain',body:'epoch 1 loss 0.4'});
  if(path==='/api/v48/projects/p/jobs/t/pause'&&method==='POST'){
   if(state.pauseStatus&&state.pauseStatus>=400)return route.fulfill({status:state.pauseStatus,json:{detail:'只有训练中的任务可以暂停'}});
   state.task={...state.task,status:'PAUSED',phase:'paused'};
   return route.fulfill({json:{status:'paused'}});
  }
  if(path==='/api/v48/projects/p/jobs/t/resume'&&method==='POST'){
   state.task={...state.task,status:'RUNNING',phase:'training'};
   return route.fulfill({json:{status:'running'}});
  }
  if(path==='/api/v48/projects/p/jobs/t/promote'&&method==='POST')
   return route.fulfill({json:{status:'queued'}});
  if(path==='/api/v12/projects/p/jobs/t'&&method==='DELETE'){
   state.task={...state.task,status:'SUCCEEDED'};
   return route.fulfill({json:{ok:true}});
  }
  return route.fulfill({status:404,json:{detail:'unexpected '+path}});
 });
}

test('native training page pauses and resumes through the real v48 lifecycle endpoints',async({page})=>{
 const state={task:{...base,status:'RUNNING',phase:'training'},writes:[] as string[]};
 await assets(page);
 await mockApi(page,state);
 await page.goto('/app/#/projects/p/training/tasks?task=t');
 const drawer=page.getByRole('dialog',{name:'任务详情'});
 await expect(drawer.getByRole('button',{name:'暂停训练',exact:true})).toBeVisible();
 expect(state.writes).toEqual([]);
 await drawer.getByRole('button',{name:'暂停训练',exact:true}).click();
 await expect(page.getByText('暂停请求已受理')).toBeVisible();
 await expect.poll(()=>state.writes.filter(row=>row.endsWith('/pause')).length).toBe(1);
 await expect(drawer.getByRole('button',{name:'继续训练',exact:true})).toBeVisible({timeout:5000});
 await drawer.getByRole('button',{name:'继续训练',exact:true}).click();
 await expect(page.getByText('继续训练请求已受理')).toBeVisible();
 await expect.poll(()=>state.writes.filter(row=>row.endsWith('/resume')).length).toBe(1);
});

test('native training page promotes queued tasks and deletes only terminal records',async({page})=>{
 const state={task:{...base,status:'QUEUED',phase:'queued'},writes:[] as string[]};
 await assets(page);
 await mockApi(page,state);
 await page.goto('/app/#/projects/p/training/tasks?task=t');
 let drawer=page.getByRole('dialog',{name:'任务详情'});
 await expect(drawer.getByRole('button',{name:'插队（排到最前）',exact:true})).toBeVisible();
 await drawer.getByRole('button',{name:'插队（排到最前）',exact:true}).click();
 await expect(page.getByText('已请求将任务排到当前训练资源队列最前')).toBeVisible();
 await expect.poll(()=>state.writes.filter(row=>row.endsWith('/promote')).length).toBe(1);
 await expect(drawer.getByRole('button',{name:'删除任务记录',exact:true})).toHaveCount(0);
 state.task={...state.task,status:'SUCCEEDED',phase:'finished'};
 await drawer.getByRole('button',{name:'刷新详情',exact:true}).click();
 await expect(drawer.getByRole('button',{name:'删除任务记录',exact:true})).toBeVisible({timeout:5000});
 page.on('dialog',dialog=>void dialog.accept());
 await drawer.getByRole('button',{name:'删除任务记录',exact:true}).click();
 await expect(page.getByText('已结束的训练任务记录已删除')).toBeVisible();
 await expect.poll(()=>state.writes.filter(row=>row==='DELETE /api/v12/projects/p/jobs/t').length).toBe(1);
 await expect(drawer).toBeHidden();
});

test('rejected training lifecycle writes show the server reason and are never auto-repeated',async({page})=>{
 const state={task:{...base,status:'RUNNING',phase:'training'},writes:[] as string[],pauseStatus:409};
 await assets(page);
 await mockApi(page,state);
 await page.goto('/app/#/projects/p/training/tasks?task=t');
 const drawer=page.getByRole('dialog',{name:'任务详情'});
 await drawer.getByRole('button',{name:'暂停训练',exact:true}).click();
 await expect(page.getByText(/暂停请求未受理：只有训练中的任务可以暂停/)).toBeVisible();
 await page.waitForTimeout(1200);
 expect(state.writes.filter(row=>row.endsWith('/pause')).length).toBe(1);
});

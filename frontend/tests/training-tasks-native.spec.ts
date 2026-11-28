import { expect, test } from '@playwright/test';
import { resolve } from 'node:path';

test('native training tasks preserve cursor, detail identity and cancellation truth', async ({page}) => {
  const requests: string[] = [];
  const parent = {project_id:'p',task_id:'t',kind:'TRAINING',status:'CANCEL_REQUESTED',phase:'cancelling',
    progress_percent:100,worker_id:'worker-1',resource_key:'training:auto',error:'等待进程退出',related_task_id:'trainprep_t'};
  const child = {project_id:'p',task_id:'trainprep_t',kind:'TRAINING_PREPARE',status:'SUCCEEDED',related_task_id:'t'};
  await page.route('**/app/**', route => {
    const path = new URL(route.request().url()).pathname.slice(5) || 'index.html';
    return route.fulfill({path:resolve('../static/vue-app',path),
      contentType:path.endsWith('.js')?'text/javascript':path.endsWith('.css')?'text/css':'text/html'});
  });
  await page.route('**/api/**', route => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    requests.push(path);
    expect(route.request().method()).toBe('GET');
    if(path==='/api/auth/session')return route.fulfill({json:{authenticated:true,user:{username:'测试'}}});
    if(path==='/api/projects')return route.fulfill({json:[{id:'p',name:'项目 P'}]});
    if(path==='/api/v62/projects/p/tasks'){
      expect(url.searchParams.get('reader_view')).toBe('true');
      expect(url.searchParams.get('limit')).toBe('20');
      expect(url.searchParams.get('query')).toBe('train');
      const next = url.searchParams.get('cursor')==='next';
      return route.fulfill({json:{ok:true,project_id:'p',items:[next?child:parent],
        next_cursor:next?null:'next',filter_options:{status:['QUEUED','CANCEL_REQUESTED'],kind:['TRAINING','TRAINING_PREPARE']}}});
    }
    if(path.endsWith('/jobs/t/log'))return route.fulfill({contentType:'text/plain',body:'checkpoint log'});
    const task = path.endsWith('/trainprep_t') ? child : path.endsWith('/foreign') ? {...parent,task_id:'foreign',project_id:'q'} : parent;
    return route.fulfill({json:{ok:true,project_id:'p',task}});
  });

  await page.goto('/app/#/projects/p/training/tasks?query=train');
  await expect(page.getByRole('cell',{name:'已请求取消',exact:true})).toBeVisible();
  await expect(page.getByText('100% · cancelling')).toBeVisible();
  await page.getByRole('button',{name:'下一页'}).click();
  await expect(page.getByRole('cell',{name:'trainprep_t',exact:true})).toBeVisible();
  await expect(page).toHaveURL(/cursor=next/);
  await page.getByRole('button',{name:'详情',exact:true}).click();
  const drawer = page.getByRole('dialog',{name:'任务详情'});
  await drawer.getByRole('button',{name:'t',exact:true}).click();
  await expect(drawer).toContainText('worker-1');
  await expect(drawer).toContainText('training:auto');
  await expect(drawer).toContainText('等待进程退出');
  await expect(drawer).toContainText('checkpoint log');
  await expect(drawer.getByRole('link',{name:'原工作台 · 停止任务'})).toHaveCount(0);
  await expect(drawer.getByRole('link',{name:'原工作台 · 操作与恢复'})).toHaveAttribute('href', /action=task-detail.*query=train.*cursor=next.*task_id=t/);
  await page.reload();
  await expect(drawer).toContainText('已请求取消 (CANCEL_REQUESTED)');
  await page.goto('/app/#/projects/p/training/tasks?query=train&task=foreign');
  await expect(drawer).toContainText('任务详情身份不一致');
  expect(requests).not.toContain('/api/projects/p/jobs/foreign/log');
});


test('native training stop requires confirmation and never reports CANCEL_REQUESTED as cancelled', async ({page}) => {
  const task = {project_id:'p',task_id:'t',kind:'TRAINING',status:'RUNNING',phase:'training',progress_percent:40};
  let stops = 0;
  await page.route('**/app/**', route => {
    const path = new URL(route.request().url()).pathname.slice(5) || 'index.html';
    return route.fulfill({path:resolve('../static/vue-app',path),
      contentType:path.endsWith('.js')?'text/javascript':path.endsWith('.css')?'text/css':'text/html'});
  });
  await page.route('**/api/**', route => {
    const url = new URL(route.request().url()), path = url.pathname, method = route.request().method();
    if(path==='/api/auth/session')return route.fulfill({json:{authenticated:true,user:{username:'测试'}}});
    if(path==='/api/projects')return route.fulfill({json:[{id:'p',name:'项目 P'}]});
    if(path==='/api/v62/projects/p/tasks'&&method==='GET')
      return route.fulfill({json:{ok:true,project_id:'p',items:[task],next_cursor:null,
        filter_options:{status:['RUNNING','CANCEL_REQUESTED'],kind:['TRAINING']}}});
    if(path==='/api/v62/projects/p/tasks/t/cancel'&&method==='POST'){
      stops += 1;
      return route.fulfill({status:202,json:{...task,status:'CANCEL_REQUESTED',phase:'cancelling'}});
    }
    if(path==='/api/v62/projects/p/training-tasks/t/recovery')
      return route.fulfill({json:{ok:true,recovery:{task_id:'t',project_id:'p',task_status:'RUNNING',
        available:false,recoverable:false,checkpoint_available:false,recovery_action:null}}});
    if(path==='/api/v62/projects/p/tasks/t'&&method==='GET')
      return route.fulfill({json:{ok:true,project_id:'p',task}});
    if(path.endsWith('/jobs/t/log'))return route.fulfill({contentType:'text/plain',body:''});
    return route.fulfill({status:404,json:{detail:'unhandled'}});
  });
  await page.goto('/app/#/projects/p/training/tasks?task=t');
  const drawer = page.getByRole('dialog',{name:'任务详情'});
  await expect(drawer.getByRole('button',{name:'停止任务',exact:true})).toBeVisible();
  expect(stops).toBe(0);
  page.on('dialog', dialog => dialog.accept());
  await drawer.getByRole('button',{name:'停止任务',exact:true}).click();
  await expect(drawer).toContainText('停止请求已记录', {timeout:10000});
  expect(stops).toBe(1);
  await expect(drawer).toContainText('已请求取消 (CANCEL_REQUESTED)');
  await expect(drawer).not.toContainText('已取消 (CANCELLED)');
});

test('native training recovery posts only a server-authorized checkpoint revalidation', async ({page}) => {
  const task = {project_id:'p',task_id:'t',kind:'TRAINING',status:'FAILED',phase:'final_validation',
    error:'final validation failed'};
  let posts = 0, payload = null;
  await page.route('**/app/**', route => {
    const path = new URL(route.request().url()).pathname.slice(5) || 'index.html';
    return route.fulfill({path:resolve('../static/vue-app',path),
      contentType:path.endsWith('.js')?'text/javascript':path.endsWith('.css')?'text/css':'text/html'});
  });
  await page.route('**/api/**', route => {
    const url = new URL(route.request().url()), path = url.pathname, method = route.request().method();
    if(path==='/api/auth/session')return route.fulfill({json:{authenticated:true,user:{username:'测试'}}});
    if(path==='/api/projects')return route.fulfill({json:[{id:'p',name:'项目 P'}]});
    if(path==='/api/v62/projects/p/tasks'&&method==='GET')
      return route.fulfill({json:{ok:true,project_id:'p',items:[task],next_cursor:null,
        filter_options:{status:['FAILED'],kind:['TRAINING']}}});
    if(path==='/api/v62/projects/p/training-tasks/t/recovery'&&method==='GET')
      return route.fulfill({json:{ok:true,recovery:{task_id:'t',project_id:'p',task_status:'FAILED',
        available:true,recoverable:true,checkpoint_available:true,
        recovery_action:'revalidate_checkpoint',failure_stage:'final_validation'}}});
    if(path==='/api/v62/projects/p/training-tasks/t/recovery'&&method==='POST'){
      posts += 1; payload = route.request().postDataJSON();
      return route.fulfill({status:202,json:{ok:true,task_id:'t',status:'FAILED',
        stage:'recovery_queued',attempt:2,recovery_requested:true}});
    }
    if(path==='/api/v62/projects/p/tasks/t'&&method==='GET')
      return route.fulfill({json:{ok:true,project_id:'p',task}});
    if(path.endsWith('/jobs/t/log'))return route.fulfill({contentType:'text/plain',body:''});
    return route.fulfill({status:404,json:{detail:'unhandled'}});
  });
  await page.goto('/app/#/projects/p/training/tasks?task=t');
  const drawer = page.getByRole('dialog',{name:'任务详情'});
  await expect(drawer).toContainText('FAILED');
  const recover = drawer.getByRole('button',{name:'恢复结果校验',exact:true});
  await expect(recover).toBeVisible({timeout:10000});
  expect(posts).toBe(0);
  page.on('dialog', dialog => dialog.accept());
  await recover.click();
  await expect(drawer).toContainText('恢复请求已受理', {timeout:10000});
  expect(posts).toBe(1);
  expect(payload).toEqual({action:'revalidate_checkpoint'});
  await expect(drawer).toContainText('FAILED');
});

async function serveApp(page) {
  await page.route('**/app/**', route => {
    const path = new URL(route.request().url()).pathname.slice(5) || 'index.html';
    return route.fulfill({path:resolve('../static/vue-app',path),
      contentType:path.endsWith('.js')?'text/javascript':path.endsWith('.css')?'text/css':'text/html'});
  });
}

test('late recovery truth from the previous task never updates the current task', async ({page}) => {
  const a = {project_id:'p',task_id:'a',kind:'TRAINING',status:'FAILED',phase:'final_validation'};
  const b = {project_id:'p',task_id:'b',kind:'TRAINING',status:'RUNNING',phase:'training',progress_percent:12};
  await serveApp(page);
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url()), path = url.pathname;
    if(path==='/api/auth/session')return route.fulfill({json:{authenticated:true,user:{username:'测试'}}});
    if(path==='/api/projects')return route.fulfill({json:[{id:'p',name:'项目 P'}]});
    if(path==='/api/v62/projects/p/tasks')return route.fulfill({json:{ok:true,project_id:'p',items:[a,b],
      next_cursor:null,filter_options:{status:['FAILED','RUNNING'],kind:['TRAINING']}}});
    if(path.endsWith('/jobs/a/log')||path.endsWith('/jobs/b/log'))
      return route.fulfill({contentType:'text/plain',body:''});
    if(path==='/api/v62/projects/p/training-tasks/a/recovery'){
      await new Promise(resolve => setTimeout(resolve, 1500));
      try {
        return await route.fulfill({json:{ok:true,recovery:{task_id:'a',project_id:'p',task_status:'FAILED',
          available:true,recoverable:true,checkpoint_available:true,
          recovery_action:'revalidate_checkpoint'}}});
      } catch { return; }
    }
    if(path==='/api/v62/projects/p/training-tasks/b/recovery')
      return route.fulfill({json:{ok:true,recovery:{task_id:'b',project_id:'p',task_status:'RUNNING',
        available:false,recoverable:false,checkpoint_available:false,recovery_action:null}}});
    if(path==='/api/v62/projects/p/tasks/a')return route.fulfill({json:{ok:true,project_id:'p',task:a}});
    if(path==='/api/v62/projects/p/tasks/b')return route.fulfill({json:{ok:true,project_id:'p',task:b}});
    return route.fulfill({status:404,json:{detail:'unhandled'}});
  });

  const slow = page.waitForRequest(request =>
    new URL(request.url()).pathname.endsWith('/training-tasks/a/recovery'));
  await page.goto('/app/#/projects/p/training/tasks?task=a');
  const drawer = page.getByRole('dialog',{name:'任务详情'});
  await slow;
  await page.goto('/app/#/projects/p/training/tasks?task=b');
  await expect(drawer).toContainText('RUNNING');
  await page.waitForTimeout(2500);
  await expect(drawer).toContainText('RUNNING');
  await expect(drawer).not.toContainText('服务端确认可恢复');
  await expect(drawer.getByRole('button',{name:'恢复结果校验',exact:true})).toHaveCount(0);
});

test('an unconfirmed stop keeps the same task identity and reconciles without a second POST', async ({page}) => {
  const task = {project_id:'p',task_id:'stop-lost',kind:'TRAINING',status:'RUNNING',phase:'training',progress_percent:30};
  let stops = 0, gets = 0, stopSent = false;
  await serveApp(page);
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    if(path==='/api/auth/session')return route.fulfill({json:{authenticated:true,user:{username:'测试'}}});
    if(path==='/api/projects')return route.fulfill({json:[{id:'p',name:'项目 P'}]});
    if(path==='/api/v62/projects/p/tasks')return route.fulfill({json:{ok:true,project_id:'p',items:[task],
      next_cursor:null,filter_options:{status:['RUNNING'],kind:['TRAINING']}}});
    if(path==='/api/v62/projects/p/tasks/stop-lost/cancel'){
      stops += 1; stopSent = true;
      return route.fulfill({status:503,json:{detail:'gateway lost the cancel receipt'}});
    }
    if(path==='/api/v62/projects/p/tasks/stop-lost'){
      gets += 1;
      const status = !stopSent ? 'RUNNING' : gets >= 3 ? 'CANCELLED' : 'CANCEL_REQUESTED';
      return route.fulfill({json:{ok:true,project_id:'p',task:{...task,status,
        phase:status==='CANCELLED'?'cancelled':status==='CANCEL_REQUESTED'?'cancelling':'training'}}});
    }
    if(path==='/api/v62/projects/p/training-tasks/stop-lost/recovery')
      return route.fulfill({json:{ok:true,recovery:{task_id:'stop-lost',project_id:'p',task_status:'RUNNING',
        available:false,recoverable:false,checkpoint_available:false,recovery_action:null}}});
    if(path.endsWith('/jobs/stop-lost/log'))return route.fulfill({contentType:'text/plain',body:''});
    return route.fulfill({status:404,json:{detail:'unhandled'}});
  });
  await page.goto('/app/#/projects/p/training/tasks?task=stop-lost');
  const drawer = page.getByRole('dialog',{name:'任务详情'});
  await expect(drawer.getByRole('button',{name:'停止任务',exact:true})).toBeVisible();
  page.on('dialog', dialog => dialog.accept());
  await drawer.getByRole('button',{name:'停止任务',exact:true}).click();
  await expect(drawer).toContainText('停止状态待核验', {timeout:10000});
  await expect(drawer).not.toContainText('已取消 (CANCELLED)');
  const pending = drawer.getByRole('button',{name:'停止待核验',exact:true});
  await expect(pending).toBeDisabled();
  await pending.click({force:true});
  expect(stops).toBe(1);
  await expect(drawer).toContainText('已取消 (CANCELLED)', {timeout:20000});
  expect(stops).toBe(1);
});

test('an unconfirmed recovery POST is not retried and is reconciled against the original task', async ({page}) => {
  const failed = {project_id:'p',task_id:'recover-lost',kind:'TRAINING',status:'FAILED',phase:'final_validation'};
  let posts = 0, allow = true, current = {...failed};
  await serveApp(page);
  await page.route('**/api/**', route => {
    const method = route.request().method(), path = new URL(route.request().url()).pathname;
    if(path==='/api/auth/session')return route.fulfill({json:{authenticated:true,user:{username:'测试'}}});
    if(path==='/api/projects')return route.fulfill({json:[{id:'p',name:'项目 P'}]});
    if(path==='/api/v62/projects/p/tasks')return route.fulfill({json:{ok:true,project_id:'p',items:[current],
      next_cursor:null,filter_options:{status:['FAILED','QUEUED'],kind:['TRAINING']}}});
    if(path==='/api/v62/projects/p/training-tasks/recover-lost/recovery'&&method==='POST'){
      posts += 1;
      return route.fulfill({status:503,json:{detail:'recovery receipt unavailable'}});
    }
    if(path==='/api/v62/projects/p/training-tasks/recover-lost/recovery')
      return route.fulfill({json:{ok:true,recovery:{task_id:'recover-lost',project_id:'p',
        task_status:current.status,available:allow,recoverable:allow,checkpoint_available:allow,
        recovery_action:allow?'revalidate_checkpoint':null}}});
    if(path==='/api/v62/projects/p/tasks/recover-lost')
      return route.fulfill({json:{ok:true,project_id:'p',task:current}});
    if(path.endsWith('/jobs/recover-lost/log'))return route.fulfill({contentType:'text/plain',body:''});
    return route.fulfill({status:404,json:{detail:'unhandled'}});
  });
  await page.goto('/app/#/projects/p/training/tasks?task=recover-lost');
  const drawer = page.getByRole('dialog',{name:'任务详情'});
  const recover = drawer.getByRole('button',{name:'恢复结果校验',exact:true});
  await expect(recover).toBeVisible();
  page.on('dialog', dialog => dialog.accept());
  await recover.click();
  await expect(drawer).toContainText('恢复请求结果待核验', {timeout:10000});
  expect(posts).toBe(1);
  await expect(recover).toHaveCount(0);
  await expect(drawer.getByRole('button',{name:'核验恢复状态',exact:true})).toBeVisible();

  allow = false;
  current = {...failed,status:'QUEUED',phase:'queued'};
  await drawer.getByRole('button',{name:'核验恢复状态',exact:true}).click();
  await expect(drawer).toContainText('QUEUED', {timeout:10000});
  await expect(drawer.getByRole('button',{name:'恢复结果校验',exact:true})).toHaveCount(0);
  expect(posts).toBe(1);
});

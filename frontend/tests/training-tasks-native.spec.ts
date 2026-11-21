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

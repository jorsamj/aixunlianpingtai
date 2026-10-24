import {test, expect} from '@playwright/test';

test('failed detail previews workspace blockers and releases only confirmed preview identity', async ({page}, testInfo)=>{
  const errors = [], posts = [];
  page.on('pageerror', error=>errors.push(error.message));
  page.on('dialog', dialog=>dialog.accept());
  await page.goto('/');
  await expect.poll(()=>page.evaluate(()=>Boolean(window.TrainingRecoveryRuntime?.openDetail && typeof state !== 'undefined' && state.uiReady))).toBe(true);
  const pid = await page.evaluate(()=>state.project.id);
  const job = {id:'workspace-smoke',task_id:'workspace-smoke',task_status:'FAILED',status:'failed',snapshot_id:'snapshot-workspace',framework:'ultralytics'};
  let mode = 'eligible', release;
  await page.route(`**/api/v62/projects/${encodeURIComponent(pid)}/training-tasks/workspace-smoke/**`, async route=>{
    const path = new URL(route.request().url()).pathname;
    let body = {};
    if (path.endsWith('/workspace/cleanup')) {
      posts.push(route.request().postDataJSON());
      await new Promise(resolve=>{release=resolve;});
      body = {workspace:{status:'deleted'}};
    } else if (path.endsWith('/workspace')) {
      if (mode === 'unknown') {await route.fulfill({status:503,json:{detail:'offline'}}); return;}
      body = {workspace:{project_id:pid,task_id:job.id,attempt:4,snapshot_id:job.snapshot_id,eligible:mode === 'eligible',blockers:mode === 'blocked' ? ['RECOVERY_DEPENDENCY'] : [],temporary_logical_bytes:2048}};
    } else if (path.endsWith('/recovery')) body = {recovery:{}};
    await route.fulfill({json:body});
  });
  await page.route(`**/api/projects/${encodeURIComponent(pid)}/jobs/workspace-smoke**`, route=>route.fulfill({json:job}));
  await page.evaluate(async value=>{state.jobs=[value]; await window.TrainingRecoveryRuntime.openDetail(value.id);},job);
  const panel = page.locator('[data-training-workspace]');
  await expect(panel).toContainText('可安全清理');
  mode = 'blocked';
  await panel.locator('[data-training-workspace-refresh]').click();
  await expect(panel).toContainText('恢复训练仍依赖');
  await expect(panel.locator('[data-training-workspace-cleanup]')).toBeDisabled();
  mode = 'unknown';
  await panel.locator('[data-training-workspace-refresh]').click();
  await expect(panel).toContainText('资格未知');
  mode = 'eligible';
  await panel.locator('[data-training-workspace-refresh]').click();
  await expect(panel.locator('[data-training-workspace-cleanup]')).toBeEnabled();
  await panel.locator('[data-training-workspace-cleanup]').click();
  await expect(panel).toContainText('正在释放');
  await expect(panel.locator('[data-training-workspace-cleanup]')).toBeDisabled();
  await expect.poll(()=>posts.length).toBe(1);
  expect(posts[0]).toEqual({confirm:'release_training_workspace',attempt:4,snapshot_id:'snapshot-workspace'});
  release();
  await expect(panel).toContainText('已释放');
  await panel.screenshot({path:testInfo.outputPath('workspace-released.png')});
  expect(errors).toEqual([]);
});

test('training page opens existing modal for read-only bounded history pages', async ({page}, testInfo)=>{
  const calls=[];
  await page.goto('/');
  await expect.poll(()=>page.evaluate(()=>Boolean(window.TrainingRecoveryRuntime && typeof state !== 'undefined' && state.uiReady))).toBe(true);
  const pid = await page.evaluate(()=>state.project.id);
  await page.route(`**/api/v62/projects/${encodeURIComponent(pid)}/training-tasks/workspace-history?**`,async route=>{
    calls.push([route.request().method(),route.request().url()]);
    const next = new URL(route.request().url()).searchParams.has('after');
    await route.fulfill({json:{ok:true,items:[{task_id:next ? 'historical-2' : 'historical-1',status:'FAILED',eligible:false,blockers:['OWNERSHIP_UNVERIFIED'],temporary_logical_bytes:1234}],next_cursor:next ? null : 'cursor-1'}});
  });
  await page.evaluate(()=>window.setPage('训练任务'));
  await page.locator('[data-training-workspace-history-open]').click();
  const history=page.locator('[data-training-workspace-history]');
  await expect(history).toContainText('historical-1');
  await expect(history).toContainText('归属尚未验证');
  await expect(history).toContainText('不会删除任何文件');
  await expect(history.locator('[data-training-workspace-cleanup]')).toHaveCount(0);
  await history.getByRole('button',{name:'下一页'}).click();
  await expect(history).toContainText('historical-2');
  expect(calls).toHaveLength(2);
  expect(calls.every(([method])=>method==='GET')).toBe(true);
  expect(calls[1][1]).toContain('limit=20&after=cursor-1');
  await history.screenshot({path:testInfo.outputPath('workspace-history-readonly.png')});
});

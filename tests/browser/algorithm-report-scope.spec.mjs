import {test, expect} from '@playwright/test';

test('algorithm report displays actual empty report scopes and an explicit mixed-history fixture', async ({page,request}) => {
  const created=await request.post('/api/projects',{data:{name:`report-scope-${Date.now()}`,labels:[]}});
  expect(created.ok()).toBeTruthy();
  const project=await created.json();
  const added=await request.post(`/api/v12/projects/${project.id}/algorithms`,{data:{name:'Report scope'}});
  expect(added.ok()).toBeTruthy();
  const {algorithm}=await added.json();
  const url=`/api/v49/projects/${project.id}/algorithms/${algorithm.id}/report`;
  const response=await request.get(url);
  expect(response.ok()).toBeTruthy();
  const actual=await response.json();
  expect(actual.summary.attempt_count).toBe(0);
  expect(actual.summary.duration_scope).toBe('all_training_attempts_including_failed');
  expect(actual.jobs_limit).toBe(20);
  await page.goto('/');
  await expect.poll(()=>page.evaluate(()=>state.uiReady)).toBe(true);
  await page.evaluate(project=>{state.project=project;},project);
  await page.evaluate(id=>window.algorithmReport429(id),algorithm.id);
  await expect(page.locator('#modalBody')).toContainText('成功训练次数');
  await expect(page.locator('#modalBody')).toContainText('完整记录 0 条');
  await page.evaluate(()=>closeModal());

  // Explicit response fixture exercises mixed results without creating GPU jobs.
  const fixture={...actual,summary:{...actual.summary,training_count:1,successful_count:1,attempt_count:23,total_duration_seconds:40,avg_duration_seconds:13,duration_record_count:3,duration_unknown_count:20},jobs_total:23,jobs_truncated:true,trend:[{job_id:'failed-fixture',status:'failed',map50:.2,images:3}]};
  await page.route(`**${url}`,route=>route.fulfill({json:fixture}));
  await page.evaluate(id=>window.algorithmReport429(id),algorithm.id);
  const body=page.locator('#modalBody');
  await expect(body).toContainText('训练任务数（含失败等状态，同任务重试不重复）');
  await expect(body).toContainText('23 次');
  await expect(body).toContainText('所有训练任务平均耗时（含失败）');
  await expect(body).toContainText('3 条有耗时记录计算，20 条耗时未知');
  await expect(body).toContainText('完整记录 23 条；任务明细返回最近 20 条（已截断）');
  await expect(body).not.toContainText('1 / 1 次');
  await expect(body.locator('tbody tr')).toHaveCount(1);
});

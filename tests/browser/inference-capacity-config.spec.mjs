import {test,expect} from '@playwright/test';

test('existing model modal checks saved capacity without another dialog',async({page,request})=>{
 const errors=[];page.on('pageerror',error=>errors.push(error.message));
 const projectResponse=await request.post('/api/projects',{data:{name:'容量隔离-'+Date.now(),labels:[]}});
 expect(projectResponse.ok()).toBeTruthy();const project=await projectResponse.json();
 await page.route('**/api/v53/bootstrap/snapshot**',route=>{const url=new URL(route.request().url());url.searchParams.set('preferred_project_id',project.id);return route.continue({url:url.toString()});});
 await page.goto('/');await expect.poll(()=>page.evaluate(()=>Boolean(state.uiReady))).toBe(true);
 await page.evaluate(()=>window.setPage('模型配置'));
 const panel=page.locator('[data-model-config-panel]');await expect(panel).toBeVisible();
 await panel.getByRole('button',{name:'新增视觉模型',exact:true}).click();
 const create=page.getByRole('dialog',{name:'新增视觉模型配置'});
 await expect(create.locator('#mcCapacityStatus')).toContainText('有效并发 1');
 await expect(create.getByRole('button',{name:'检查已保存容量证据'})).toHaveCount(0);
 await expect(create).toContainText('保存后可检查容量证据');
 const name='串行容量-'+Date.now();await create.locator('#mcName').fill(name);
 await create.locator('#mcModel').fill('capacity-test-model');await create.locator('#mcUrl').fill('http://capacity-test.invalid/v1');
 const [savedResponse]=await Promise.all([page.waitForResponse(r=>r.url().endsWith('/api/v35/model-configs')&&r.request().method()==='POST'),create.getByRole('button',{name:'保存配置'}).click()]);
 expect(savedResponse.ok()).toBeTruthy();const saved=await savedResponse.json();
 try{
  await panel.locator('tbody tr').filter({hasText:name}).getByRole('button',{name:'配置',exact:true}).click();
  const edit=page.getByRole('dialog',{name:'编辑视觉模型配置'});
  await expect(edit.locator('#mcCapacityStatus')).toContainText('容量未知时串行');
  const button=edit.getByRole('button',{name:'检查已保存容量证据'});await expect(button).toBeEnabled();
  const [checked]=await Promise.all([page.waitForResponse(r=>r.url().endsWith(`/api/v35/model-configs/${saved.id}/capacity-check`)),button.click()]);
  expect(checked.ok()).toBeTruthy();const body=await checked.json();expect(body.policy.concurrency).toBe(1);expect(body.policy.evidence_status).toBe('unknown');
  await expect(edit.locator('#mcCapacityStatus')).toContainText('有效并发 1 · 容量未知');
  await expect(edit.locator('#mcCapacityStatus')).toContainText('连接成功或图片解析通过不能证明双实例');
  await expect(page.getByRole('dialog')).toHaveCount(1);await expect(edit).toBeVisible();expect(errors).toEqual([]);
 }finally{expect((await request.delete('/api/v35/model-configs/'+saved.id)).ok()).toBeTruthy()}
});

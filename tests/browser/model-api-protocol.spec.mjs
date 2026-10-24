import {test,expect} from '@playwright/test';

test('vision API protocol and output capability persist across save refresh and re-edit',async({page,request})=>{
 const errors=[];page.on('pageerror',error=>errors.push(error.message));
 const r=await request.post('/api/projects',{data:{name:'协议隔离-'+Date.now(),labels:[]}});expect(r.ok()).toBeTruthy();const project=await r.json();
 await page.route('**/api/v53/bootstrap/snapshot**',route=>{const url=new URL(route.request().url());url.searchParams.set('preferred_project_id',project.id);return route.continue({url:url.toString()});});
 await page.route('https://ark.cn-beijing.volces.com/**',route=>route.abort());
 await page.goto('/');await expect.poll(()=>page.evaluate(()=>Boolean(state.uiReady))).toBe(true);
 await page.evaluate(()=>window.setPage('模型配置'));
 await page.getByRole('button',{name:/新增模型/}).click();
 const dialog=page.getByRole('dialog',{name:'新增视觉模型配置'});
 await dialog.locator('#mcName').fill('Responses隔离配置');await dialog.locator('#mcProviderAdapter').selectOption('volcengine_ark');
 await dialog.locator('#mcModel').fill('glm-5-3-flash-260828');
 const endpoint='https://ark.cn-beijing.volces.com/api/v3/responses';await dialog.locator('#mcUrl').fill(endpoint);
 await dialog.locator('summary').filter({hasText:'高级设置'}).click();
 await expect(dialog.locator('#mcApiProtocol')).toHaveValue('auto');
 await dialog.locator('#mcApiProtocol').selectOption('responses');await dialog.locator('#mcStructuredOutput').selectOption('prompt');
 const [savedResponse]=await Promise.all([page.waitForResponse(r=>r.url().endsWith('/api/v35/model-configs')&&r.request().method()==='POST'),dialog.getByRole('button',{name:'保存配置'}).click()]);
 expect(savedResponse.ok()).toBeTruthy();const saved=await savedResponse.json();
 expect(savedResponse.request().postDataJSON().api_protocol).toBe('responses');expect(saved.api_protocol).toBe('responses');expect(saved.base_url).toBe(endpoint);
 await page.reload();await expect.poll(()=>page.evaluate(()=>Boolean(state.uiReady))).toBe(true);
 await page.evaluate(id=>window.openModelConfigModalV35(id),saved.id);
 const edit=page.getByRole('dialog',{name:'编辑视觉模型配置'});await edit.locator('summary').filter({hasText:'高级设置'}).click();
 await expect(edit.locator('#mcUrl')).toHaveValue(endpoint);await expect(edit.locator('#mcApiProtocol')).toHaveValue('responses');await expect(edit.locator('#mcStructuredOutput')).toHaveValue('prompt');await expect(edit.locator('#mcApiKey')).toHaveValue('');
 await edit.locator('#mcApiProtocol').selectOption('auto');
 const [updatedResponse]=await Promise.all([page.waitForResponse(r=>r.url().endsWith('/api/v35/model-configs/'+saved.id)&&r.request().method()==='PUT'),edit.getByRole('button',{name:'保存配置'}).click()]);expect(updatedResponse.ok()).toBeTruthy();
 const listed=await(await request.get('/api/v35/model-configs')).json();const found=listed.items.find(x=>x.id===saved.id);expect(found.api_protocol).toBe('auto');expect(found.structured_output).toBe('prompt');expect(found.base_url).toBe(endpoint);
 expect(errors).toEqual([]);expect((await request.delete('/api/v35/model-configs/'+saved.id)).ok()).toBeTruthy();
});

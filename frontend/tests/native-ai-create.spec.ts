import {test,expect} from '@playwright/test';
import {resolve} from 'node:path';

test('AI create freezes a large selection, excludes one image and recovers the original request',async({page})=>{
  let creates=0,previews=0,reads=0,savedRequest='';
  const ids=['visible-a','visible-b'];
  const rows=ids.map(id=>({id,filename:id+'.jpg',width:32,height:32,annotation_state:'unannotated'}));
  await page.route('**/app/**',route=>{
    const name=new URL(route.request().url()).pathname.slice('/app/'.length)||'index.html';
    return route.fulfill({path:resolve('../static/vue-app',name),contentType:name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':'text/html'});
  });
  await page.route('**/api/**',async route=>{
    const url=new URL(route.request().url()),path=url.pathname,method=route.request().method();
    if(path==='/api/auth/session')return route.fulfill({json:{authenticated:true,provider:'local',user:{username:'operator'}}});
    if(path==='/api/projects')return route.fulfill({json:[{id:'p',name:'项目'}]});
    if(path.endsWith('/model-configs'))return route.fulfill({json:{items:[{id:'vision',default_for_annotation:true,name:'视觉模型'}]}});
    if(path.endsWith('/prompt-templates'))return route.fulfill({json:{items:[]}});
    if(path.endsWith('/labels'))return route.fulfill({json:{items:[{code:'smoke',class_id:0,display_name:'烟雾'}]}});
    if(path.endsWith('/materials'))return route.fulfill({json:{ok:true,project_id:'p',items:rows,page:1,page_size:48,total:20001,total_pages:417,has_next:true}});
    if(path.endsWith('/annotation-selections'))return route.fulfill({json:{selection_ref:'ref-large',count:20001}});
    if(path.endsWith('/annotation-selections/membership')){
      expect(route.request().postDataJSON()).toMatchObject({selection_ref:'ref-large',image_ids:ids});
      return route.fulfill({json:{items:ids}});
    }
    if(path.endsWith('/annotation-selections/summary')){
      expect(route.request().postDataJSON()).toEqual({image_ids:[],previous_ref:'ref-large',excluded_image_ids:['visible-a']});
      return route.fulfill({json:{count:20000,state_counts:{unannotated:20000},repository_revision:3}});
    }
    if(path.endsWith('/annotation-preview')){
      previews++;
      expect(route.request().postDataJSON()).toMatchObject({image_ids:['visible-b'],labels_text:'smoke',model_config_id:'vision'});
      return route.fulfill({json:{image:rows[1],preview_only:true,boxes:[],latency_ms:25}});
    }
    if(path.endsWith('/annotation-tasks')&&method==='POST'){
      creates++;
      const body=route.request().postDataJSON();
      expect(body).toMatchObject({selection_ref:'ref-large',image_ids:[],excluded_image_ids:['visible-a'],model_config_id:'vision',threshold:0.45,overwrite:false});
      savedRequest=body.request_id;
      expect(savedRequest).toMatch(/^ai-[a-f0-9]{32}$/);
      return route.abort('failed');
    }
    if(path.includes('/by-request/')){
      reads++;expect(path.split('/').at(-1)).toBe(savedRequest);
      return route.fulfill({json:{id:'task-created',project_id:'p'}});
    }
    if(path.endsWith('/annotation-tasks'))return route.fulfill({json:{ok:true,project_id:'p',items:[],next_cursor:null}});
    return route.fulfill({status:404,json:{detail:'unexpected route'}});
  });
  await page.goto('/app/#/projects/p/ai/create');
  await page.getByRole('button',{name:'冻结全部筛选结果'}).click();
  const first=page.locator('article').filter({hasText:'visible-a.jpg'});
  await expect(first.getByRole('checkbox')).toBeChecked();
  await first.locator('.el-checkbox').click();
  await expect(first.getByRole('checkbox')).not.toBeChecked();
  await page.locator('article').filter({hasText:'visible-b.jpg'}).getByRole('button',{name:'试跑此图'}).click();
  await page.getByRole('combobox',{name:'审核标签'}).click();
  await page.getByRole('option',{name:'烟雾 · smoke'}).click();
  await page.keyboard.press('Escape');
  expect(previews).toBe(0);
  await page.getByRole('button',{name:'运行单图试跑'}).click();
  await expect(page.getByText('0 个候选框 · 25 ms')).toBeVisible();
  expect(previews).toBe(1);
  await page.getByRole('button',{name:'核对配置和范围'}).click();
  await expect(page.getByText('未标注 20000 张',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'确认创建任务'}).click();
  await expect(page.getByRole('button',{name:'核对原请求'})).toBeVisible();
  expect(creates).toBe(1);
  await page.reload();
  await page.getByRole('button',{name:'核对原请求'}).click();
  await expect(page).toHaveURL(/\/ai\/tasks\?created=task-created/);
  expect(creates).toBe(1);
  expect(reads).toBe(1);
  expect(previews).toBe(1);
});

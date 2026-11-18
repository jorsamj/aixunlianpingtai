import {test,expect,type Page} from '@playwright/test';
import {resolve} from 'node:path';
async function assets(page:Page){
 await page.route('**/app/**',route=>{
  const name=new URL(route.request().url()).pathname.slice('/app/'.length)||'index.html';
  if(name.includes('..'))throw new Error('unsafe fixture asset');
  return route.fulfill({path:resolve('../static/vue-app',name),contentType:name.endsWith('.css')?'text/css':name.endsWith('.js')?'text/javascript':'text/html'});
 });
}
test('independent cards use canonical API for CRUD, versions and refresh without loading legacy code',async({page})=>{
 await assets(page);const calls:string[]=[],errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>calls.push(new URL(r.url()).pathname));
 const records=Array.from({length:21},(_,i)=>({id:`a${i}`,name:`算法 ${i}`,remark:'',industry:'工业',algorithm_type:'yolo_ultralytics',source_type:'local',editable:true,current_version_id:i===0?'v1':'',version_count:i===0?1:0}));
 let writes=0,holdBasic=false,basicHeld=false,releaseBasic=()=>{};
 await page.route('**/api/**',async route=>{
  const url=new URL(route.request().url()),method=route.request().method(),path=url.pathname;
  if(path==='/api/auth/session')return route.fulfill({json:{authenticated:true,user:{username:'原会话'}}});
  if(path==='/api/projects')return route.fulfill({json:[{id:'p',name:'原项目'}]});
  const root='/api/v12/projects/p/algorithms',id=decodeURIComponent(path.slice(root.length+1));
  if(method==='POST'){writes++;const row={...records[0],...route.request().postDataJSON(),id:'created',current_version_id:'',version_count:0};records.unshift(row);return route.fulfill({json:{ok:true,algorithm:{id:row.id}}})}
  if(method==='PUT'){writes++;Object.assign(records.find(row=>row.id===id)!,route.request().postDataJSON());return route.fulfill({json:{ok:true,algorithm:{id}}})}
  if(path===root){const rows=records.filter(row=>row.name.includes(url.searchParams.get('query')||'')),p=Number(url.searchParams.get('page')||1),size=Number(url.searchParams.get('page_size')||20);return route.fulfill({json:{ok:true,project_id:'p',items:rows.slice((p-1)*size,p*size),total:rows.length,page:p,page_size:size,filter_options:{industry:['工业'],algorithm_type:['yolo_ultralytics']}}})}
  const algorithm=records.find(row=>row.id===id),version={id:'v1',algorithm_id:id,version_name:'原版本 V1',training_status:'SUCCEEDED',framework:'ultralytics',metrics:{map50:0.75}};
  if(url.searchParams.has('basic_only')){if(holdBasic){basicHeld=true;await new Promise<void>(r=>{releaseBasic=r})}return route.fulfill({json:{ok:true,project_id:'p',algorithm}}).catch(()=>{})}
  if(url.searchParams.has('version_id'))return route.fulfill({json:{ok:true,project_id:'p',algorithm_id:id,version,artifacts:{items:[],total:0,truncated:false}}});
  return route.fulfill({json:{ok:true,project_id:'p',algorithm,items:id==='a0'?[version]:[],total:id==='a0'?1:0,page:1,page_size:20}});
 });
 await page.goto('/app/#/projects/p/algorithms');await expect(page.locator('.algorithm-card')).toHaveCount(10);await page.locator('.pagination .btn-next').click();await page.locator('.pagination .btn-next').click();await expect(page.locator('.algorithm-card')).toHaveCount(1);await page.locator('.pagination .btn-prev').click();await page.locator('.pagination .btn-prev').click();await expect(page.locator('.algorithm-card')).toHaveCount(10);
 await page.getByRole('button',{name:'算法 0',exact:true}).click();await expect(page.getByText('原版本 V1',{exact:true})).toBeVisible();await page.getByRole('button',{name:'版本详情',exact:true}).click();await expect(page.getByRole('heading',{name:'模型版本详情',exact:true})).toBeVisible();await expect(page.getByText('0.75',{exact:true})).toBeVisible();await page.getByRole('button',{name:'关闭此对话框',exact:true}).click();
 const conversion=page.getByRole('link',{name:'转换 · 原流程'});await expect(conversion).toHaveAttribute('href',/algorithm_id=a0&version_id=v1&action=conversion/);
 await page.reload();await expect(page.getByText('原版本 V1',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'新增本地算法',exact:true}).click();await page.getByRole('textbox',{name:'算法名称',exact:true}).fill('新本地算法');await page.getByRole('button',{name:'保存并核验',exact:true}).click();await expect(page.getByRole('button',{name:'新本地算法',exact:true})).toBeVisible();expect(writes).toBe(1);
 const card=page.locator('.algorithm-card').filter({has:page.getByRole('button',{name:'新本地算法',exact:true})});await card.getByRole('button',{name:'基本编辑',exact:true}).click();await expect(page.getByRole('textbox',{name:'算法名称',exact:true})).toHaveValue('新本地算法');await page.getByRole('textbox',{name:'算法名称',exact:true}).fill('修改后算法');await page.getByRole('button',{name:'保存并核验',exact:true}).click();await expect(page.getByRole('button',{name:'修改后算法',exact:true})).toBeVisible();await expect(page.locator('.version-panel h2')).toHaveText('修改后算法');expect(writes).toBe(2);
 await page.getByRole('textbox',{name:'搜索算法',exact:true}).fill('修改后');await page.getByRole('button',{name:'查询',exact:true}).click();await expect(page.locator('.algorithm-card')).toHaveCount(1);await page.reload();await expect(page.getByRole('textbox',{name:'搜索算法',exact:true})).toHaveValue('修改后');
 await page.goBack();await expect(page.locator('.algorithm-card')).toHaveCount(10);
 holdBasic=true;await page.locator('.algorithm-card').filter({has:page.getByRole('button',{name:'修改后算法',exact:true})}).getByRole('button',{name:'基本编辑',exact:true}).click();await expect.poll(()=>basicHeld).toBe(true);await page.getByRole('button',{name:'关闭此对话框',exact:true}).click();await page.getByRole('button',{name:'新增本地算法',exact:true}).click();releaseBasic();await expect(page.getByRole('textbox',{name:'算法名称',exact:true})).toHaveValue('');
 expect(calls.some(url=>url==='/static/app.js'||url==='/static/main.mjs')).toBe(false);expect(errors).toEqual([]);
});
test('project switch aborts old reads and rejects an unlisted project',async({page})=>{
 await assets(page);let held=false,aborted=false,releaseRead=()=>{};
 page.on('requestfailed',r=>{if(r.url().includes('/projects/p/algorithms'))aborted=true});
 await page.route('**/api/**',async route=>{
  const path=new URL(route.request().url()).pathname;
  if(path==='/api/auth/session')return route.fulfill({json:{authenticated:true,user:{username:'同源会话'}}});
  if(path==='/api/projects')return route.fulfill({json:[{id:'p',name:'项目 P'},{id:'q',name:'项目 Q'}]});
  const project=path.includes('/projects/p/')?'p':'q';if(project==='p'){held=true;await new Promise<void>(r=>{releaseRead=r})}
  await route.fulfill({json:{ok:true,project_id:project,items:[],total:0,page:1,page_size:20}}).catch(()=>{});
 });
 await page.goto('/app/#/projects/p/algorithms');await expect.poll(()=>held).toBe(true);await page.getByRole('combobox',{name:'当前项目'}).focus();await page.getByRole('combobox',{name:'当前项目'}).press('ArrowDown');await page.getByRole('option',{name:'项目 Q',exact:true}).click();await expect(page).toHaveURL(/projects\/q\/algorithms/);releaseRead();await expect.poll(()=>aborted).toBe(true);
 await page.goto('/app/#/projects/foreign/algorithms');await expect(page.getByText('页面不存在，请从侧栏选择业务入口。')).toBeVisible();
});
test('anonymous shell returns to the existing login with its route preserved',async({page})=>{
 await assets(page);await page.route('**/api/auth/session',route=>route.fulfill({json:{authenticated:false}}));await page.goto('/app/#/projects/p/algorithms');await expect(page).toHaveURL(/\/login\?next=.*app/);
});


test('unknown algorithm writes survive refresh, stay project scoped and clear only after authoritative verification',async({page})=>{
 await assets(page);let writes=0,failRead=true,rejectWrite=false;
 const record={id:'committed',name:'待核算法',remark:'',industry:'',algorithm_type:'',editable:true,source_type:'local'};
 await page.route('**/api/**',async route=>{
  const request=route.request(),url=new URL(request.url()),path=url.pathname;
  if(path==='/api/auth/session')return route.fulfill({json:{authenticated:true,user:{username:'同源会话'}}});
  if(path==='/api/projects')return route.fulfill({json:[{id:'p',name:'项目 P'},{id:'q',name:'项目 Q'}]});
  if(request.method()==='POST'){writes++;if(rejectWrite)return route.fulfill({status:400,json:{detail:'明确拒绝'}});Object.assign(record,request.postDataJSON());return route.abort('failed')}
  if(url.searchParams.has('basic_only'))return failRead?route.fulfill({status:503,json:{detail:'读取暂不可用'}}):route.fulfill({json:{ok:true,project_id:'p',algorithm:record}});
  return route.fulfill({json:{ok:true,project_id:path.includes('/projects/p/')?'p':'q',algorithm:record,items:[],total:0,page:1,page_size:10}});
 });
 await page.goto('/app/#/projects/p/algorithms');await page.getByRole('button',{name:'新增本地算法',exact:true}).click();await page.getByRole('textbox',{name:'算法名称',exact:true}).fill(record.name);await page.getByRole('button',{name:'保存并核验',exact:true}).click();
 await expect(page.getByRole('button',{name:'新增本地算法',exact:true})).toBeDisabled();expect(writes).toBe(1);
 await page.reload();await expect(page.getByText('保存结果尚未核验，请先核对，勿重复提交。',{exact:true})).toBeVisible();await expect(page.getByRole('button',{name:'新增本地算法',exact:true})).toBeDisabled();
 await page.goto('/app/#/projects/q/algorithms');await expect(page.getByRole('button',{name:'新增本地算法',exact:true})).toBeEnabled();
 await page.goto('/app/#/projects/p/algorithms');await expect(page.getByRole('button',{name:'新增本地算法',exact:true})).toBeDisabled();
 await page.getByRole('textbox',{name:'待核算法 ID',exact:true}).fill(record.id);await page.getByRole('button',{name:'核对保存结果',exact:true}).click();await expect(page.getByText('读取暂不可用',{exact:true})).toBeVisible();expect(writes).toBe(1);
 failRead=false;record.name='不匹配的记录';await page.getByRole('button',{name:'核对保存结果',exact:true}).click();await expect(page.getByText('权威记录与待核内容不同，请到原完整算法管理核对。',{exact:true})).toBeVisible();await expect(page.getByRole('button',{name:'新增本地算法',exact:true})).toBeDisabled();
 record.name='待核算法';await page.getByRole('button',{name:'核对保存结果',exact:true}).click();await expect(page.getByRole('button',{name:'新增本地算法',exact:true})).toBeEnabled();expect(writes).toBe(1);
 await page.reload();await expect(page.getByRole('button',{name:'新增本地算法',exact:true})).toBeEnabled();
 rejectWrite=true;await page.getByRole('button',{name:'新增本地算法',exact:true}).click();await page.getByRole('textbox',{name:'算法名称',exact:true}).fill('拒绝提交');await page.getByRole('button',{name:'保存并核验',exact:true}).click();await expect(page.getByText('明确拒绝',{exact:true})).toBeVisible();await page.reload();await expect(page.getByRole('button',{name:'新增本地算法',exact:true})).toBeEnabled();expect(writes).toBe(2);
});

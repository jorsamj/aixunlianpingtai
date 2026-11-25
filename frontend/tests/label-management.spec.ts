import {test,expect,type Page} from '@playwright/test';
import {resolve} from 'node:path';

async function assets(page:Page){
 await page.route('**/app/**',route=>{
  const name=new URL(route.request().url()).pathname.slice('/app/'.length)||'index.html';
  if(name.includes('..'))throw new Error('unsafe fixture asset');
  return route.fulfill({path:resolve('../static/vue-app',name),contentType:name.endsWith('.css')?'text/css':name.endsWith('.js')?'text/javascript':'text/html'});
 });
}
const initial=()=>[
 {class_id:0,code:'person',display_name:'人员',color:'#525252',hotkey:'1',aliases:[],affected_images:4,usage_boxes:6},
 {class_id:1,code:'worker',display_name:'作业人员',color:'#737373',hotkey:'2',aliases:[],affected_images:3,usage_boxes:3},
 {class_id:2,code:'human',display_name:'人员统一',color:'#404040',hotkey:'3',aliases:[],affected_images:0,usage_boxes:0},
];

test('label catalog preserves metadata, reference rejection and confirmed writes at desktop sizes',async({page},testInfo)=>{
 await assets(page);let rows=initial(),writes=0,usageReads=0;
 const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message));
 await page.route('**/api/**',async route=>{
  const url=new URL(route.request().url()),method=route.request().method(),path=url.pathname;
  if(path==='/api/auth/session')return route.fulfill({json:{authenticated:true,provider:'local',user:{username:'operator'}}});
  if(path==='/api/projects')return route.fulfill({json:[{id:'p',name:'工程项目'}]});
  if(path.endsWith('/label-schema')){usageReads++;return route.fulfill({json:{ok:true,items:rows,governance:rows}})}
  if(path.endsWith('/labels')&&method==='GET')return route.fulfill({json:{ok:true,items:rows.map(({affected_images,usage_boxes,...row})=>row),governance:rows}});
  if(path.endsWith('/labels')&&method==='POST'){
   writes++;const body=route.request().postDataJSON();rows.push({class_id:rows.length,code:body.label,display_name:body.display_name,color:body.color||'#111111',hotkey:'4',aliases:body.aliases,affected_images:0,usage_boxes:0});
   return route.fulfill({json:{ok:true}});
  }
  if(/\/labels\/\d+$/.test(path)){
   const id=Number(path.split('/').at(-1)),row=rows.find(row=>row.class_id===id)!;
   if(method==='PUT'){writes++;Object.assign(row,route.request().postDataJSON());return route.fulfill({json:{ok:true}})}
   if(method==='DELETE'){
    writes++;if(row.affected_images)return route.fulfill({status:400,json:{detail:'该标签仍被正式标注或 confirmed_empty 范围引用，请先统一标签后再删除'}});
    rows=rows.filter(row=>row!==row);return route.fulfill({json:{ok:true}});
   }
  }
  return route.fulfill({status:404,json:{detail:'unexpected fixture request: '+path}});
 });
 await page.goto('/app/#/projects/p/labels');
 await expect(page.getByText('人员',{exact:true})).toBeVisible();expect(usageReads).toBe(0);
 for(const [width,height] of [[1366,768],[1920,1080],[2560,1440]]){
  await page.setViewportSize({width,height});
  await expect(page.getByRole('button',{name:'新增标签',exact:true})).toBeInViewport();
  await page.screenshot({path:testInfo.outputPath(`labels-${width}.png`),fullPage:true});
 }
 await page.getByRole('button',{name:'新增标签',exact:true}).click();
 await page.getByRole('textbox',{name:'标签编码',exact:true}).fill('helmet');await page.getByRole('textbox',{name:'标签显示名称',exact:true}).fill('安全帽');
 await page.getByRole('textbox',{name:'标签别名',exact:true}).fill('头盔');await page.getByRole('button',{name:'保存',exact:true}).click();
 await expect(page.getByRole('dialog')).toHaveCount(0);await expect(page.getByText('安全帽',{exact:true})).toBeVisible();
 const row=page.getByRole('row').filter({hasText:'安全帽'});await row.getByRole('button',{name:'编辑',exact:true}).click();
 await page.getByRole('textbox',{name:'标签快捷键',exact:true}).fill('h');await page.getByRole('button',{name:'保存',exact:true}).click();await expect(page.getByRole('dialog')).toHaveCount(0);await expect(row).toContainText('h');
 await page.getByRole('row').filter({hasText:'作业人员'}).getByRole('button',{name:'删除',exact:true}).click();await page.getByRole('button',{name:'确认删除',exact:true}).click();
 await expect(page.getByRole('dialog')).toContainText('仍被正式标注');await page.getByRole('button',{name:'取消',exact:true}).click();
 await row.getByRole('button',{name:'删除',exact:true}).click();await page.getByRole('button',{name:'确认删除',exact:true}).click();await expect(page.getByRole('dialog')).toHaveCount(0);await expect(page.getByText('安全帽',{exact:true})).toHaveCount(0);
 expect(writes).toBe(4);expect(errors).toEqual([]);
});

test('label unification keeps exact sources, original task logs, task recovery and cancel truth',async({page},testInfo)=>{
 await assets(page);const rows=initial();let creates=0,cancels=0,previews:number[][]=[],resultReads=0;
 let task={task_id:'merge-1',id:'merge-1',project_id:'p',operation:'REMAP_ANNOTATION_LABELS',status:'RUNNING',total:7,processed:2,succeeded:2,failed:0,source_labels:['person','worker'],target_label:'human',retire_sources_on_success:true,log_available:true};
 await page.route('**/api/**',async route=>{
  const url=new URL(route.request().url()),method=route.request().method(),path=url.pathname;
  if(path==='/api/auth/session')return route.fulfill({json:{authenticated:true,provider:'local',user:{username:'operator'}}});
  if(path==='/api/projects')return route.fulfill({json:[{id:'p',name:'工程项目'}]});
  if(path.endsWith('/label-schema')||path.endsWith('/labels')&&method==='GET')return route.fulfill({json:{ok:true,items:rows,governance:rows}});
  if(path.endsWith('/unify/preview')){const ids=route.request().postDataJSON().source_class_ids;previews.push(ids);return route.fulfill({json:{ok:true,source_labels:ids.map((id:number)=>rows.find(row=>row.class_id===id)!.code),positive_images:4,scope_images:2,boxes:9,affected_images:7}})}
  if(path.endsWith('/labels/unify')){creates++;expect(route.request().postDataJSON()).toEqual({source_class_ids:[0,1],target_label:'human'});return route.fulfill({json:task})}
  if(path.endsWith('/merge-1/cancel')){cancels++;task={...task,status:'CANCEL_REQUESTED'};return route.fulfill({json:task})}
  if(path.endsWith('/merge-1/results')){resultReads++;return route.fulfill({status:409,json:{detail:'this task has no cleaning results'}})}
  if(path.endsWith('/merge-1'))return route.fulfill({json:task});
  return route.fulfill({status:404,json:{detail:path}});
 });
 await page.goto('/app/#/projects/p/labels?tab=unify');
 await page.getByRole('checkbox',{name:/人员 person/}).check();await page.getByRole('checkbox',{name:/作业人员 worker/}).check();
 await expect(page.locator('.impact')).toContainText('7');
 await page.getByRole('combobox',{name:'统一目标标签'}).click();await page.getByRole('option',{name:'人员统一 · human'}).click();
 await page.setViewportSize({width:1366,height:768});await page.screenshot({path:testInfo.outputPath('label-unify-1366.png'),fullPage:true});
 await page.getByRole('button',{name:'开始后台统一',exact:true}).click();await expect(page.locator('.unify-task')).toContainText('处理中');
 expect(previews.at(-1)).toEqual([0,1]);expect(creates).toBe(1);
 await page.reload();await expect(page.locator('.unify-task')).toContainText('merge-1');expect(creates).toBe(1);
 await expect(page.getByRole('link',{name:'完整任务日志'})).toHaveAttribute('href','/api/v62/projects/p/material-batches/merge-1/log');expect(resultReads).toBe(0);
 await page.getByRole('button',{name:'取消任务',exact:true}).click();await expect(page.locator('.unify-task')).toContainText('正在取消');expect(cancels).toBe(1);
 task={...task,status:'CANCELLED'};await page.getByRole('button',{name:'刷新状态'}).click();await expect(page.locator('.unify-task')).toContainText('已取消');expect(creates).toBe(1);
});

test('unresolved label unify refresh only reads and refuses another task identity',async({page})=>{
 await assets(page);let posts=0;
 await page.route('**/api/**',async route=>{
  const path=new URL(route.request().url()).pathname;
  if(route.request().method()==='POST')posts++;
  if(path==='/api/auth/session')return route.fulfill({json:{authenticated:true,provider:'local',user:{username:'operator'}}});
  if(path==='/api/projects')return route.fulfill({json:[{id:'p',name:'工程项目'}]});
  if(path.endsWith('/label-schema'))return route.fulfill({json:{ok:true,items:initial()}});
  if(path.endsWith('/other'))return route.fulfill({json:{task_id:'other',id:'other',project_id:'p',operation:'REMAP_ANNOTATION_LABELS',retire_sources_on_success:true,source_labels:['worker'],target_label:'person',status:'SUCCEEDED'}});
  if(path.endsWith('/original'))return route.fulfill({json:{task_id:'original',id:'original',project_id:'p',operation:'REMAP_ANNOTATION_LABELS',retire_sources_on_success:true,source_labels:['person','worker'],target_label:'human',status:'RUNNING'}});
  return route.fulfill({status:404,json:{detail:path}});
 });
 const query=new URLSearchParams({tab:'unify',unify_pending:'1',unify_sources:JSON.stringify(['person','worker']),unify_target:'human'});
 await page.goto('/app/#/projects/p/labels?'+query);
 await expect(page.getByText('创建结果待核对，请勿重复提交。请在原任务记录核对任务 ID 后读取。',{exact:true})).toBeVisible();
 await page.reload();await page.getByRole('textbox',{name:'标签统一任务 ID'}).fill('other');await page.getByRole('button',{name:'读取已有任务'}).click();
 await expect(page.getByText('任务来源及目标标签与原请求不一致',{exact:true})).toBeVisible();await expect(page.getByRole('button',{name:'开始后台统一'})).toBeDisabled();
 await page.getByRole('textbox',{name:'标签统一任务 ID'}).fill('original');await page.getByRole('button',{name:'读取已有任务'}).click();await expect(page.locator('.unify-task')).toContainText('original');expect(posts).toBe(0);
});

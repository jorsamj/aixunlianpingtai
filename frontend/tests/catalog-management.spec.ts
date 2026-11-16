import {test,expect,type Page} from '@playwright/test';
import {fixture} from './fixture';

async function harness(page:Page){
 const vendors=Array.from({length:12},(_,i)=>({id:`v${i}`,name:`原厂商${String(i).padStart(2,'0')}`,template_id:'rknn',enabled:true}));
 const chips:any[]=[];let revision=7,mode='',protectedId='',deleteRace=false;
 const packets:any[]=[],reads:string[]=[],detections:string[]=[];const receipts=new Map<string,any>();
 const refs=(id:string)=>id===protectedId?{check_status:'UNVERIFIED',can_delete:false,reference_count:null,diagnostic:{code:'CATALOG_REFERENCE_CHECK_FAILED',detail:'历史任务证据缺失',solution:'保留身份，可编辑名称或停用'}}:{check_status:'VERIFIED',can_delete:true,reference_count:0,references:[]};
 const enrich=(row:any,entity:string)=>entity==='vendors'?{...row,template_name:'RKNN Toolkit2',chip_count:chips.filter(c=>c.vendor_id===row.id).length}: {...row,capability:{status:'pending_configuration',status_label:'待配置',sdk_ready:false,resources:[]}};
 await page.route('**/preview-fixture*',route=>route.fulfill({contentType:'text/html',body:fixture}));
 await page.route('**/api/**',async route=>{
  const req=route.request(),url=new URL(req.url()),path=url.pathname;reads.push(req.method()+' '+url.pathname+url.search);
  const error=(code:string,message:string,status=409)=>route.fulfill({status,json:{code,message}});
  if(path==='/api/auth/session')return route.fulfill({json:{authenticated:true,user:{username:'隔离用户'}}});
  const match=path.match(/\/records\/(vendors|chips)\/([^/]+)$/);
  if(match){const entity=match[1],row=(entity==='vendors'?vendors:chips).find(x=>x.id===match[2]);return row?route.fulfill({json:{ok:true,item:enrich(row,entity),revision,references:refs(row.id)}}):error('CATALOG_NOT_FOUND','记录已不存在',404)}
  if(path.endsWith('/records')){
   const entity=url.searchParams.get('entity')||'vendors';let items:any[]=[...(entity==='vendors'?vendors:chips)].map(row=>enrich(row,entity));
   if(entity==='chips')items=items.filter(row=>row.vendor_id===url.searchParams.get('vendor_id'));
   if(url.searchParams.get('query'))items=items.filter(row=>row.name.includes(url.searchParams.get('query')));
   if(url.searchParams.get('enabled'))items=items.filter(row=>String(row.enabled)===url.searchParams.get('enabled'));
   if(url.searchParams.get('template_id'))items=items.filter(row=>row.template_id===url.searchParams.get('template_id'));
   items.sort((a,b)=>a.name.localeCompare(b.name,'zh-CN'));if(url.searchParams.get('sort')==='name_desc')items.reverse();
   const index=Number(url.searchParams.get('page')||1),total=items.length;
   return route.fulfill({json:{ok:true,items:items.slice((index-1)*10,index*10),total,page:index,page_size:10,revision,templates:[{id:'rknn',name:'RKNN Toolkit2'},{id:'atlas-atc',name:'华为 Atlas ATC'}]}});
  }
  if(path.includes('/operations/')){const value=receipts.get(path.split('/').pop()!);return value?route.fulfill({json:value}):error('CATALOG_OPERATION_NOT_FOUND','未找到已确认的操作回执',404)}
  if(path.endsWith('/operations')){
   const op=req.postDataJSON();packets.push(op);
   if(mode==='not-received'){mode='';return route.fulfill({contentType:'application/json',body:'{broken'})}
   if(mode==='conflict'){revision++;mode='';return error('CATALOG_REVISION_CONFLICT','revision 已变化，请重新读取')}
   if(receipts.has(op.operation_id))return route.fulfill({json:{...receipts.get(op.operation_id),replayed:true}});
   if(op.expected_revision!==revision)return error('CATALOG_REVISION_CONFLICT','revision 已变化，请重新读取');
   const rows:any[]=op.entity==='vendors'?vendors:chips;let row=rows.find(x=>x.id===op.id);
   if(op.action==='delete'&&(deleteRace||refs(op.id).can_delete!==true))return error('CATALOG_REFERENCED','存在业务引用，不能物理删除或改挂');
   if(op.action==='create'){row={...op.record,id:`server-${packets.length}`,...(op.entity==='chips'?{code:'server-local-code',sdk_code:op.record.sdk_code||''}:{})};rows.push(row)}
   else if(op.action==='update')Object.assign(row,op.record);
   else if(op.action==='delete')rows.splice(rows.indexOf(row),1);
   else row.enabled=op.action==='enable';
   const result={ok:true,operation_id:op.operation_id,entity:op.entity,action:op.action,id:row.id,item:op.action==='delete'?null:row,revision:++revision};receipts.set(op.operation_id,result);
   if(mode==='lost-reply'){mode='';return route.fulfill({contentType:'application/json',body:'{broken'})}
   return route.fulfill({json:result});
  }
  if(path.endsWith('/detect')){detections.push(path);return route.fulfill({json:{ok:true,id:path.split('/').at(-2),capability:{status:'pending_detection',status_label:'待检测'}}})}
  return error('UNEXPECTED_API','未允许的API',400);
 });
 await page.goto('/preview-fixture?vue_catalog_manage=1');await page.getByRole('button',{name:'Vue 正式管理',exact:true}).click();await expect(page.getByRole('heading',{name:'厂商与芯片',exact:true})).toBeVisible();
 return {vendors,chips,packets,reads,detections,setMode:(value:string)=>mode=value,protect:(id:string)=>protectedId=id,race:()=>deleteRace=true};
}
async function createVendor(page:Page,name='000正式厂商'){
 await page.getByRole('button',{name:'新增厂商',exact:true}).click();await page.getByRole('textbox',{name:'厂商名称',exact:true}).fill(name);await page.getByRole('button',{name:'保存厂商',exact:true}).click();await expect(page.locator('.preview-editor')).toHaveCount(0);
}
async function menu(page:Page,name:string,action:string){await page.getByRole('button',{name:`${name}更多操作`,exact:true}).click();await page.getByRole('menuitem',{name:action,exact:true}).click()}

test('formal catalog CRUD uses original operations, filtering and explicit detection without replacing legacy management',async({page})=>{
 const h=await harness(page);await createVendor(page);expect(h.packets[0].record.id).toBeUndefined();
 await page.getByRole('button',{name:'新增芯片',exact:true}).click();await page.getByRole('textbox',{name:'芯片名称',exact:true}).fill('未知芯片');await page.getByRole('button',{name:'保存芯片',exact:true}).click();await expect(page.getByText('待配置',{exact:true})).toBeVisible();expect(h.detections).toHaveLength(0);
 await page.getByRole('button',{name:'编辑未知芯片',exact:true}).click();await page.getByRole('textbox',{name:'芯片名称',exact:true}).fill('未知芯片改名');await page.getByRole('button',{name:'保存芯片',exact:true}).click();await expect(page.getByText('未知芯片改名',{exact:true})).toBeVisible();
 await menu(page,'未知芯片改名','停用');await page.getByRole('button',{name:'确认停用芯片',exact:true}).click();await expect(page.getByRole('region',{name:'芯片列表',exact:true}).getByText('已停用',{exact:true})).toBeVisible();
 await menu(page,'未知芯片改名','启用');await page.getByRole('button',{name:'确认启用芯片',exact:true}).click();
 await menu(page,'未知芯片改名','检测 SDK 能力');await expect.poll(()=>h.detections.length).toBe(1);await expect(page.getByText('检测请求已完成，状态以最新资源证据为准')).toBeVisible();
 for(const width of [1366,768]){await page.setViewportSize({width,height:1000});await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:`../test-results/vue-catalog/catalog-management-${width}.png`,fullPage:true,animations:'disabled'})}
 const before=h.packets.length;await menu(page,'未知芯片改名','删除');expect(h.packets.length).toBe(before);await page.getByRole('button',{name:'确认删除',exact:true}).click();await expect.poll(()=>h.chips.length).toBe(0);
 await menu(page,'000正式厂商','删除');await page.getByRole('button',{name:'确认删除',exact:true}).click();await expect.poll(()=>h.vendors.length).toBe(12);
 const list=page.getByRole('region',{name:'厂商列表',exact:true});await list.locator('.btn-next').click();await expect.poll(()=>h.reads.some(x=>x.includes('page=2'))).toBe(true);
 await page.getByRole('textbox',{name:'搜索厂商',exact:true}).fill('原厂商');await list.getByRole('button',{name:'查询',exact:true}).click();expect(h.vendors.length).toBe(12);
 expect(h.reads.some(x=>x.startsWith('PUT'))).toBe(false);await page.getByRole('button',{name:'返回完整管理',exact:true}).click();await expect(page.getByRole('button',{name:'+ 新增厂商',exact:true})).toBeVisible();
});

test('unknown mutation results recover exact original operation across exit; revision conflicts require reread',async({page})=>{
 const h=await harness(page);h.setMode('lost-reply');await createVendor(page);expect(h.packets.length).toBe(1);expect(h.reads.some(x=>x.includes('/operations/'+h.packets[0].operation_id))).toBe(true);
 h.setMode('not-received');await page.getByRole('button',{name:'新增厂商',exact:true}).click();await page.getByRole('textbox',{name:'厂商名称',exact:true}).fill('001恢复厂商');await page.getByRole('button',{name:'保存厂商',exact:true}).click();await expect(page.getByRole('region',{name:'待确认的字典操作'})).toBeVisible();await expect(page.getByRole('textbox',{name:'厂商名称',exact:true})).toBeDisabled();
 const original=structuredClone(h.packets.at(-1));await page.getByRole('button',{name:'返回列表',exact:true}).click();await page.getByRole('button',{name:'返回完整管理',exact:true}).click();await page.evaluate(()=>{window.state.project={id:'another-project'};window.setPage('厂商芯片正式管理')});await expect(page.getByRole('button',{name:'新增厂商',exact:true})).toBeDisabled();await page.reload();await page.getByRole('button',{name:'Vue 正式管理',exact:true}).click();await expect(page.getByRole('button',{name:'新增厂商',exact:true})).toBeDisabled();expect(h.packets.length).toBe(2);
 await page.getByRole('button',{name:'使用原请求恢复',exact:true}).click();await expect(page.getByRole('region',{name:'待确认的字典操作'})).toHaveCount(0);expect(h.packets.at(-1)).toEqual(original);
 h.setMode('conflict');await page.getByRole('button',{name:'编辑001恢复厂商',exact:true}).click();await page.getByRole('textbox',{name:'厂商名称',exact:true}).fill('未保存名称');await page.getByRole('button',{name:'保存厂商',exact:true}).click();await expect(page.getByRole('button',{name:'保存厂商',exact:true})).toBeDisabled();await page.getByRole('button',{name:'重新读取当前记录',exact:true}).click();await expect(page.getByRole('textbox',{name:'厂商名称',exact:true})).toHaveValue('001恢复厂商');
});

test('unverified history permits ordinary editing but locks identity and deletion; backend rechecks late references',async({page})=>{
 const h=await harness(page);await createVendor(page);const id=h.packets[0].record.id||h.vendors.find(x=>x.name==='000正式厂商')!.id;h.protect(id);
 await page.getByRole('button',{name:'编辑000正式厂商',exact:true}).click();await expect(page.getByRole('combobox',{name:'SDK 模板',exact:true})).toBeDisabled();await page.getByText('引用诊断详情',{exact:true}).click();await expect(page.getByText('CATALOG_REFERENCE_CHECK_FAILED',{exact:false})).toBeVisible();await page.getByRole('textbox',{name:'厂商名称',exact:true}).fill('000保留身份');await page.getByRole('button',{name:'保存厂商',exact:true}).click();
 await menu(page,'000保留身份','删除');await expect(page.getByRole('button',{name:'确认删除',exact:true})).toBeDisabled();await page.getByRole('button',{name:'取消',exact:true}).click();h.protect('');
 await menu(page,'000保留身份','删除');h.race();await page.getByRole('button',{name:'确认删除',exact:true}).click();await expect(page.getByText('存在业务引用，不能物理删除或改挂',{exact:true})).toBeVisible();expect(h.vendors.some(x=>x.id===id)).toBe(true);
});

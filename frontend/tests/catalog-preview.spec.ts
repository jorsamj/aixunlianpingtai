import {test,expect} from '@playwright/test';
import {fixture} from './fixture';
const vendors=Array.from({length:12},(_,i)=>({id:`vendor-${i}`,name:i===0?'瑞芯微视觉计算':`计算厂商 ${String(i).padStart(2,'0')}`,template_id:'rknn',template_name:'RKNN Toolkit2',enabled:true,implemented:true,chip_count:2,enabled_chip_count:1}));
async function setup(page:any){
  const requests:{method:string;url:string}[]=[];let fail=false,hold=false;
  await page.route('**/preview-fixture*',route=>route.fulfill({contentType:'text/html',body:fixture}));
  await page.route('**/api/**',async route=>{
    const request=route.request(),url=new URL(request.url());requests.push({method:request.method(),url:request.url()});
    if(url.pathname==='/api/auth/session')return route.fulfill({json:{authenticated:true,provider:'local',user:{username:'原有登录用户'},remaining_seconds:7200}});
    const readonly=url.searchParams.get('observe_only')==='true';
    if(readonly&&hold)await new Promise(resolve=>setTimeout(resolve,700));
    if(readonly&&fail)return route.fulfill({status:503,json:{message:'字典服务暂不可用'}});
    const entity=url.searchParams.get('entity')||'vendors';
    if(url.pathname.endsWith('/records')){
      let items=entity==='vendors'?vendors:[{id:'rk3588',name:'RK3588',sdk_code:'rk3588',enabled:true,capability:{allowed_precisions:[],resources:[]}}];
      const query=url.searchParams.get('query')||'';items=items.filter(row=>row.name.includes(query));
      if(url.searchParams.get('enabled')==='false')items=[];
      if(url.searchParams.get('sort')==='name_desc')items=[...items].reverse();
      const index=Number(url.searchParams.get('page')||1);return route.fulfill({json:{ok:true,items:items.slice((index-1)*10,index*10),page:index,page_size:10,total:items.length,revision:7,templates:[{id:'rknn',name:'RKNN Toolkit2'}]}});
    }
    return route.fulfill({json:{ok:true,item:{id:'rk3588',name:'RK3588',enabled:true,sdk_code:'rk3588',capability:{resources:[]}},revision:7,references:{check_status:'UNVERIFIED'}}});
  });
  await page.goto('/preview-fixture?vue_catalog_preview=1');
  await expect(page.getByText('原有登录用户')).toBeVisible();
  return {requests,setFail:(v:boolean)=>fail=v,setHold:(v:boolean)=>hold=v};
}

test('original session and management coexist with paged read-only Vue preview',async({page})=>{
  const jsErrors:string[]=[];page.on('pageerror',e=>jsErrors.push(e.message));
  const h=await setup(page);
  await page.getByRole('button',{name:'只读预览',exact:true}).click();
  await expect(page.getByRole('heading',{name:'厂商与芯片',exact:true})).toBeVisible();
  await expect(page.getByText('未核验',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'查看RK3588详情'}).click();
  await expect(page.getByText('历史引用未核验，不能据此判断可删除或改挂。')).toBeVisible();
  await page.getByRole('button',{name:'关闭详情'}).click();
  const vendorList=page.getByRole('region',{name:'厂商列表',exact:true});
  await vendorList.locator('.el-pagination .btn-next').click();
  await expect.poll(()=>h.requests.some(r=>r.url.includes('entity=vendors')&&r.url.includes('page=2'))).toBe(true);
  await page.getByRole('textbox',{name:'搜索厂商',exact:true}).fill('不存在');
  await vendorList.getByRole('button',{name:'查询',exact:true}).click();
  await expect(page.getByText('暂无匹配记录')).toBeVisible();
  await page.getByRole('textbox',{name:'搜索厂商',exact:true}).fill('');await vendorList.getByRole('button',{name:'查询',exact:true}).click();
  for(const width of [1366,768]){
    await page.setViewportSize({width,height:900});await expect(page.getByText('RK3588',{exact:true})).toBeVisible();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await page.screenshot({path:`../test-results/vue-catalog/catalog-${width}.png`,fullPage:true});
  }
  await page.getByRole('button',{name:'返回完整管理'}).click();
  await expect(page.getByRole('button',{name:'+ 新增厂商'})).toBeVisible();
  await expect(page.locator('.catalog-preview')).toHaveCount(0);
  const before=h.requests.filter(r=>r.url.includes('observe_only=true')&&r.url.includes('entity=vendors')).length;
  await page.getByRole('button',{name:'只读预览',exact:true}).click();await expect(page.getByText('RK3588',{exact:true})).toBeVisible();
  expect(h.requests.filter(r=>r.url.includes('observe_only=true')&&r.url.includes('entity=vendors')).length).toBe(before+1);
  expect(h.requests.every(r=>r.method==='GET')).toBe(true);expect(jsErrors).toEqual([]);
});

test('failed reads can retry and navigation aborts pending preview reads',async({page})=>{
  const h=await setup(page);h.setFail(true);
  await page.getByRole('button',{name:'只读预览',exact:true}).click();
  await expect(page.getByText('字典服务暂不可用',{exact:true})).toBeVisible();
  h.setFail(false);await page.getByRole('button',{name:'重新读取'}).click();await expect(page.getByText('RK3588',{exact:true})).toBeVisible();
  h.setHold(true);let aborted=false;page.on('requestfailed',r=>{if(r.url().includes('observe_only=true'))aborted=true});
  await page.getByRole('region',{name:'厂商列表',exact:true}).getByRole('button',{name:'刷新',exact:true}).click();
  await page.getByRole('button',{name:'返回完整管理'}).click();
  await expect(page.getByRole('button',{name:'+ 新增厂商'})).toBeVisible();await expect.poll(()=>aborted).toBe(true);
  await expect(page.locator('.catalog-preview')).toHaveCount(0);expect(h.requests.every(r=>r.method==='GET')).toBe(true);
});


test('backend status labels survive false SDK readiness in list and resource details',async({page})=>{
  await setup(page);
  const statuses=[['pending_configuration','待配置'],['pending_detection','待检测'],['detection_in_progress','检测中'],['detection_expired','检测已过期'],['detection_failed','检测失败'],['not_convertible','不兼容'],['not_adapted','暂未适配'],['service_unavailable','转换资源不可用'],['convertible','可转换']];
  const chips=statuses.map(([status,status_label],i)=>({id:`chip-${i}`,name:`证据芯片 ${i}`,enabled:true,capability:{sdk_ready:false,status,status_label,resources:[{resource_id:`resource-${i}`,resource_name:'原资源证据',ready:false,status,status_label}]}}));
  const raw={id:'chip-raw',name:'原始状态芯片',enabled:true,capability:{sdk_ready:false,status:'future_backend_status',status_label:'',resources:[]}};
  await page.route('**/api/v39/deploy/catalog/records**',route=>{
    const url=new URL(route.request().url());
    if(url.pathname.endsWith('/records')&&url.searchParams.get('entity')==='chips')return route.fulfill({json:{ok:true,items:[...chips,raw],page:1,page_size:10,total:10,revision:7,templates:[]}});
    const chip=chips.find(item=>url.pathname.endsWith('/'+item.id));
    if(chip)return route.fulfill({json:{ok:true,item:chip,revision:7,references:{check_status:'UNVERIFIED'}}});
    return route.fallback();
  });
  await page.getByRole('button',{name:'只读预览',exact:true}).click();
  const list=page.getByRole('region',{name:'芯片列表',exact:true});
  for(const [i,[,label]] of statuses.entries()){
    await expect(list.getByText(label,{exact:true})).toBeVisible();
    await page.getByRole('button',{name:`查看证据芯片 ${i}详情`,exact:true}).click();
    await expect(page.locator('.preview-resource').getByText(label,{exact:true})).toBeVisible();
    await page.getByRole('button',{name:'关闭详情'}).click();
  }
  await expect(list.getByText('future_backend_status',{exact:true})).toBeVisible();
});

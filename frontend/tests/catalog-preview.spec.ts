import {test,expect} from '@playwright/test';
import {readFileSync} from 'node:fs';
// Existing API owner, session, navigation and complete legacy dictionary runtime.
// Only HTTP data is synthetic; no FastAPI startup, SDK scan or business database.
const originalApi=readFileSync('../static/app.js','utf8').split('// Shared request identity')[0];
const fixture=`<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><link rel="stylesheet" href="/static/styles.css"><style>body{background:#f5f7fb;margin:0}#view{padding:24px;max-width:1640px;margin:auto}</style></head><body><span id="authUsername"></span><main id="view"></main><script src="/static/auth-session.js"></script><script type="module">
import {installNavigationStability} from '/static/modules/navigation-stability.js';
import {installPageRequestScope} from '/static/modules/page-request-scope.js';
import {installPollRegistry} from '/static/modules/poll-registry.js';
import {installConversionCatalogRuntime} from '/static/modules/conversion-catalog-runtime.js';
import {installCatalogPreview,PREVIEW_PAGE} from '/static/modules/catalog-preview-runtime.js';
${originalApi}
const state={page:'部署资源',project:{id:'p'}};window.state=state;
const scope=installPageRequestScope({getPage:()=>state.page});
const polls=installPollRegistry({getState:()=>state});
const old=installConversionCatalogRuntime({api,getState:()=>state,modal(){},closeModal(){}});
let preview;
function legacy(){document.querySelector('#view').innerHTML='<div id="conversion-catalog-host"></div>';return old.mount(document.querySelector('#conversion-catalog-host'))}
const nav=installNavigationStability({getState:()=>state,requestScope:scope,pollRegistry:polls,knownPages:['部署资源',PREVIEW_PAGE],performNavigation:page=>{preview?.leave();old.leave();state.page=page;return page===PREVIEW_PAGE?nav.renderPage(page):legacy()}});
preview=installCatalogPreview({enabled:new URLSearchParams(location.search).get('vue_catalog_preview')==='1',navigation:nav,getState:()=>state,request:api,deadline:(await import('/static/modules/api.js')).withRequestDeadline});
window.preview=preview;await legacy();
</script></body></html>`;
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

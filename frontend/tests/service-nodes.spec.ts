import {test,expect} from '@playwright/test';
import {fixture} from './fixture';

test('node overview displays server facts, refreshes manually, filters locally and cancels on return',async({page})=>{
 const requests:{method:string;path:string}[]=[],errors:string[]=[];let count=0,hold=false;
 page.on('pageerror',e=>errors.push(e.message));
 const node={node_id:'node-arm',display_name:'边缘计算节点',connection_mode:'agent',status:'ONLINE',os_name:'Linux',architecture:'aarch64',last_heartbeat_at:'2026-11-16T15:00:00Z',agent_version:'agent-test-1',allowed_capabilities:['training','conversion'],reported_capabilities:['conversion'],effective_capabilities:['conversion'],resources:{cpu:{usage_percent:17},memory:{total_bytes:8589934592,available_bytes:4294967296,usage_percent:50},gpu:{gpus:[{id:'gpu-fixture',name:'已上报测试GPU',memory_total_bytes:8589934592,memory_free_bytes:2147483648,utilization_percent:23}]}},durable_tasks:[{task_id:'isolated-task',kind:'MODEL_CONVERSION',stage:'等待证据',progress:12}],workers:[],last_error:'仅展示已有资源证据',agent_token:'MUST-NOT-RENDER'};
 await page.route('**/preview-fixture*',r=>r.fulfill({contentType:'text/html',body:fixture}));
 await page.route('**/api/**',async route=>{
  const path=new URL(route.request().url()).pathname;requests.push({method:route.request().method(),path});
  if(path==='/api/auth/session')return route.fulfill({json:{authenticated:true,user:{username:'原用户'}}});
  if(path==='/api/v63/service-nodes'){count++;if(hold)await new Promise(r=>setTimeout(r,800));return route.fulfill({json:{items:[node,{node_id:'node-off',display_name:'离线节点',connection_mode:'local',status:'OFFLINE',resources:{},allowed_capabilities:[],reported_capabilities:[],effective_capabilities:[]}],supported_capabilities:['training','conversion']}})}
  return route.fulfill({json:{ok:true,items:[],total:0,page:1,page_size:10,revision:1,templates:[]}});
 });
 await page.goto('/preview-fixture?vue_service_nodes=1');await page.evaluate(()=>window.setPage('服务节点只读总览'));
 await expect(page.getByRole('heading',{name:'服务节点与算力',exact:true})).toBeVisible();await expect(page.getByText('aarch64',{exact:false})).toBeVisible();await expect(page.getByText('已上报测试GPU',{exact:true})).toBeVisible();await page.getByText('任务占用与 Worker · 1 项持久任务',{exact:true}).click();await expect(page.getByText('isolated-task',{exact:false})).toBeVisible();await expect(page.getByText('MUST-NOT-RENDER',{exact:false})).toHaveCount(0);
 const card=page.getByRole('article',{name:'边缘计算节点',exact:true});await expect(card.getByLabel('管理员允许的能力')).toContainText('training');await expect(card.getByLabel('当前可调度能力')).not.toContainText('training');
 await page.getByRole('textbox',{name:'搜索节点',exact:true}).fill('不存在');await expect(page.getByText('没有匹配的服务节点')).toBeVisible();expect(count).toBe(1);await page.getByRole('textbox',{name:'搜索节点',exact:true}).fill('');
 for(const width of [1366,768]){await page.setViewportSize({width,height:1000});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:`../test-results/vue-catalog/service-nodes-${width}.png`,fullPage:true})}
 await page.getByRole('button',{name:'刷新节点',exact:true}).click();await expect.poll(()=>count).toBe(2);await expect(page.getByRole('button',{name:'刷新节点',exact:true})).toBeEnabled();
 hold=true;let aborted=false;page.on('requestfailed',r=>{if(r.url().includes('/service-nodes'))aborted=true});await page.getByRole('button',{name:'刷新节点',exact:true}).click();await page.getByRole('button',{name:'返回完整管理',exact:true}).click();await expect.poll(()=>aborted).toBe(true);expect(requests.every(r=>r.method==='GET')).toBe(true);expect(count).toBe(3);expect(errors).toEqual([]);await expect(page.getByRole('button',{name:'+ 新增厂商',exact:true})).toBeVisible();
});

test('node overview distinguishes forbidden, failed, and empty responses',async({page})=>{
 let status=403;
 await page.route('**/preview-fixture*',r=>r.fulfill({contentType:'text/html',body:fixture}));
 await page.route('**/api/**',route=>{
  if(route.request().url().includes('/service-nodes'))return route.fulfill({status,json:status===200?{items:[],supported_capabilities:[]}:{code:status===403?'FORBIDDEN':'TEMPORARY',message:status===403?'没有节点读取权限':'服务节点暂不可读'}});
  if(route.request().url().includes('/auth/session'))return route.fulfill({json:{authenticated:true,user:{username:'隔离用户'}}});
  return route.fulfill({json:{ok:true,items:[],page:1,page_size:10,total:0,revision:1,templates:[]}});
 });
 await page.goto('/preview-fixture?vue_service_nodes=1');await page.evaluate(()=>window.setPage('服务节点只读总览'));await expect(page.getByText('没有节点读取权限',{exact:true})).toBeVisible();status=503;await page.getByRole('button',{name:'刷新节点',exact:true}).click();await expect(page.getByText('服务节点暂不可读',{exact:true})).toBeVisible();status=200;await page.getByRole('button',{name:'刷新节点',exact:true}).click();await expect(page.getByText('暂无已登记的服务节点',{exact:true})).toBeVisible();
});

test('missing offline CSS keeps Vue unmounted and exposes the original management return',async({page})=>{
 await page.route('**/preview-fixture*',r=>r.fulfill({contentType:'text/html',body:fixture}));
 await page.route('**/api/**',route=>route.fulfill({json:route.request().url().includes('/auth/session')?{authenticated:true,user:{username:'隔离用户'}}:{ok:true,items:[],page:1,page_size:10,total:0,revision:1,templates:[]}}));
 await page.route('**/static/vue-catalog/*.css*',route=>route.fulfill({status:404,body:'missing offline asset'}));
 await page.goto('/preview-fixture?vue_service_nodes=1');await page.evaluate(()=>window.setPage('服务节点只读总览'));await expect(page.getByText('Vue 页面未能打开。',{exact:false})).toBeVisible();await expect(page.locator('.node-overview')).toHaveCount(0);await page.getByRole('button',{name:'返回完整管理',exact:true}).click();await expect(page.getByRole('button',{name:'+ 新增厂商',exact:true})).toBeVisible();
});

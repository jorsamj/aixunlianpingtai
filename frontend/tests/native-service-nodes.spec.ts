import {expect,test,type Page} from '@playwright/test';
import {resolve} from 'node:path';

async function assets(page:Page){
 await page.route('**/app/**',route=>{
  const name=new URL(route.request().url()).pathname.slice('/app/'.length)||'index.html';
  return route.fulfill({path:resolve('../static/vue-app',name),contentType:name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':'text/html'});
 });
}
const node={node_id:'node-arm',display_name:'边缘测试节点',connection_mode:'agent',status:'ONLINE',os_name:'Linux',architecture:'aarch64',
 agent_version:'agent-test-1',last_heartbeat_at:'2026-11-24T06:00:00Z',last_error:'最近一次心跳上报缺少磁盘信息',
 allowed_capabilities:['training','conversion'],reported_capabilities:['conversion'],effective_capabilities:['conversion'],
 resources:{cpu:{usage_percent:17},memory:{usage_percent:50,total_bytes:8589934592,available_bytes:4294967296,used_bytes:4294967296}},
 durable_tasks:[{task_id:'persist-task-1',kind:'MODEL_CONVERSION',stage:'验证产物',progress:12}],workers:[]};

test('native service nodes page reuses the pilot read-only overview and exposes no node write action',async({page})=>{
 const writes:string[]=[];page.on('request',r=>{if(!['GET','HEAD'].includes(r.method()))writes.push(r.method()+' '+new URL(r.url()).pathname)});
 await assets(page);
 await page.route('**/api/**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path==='/api/auth/session')return route.fulfill({json:{authenticated:true,user:{username:'隔离用户'}}});
  if(path==='/api/projects')return route.fulfill({json:[{id:'p',name:'项目 P'}]});
  if(path==='/api/v63/service-nodes')return route.fulfill({json:{items:[node],supported_capabilities:['training','conversion']}});
  return route.fulfill({status:404,json:{detail:'unexpected '+path}});
 });
 await page.goto('/app/#/projects/p/nodes');
 await expect(page.locator('.catalog-preview h1')).toHaveText('服务节点与算力');
 const card=page.getByRole('article',{name:'边缘测试节点',exact:true});
 await expect(card).toContainText('在线');
 await expect(card).toContainText('2026-11-24T06:00:00Z');
 await expect(card.getByLabel('当前有效能力')).toContainText('conversion');
 await expect(card).toContainText('最近一次心跳上报缺少磁盘信息');
 await card.getByText('任务占用与 Worker · 1 项持久任务',{exact:true}).click();
 await expect(card).toContainText('persist-task-1');
 for(const name of ['连接测试','轮换令牌','删除节点','停止任务']){
  await expect(page.getByRole('button',{name,exact:true})).toHaveCount(0);
 }
 await page.getByRole('textbox',{name:'搜索节点',exact:true}).fill('不存在的节点');
 await expect(page.getByText('没有匹配的服务节点',{exact:true})).toBeVisible();
 expect(writes).toEqual([]);
 await page.getByRole('button',{name:'返回完整管理',exact:true}).click();
 await expect(page).toHaveURL(/\/app\/#\/projects\/p\/legacy\//);
 await expect(page.getByRole('heading',{level:2,name:'算力与节点',exact:true})).toBeVisible();
 await expect(page.getByRole('link',{name:'原生服务节点只读总览',exact:true})).toBeVisible();
 await expect(page.getByRole('link',{name:'进入原算力与节点',exact:true})).toBeVisible();
});

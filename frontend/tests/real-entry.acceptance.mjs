// Run only against tools/test_vue_productization_server.py on loopback:8028.
// Real auth/API/temporary repositories; reported hardware is synthetic.
import {chromium,expect} from '@playwright/test';
import {mkdir,writeFile} from 'node:fs/promises';
const base='http://127.0.0.1:8028';
const browser=await chromium.launch({channel:'chrome'});
const page=await browser.newPage({viewport:{width:1600,height:1000}});
const errors=[],assets=[],operations=[];
page.on('pageerror',error=>errors.push(error.message));
page.on('response',response=>{if(response.url().includes('/static/vue-catalog/'))assets.push({path:new URL(response.url()).pathname,status:response.status()})});
page.on('request',request=>{if(request.method()==='POST'&&request.url().endsWith('/catalog/operations'))operations.push(request.postDataJSON())});
const output='../test-results/p1bd-real-entry';await mkdir(output,{recursive:true});
async function menu(name,action){await page.getByRole('button',{name:`${name}更多操作`,exact:true}).click();await page.getByRole('menuitem',{name:action,exact:true}).click()}
async function idle(){await expect(page.locator('.preview-editor')).toHaveCount(0)}
try{
 await page.goto(base+'/');await expect(page).toHaveURL(/\/login/);
 await page.locator('#loginUsername').fill('vue-acceptance');await page.locator('#loginPassword').fill('isolated-test-only');await page.locator('#loginSubmit').click();await expect(page.locator('#authUsername')).toHaveText('vue-acceptance');
 await page.goto(base+'/?vue_catalog_manage=1&vue_service_nodes=1');await expect.poll(()=>page.evaluate(()=>state.uiReady&&!!window.PlatformCore?.navigation)).toBe(true);
 await page.evaluate(()=>window.setPage('部署资源'));await page.getByRole('button',{name:'厂商与芯片字典',exact:true}).click();await page.getByRole('button',{name:'Vue 正式管理',exact:true}).click();
 const vendorName='验收厂商 '+Date.now();
 await page.getByRole('button',{name:'新增厂商',exact:true}).click();await page.getByRole('textbox',{name:'厂商名称',exact:true}).fill(vendorName);await page.getByRole('combobox',{name:'SDK 模板',exact:true}).press('Enter');await page.getByRole('option',{name:'瑞芯微 RKNN',exact:true}).click();await page.getByRole('button',{name:'保存厂商',exact:true}).click();await idle();
 await page.getByRole('button',{name:'新增芯片',exact:true}).click();await page.getByRole('textbox',{name:'芯片名称',exact:true}).fill('RK3568');await page.getByRole('button',{name:'保存芯片',exact:true}).click();await idle();
 const vendorList=await(await page.request.get(base+'/api/v39/deploy/catalog/records?entity=vendors&observe_only=true&query='+encodeURIComponent(vendorName))).json();const vendorId=vendorList.items.find(row=>row.name===vendorName).id;
 const listed=await(await page.request.get(base+'/api/v39/deploy/catalog/records?entity=chips&observe_only=true&vendor_id='+vendorId)).json();const chip=listed.items.find(row=>row.name==='RK3568');expect(chip.sdk_code).toBe('rk3568');
 await page.getByRole('button',{name:'编辑RK3568',exact:true}).click();await page.getByRole('textbox',{name:'芯片名称',exact:true}).fill('RK3568 显示名');await page.getByRole('button',{name:'保存芯片',exact:true}).click();await idle();
 for(const [action,label] of [['停用','确认停用芯片'],['启用','确认启用芯片']]){await menu('RK3568 显示名',action);await page.getByRole('button',{name:label,exact:true}).click();await idle()}
 const reread=await(await page.request.get(base+`/api/v39/deploy/catalog/records/chips/${chip.id}?observe_only=true`)).json();expect(reread.item.id).toBe(chip.id);expect(reread.item.sdk_code).toBe('rk3568');expect(reread.item.enabled).toBe(true);
 await menu('RK3568 显示名','检测 SDK 能力');await expect(page.getByText('暂无该模板的可检测资源',{exact:false})).toBeVisible();
 for(const width of [1600,768]){await page.setViewportSize({width,height:1000});await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:`${output}/real-catalog-management-${width}.png`,fullPage:true,animations:'disabled'})}
 await menu(vendorName,'删除');await expect(page.getByRole('button',{name:'确认删除',exact:true})).toBeDisabled();await page.getByRole('button',{name:'取消',exact:true}).click();
 await menu('RK3568 显示名','删除');await page.getByRole('button',{name:'确认删除',exact:true}).click();await idle();await menu(vendorName,'删除');await page.getByRole('button',{name:'确认删除',exact:true}).click();await idle();expect((await page.request.get(base+`/api/v39/deploy/catalog/records/chips/${chip.id}?observe_only=true`)).status()).toBe(404);
 // A real committed operation whose reply becomes undecodable must resolve by GET receipt.
 let lost=false;const before=operations.length;
 await page.route('**/api/v39/deploy/catalog/operations',async route=>{if(lost)return route.continue();lost=true;const response=await route.fetch();expect(response.ok()).toBe(true);await route.fulfill({status:200,contentType:'application/json',body:'{broken'})});
 await page.getByRole('button',{name:'新增厂商',exact:true}).click();await page.getByRole('textbox',{name:'厂商名称',exact:true}).fill('回执验收厂商 '+Date.now());await page.getByRole('button',{name:'保存厂商',exact:true}).click();await idle();expect(operations.length).toBe(before+1);await page.unroute('**/api/v39/deploy/catalog/operations');
 await page.getByRole('button',{name:'返回完整管理',exact:true}).click();await expect(page.getByRole('button',{name:'+ 新增厂商',exact:true})).toBeVisible();
 await page.evaluate(()=>window.setPage('服务节点'));await page.getByRole('button',{name:'Vue 只读总览',exact:true}).click();await expect(page.getByRole('heading',{name:'服务节点与算力',exact:true})).toBeVisible();await expect(page.getByText('Linux / aarch64',{exact:true})).toBeVisible();
 const node=page.getByRole('article',{name:'ARM64 测试快照节点',exact:true});await expect(node.getByLabel('管理员允许的能力')).toContainText('training');await expect(node.getByLabel('当前可调度能力')).not.toContainText('training');
 for(const width of [1600,768]){await page.setViewportSize({width,height:1000});await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:`${output}/real-service-nodes-${width}.png`,fullPage:true,animations:'disabled'})}
 await page.getByRole('button',{name:'刷新节点',exact:true}).click();await expect(page.getByRole('button',{name:'刷新节点',exact:true})).toBeEnabled();await page.getByRole('button',{name:'返回完整管理',exact:true}).click();await expect(page.getByRole('button',{name:'＋ 新增服务节点',exact:true})).toBeVisible();
 await page.locator('#logoutBtn').click();await expect(page).toHaveURL(/\/login/);expect((await(await page.request.get(base+'/api/auth/session')).json()).authenticated).toBe(false);expect(errors).toEqual([]);expect(assets.every(asset=>asset.status===200)).toBe(true);
 const receipt={scope:'real entry + original auth/HTTP + temporary repositories; synthetic heartbeat; lifespan/SDK off',crud:true,backendSuggestedSdk:'rk3568',stableIdentity:true,unknownReplyRecoveredWithoutSecondPost:true,originalCatalogAccessible:true,serviceNodeOriginalApi:true,serviceNodeManagementAccessible:true,logout:true,assets,errors,operationCount:operations.length};await writeFile(`${output}/real-productization-entry.json`,JSON.stringify(receipt,null,2));console.log(JSON.stringify(receipt));
}catch(error){await page.screenshot({path:`${output}/real-entry-failure.png`,fullPage:true});throw error}finally{await browser.close()}

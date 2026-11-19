import { expect, test } from '@playwright/test';
import { resolve } from 'node:path';

test('project pool restores an unknown write by scoped receipt', async ({page}) => {
 const pool='/api/v61/projects/p/negative-pool';
 let writes=0, receipts=0, operationId='', present=false, account='tester';
 let releaseRead:()=>void=()=>{};
 const delayedRead=new Promise<void>(resolve=>{releaseRead=resolve});
 const row={id:'reflection',filename:'reflection.jpg',annotation_state:'unannotated',
  negative_pool:{review_status:'unannotated',categories:[{id:'c',name:'反光'}]}};
 await page.route('**/app/**',route=>{
  const name=new URL(route.request().url()).pathname.slice(5)||'index.html';
  return route.fulfill({path:resolve('../static/vue-app',name),contentType:name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':'text/html'});
 });
 await page.route('**/api/**',async route=>{
  const request=route.request(),url=new URL(request.url()),path=url.pathname;
  if(path==='/api/auth/session')return route.fulfill({json:{authenticated:true,user:{username:account}}});
  if(path==='/api/projects')return route.fulfill({json:[{id:'p',name:'隔离项目'},{id:'q',name:'第二项目'}]});
  if(path===pool+'/categories')return route.fulfill({json:{items:[{id:'c',name:'反光',enabled:true}]}});
  if(path==='/api/v61/projects/q/negative-pool/categories')return route.fulfill({json:{items:[]}});
  if(path==='/api/v61/projects/q/negative-pool')return route.fulfill({json:{project_id:'q',negative_pool_revision:'9',items:[{...row,id:'q-background',filename:'second-project.jpg'}],total:1}});
  if(path===pool&&url.searchParams.get('query')==='delayed')await delayedRead;
  if(path===pool)return route.fulfill({json:{project_id:'p',negative_pool_revision:present?'1':'0',items:present?[row]:[],total:present?1:0}});
  if(path.endsWith('/materials'))return route.fulfill({json:{project_id:'p',items:[row],total:1}});
  if(path===pool+'/members'){
   const packet=request.postDataJSON();
   expect(packet.algorithm_id).toBeUndefined();
   expect(packet.operation_kind).toBe('negative_pool.members.v2');
   expect(packet.image_ids).toEqual(['reflection']);
   writes++;operationId=packet.operation_id;present=true;
   return route.fulfill({status:503,json:{detail:'回执暂不可用'}});
  }
  if(path===pool+'/operations/'+operationId){
   receipts++;
   expect(account).toBe('tester');
   expect(url.searchParams.get('operation_kind')).toBe('negative_pool.members.v2');
   return route.fulfill({json:{project_id:'p',operation_id:operationId,operation_kind:'negative_pool.members.v2',
    action:'add',affected:1,added:1,already_present:0,negative_pool_revision:'1'}});
  }
  throw new Error('Unexpected request '+path);
 });
 await page.goto('/app/#/projects/p/materials/negative-pool');
 await expect(page.getByRole('heading',{name:'项目公共负样本池'}).first()).toBeVisible();
 await page.locator('.project-pool form .el-select__wrapper').first().click();
 await page.getByRole('option',{name:'从素材库选择入池'}).click();
 await page.getByText('reflection.jpg',{exact:true}).click();
 await page.getByRole('button',{name:'加入公共池'}).click();
 await page.getByRole('dialog').getByRole('button',{name:'确认',exact:true}).click();
 await expect(page.getByRole('button',{name:'查询待确认操作回执'})).toBeVisible();
 const recover=page.getByRole('button',{name:'查询待确认操作回执'});
 // The former project-only key has no authenticated owner.
 await page.evaluate(()=>sessionStorage.setItem('public-negative-pool:p','{}'));
 account='other-user';
 await page.reload();
 await expect(page.getByText('reflection.jpg',{exact:true})).toBeVisible();
 await expect(recover).toHaveCount(0);
 expect(receipts).toBe(0);
 account='tester';
 await page.reload();
 await expect(recover).toBeVisible();
 await page.getByRole('textbox',{name:'搜索素材'}).fill('delayed');
 const reading=page.waitForRequest(r=>new URL(r.url()).searchParams.get('query')==='delayed');
 await page.getByRole('button',{name:'查询',exact:true}).click();
 await reading;
 await page.locator('.session-tools .el-select__wrapper').click();
 await page.getByRole('option',{name:'第二项目'}).click();
 await expect(page).toHaveURL(/projects\/q\/materials\/negative-pool/);
 await expect(page.locator('.app-header')).toContainText('第二项目');
 await expect(page.getByText('second-project.jpg',{exact:true})).toBeVisible();
 releaseRead();
 await expect(page.getByText('reflection.jpg',{exact:true})).toHaveCount(0);
 await expect(page.getByRole('textbox',{name:'搜索素材'})).toHaveValue('');
 await expect(recover).toHaveCount(0);
 await page.locator('.session-tools .el-select__wrapper').click();
 await page.getByRole('option',{name:'隔离项目'}).click();
 await recover.click();
 await expect(page.getByRole('status')).toHaveText('操作已核实');
 await expect(page.getByText('reflection.jpg',{exact:true})).toBeVisible();
 expect(writes).toBe(1);
 expect(receipts).toBe(1);
});

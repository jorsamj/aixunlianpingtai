import {test,expect} from '@playwright/test';
import {fixture} from './fixture';

test('AI task reader keeps unknown facts, original cursors, lazy failure pages and scoped legacy delegation',async({page})=>{
 const writes:string[]=[],reads:string[]=[];let deny=false,releaseLate:(()=>void)|undefined;
 const row=(id:string,project='p')=>({id,project_id:project,name:`隔离任务 ${id}`,status:id==='next'?'AWAITING_CONFIRMATION':'FAILED',statistics_known:false,total_count:null,completed_count:null,remaining_count:null,counts:{failed:null,gt_committed:null,success:null,empty:null,accepted:null}});
 await page.route('**/ai-fixture*',route=>route.fulfill({contentType:'text/html',body:fixture}));
 await page.route('**/api/**',async route=>{const request=route.request(),u=new URL(request.url()),path=u.pathname;reads.push(path+'?'+u.searchParams);
  if(request.method()!=='GET'){writes.push(request.method()+' '+path);return route.fulfill({status:500,json:{detail:'测试禁止业务写入'}})}
  if(path==='/api/auth/session')return route.fulfill({json:{authenticated:true,user:{username:'隔离用户'}}});
  if(path.includes('/annotation-tasks')){
   expect(u.searchParams.get('reader_view')).toBe('true');const project=path.split('/projects/')[1].split('/')[0];
   if(deny)return route.fulfill({status:403,json:{message:'没有AI任务读取权限'}});
   if(path.endsWith('/candidates')){expect(u.searchParams.get('filter')).toBe('failed');expect(u.searchParams.get('limit')).toBe('12');const second=u.searchParams.get('cursor')==='12';return route.fulfill({json:{ok:true,project_id:project,task_id:'next',items:Array.from({length:second?1:12},(_,i)=>({image_id:`image-${i+(second?12:0)}`,filename:`失败图片-${i+(second?12:0)}.jpg`,status:'failed',thumbnail_url:`/api/v61/projects/${project}/materials/image-${i}/content/thumbnail?edge=384`,error_code:'MODEL_TIMEOUT',error:'模型连接超时'})),total:13,next_cursor:second?null:'12',review_revision:3}})}
   const id=path.split('/annotation-tasks/')[1];if(id)return route.fulfill({json:{ok:true,project_id:project,task:row(id,project)}});
   if(u.searchParams.get('q')==='indexing')return route.fulfill({status:202,json:{ok:true,project_id:project,indexing:true,indexed:2,total:8,remaining:6,items:[],next_cursor:null}});
   if(u.searchParams.get('q')==='late'){await new Promise<void>(resolve=>{releaseLate=resolve});try{await route.fulfill({json:{ok:true,project_id:project,items:[row('old-late',project)],next_cursor:null}})}catch{}return}
   const next=u.searchParams.get('cursor')==='original-next';return route.fulfill({json:{ok:true,project_id:project,items:[row(project==='q'?'new-project':next?'next':'unknown',project)],next_cursor:next||project==='q'?null:'original-next'}});
  }
  if(path.includes('/content/thumbnail'))return route.fulfill({status:404,body:''});
  return route.fulfill({json:{ok:true,items:[],page:1,page_size:10,total:0,revision:1,templates:[]}});
 });
 await page.goto('/ai-fixture?vue_ai_tasks=1');await page.waitForFunction(()=>window.fixtureReady);await page.evaluate(()=>window.setPage('AI标注任务正式浏览'));
 await expect(page.getByRole('heading',{name:'AI 标注任务',exact:true})).toBeVisible();const first=page.getByRole('row').filter({hasText:'隔离任务 unknown'});await expect(first).toContainText('已处理 未知 / 未知');await expect(first).toContainText('失败 未知');await expect(first).not.toContainText('失败 0');await expect(page.getByText('第 1 页 · 本页 1 条 · 总数未提供')).toBeVisible();expect(reads.some(url=>url.includes('/candidates'))).toBe(false);
 await page.getByRole('button',{name:'下一页',exact:true}).click();await expect(page.getByText('隔离任务 next',{exact:true})).toBeVisible();expect(reads.some(url=>url.includes('cursor=original-next'))).toBe(true);
 await page.getByRole('button',{name:'详情',exact:true}).click();await expect(page.getByRole('heading',{name:'逐图失败记录'})).toBeVisible();expect(reads.some(url=>url.includes('/candidates'))).toBe(false);await page.getByRole('button',{name:'读取失败图片',exact:true}).click();await expect(page.locator('.failure-grid article')).toHaveCount(12);await page.getByRole('button',{name:'下一页失败图',exact:true}).click();await expect(page.locator('.failure-grid article')).toHaveCount(1);await expect(page.getByRole('heading',{name:'失败图片-12.jpg'})).toBeVisible();
 await page.getByRole('button',{name:'返回任务列表',exact:true}).click();await page.getByRole('textbox',{name:'搜索AI标注任务'}).fill('indexing');await page.getByRole('button',{name:'查询任务',exact:true}).click();await expect(page.getByText(/当前空列表不是零条匹配/)).toBeVisible();await expect(page.getByText('当前条件下没有任务',{exact:true})).toHaveCount(0);
 await page.getByRole('textbox',{name:'搜索AI标注任务'}).fill('');await page.getByRole('button',{name:'查询任务',exact:true}).click();await expect(page.getByText('隔离任务 unknown',{exact:true})).toBeVisible();deny=true;await page.getByRole('button',{name:'刷新',exact:true}).click();await expect(page.getByText('没有AI任务读取权限',{exact:true})).toBeVisible();deny=false;
 await page.getByRole('textbox',{name:'搜索AI标注任务'}).fill('late');await page.getByRole('button',{name:'查询任务',exact:true}).click();await expect.poll(()=>!!releaseLate).toBe(true);await page.evaluate(()=>{window.state.project={id:'q'};return window.setPage('AI标注任务正式浏览')});await expect(page.getByText('隔离任务 new-project',{exact:true})).toBeVisible();releaseLate!();await expect(page.getByText('隔离任务 old-late',{exact:true})).toHaveCount(0);
 await page.evaluate(()=>{const original=window.setPage;window.delegations=[];window.setPage=(name:string)=>{if(name==='自动标注及清洗'){window.state.page=name;window.delegations.push('legacy-page');return}return original(name)};window.showAiTask60=(id:string)=>window.delegations.push('detail:'+id)});await page.getByRole('button',{name:'原管理',exact:true}).click();await expect.poll(()=>page.evaluate(()=>window.delegations)).toEqual(['legacy-page','detail:new-project']);expect(writes).toEqual([]);expect(reads.some(url=>url.includes('/retry'))).toBe(false);
});

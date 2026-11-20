import {expect,test} from '@playwright/test';
import {resolve} from 'node:path';

const route=(task='review-a',project='review-project')=>`/app/#/projects/${project}/ai/tasks/${task}/review`;
const project={id:'review-project',name:'审核项目'};
const other={id:'other-project',name:'其他项目'};
const task=(id,projectId,status='AWAITING_CONFIRMATION')=>({project_id:projectId,
  task:{id,project_id:projectId,name:'隔离审核 '+id,status}});
const candidate=index=>({image_id:'image-'+index,filename:'候选 '+index+'.jpg',width:80,height:60,
  status:'success',boxes:[{label:'person',x1:8,y1:8,x2:44,y2:42,confidence:0.8}]});
const svg='<svg xmlns="http://www.w3.org/2000/svg" width="80" height="60"><rect width="80" height="60" fill="#ddd"/></svg>';
async function fixture(page){
  await page.route('**/app/**',r=>{
    const path=new URL(r.request().url()).pathname.slice('/app/'.length)||'index.html';
    return r.fulfill({path:resolve('../static/vue-app',path),
      contentType:path.endsWith('.js')?'text/javascript':path.endsWith('.css')?'text/css':'text/html'});
  });
  const session={authenticated:true,provider:'local',user:{username:'reviewer'}};
  await page.route('**/api/auth/session',r=>r.fulfill({json:session}));
  await page.route('**/api/projects',r=>r.fulfill({json:[project,other]}));
  const media=[];
  await page.route('**/api/v61/projects/*/materials/*/content**',r=>{
    media.push(new URL(r.request().url()).pathname);
    return r.fulfill({contentType:'image/svg+xml',body:svg});
  });
  return {media,session};
}

test('原生审核读取 24 张分页及失败诊断，三个视口保留原工作台入口',async({page})=>{
  const {media}=await fixture(page);
  const reads=[],writes=[];
  await page.route('**/api/v60/projects/*/annotation-tasks/**',r=>{
    const {pathname,searchParams}=new URL(r.request().url());
    if(r.request().method()!=='GET'){writes.push(pathname);return r.abort()}
    if(pathname.endsWith('/review-a')){
      expect(searchParams.get('reader_view')).toBe('true');
      return r.fulfill({json:task('review-a',project.id)});
    }
    if(pathname.endsWith('/candidates')){
      expect(searchParams.get('limit')).toBe('24');
      const filter=searchParams.get('filter'),cursor=searchParams.get('cursor');
      reads.push([filter,cursor]);
      const items=filter==='failed'?[{...candidate(99),status:'failed',boxes:[],error:'候选生成失败'}]:
        Array.from({length:24},(_,i)=>candidate(Number(cursor)+i));
      return r.fulfill({json:{items,total:filter==='failed'?1:20000,
        next_cursor:filter==='failed'?null:String(Number(cursor)+24),review_revision:5,summary:{failed:1}}});
    }
    if(pathname.endsWith('/image-0'))return r.fulfill({json:{item:{...candidate(0),draft_revision:2,
      original_boxes:[{label:'original',x1:4,y1:4,x2:24,y2:30}]}}});
    if(pathname.endsWith('/image-99'))return r.fulfill({json:{item:{...candidate(99),status:'failed',boxes:[],
      error:'候选生成失败',error_stage:'inference',http_status:502}}});
    if(pathname.endsWith('/image-99/diagnostics')){
      reads.push(['diagnostics',null]);
      return r.fulfill({json:{image_id:'image-99',status:'available',diagnostics:{model_name:'隔离模型',latency_ms:0}}});
    }
    return r.abort();
  });
  await page.setViewportSize({width:1920,height:1080});
  await page.goto(route());
  await expect(page.getByText('任务 review-a · 待人工审核')).toBeVisible();
  const cards=page.locator('.review-candidate');
  await expect(cards).toHaveCount(24);
  await expect(page.getByText('20000 张',{exact:true})).toBeVisible();
  expect(reads).toEqual([['all',null]]);
  expect(media.filter(path=>path.endsWith('/thumbnail')).length).toBeLessThanOrEqual(24);
  expect(media.filter(path=>path.endsWith('/content'))).toHaveLength(0);
  await page.getByRole('button',{name:'列表',exact:true}).click();
  await expect(page.locator('.review-cards')).toHaveClass(/list/);
  await page.getByRole('button',{name:'网格',exact:true}).click();
  await page.getByRole('button',{name:'候选 0.jpg'}).click();
  const inspector=page.getByRole('complementary',{name:'当前图片检查'});
  await expect(inspector.getByText('草稿版本 2')).toBeVisible();
  await expect(inspector.locator('svg rect')).toHaveCount(1);
  await inspector.getByRole('button',{name:'原始候选框'}).click();
  await expect(inspector.getByRole('list',{name:'候选框'})).toContainText('original');
  await inspector.getByRole('button',{name:'关闭检查'}).click();
  await page.getByRole('button',{name:'下一页'}).click();
  await expect(cards.first()).toContainText('候选 24.jpg');
  await page.getByRole('button',{name:'上一页'}).click();
  await expect(cards.first()).toContainText('候选 0.jpg');
  await page.getByRole('button',{name:/^失败/}).click();
  await expect(cards).toHaveCount(1);
  expect(reads).toEqual([['all',null],['all','24'],['all',null],['failed',null]]);

  for(const [width,height] of [[1920,1080],[1366,768],[768,1024]]){
    await page.setViewportSize({width,height});
    await page.getByRole('button',{name:'候选 99.jpg'}).focus();
    await page.keyboard.press('Enter');
    await expect(page.getByRole('heading',{name:'当前图片检查'})).toBeFocused();
    await expect(page.getByText('502',{exact:true})).toBeVisible();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    if(width!==768){
      expect(await page.locator('.review-columns').evaluate(el=>getComputedStyle(el).gridTemplateColumns.split(' ').length)).toBe(3);
      await page.getByRole('button',{name:'关闭检查'}).click();
    }
  }
  expect(reads.filter(([operation])=>operation==='diagnostics')).toHaveLength(0);
  await page.getByRole('button',{name:'读取诊断'}).click();
  await expect(page.getByText('隔离模型',{exact:true})).toBeVisible();
  await expect(page.getByText('0',{exact:true})).toBeVisible();
  expect(reads.filter(([operation])=>operation==='diagnostics')).toHaveLength(1);
  expect(writes).toEqual([]);
  await page.getByRole('button',{name:'关闭检查'}).click();
  const legacy=page.getByRole('link',{name:'返回原工作台'});
  const destination=new URL(await legacy.getAttribute('href'),page.url());
  expect(destination.pathname).toBe('/');
  expect(destination.searchParams.get('project_id')).toBe(project.id);
  expect(destination.searchParams.get('page')).toBe('自动标注及清洗');
  expect(await page.evaluate(()=>typeof window.reviewAiLabel427)).toBe('undefined');
  await page.route(url=>url.pathname==='/',r=>r.fulfill({path:resolve('../static/index.html'),contentType:'text/html'}));
  await legacy.click();
  await expect(page).toHaveURL(url=>url.pathname==='/');
  await expect.poll(()=>page.evaluate(()=>typeof window.reviewAiLabel427==='function')).toBe(true);
});

test('原生审核拒绝错配身份，切项目与离页取消在途读取',async({page})=>{
  const {session}=await fixture(page);
  const candidateRequests=[];
  const pending=[];
  await page.route('**/api/v60/projects/*/annotation-tasks/**',async r=>{
    const parts=new URL(r.request().url()).pathname.split('/');
    const projectId=parts[4],id=parts[6];
    if(parts.length===7)return r.fulfill({json:task(id,id==='wrong'?'foreign-project':projectId,
      id==='empty'?'FAILED':'AWAITING_CONFIRMATION')});
    candidateRequests.push(id);
    if(id==='account'&&session.user.username==='reviewer-two')return r.fulfill({json:{
      items:[candidate(2)],total:1,next_cursor:null,review_revision:1,
    }});
    if(id==='empty')return r.fulfill({json:{items:[],total:0,next_cursor:null,review_revision:0,
      task_error:{code:'CANDIDATES_NOT_GENERATED',message:'尚未生成候选结果'}}});
    pending.push(r);
  });
  const navigate=async(target)=>page.evaluate(hash=>{location.hash=hash},target.split('#')[1]);
  await page.goto(route('wrong'));
  await expect(page.getByRole('alert')).toContainText('任务编号不一致');
  expect(candidateRequests).toEqual([]);
  await navigate(route('slow'));
  await expect.poll(()=>candidateRequests).toEqual(['slow']);
  const cancelled=page.waitForEvent('requestfailed',{predicate:r=>r.url().includes('/slow/candidates')});
  await navigate(route('empty',other.id));
  await cancelled;
  await expect(page.getByText('任务 empty · 失败')).toBeVisible();
  await expect(page.getByText('尚未生成候选结果')).toBeVisible();
  await expect(page.getByText('0 张',{exact:true})).toHaveCount(0);

  await navigate(route('leave',other.id));
  await expect.poll(()=>candidateRequests).toEqual(['slow','empty','leave']);
  const left=page.waitForEvent('requestfailed',{predicate:r=>r.url().includes('/leave/candidates')});
  await navigate('/app/#/unknown-path');
  await left;
  await Promise.allSettled(pending.map(r=>r.fulfill({json:{items:[candidate(1)]}})));
  await expect(page.getByText('页面不存在，请从侧栏选择业务入口。')).toBeVisible();
  await expect(page.locator('.review-candidate')).toHaveCount(0);

  await navigate(route('account'));
  await expect.poll(()=>candidateRequests.at(-1)).toBe('account');
  const accountCancelled=page.waitForEvent('requestfailed',{predicate:r=>r.url().includes('/account/candidates')});
  await page.evaluate(()=>{
    Object.defineProperty(document,'hidden',{value:true,configurable:true});
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await accountCancelled;
  session.user.username='reviewer-two';
  await page.evaluate(()=>{
    delete document.hidden;
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await expect(page.getByText('reviewer-two',{exact:true})).toBeVisible();
  await expect(page.locator('.review-candidate')).toHaveCount(1);
  await expect(page.getByRole('button',{name:'候选 2.jpg'})).toBeVisible();
});

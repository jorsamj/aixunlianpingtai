import {expect,test} from '@playwright/test';
import {resolve} from 'node:path';

const projectId='review-project',taskId='review-bulk';
const route=`/app/#/projects/${projectId}/ai/tasks/${taskId}/review`;
const selectionId='a'.repeat(32);

function rows(){
  return Array.from({length:30},(_,index)=>({
    image_id:`image-${index}`,filename:`候选 ${index}.jpg`,width:80,height:60,status:'success',
    boxes:[{label:'person',x1:8,y1:8,x2:44,y2:42}],review_state:'active',
  }));
}
const intentBody=body=>({operation_id:'operation-1',request_id:body.request_id,project_id:projectId,
  task_id:taskId,selection_id:body.selection_id,review_revision:body.review_revision,purpose:'gt',
  original_count:30,excluded_count:body.excluded_image_ids.length,count:30-body.excluded_image_ids.length,
  status:'accepted',accepted_at:'2026-11-21T00:00:00Z',
  manifest_ref:`evidence-versions/v1/sha256-${'b'.repeat(64)}.json`,manifest_digest:'b'.repeat(64)});
const executionView=(state,overrides={})=>({
  operation_id:'operation-1',execution_task_id:'fbulk-test',status:'RUNNING',stage:'running',
  total_images:state.sealed?state.sealed.count:30,committed_images:null,committed_images_proven:false,
  pending_images:null,completed_batches:0,total_batches:1,current_batch:null,
  candidate_adopted_images:0,candidate_only_uncommitted_images:0,candidate_only_gt_changed_images:0,
  uncommitted_gt_changed_images:0,cancellation_requested:false,blocked:false,blocked_code:null,
  blocked_reason:null,manual_review_required:false,last_error_code:null,last_error_message:null,
  finished_at:null,...overrides});

async function fixture(page){
  const state={sealed:null,executes:0,intents:[],failNextSeal:false,mode:'success',executionPolls:0,recoverStatus:0};
  await page.route('**/app/**',r=>{
    const path=new URL(r.request().url()).pathname.slice('/app/'.length)||'index.html';
    return r.fulfill({path:resolve('../static/vue-app',path),
      contentType:path.endsWith('.js')?'text/javascript':path.endsWith('.css')?'text/css':'text/html'});
  });
  await page.route('**/api/auth/session',r=>r.fulfill({json:{authenticated:true,provider:'local',user:{username:'reviewer'}}}));
  await page.route('**/api/projects',r=>r.fulfill({json:[{id:projectId,name:'审核项目'},
    {id:'other-project',name:'其他项目'}]}));
  await page.route('**/api/v61/projects/*/materials/*/content**',r=>r.fulfill({contentType:'image/svg+xml',
    body:'<svg xmlns="http://www.w3.org/2000/svg" width="80" height="60"><rect width="80" height="60" fill="#ddd"/></svg>'}));
  await page.route('**/api/v12/projects/*/labels',r=>r.fulfill({json:{items:[{code:'person',class_id:0}]}}));
  await page.route('**/api/v60/projects/*/annotation-tasks/**',async r=>{
    const request=r.request(),url=new URL(request.url()),method=request.method();
    const tail=url.pathname.split('/').slice(6);
    if(method==='GET'&&tail.length===1)return r.fulfill({json:{project_id:projectId,
      task:{id:tail[0],project_id:projectId,name:'隔离审核',status:'AWAITING_CONFIRMATION',
        review_scope_policy:'task_uniform_legacy'}}});
    if(method==='GET'&&tail.at(-1)==='candidates'){
      const start=Number(url.searchParams.get('cursor')||0);
      const member=url.searchParams.has('selection_id');
      const all=rows().map(row=>member?{...row,selection_member:true}:row);
      return r.fulfill({json:{items:all.slice(start,start+24),total:all.length,
        next_cursor:start+24<all.length?String(start+24):null,review_revision:1,summary:{}}});
    }
    if(method==='POST'&&tail.at(-1)==='review-selection')return r.fulfill({json:{selection_id:selectionId,
      filter:'all',purpose:'gt',review_revision:1,filtered_total:30,count:30,excluded:0,reasons:{}}});
    if(tail.includes('bulk-formal')){
      const bulk=tail.slice(tail.indexOf('bulk-formal')+1);
      if(method==='POST'&&bulk.length===1){
        const body=request.postDataJSON();state.intents.push(body);
        if(state.failNextSeal){state.failNextSeal=false;return r.abort('failed')}
        state.sealed=intentBody(body);
        return r.fulfill({json:state.sealed});
      }
      if(method==='GET'&&bulk.length===2)
        return state.sealed&&bulk[1]===state.sealed.request_id
          ?r.fulfill({json:state.sealed}):r.fulfill({status:404,json:{detail:'intent not found'}});
      if(method==='POST'&&bulk.at(-1)==='execute'){
        state.executes+=1;
        if(state.executeDelay)await new Promise(done=>setTimeout(done,state.executeDelay));
        return r.fulfill({json:executionView(state,{status:'QUEUED'})});
      }
      if(method==='GET'&&bulk.at(-1)==='execution'){
        state.executionPolls+=1;
        if(state.mode==='blocked')return r.fulfill({json:executionView(state,{status:'RUNNING',stage:'formal_bulk_blocked',
          blocked:true,blocked_code:'FORMAL_BULK_EVIDENCE_UNPROVEN',blocked_reason:'持久证据互相矛盾',
          manual_review_required:true,cancellation_requested:true})});
        if(state.mode==='cancel-requested')return r.fulfill({json:executionView(state,{status:'CANCEL_REQUESTED',
          stage:'cancelling',cancellation_requested:true})});
        if(state.executionPolls<=1)return r.fulfill({json:executionView(state,{status:'RUNNING'})});
        return r.fulfill({json:executionView(state,{status:'SUCCEEDED',committed_images:state.sealed.count,
          committed_images_proven:true,pending_images:0,completed_batches:1,total_batches:1,
          current_batch:0,finished_at:'2026-11-21T00:00:10Z'})});
      }
      if(method==='POST'&&bulk.at(-1)==='cancel')
        return r.fulfill({json:executionView(state,{status:'CANCEL_REQUESTED',cancellation_requested:true})});
      if(method==='POST'&&bulk.at(-1)==='recover')
        return state.recoverStatus
          ?r.fulfill({status:state.recoverStatus,json:{detail:'持久证据仍不能证明可安全恢复'}})
          :r.fulfill({json:executionView(state,{status:'QUEUED'})});
    }
    return r.fulfill({status:404,json:{detail:'unhandled'}});
  });
  return state;
}

const storageKey=projectId=>'ai-review-bulk:v1:'+JSON.stringify([JSON.stringify(['local','reviewer']),projectId,taskId]);
const readRecord=page=>page.evaluate(key=>JSON.parse(sessionStorage.getItem(key)||'null'),storageKey(projectId));

test('冻结范围后台入库：跨页排除、预检封存、幂等确认、未证明进度与成功刷新',async({page})=>{
  const state=await fixture(page);
  await page.goto(route);
  await page.getByRole('button',{name:'选择全部筛选结果'}).click();
  await expect(page.getByText(/可操作 30 张/)).toBeVisible();
  await page.getByRole('button',{name:'下一页'}).click();
  await page.getByRole('checkbox',{name:'选择 候选 24.jpg',exact:true}).uncheck();
  await expect(page.locator('.review-selection').getByText(/已选 29 张/).first()).toBeVisible();

  await page.getByRole('button',{name:'后台正式入库 29 张'}).click();
  await page.getByRole('dialog').getByRole('button',{name:'预检并封存'}).click();
  await expect(page.getByRole('dialog')).toContainText('可入库 29 张');
  expect(state.intents).toHaveLength(1);
  const sealedBody=state.intents[0];
  expect(sealedBody.excluded_image_ids).toEqual(['image-24']);
  expect(sealedBody.selection_id).toBe(selectionId);
  expect(await readRecord(page)).toMatchObject({request_id:sealedBody.request_id,selection_id:selectionId,
    excluded_image_ids:['image-24']});

  const confirm=page.getByRole('dialog').getByRole('button',{name:'确认创建后台任务'});
  state.executeDelay=400;
  const first=confirm.click();
  await page.waitForTimeout(100);
  await confirm.click({force:true}).catch(()=>{});
  await first;
  await expect(page.locator('.review-bulk')).toContainText('未证明');
  await expect(page.locator('.review-bulk')).toContainText('后台执行中');
  await expect(page.locator('.review-bulk')).toContainText('已完成',{timeout:10000});
  await expect(page.locator('.review-bulk')).toContainText('已证明提交 GT 29');
  expect(state.executes).toBe(1);
  await expect(page.locator('.review-selection').getByText(/已选 0 张/).first()).toBeVisible();
});

test('封存响应丢失后复用同一 request_id，刷新可找回原操作',async({page})=>{
  const state=await fixture(page);
  state.failNextSeal=true;
  await page.goto(route);
  await page.getByRole('button',{name:'选择全部筛选结果'}).click();
  await page.getByRole('button',{name:'后台正式入库 30 张'}).click();
  await page.getByRole('dialog').getByRole('button',{name:'预检并封存'}).click();
  await expect(page.getByRole('dialog').getByRole('alert')).toBeVisible();
  const first=await readRecord(page);
  expect(first).not.toBeNull();

  await page.reload();
  await expect(page.getByText('上次预检结果未确认，可重试同一操作。')).toBeVisible();
  await page.getByRole('button',{name:'重试上次预检'}).click();
  await expect(page.getByText(/已封存 30 张/)).toBeVisible();
  expect(state.intents).toHaveLength(2);
  expect(state.intents[1].request_id).toBe(first.request_id);
  expect(state.intents[1]).toEqual(state.intents[0]);
  expect(new Set(state.intents.map(item=>item.request_id)).size).toBe(1);
});

test('取消请求与阻断状态不被展示为成功，恢复 409 保留阻断',async({page})=>{
  const state=await fixture(page);
  state.mode='cancel-requested';
  await page.goto(route);
  await page.getByRole('button',{name:'选择全部筛选结果'}).click();
  await page.getByRole('button',{name:'后台正式入库 30 张'}).click();
  await page.getByRole('dialog').getByRole('button',{name:'预检并封存'}).click();
  await page.getByRole('dialog').getByRole('button',{name:'确认创建后台任务'}).click();
  await page.getByRole('dialog').getByRole('button',{name:'关闭'}).last().click();
  await expect(page.locator('.review-bulk')).toContainText('正在取消');
  await expect(page.locator('.review-bulk')).not.toContainText('已完成');

  state.mode='blocked';
  await page.locator('.review-bulk').getByRole('button',{name:'刷新进度'}).click();
  await expect(page.locator('.review-bulk')).toContainText('任务已阻断');
  await expect(page.locator('.review-bulk')).not.toContainText('已完成');
  state.recoverStatus=409;
  await page.locator('.review-bulk').getByRole('button',{name:'核验并恢复'}).click();
  await expect(page.locator('.review-bulk')).toContainText('任务已阻断');
  await expect(page.locator('.review-bulk')).not.toContainText('已完成');
});

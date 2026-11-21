import {expect,test} from '@playwright/test';
import {resolve} from 'node:path';

const projectId='review-project',taskId='review-bulk';
const route=`/app/#/projects/${projectId}/ai/tasks/${taskId}/review`;
const selectionId='a'.repeat(32);
const key=()=>'ai-review-bulk:v1:'+JSON.stringify([JSON.stringify(['local','reviewer']),projectId,taskId]);

function rows(committed){
  return Array.from({length:30},(_,index)=>({
    image_id:`image-${index}`,filename:`候选 ${index}.jpg`,width:80,height:60,status:'success',
    boxes:[{label:'person',x1:8,y1:8,x2:44,y2:42}],review_state:'active',
    ...(committed?{gt_committed:index!==24}:{}),
  }));
}
const available=state=>state.committed?1:30;
const intentBody=(state,body)=>({operation_id:'operation-'+(state.intents.length),request_id:body.request_id,
  project_id:projectId,task_id:taskId,selection_id:body.selection_id,review_revision:body.review_revision,
  purpose:'gt',original_count:30,excluded_count:body.excluded_image_ids.length,
  count:available(state)-body.excluded_image_ids.length,status:'accepted',
  accepted_at:'2026-11-21T00:00:00Z',manifest_ref:`evidence-versions/v1/sha256-${'b'.repeat(64)}.json`,
  manifest_digest:'b'.repeat(64)});
const executionView=(state,overrides={})=>({
  operation_id:state.sealed.operation_id,execution_task_id:'fbulk-test',status:'RUNNING',stage:'running',
  total_images:state.sealed.count,committed_images:null,committed_images_proven:false,pending_images:null,
  completed_batches:0,total_batches:1,current_batch:null,candidate_adopted_images:0,
  candidate_only_uncommitted_images:0,candidate_only_gt_changed_images:0,
  uncommitted_gt_changed_images:0,cancellation_requested:false,blocked:false,blocked_code:null,
  blocked_reason:null,manual_review_required:false,last_error_code:null,last_error_message:null,
  finished_at:null,...overrides});

async function fixture(page){
  const state={sealed:null,executes:0,intents:[],failNextSeal:false,loseSealResponse:false,
    committed:false,mode:'success',executionPolls:0,recoverStatus:0,executeDelay:0,
    holdSeal:false,sealStarted:false,sealGate:null};
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
      const start=Number(url.searchParams.get('cursor')||0),member=url.searchParams.has('selection_id');
      const all=rows(state.committed).map(row=>member?{...row,selection_member:true}:row);
      return r.fulfill({json:{items:all.slice(start,start+24),total:all.length,
        next_cursor:start+24<all.length?String(start+24):null,review_revision:1,summary:{}}});
    }
    if(method==='POST'&&tail.at(-1)==='review-selection')return r.fulfill({json:{selection_id:selectionId,
      filter:'all',purpose:'gt',review_revision:1,filtered_total:30,count:available(state),
      excluded:30-available(state),reasons:{committed:30-available(state)}}});
    if(tail.includes('bulk-formal')){
      const bulk=tail.slice(tail.indexOf('bulk-formal')+1);
      if(method==='POST'&&bulk.length===1){
        const body=request.postDataJSON();state.intents.push(body);state.sealStarted=true;
        if(state.holdSeal&&state.sealGate)await state.sealGate;
        if(state.failNextSeal){state.failNextSeal=false;return r.abort('failed')}
        state.sealed=intentBody(state,body);
        if(state.loseSealResponse){state.loseSealResponse=false;return r.abort('failed')}
        return r.fulfill({json:state.sealed});
      }
      if(method==='GET'&&bulk.length===2)
        return state.sealed&&bulk[1]===state.sealed.request_id
          ?r.fulfill({json:state.sealed}):r.fulfill({status:404,json:{detail:'intent not found'}});
      if(method==='POST'&&bulk.at(-1)==='execute'){
        state.executes+=1;state.executionPolls=0;
        if(state.executeDelay)await new Promise(done=>setTimeout(done,state.executeDelay));
        return r.fulfill({json:executionView(state,{status:'QUEUED'})});
      }
      if(method==='GET'&&bulk.at(-1)==='execution'){
        if(state.executes===0)return r.fulfill({status:404,json:{detail:'execution not found'}});
        state.executionPolls+=1;
        if(state.mode==='blocked')return r.fulfill({json:executionView(state,{status:'RUNNING',
          stage:'formal_bulk_blocked',blocked:true,blocked_code:'FORMAL_BULK_EVIDENCE_UNPROVEN',
          blocked_reason:'持久证据互相矛盾',manual_review_required:true,cancellation_requested:true})});
        if(state.mode==='cancel-requested')return r.fulfill({json:executionView(state,{status:'CANCEL_REQUESTED',
          stage:'cancelling',cancellation_requested:true})});
        if(state.executionPolls<=1)return r.fulfill({json:executionView(state,{status:'RUNNING'})});
        state.committed=true;
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
const readRecord=page=>page.evaluate(k=>JSON.parse(sessionStorage.getItem(k)||'null'),key());

async function seal(page,label='后台正式入库 30 张'){
  await page.getByRole('button',{name:label}).click();
  await page.getByRole('dialog').getByRole('button',{name:'预检并封存'}).click();
}

test('冻结→排除→封存→确认→进度→成功，随后可发起第二笔新操作',async({page})=>{
  const state=await fixture(page);
  await page.goto(route);
  await page.getByRole('button',{name:'选择全部筛选结果'}).click();
  await expect(page.getByText(/可操作 30 张/)).toBeVisible();
  await page.getByRole('button',{name:'下一页'}).click();
  await page.getByRole('checkbox',{name:'选择 候选 24.jpg',exact:true}).uncheck();
  await expect(page.locator('.review-selection').getByText(/已选 29 张/).first()).toBeVisible();

  await seal(page,'后台正式入库 29 张');
  await expect(page.getByRole('dialog')).toContainText('可入库 29 张');
  const firstBody=state.intents[0];
  expect(firstBody.excluded_image_ids).toEqual(['image-24']);
  expect(await readRecord(page)).toMatchObject({request_id:firstBody.request_id,selection_id:selectionId});
  // Sealed range is locked: no checkbox / clear-selection drift.
  await expect(page.getByRole('dialog').getByRole('button',{name:'确认创建后台任务'})).toBeVisible();
  await expect(page.getByRole('dialog').getByRole('button',{name:'放弃预检'})).toBeVisible();

  state.executeDelay=400;
  const confirm=page.getByRole('dialog').getByRole('button',{name:'确认创建后台任务'});
  const first=confirm.click();
  await page.waitForTimeout(100);
  await confirm.click({force:true}).catch(()=>{});
  await first;
  await page.getByRole('dialog').getByRole('button',{name:'关闭'}).last().click();
  await expect(page.locator('.review-bulk')).toContainText('未证明');
  await expect(page.locator('.review-bulk')).toContainText('已完成',{timeout:10000});
  await expect(page.locator('.review-bulk')).toContainText('已证明提交 GT 29');
  expect(state.executes).toBe(1);
  await expect(page.locator('.review-selection').getByText(/已选 0 张/).first()).toBeVisible();

  // Second operation after a terminal result: fresh identity, last result kept.
  await page.getByRole('button',{name:'选择全部筛选结果'}).click();
  await expect(page.getByText(/可操作 1 张/)).toBeVisible();
  await page.getByRole('button',{name:'后台正式入库 1 张'}).click();
  await page.getByRole('dialog').getByRole('button',{name:'预检并封存'}).click();
  await expect(page.getByRole('dialog')).toContainText('可入库 1 张');
  await page.getByRole('dialog').getByRole('button',{name:'确认创建后台任务'}).click();
  await page.getByRole('dialog').getByRole('button',{name:'关闭'}).last().click();
  await expect(page.locator('.review-bulk')).toContainText('已完成',{timeout:10000});
  expect(state.executes).toBe(2);
  expect(state.intents).toHaveLength(2);
  expect(state.intents[1].request_id).not.toBe(firstBody.request_id);
});

test('服务端未封存的中断：重试复用同一 request_id',async({page})=>{
  const state=await fixture(page);
  state.failNextSeal=true;
  await page.goto(route);
  await page.getByRole('button',{name:'选择全部筛选结果'}).click();
  await seal(page);
  await expect(page.getByRole('dialog').getByRole('alert')).toBeVisible();
  const first=await readRecord(page);

  await page.reload();
  await expect(page.getByText('上次预检结果未确认，可重试同一操作。')).toBeVisible();
  await page.getByRole('button',{name:'重试上次预检'}).click();
  await expect(page.getByText(/已封存 30 张/)).toBeVisible();
  expect(state.intents).toHaveLength(2);
  expect(state.intents[1]).toEqual(state.intents[0]);
  expect(state.intents[1].request_id).toBe(first.request_id);
});

test('服务端已封存但响应丢失：刷新查到原 intent 并继续，不建第二笔',async({page})=>{
  const state=await fixture(page);
  state.loseSealResponse=true;
  await page.goto(route);
  await page.getByRole('button',{name:'选择全部筛选结果'}).click();
  await seal(page);
  await expect(page.getByRole('dialog').getByRole('alert')).toBeVisible();
  expect(state.intents).toHaveLength(1);
  expect(state.sealed).not.toBeNull();

  await page.reload();
  await expect(page.getByText(/已封存 30 张/)).toBeVisible();
  await expect(page.getByText('上次预检结果未确认，可重试同一操作。')).toHaveCount(0);
  expect(state.intents).toHaveLength(1);
  await page.locator('.review-bulk').getByRole('button',{name:'查看预检'}).click();
  await page.getByRole('dialog').getByRole('button',{name:'确认创建后台任务'}).click();
  await page.getByRole('dialog').getByRole('button',{name:'关闭'}).last().click();
  await expect(page.locator('.review-bulk')).toContainText('已完成',{timeout:10000});
  expect(state.executes).toBe(1);
});

test('sessionStorage 不可用时不发送封存请求',async({page})=>{
  const state=await fixture(page);
  await page.addInitScript(()=>{
    const original=Storage.prototype.setItem;
    Storage.prototype.setItem=function(name,value){
      if(String(name).startsWith('ai-review-bulk:'))throw new Error('quota');
      return original.call(this,name,value);
    };
  });
  await page.goto(route);
  await page.getByRole('button',{name:'选择全部筛选结果'}).click();
  await page.getByRole('button',{name:'后台正式入库 30 张'}).click();
  await page.getByRole('dialog').getByRole('button',{name:'预检并封存'}).click();
  await expect(page.getByRole('dialog').getByRole('alert')).toContainText('浏览器无法保存本次操作身份');
  expect(state.intents).toHaveLength(0);
  expect(state.sealed).toBeNull();
});

test('取消请求与阻断不被展示为成功，恢复 409 保留阻断',async({page})=>{
  const state=await fixture(page);
  state.mode='cancel-requested';
  await page.goto(route);
  await page.getByRole('button',{name:'选择全部筛选结果'}).click();
  await seal(page);
  await page.getByRole('dialog').getByRole('button',{name:'确认创建后台任务'}).click();
  await page.getByRole('dialog').getByRole('button',{name:'关闭'}).last().click();
  await expect(page.locator('.review-bulk')).toContainText('正在取消');
  await expect(page.locator('.review-bulk')).not.toContainText('已完成');

  state.mode='blocked';
  await page.locator('.review-bulk').getByRole('button',{name:'刷新进度'}).click();
  await expect(page.locator('.review-bulk')).toContainText('任务已阻断');
  state.recoverStatus=409;
  await page.locator('.review-bulk').getByRole('button',{name:'核验并恢复'}).click();
  await expect(page.locator('.review-bulk')).toContainText('任务已阻断');
  await expect(page.locator('.review-bulk')).not.toContainText('已完成');
});


test('pending preflight locks the frozen range until the request resolves',async({page})=>{
  const state=await fixture(page);
  state.holdSeal=true;
  state.sealGate=new Promise(resolve=>{state.releaseSeal=resolve;});
  await page.goto(route);
  await page.getByRole('button',{name:'选择全部筛选结果'}).click();
  await expect(page.getByText(/可操作 30 张/)).toBeVisible();
  await page.getByRole('button',{name:'后台正式入库 30 张'}).click();
  const sealing=page.getByRole('dialog').getByRole('button',{name:'预检并封存'}).click();
  await expect.poll(()=>state.sealStarted).toBe(true);
  await expect(page.getByRole('checkbox',{name:'选择 候选 0.jpg',exact:true})).toBeDisabled();
  await expect(page.getByRole('button',{name:'清空选择'})).toBeDisabled();
  state.releaseSeal();
  await sealing;
  await expect(page.getByRole('dialog')).toContainText('可入库 30 张');
});
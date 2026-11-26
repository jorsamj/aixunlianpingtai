import {expect,test} from '@playwright/test';
import {resolve} from 'node:path';

const projectId='review-project',taskId='review-bulk';
const route=`/app/#/projects/${projectId}/ai/tasks/${taskId}/review`;
const selectionId='a'.repeat(32);
const key=()=>'ai-review-bulk:v1:'+JSON.stringify([JSON.stringify(['local','reviewer']),projectId,taskId]);
const eligibilityCount=dialog=>dialog.locator('dt').filter({hasText:/^符合入库条件$/})
  .locator('xpath=following-sibling::dd[1]');

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
    holdSeal:false,sealStarted:false,sealGate:null,
    loseExecuteResponse:false,hideExecution:false,conflictExisting:false,
    sealedRequest:null,intentStatus:0,executionStatus:0,sealFailures:0,replayStatus:0,
    transferPreview:null,transferWrites:[],transferUndo:0,transferReads:0,transferStatus:''};
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
  await page.route('**/api/v12/projects/*/algorithms?**',r=>r.fulfill({json:{
    ok:true,project_id:projectId,items:[],page:1,page_size:20,total:0}}));
  await page.route('**/negative-pool/categories',r=>r.fulfill({json:{items:[{id:'difficult',name:'困难负样本',enabled:true}]}}));
  await page.route('**/api/v60/projects/*/annotation-tasks/**',async r=>{
    const request=r.request(),url=new URL(request.url()),method=request.method();
    const tail=url.pathname.split('/').slice(6);
    if(method==='GET'&&tail.length===1)return r.fulfill({json:{project_id:projectId,
      task:{id:tail[0],project_id:projectId,name:'隔离审核',status:'AWAITING_CONFIRMATION',
        review_scope_policy:'task_uniform_legacy'}}});
    if(method==='GET'&&tail.at(-1)==='candidates'){
      const start=Number(url.searchParams.get('cursor')||0),member=url.searchParams.has('selection_id');
      const all=rows(state.committed).map(row=>({...row,...(member?{selection_member:true}:{}),
        ...(state.transferStatus==='completed'&&row.image_id!=='image-24'?{review_state:'transferred'}:{})}));
      return r.fulfill({json:{items:all.slice(start,start+24),total:all.length,
        next_cursor:start+24<all.length?String(start+24):null,review_revision:1,summary:{}}});
    }
    if(method==='POST'&&tail.at(-1)==='review-selection')return r.fulfill({json:{selection_id:selectionId,
      filter:'all',purpose:request.postDataJSON().purpose,review_revision:1,filtered_total:30,count:available(state),
      excluded:30-available(state),reasons:{committed:30-available(state)}}});
    if(method==='POST'&&tail.at(-1)==='negative-transfer-preview'){
      state.transferPreview=request.postDataJSON();
      return r.fulfill({json:{total:29,eligible:29,conflicts:0,with_boxes:29,zero:0,discarded_boxes:29,
        ineligible_reasons:{},review_revision:1}});
    }
    if(method==='POST'&&tail.at(-1)==='negative-transfer'){
      state.transferWrites.push(request.postDataJSON());
      state.transferStatus='completed';
      return r.abort('failed');
    }
    if(tail[1]==='negative-transfer'&&tail[2]===state.transferPreview?.request_id){
      if(method==='POST'&&tail[3]==='undo'){
        state.transferUndo++;state.transferStatus='undone';
        return r.fulfill({json:{status:'undone'}});
      }
      if(method==='GET'){
        state.transferReads++;
        return r.fulfill({json:{request_id:tail[2],total:29,processed:29,status:state.transferStatus,
          target:{algorithm_id:'',category_ids:['difficult'],confirm_absent:false},
          items:[{image_id:'image-0',filename:'候选 0.jpg',status:state.transferStatus==='undone'?'undone':'transferred'}],next_cursor:null}});
      }
    }
    if(tail.includes('bulk-formal')){
      const bulk=tail.slice(tail.indexOf('bulk-formal')+1);
      if(method==='POST'&&bulk.length===1){
        const body=request.postDataJSON();state.intents.push(body);state.sealStarted=true;
        if(state.replayStatus){const code=state.replayStatus;state.replayStatus=0;
          return r.fulfill({status:code,json:{detail:'seal proof unavailable'}});}
        if(state.holdSeal&&state.sealGate)await state.sealGate;
        if(state.sealed&&state.sealed.request_id===body.request_id
          &&JSON.stringify(state.sealedRequest)===JSON.stringify(body))
          return r.fulfill({json:state.sealed});
        if(state.sealed&&state.sealed.request_id===body.request_id)
          return r.fulfill({status:409,json:{detail:'同一操作编号的入库意图不一致'}});
        if(state.conflictExisting){
          const existing={...body,excluded_image_ids:['image-24']};
          state.conflictExisting=false;state.sealedRequest=existing;
          state.sealed=intentBody(state,existing);
          return r.fulfill({status:409,json:{detail:'同一操作编号的入库意图不一致'}});
        }
        if(state.sealFailures>0){state.sealFailures-=1;return r.abort('failed')}
        state.sealedRequest=body;state.sealed=intentBody(state,body);
        if(state.loseSealResponse){state.loseSealResponse=false;return r.abort('failed')}
        return r.fulfill({json:state.sealed});
      }
      if(method==='GET'&&bulk.length===2){
        if(state.intentStatus)return r.fulfill({status:state.intentStatus,json:{detail:'intent read unavailable'}});
        return state.sealed&&bulk[1]===state.sealed.request_id
          ?r.fulfill({json:state.sealed}):r.fulfill({status:404,json:{detail:'intent not found'}});
      }
      if(method==='POST'&&bulk.at(-1)==='execute'){
        state.executes+=1;state.executionPolls=0;
        if(state.executeDelay)await new Promise(done=>setTimeout(done,state.executeDelay));
        if(state.loseExecuteResponse){state.loseExecuteResponse=false;return r.abort('failed')}
        return r.fulfill({json:executionView(state,{status:'QUEUED'})});
      }
      if(method==='GET'&&bulk.at(-1)==='execution'){
        if(state.executionStatus)return r.fulfill({status:state.executionStatus,json:{detail:'execution read unavailable'}});
        if(state.hideExecution||state.executes===0)return r.fulfill({status:404,json:{detail:'execution not found'}});
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
  await page.getByRole('dialog').getByRole('button',{name:'检查并确认范围'}).click();
}

test('转池保留冻结排除及原预检身份，丢失响应后只读核验并按原回执撤销',async({page})=>{
  const state=await fixture(page);
  await page.goto(route);
  await page.getByRole('button',{name:'选择筛选内可转池素材'}).click();
  await expect(page.getByText(/可操作 30 张/)).toBeVisible();
  await page.getByRole('button',{name:'下一页'}).click();
  await page.getByRole('checkbox',{name:'选择 候选 24.jpg',exact:true}).uncheck();
  await page.getByRole('button',{name:'已选转负样本池'}).click();
  const dialog=page.getByRole('dialog',{name:'转入负样本池'});
  await dialog.getByText('选择分类',{exact:true}).click();
  await page.getByRole('option',{name:'困难负样本'}).click();
  await dialog.getByRole('button',{name:'预检转池'}).click();
  await expect(dialog).toContainText('可转池 29 张');
  expect(state.transferPreview).toMatchObject({selection_id:selectionId,excluded_image_ids:['image-24'],image_ids:[],review_revision:1});
  await dialog.getByText('确认转池范围及候选框弃用',{exact:true}).click();
  await dialog.getByRole('button',{name:'确认转池',exact:true}).click();
  await expect(dialog).toContainText('执行结果待核验');
  await page.reload();
  await page.getByRole('button',{name:'转池回执'}).click();
  await expect(dialog).toContainText('转池完成');
  expect(state.transferReads).toBeGreaterThan(0);
  expect(state.transferWrites).toEqual([state.transferPreview]);
  await dialog.getByRole('button',{name:'关闭此对话框'}).click();
  await expect(page.getByRole('checkbox',{name:'选择 候选 0.jpg',exact:true})).toBeDisabled();
  await page.getByRole('button',{name:'转池回执'}).click();
  await dialog.getByText('确认按原回执核验撤销资格',{exact:true}).click();
  await dialog.getByRole('button',{name:'撤销转池'}).click();
  await expect(dialog).toContainText('已撤销');
  expect(state.transferUndo).toBe(1);
  await dialog.getByRole('button',{name:'关闭并清除本地记录'}).click();
  await expect(page.getByRole('checkbox',{name:'选择 候选 0.jpg',exact:true})).toBeEnabled();
});

test('冻结→排除→封存→确认→进度→成功，随后可发起第二笔新操作',async({page})=>{
  const state=await fixture(page);
  await page.goto(route);
  await page.getByRole('button',{name:'选择全部筛选结果'}).click();
  await expect(page.getByText(/可操作 30 张/)).toBeVisible();
  await page.getByRole('button',{name:'下一页'}).click();
  await page.getByRole('checkbox',{name:'选择 候选 24.jpg',exact:true}).uncheck();
  await expect(page.locator('.review-selection').getByText(/已选 29 张/).first()).toBeVisible();

  await seal(page,'后台正式入库 29 张');
  await page.screenshot({path:'../test-results/vue-catalog/review-bulk-confirm.png',animations:'disabled'});
  const dialog=page.getByRole('dialog',{name:'审核入库'});
  await expect(eligibilityCount(dialog)).toHaveText('29');
  const firstBody=state.intents[0];
  expect(firstBody.excluded_image_ids).toEqual(['image-24']);
  expect(await readRecord(page)).toMatchObject({request_id:firstBody.request_id,selection_id:selectionId});
  // Sealed range is locked: no checkbox / clear-selection drift.
  await expect(page.getByRole('dialog').getByRole('button',{name:'确认创建后台任务'})).toBeVisible();
  await expect(page.getByRole('dialog').getByRole('button',{name:'放弃预检'})).toBeVisible();

  state.executeDelay=400;
  const confirm=page.getByRole('dialog').getByRole('button',{name:'确认创建后台任务'});
  // Wait for the actual button to finish its transition before exercising
  // the duplicate-event guard on the same confirmation control.
  await confirm.click({trial:true});
  await confirm.evaluate(button=>{button.click();button.click()});
  const preflight=dialog.getByRole('button',{name:'检查并确认范围'});
  await expect(dialog.getByText('后台执行中',{exact:true})).toBeVisible();
  await expect(preflight).toHaveCount(0);
  await expect(page.locator('.review-bulk')).toContainText('未证明');
  await expect(page.locator('.review-bulk')).toContainText('已完成',{timeout:10000});
  await expect(page.locator('.review-bulk')).toContainText('已证明提交 GT 29');
  await expect(preflight).toHaveCount(0);
  await expect(confirm).toHaveCount(0);
  await dialog.getByRole('button',{name:'完成',exact:true}).click();
  expect(state.executes).toBe(1);
  await expect(page.locator('.review-selection').getByText(/已选 0 张/).first()).toBeVisible();

  // Second operation after a terminal result: fresh identity, last result kept.
  await page.getByRole('button',{name:'选择全部筛选结果'}).click();
  await expect(page.getByText(/可操作 1 张/)).toBeVisible();
  await page.getByRole('button',{name:'后台正式入库 1 张'}).click();
  await page.getByRole('dialog').getByRole('button',{name:'检查并确认范围'}).click();
  await expect(eligibilityCount(dialog)).toHaveText('1');
  await page.getByRole('dialog').getByRole('button',{name:'确认创建后台任务'}).click();
  await page.getByRole('dialog').getByRole('button',{name:/^(关闭|完成)$/}).click();
  await expect(page.locator('.review-bulk')).toContainText('已完成',{timeout:10000});
  expect(state.executes).toBe(2);
  expect(state.intents).toHaveLength(2);
  expect(state.intents[1].request_id).not.toBe(firstBody.request_id);
});

test('服务端未封存的中断：重试复用同一 request_id',async({page})=>{
  const state=await fixture(page);
  state.sealFailures=2;
  await page.goto(route);
  await page.getByRole('button',{name:'选择全部筛选结果'}).click();
  await seal(page);
  await expect(page.getByRole('dialog').getByRole('alert')).toBeVisible();
  const first=await readRecord(page);

  await page.reload();
  await expect(page.getByText('上次预检结果未确认，可重试同一操作。')).toBeVisible();
  await page.getByRole('button',{name:'重试上次预检'}).click();
  await expect(page.getByText(/已封存 30 张/)).toBeVisible();
  expect(new Set(state.intents.map(item=>item.request_id)).size).toBe(1);
  expect(state.intents.every(item=>JSON.stringify(item)===JSON.stringify(state.intents[0]))).toBe(true);
});

test('服务端已封存但响应丢失：刷新查到原 intent 并继续，不建第二笔',async({page})=>{
  const state=await fixture(page);
  state.loseSealResponse=true;
  await page.goto(route);
  await page.getByRole('button',{name:'选择全部筛选结果'}).click();
  await seal(page);
  // The lost response is resolved by replaying the exact same request body;
  // the backend's idempotent response proves the persisted intent matches.
  await expect(eligibilityCount(page.getByRole('dialog'))).toHaveText('30');
  expect(state.intents).toHaveLength(2);
  expect(state.intents[1]).toEqual(state.intents[0]);
  expect(state.sealed).not.toBeNull();

  await page.reload();
  await expect(page.getByText(/已封存 30 张/)).toBeVisible();
  await expect(page.getByText('上次预检结果未确认，可重试同一操作。')).toHaveCount(0);
  expect(new Set(state.intents.map(item=>item.request_id)).size).toBe(1);
  await page.locator('.review-bulk').getByRole('button',{name:'查看预检'}).click();
  await page.getByRole('dialog').getByRole('button',{name:'确认创建后台任务'}).click();
  await page.getByRole('dialog').getByRole('button',{name:/^(关闭|完成)$/}).click();
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
  await page.getByRole('dialog').getByRole('button',{name:'检查并确认范围'}).click();
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
  await page.getByRole('dialog').getByRole('button',{name:/^(关闭|完成)$/}).click();
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
  const sealing=page.getByRole('dialog').getByRole('button',{name:'检查并确认范围'}).click();
  await expect.poll(()=>state.sealStarted).toBe(true);
  await expect(page.getByRole('checkbox',{name:'选择 候选 0.jpg',exact:true})).toBeDisabled();
  await expect(page.getByRole('button',{name:'清空选择'})).toBeDisabled();
  state.releaseSeal();
  await sealing;
  await expect(eligibilityCount(page.getByRole('dialog'))).toHaveText('30');
});

test('execute response loss keeps the original task identity and blocks abandon',async({page})=>{
  const state=await fixture(page);
  await page.goto(route);
  await page.getByRole('button',{name:'选择全部筛选结果'}).click();
  await seal(page);
  const requestId=(await readRecord(page)).request_id;
  state.hideExecution=true;
  state.loseExecuteResponse=true;
  await page.getByRole('dialog').getByRole('button',{name:'确认创建后台任务'}).click();
  await expect(page.locator('.review-bulk')).toContainText('后台任务创建结果未确认');
  await expect(page.getByRole('button',{name:'放弃预检'})).toHaveCount(0);
  await expect(page.getByRole('button',{name:'放弃'})).toHaveCount(0);
  expect(state.executes).toBe(1);
  expect(state.intents).toHaveLength(1);
  const record=await readRecord(page);
  expect(record.request_id).toBe(requestId);
  expect(record.execution_attempted).toBe(true);
  expect(await page.evaluate(k=>sessionStorage.getItem(k),key())).not.toBeNull();

  state.hideExecution=false;
  // 1) Both reads fail after refresh: the persisted execute attempt must keep
  // the identity locked.
  state.intentStatus=503;
  state.executionStatus=503;
  await page.reload();
  await expect(page.locator('.review-bulk')).toContainText(/已尝试创建后台任务|后台任务创建结果未确认/);
  await expect(page.getByRole('button',{name:'放弃预检'})).toHaveCount(0);
  const locked=await readRecord(page);
  expect(locked.request_id).toBe(requestId);
  expect(locked.execution_attempted).toBe(true);

  // 2) A seal 404 must not downgrade an attempted execution.
  state.intentStatus=404;
  state.executionStatus=0;
  state.hideExecution=true;
  state.sealed=null;
  await page.reload();
  await expect(page.locator('.review-bulk')).toContainText('已尝试创建后台任务');
  await expect(page.getByRole('button',{name:'放弃预检'})).toHaveCount(0);

  // 3) Restore authoritative reads: the SAME deterministic task completes.
  state.intentStatus=0;
  state.hideExecution=false;
  state.sealed=intentBody(state,{request_id:requestId,selection_id:selectionId,
    review_revision:1,excluded_image_ids:[]});
  state.sealedRequest={request_id:requestId,selection_id:selectionId,review_revision:1,
    excluded_image_ids:[]};
  await page.reload();
  await expect(page.locator('.review-bulk')).toContainText('已完成',{timeout:10000});
  expect(state.executes).toBe(1);
  expect(new Set(state.intents.map(item=>item.request_id)).size).toBe(1);
});

test('seal 409 with a different exclusion set blocks execution and keeps the original intent',async({page})=>{
  const state=await fixture(page);
  state.conflictExisting=true;
  await page.goto(route);
  await page.getByRole('button',{name:'选择全部筛选结果'}).click();
  await expect(page.getByText(/可操作 30 张/)).toBeVisible();
  await page.getByRole('checkbox',{name:'选择 候选 0.jpg',exact:true}).uncheck();
  await expect(page.locator('.review-selection').getByText(/已选 29 张/).first()).toBeVisible();
  await seal(page,'后台正式入库 29 张');
  await expect(page.getByRole('dialog')).toContainText('无法证明与本次选择一致');
  await expect(page.getByRole('dialog')).toContainText('已阻止执行');
  await expect(page.getByRole('dialog')).not.toContainText('预检通过');
  await expect(page.getByRole('dialog').getByRole('button',{name:'确认创建后台任务'})).toHaveCount(0);
  expect(state.executes).toBe(0);
  // The original server intent (excluded image-24) was not replaced.
  expect(state.sealedRequest.excluded_image_ids).toEqual(['image-24']);
  const conflictRecord=await readRecord(page);
  expect(conflictRecord).not.toBeNull();

  // A refresh must NOT turn the conflict into an executable intent.
  await page.reload();
  await expect(page.locator('.review-bulk')).toContainText('预检冲突，已阻止执行');
  await expect(page.getByRole('button',{name:'确认创建后台任务'})).toHaveCount(0);
  expect(state.executes).toBe(0);
  expect(state.sealedRequest.excluded_image_ids).toEqual(['image-24']);
  expect((await readRecord(page)).request_id).toBe(conflictRecord.request_id);

  // Explicit abandon clears only the local identity; a new operation must use
  // a NEW request_id and can then proceed.
  await page.locator('.review-bulk').getByRole('button',{name:'放弃预检'}).click();
  await expect(page.locator('.review-bulk')).toHaveCount(0);
  expect(await readRecord(page)).toBeNull();
  await page.getByRole('button',{name:'选择全部筛选结果'}).click();
  await expect(page.getByText(/可操作 30 张/)).toBeVisible();
  await page.getByRole('checkbox',{name:'选择 候选 0.jpg',exact:true}).uncheck();
  await expect(page.locator('.review-selection').getByText(/已选 29 张/).first()).toBeVisible();
  await seal(page,'后台正式入库 29 张');
  await expect(eligibilityCount(page.getByRole('dialog'))).toHaveText('29');
  const newRecord=await readRecord(page);
  expect(newRecord.request_id).not.toBe(conflictRecord.request_id);
  await page.getByRole('dialog').getByRole('button',{name:'确认创建后台任务'}).click();
  await page.getByRole('dialog').getByRole('button',{name:/^(关闭|完成)$/}).click();
  await expect(page.locator('.review-bulk')).toContainText('已完成',{timeout:10000});
  expect(state.executes).toBe(1);
});
test('unprovable seal replay is unknown state, not a digest conflict',async({page})=>{
  const state=await fixture(page);
  await page.goto(route);
  await page.getByRole('button',{name:'选择全部筛选结果'}).click();
  await seal(page);
  const before=await readRecord(page);
  expect(before).not.toBeNull();
  state.replayStatus=503;
  await page.reload();
  await expect(page.locator('.review-bulk')).toContainText('无法确认原封存状态');
  await expect(page.getByRole('button',{name:'确认创建后台任务'})).toHaveCount(0);
  expect(await page.evaluate(()=>document.body.innerText.includes('预检冲突'))).toBe(false);
  expect((await readRecord(page)).request_id).toBe(before.request_id);
});

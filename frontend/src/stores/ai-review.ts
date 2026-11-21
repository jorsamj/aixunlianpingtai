import {computed,ref,shallowRef} from 'vue';
import {defineStore} from 'pinia';
import {getReviewTask,getReviewPage,getReviewCandidateDetail,getReviewDiagnostics,sendSingleDecision,getDecisionReceipt,freezeReviewSelection,getReviewLabels,getFormalAnnotation,submitFormalDecision,getFormalReceipt,sealBulkFormalIntent,getBulkFormalIntent,startBulkFormalExecution,getBulkFormalExecution,cancelBulkFormalExecution,recoverBulkFormalExecution} from '../api/ai-review';
import type {ReviewAddress,ReviewTask,ReviewPage,ReviewCandidate,ReviewDiagnostics,ReviewFilter,SingleDecision,CompletedDecision,ReviewSelection,BulkFormalIntent,BulkFormalExecution} from '../api/ai-review';

import {bodyDigest,formalBody,formalKey,loadFormalOperation,matchesFormalReceipt,readSelected,withFormalStorage} from './ai-review-formal';
import type {FormalOperation} from './ai-review-formal';
import {draftRecoveryKey} from '../app/ai-draft-recovery';
import {canAdopt,decisionKey,hasUnresolvedAmbiguity,loadDecision,matchesCompletion,validRevision} from './ai-review-decision';
import type {DecisionRecovery} from './ai-review-decision';

type Scope=ReviewAddress&{actorKey:string};
export const useAiReviewStore=defineStore('ai-review-native',()=>{
  const task=shallowRef<ReviewTask>(),page=shallowRef<ReviewPage>(),filter=ref<ReviewFilter>('all');
  const cursors=ref<(string|null)[]>([null]);
  const pageNumber=computed(()=>cursors.value.length);
  const item=shallowRef<ReviewCandidate>(),diagnostics=shallowRef<ReviewDiagnostics>();
  const taskBusy=ref(false),pageBusy=ref(false),itemBusy=ref(false),diagnosticsBusy=ref(false);
  const taskError=ref(''),pageError=ref(''),itemError=ref(''),diagnosticsError=ref('');
  const revision=ref<number>(),decision=shallowRef<DecisionRecovery>();
  const decisionBusy=ref(false),decisionNotice=ref(''),decisionStorageError=ref(''),draftOutstanding=ref(false);
  const formalPlan=shallowRef<{ids:string[];revision:number;boxed:number}>();
  const formalOperation=shallowRef<FormalOperation>();
  const formalBusy=ref(false),formalStorageError=ref(false),formalNotice=ref('');
  let formalRequest:AbortController|undefined;
  // Durable bulk formal GT (C2-B): frozen server selection only, never an
  // expanded ID list in the browser.
  const bulkIntent=shallowRef<BulkFormalIntent>(),bulkExecution=shallowRef<BulkFormalExecution>();
  const bulkBusy=ref(false),bulkNotice=ref(''),bulkError=ref(''),bulkDialog=ref(false);
  const bulkRequestId=ref('');
  const bulkPendingUnknown=ref(false);
  let bulkPoll:number|undefined,bulkAbort:AbortController|undefined;
  const bulkStatus=computed(()=>String(bulkExecution.value?.status||''));
  const bulkTerminal=computed(()=>['SUCCEEDED','PARTIAL_SUCCESS','FAILED','CANCELLED'].includes(bulkStatus.value));
  const bulkRunning=computed(()=>!!bulkExecution.value&&!bulkTerminal.value);
  // A sealed intent locks the selection identity until it is executed or the
  // user explicitly abandons it; otherwise a user could edit the range and
  // then confirm an already sealed (different) operation.
  const bulkSealed=computed(()=>!!bulkIntent.value&&!bulkTerminal.value);
  const formalLocked=computed(()=>formalBusy.value||!!formalPlan.value||!!formalOperation.value||formalStorageError.value||bulkRunning.value||bulkSealed.value);
  const explicitSelection=ref(new Set<string>());
  const frozenSelection=shallowRef<ReviewSelection>();
  const excludedIds=ref(new Set<string>()),membershipId=ref<string>();
  const selectionBusy=ref(false),selectionNotice=ref('');
  let selectionRequest:AbortController|undefined;
  const selectedCount=computed(()=>frozenSelection.value
    ?frozenSelection.value.count-excludedIds.value.size:explicitSelection.value.size);
  const canSelect=computed(()=>task.value?.status.toUpperCase()==='AWAITING_CONFIRMATION'&&!!page.value
    &&!pageBusy.value&&!pageError.value&&!selectionBusy.value&&!page.value.task_error&&!formalLocked.value);
  const canBulkFormal=computed(()=>!!frozenSelection.value&&canSelect.value&&selectedCount.value>0&&!bulkBusy.value);
  let decisionRequest:AbortController|undefined;
  const decisionEligible=computed(()=>task.value?.status.toUpperCase()==='AWAITING_CONFIRMATION'
    &&revision.value!==undefined&&!itemBusy.value&&!itemError.value&&!draftOutstanding.value
    &&!formalLocked.value&&!decisionBusy.value&&!decision.value&&!decisionStorageError.value
    &&item.value?.review_state==='active'&&!item.value.gt_committed&&['success','empty'].includes(item.value.status));
  const decisionOutsidePage=computed(()=>!!item.value&&!!page.value
    &&!page.value.items.some(row=>row.image_id===item.value?.image_id));
  const decisionScope=()=>scope&&item.value?{...scope,imageId:item.value.image_id}:undefined;
  let scope:Scope|undefined, generation=0;
  let taskRead:AbortController|undefined,pageRead:AbortController|undefined,imageRead:AbortController|undefined;
  const message=(cause:unknown)=>cause instanceof Error?cause.message:'读取失败';

  function closeImage(){
    imageRead?.abort();decisionRequest?.abort();
    revision.value=undefined;decision.value=undefined;
    decisionBusy.value=draftOutstanding.value=false;
    decisionNotice.value=decisionStorageError.value='';
    item.value=diagnostics.value=undefined;
    itemBusy.value=diagnosticsBusy.value=false;
    itemError.value=diagnosticsError.value='';
  }
  function reset(){
    generation++;
    formalRequest?.abort();formalPlan.value=formalOperation.value=undefined;
    formalBusy.value=formalStorageError.value=false;formalNotice.value='';
    stopBulkPoll();bulkAbort?.abort();
    bulkIntent.value=bulkExecution.value=undefined;
    bulkBusy.value=false;bulkError.value=bulkNotice.value='';bulkDialog.value=false;bulkRequestId.value='';
    bulkPendingUnknown.value=false;
    clearSelection();
    scope=undefined;
    taskRead?.abort();pageRead?.abort();closeImage();
    task.value=page.value=undefined;
    taskBusy.value=pageBusy.value=false;
    taskError.value=pageError.value='';
    filter.value='all';cursors.value=[null];
  }
  async function readPage(nextFilter:ReviewFilter,nextCursors:(string|null)[],preserveImage=false,decisionSignal?:AbortSignal){
    if(!scope||!task.value)return;
    pageRead?.abort();if(!preserveImage)closeImage();
    const controller=pageRead=new AbortController(),epoch=generation;
    const current=()=>generation===epoch&&!controller.signal.aborted;
    pageBusy.value=!preserveImage;pageError.value='';
    const cancel=()=>controller.abort();
    decisionSignal?.addEventListener('abort',cancel,{once:true});
    try{
      const address=scope;
      const read=async(cursor:string|null)=>{
        const snapshot=frozenSelection.value?.filter===nextFilter?frozenSelection.value:undefined;
        let result:ReviewPage;
        try{
          result=await getReviewPage(address,nextFilter,cursor,controller.signal,snapshot?.selection_id);
        }catch(cause){
          const status=(cause as {httpStatus?:number}).httpStatus;
          if(!snapshot||!current()||(status!==404&&status!==409))throw cause;
          if(snapshot===frozenSelection.value)invalidateSelection();
          return getReviewPage(address,nextFilter,cursor,controller.signal);
        }
        if(current()&&snapshot===frozenSelection.value&&snapshot
          &&(result.selection_stale||result.review_revision!==snapshot.review_revision))invalidateSelection();
        return result;
      };
      let result=await read(nextCursors.at(-1)??null);
      if(preserveImage&&current()&&!result.task_error&&!result.items.length&&nextCursors.length>1){
        nextCursors=nextCursors.slice(0,-1);
        result=await read(nextCursors.at(-1)??null);
      }
      if(current()){
        if(preserveImage&&result.task_error)return false;
        if(!formalLocked.value&&explicitSelection.value.size&&page.value?.review_revision!==result.review_revision)
          invalidateSelection();
        membershipId.value=frozenSelection.value?.selection_id;
        page.value=result;filter.value=nextFilter;cursors.value=nextCursors;
        return true;
      }
    }catch(cause){if(current()&&!preserveImage)pageError.value=message(cause)}
    finally{
      decisionSignal?.removeEventListener('abort',cancel);
      if(current())pageBusy.value=false;
    }
  }
  async function open(next:Scope){
    reset();
    if(!next.actorKey)return;
    scope=next;
    const controller=taskRead=new AbortController(),epoch=generation;
    const current=()=>generation===epoch&&!controller.signal.aborted;
    taskBusy.value=true;
    try{
      const result=await getReviewTask(next,controller.signal);
      if(current()){
        task.value=result;
        try{
          const saved=await loadFormalOperation(next);
          if(current())formalOperation.value=saved;
        }catch(cause){
          if(current()){formalStorageError.value=true;formalNotice.value=message(cause)}
        }
        if(current())await readPage('all',[null]);
        if(current())await restoreBulk(next);
      }
    }catch(cause){if(current())taskError.value=message(cause)}
    finally{if(current())taskBusy.value=false}
  }
  function setFilter(value:ReviewFilter){
    if(formalLocked.value)return;
    if(value!==filter.value)clearSelection();
    return readPage(value,[null]);
  }
  function clearSelection(){
    if(formalLocked.value)return;
    selectionRequest?.abort();selectionBusy.value=false;
    explicitSelection.value.clear();excludedIds.value.clear();
    frozenSelection.value=undefined;membershipId.value=undefined;selectionNotice.value='';
  }
  function invalidateSelection(){
    explicitSelection.value.clear();excludedIds.value.clear();
    frozenSelection.value=undefined;membershipId.value=undefined;
    selectionNotice.value='筛选快照已失效，请重新选择';
  }
  function selectionReason(row:ReviewCandidate){
    const snapshot=frozenSelection.value;
    if(snapshot&&membershipId.value===snapshot.selection_id&&row.selection_member===true)return '';
    if(row.gt_committed)return '已正式入库';
    if(row.review_state==='transferred')return '已转池';
    if(row.review_state==='pending_transfer')return '转池待恢复';
    if(row.review_state!=='active')return '当前候选不可操作';
    if(!['success','empty'].includes(row.status))return '候选生成失败或未生成';
    if(row.accepted===false)return '已拒绝';
    if(row.manual_review_required&&(!row.draft_revision||row.draft?.auto_resolution))return '待人工消歧';
    if(frozenSelection.value&&(membershipId.value!==frozenSelection.value.selection_id||row.selection_member!==true))
      return '不在服务端冻结范围';
    return '';
  }
  function isSelected(row:ReviewCandidate){
    return frozenSelection.value
      ?membershipId.value===frozenSelection.value.selection_id&&row.selection_member===true&&!excludedIds.value.has(row.image_id)
      :explicitSelection.value.has(row.image_id);
  }
  function selectCandidate(row:ReviewCandidate,checked:boolean){
    if(!canSelect.value||selectionReason(row))return;
    if(frozenSelection.value){
      if(checked)excludedIds.value.delete(row.image_id);
      else excludedIds.value.add(row.image_id);
    }else if(checked)explicitSelection.value.add(row.image_id);
    else explicitSelection.value.delete(row.image_id);
  }
  function selectPage(){
    for(const row of page.value?.items??[])selectCandidate(row,true);
  }
  async function freezeSelection(){
    const currentPage=page.value,address=scope;
    if(!address||!currentPage||!canSelect.value||!validRevision(currentPage.review_revision))return;
    const requestedFilter=filter.value,expected=currentPage.review_revision;
    const controller=selectionRequest=new AbortController(),epoch=generation;
    const current=()=>generation===epoch&&!controller.signal.aborted;
    selectionBusy.value=true;selectionNotice.value='';
    try{
      const snapshot=await freezeReviewSelection(address,requestedFilter,expected,controller.signal);
      if(!current())return;
      if(snapshot.filter!==requestedFilter||snapshot.purpose!=='gt'||snapshot.review_revision!==expected
        ||page.value?.review_revision!==expected){
        invalidateSelection();
        return;
      }
      frozenSelection.value=snapshot;
      explicitSelection.value.clear();excludedIds.value.clear();membershipId.value=undefined;
      if(!await readPage(requestedFilter,cursors.value,true,controller.signal)&&current())
        invalidateSelection();
    }catch(cause){
      if(!current())return;
      if((cause as {httpStatus?:number}).httpStatus===409){
        invalidateSelection();
        await readPage(requestedFilter,cursors.value,true,controller.signal);
      }else selectionNotice.value=message(cause);
    }finally{if(current())selectionBusy.value=false}
  }
  function nextPage(){
    if(formalLocked.value)return;
    const next=page.value?.next_cursor;
    if(next!=null)return readPage(filter.value,[...cursors.value,next]);
  }
  function previousPage(){if(!formalLocked.value&&pageNumber.value>1)return readPage(filter.value,cursors.value.slice(0,-1))}
  function reloadPage(){return readPage(filter.value,cursors.value)}
  async function refreshAfterDraft(id:string){
    const epoch=generation;
    await reloadPage();
    if(epoch!==generation||pageError.value)return;
    if(!page.value?.items.length&&pageNumber.value>1)await previousPage();
    if(epoch!==generation||pageError.value)return;
    const row=page.value?.items.find(candidate=>candidate.image_id===id);
    if(row)await inspect(row);
  }
  async function inspect(row:ReviewCandidate){
    if(!scope)return;
    closeImage();item.value=row;
    const address=decisionScope()!;
    try{decision.value=loadDecision(address)}catch{
      decisionStorageError.value='无法读取原审核记录，请核对后再操作。';
    }
    checkDraftOutstanding();
    if(decision.value&&decision.value.status!=='pending')await retryDecisionRefresh();
    else await readDetail(row);
  }
  async function readDetail(row:ReviewCandidate){
    if(!scope)return;
    imageRead?.abort();
    revision.value=undefined;
    itemError.value='';
    diagnosticsBusy.value=false;
    const controller=imageRead=new AbortController(),epoch=generation;
    const current=()=>epoch===generation&&!controller.signal.aborted;
    itemBusy.value=true;
    try{
      const {item:result,review_revision}=await getReviewCandidateDetail(scope,row.image_id,controller.signal);
      if(current()){
        item.value={...result,filename:result.filename||row.filename};
        revision.value=validRevision(review_revision)?review_revision:undefined;
        if(frozenSelection.value&&validRevision(review_revision)
          &&review_revision>frozenSelection.value.review_revision)invalidateSelection();
        return revision.value!==undefined;
      }
    }catch(cause){if(current())itemError.value=message(cause)}
    finally{if(current())itemBusy.value=false}
  }
  function checkDraftOutstanding(){
    const address=decisionScope();
    if(!address)return;
    try{draftOutstanding.value=sessionStorage.getItem(draftRecoveryKey(address))!==null}
    catch{draftOutstanding.value=true}
  }
  function persist(record:DecisionRecovery){
    sessionStorage.setItem(decisionKey(record.scope),JSON.stringify(record));
    decision.value=record;
  }
  async function synchronizeDecision(record:DecisionRecovery,signal:AbortSignal){
    if(!item.value)return;
    const [detail,pageReadOk]=await Promise.all([
      readDetail(item.value),readPage(filter.value,cursors.value,true,signal),
    ]);
    if(signal.aborted)return;
    if(!detail||!pageReadOk){
      decisionNotice.value=record.status==='completed'
        ?'审核已完成，候选或统计刷新失败。':'请重新读取候选，以核对当前审核状态。';
      return;
    }
    sessionStorage.removeItem(decisionKey(record.scope));
    decision.value=undefined;
    decisionNotice.value=record.reason??'';
  }
  async function runDecision(action:(signal:AbortSignal)=>Promise<void>){
    if(decisionBusy.value)return;
    const controller=decisionRequest=new AbortController();
    decisionBusy.value=true;decisionNotice.value='';
    try{await action(controller.signal)}
    catch(cause){if(!controller.signal.aborted)decisionNotice.value=message(cause)}
    finally{if(!controller.signal.aborted)decisionBusy.value=false}
  }
  async function confirmDecision(record:DecisionRecovery,result:CompletedDecision,signal:AbortSignal){
    if(!matchesCompletion(result,record.body))throw new Error('原审核回执与请求身份不一致。');
    const completed:DecisionRecovery={...record,status:'completed',receipt:result};
    persist(completed);
    await synchronizeDecision(completed,signal);
  }
  async function rejectDecision(record:DecisionRecovery,reason:string,signal:AbortSignal){
    const rejected:DecisionRecovery={...record,status:'rejected',reason};
    persist(rejected);
    await synchronizeDecision(rejected,signal);
  }
  async function decide(accepted:boolean,reviewScope:string[]){
    checkDraftOutstanding();
    const address=decisionScope(),row=item.value,expected=revision.value;
    if(!address||!row||expected===undefined||!decisionEligible.value||row.accepted===accepted
      ||(accepted&&!canAdopt(row,reviewScope)))return;
    await runDecision(async signal=>{
      // Detail is returned with a separately-read task revision. A second read after the
      // displayed revision was observed prevents using a stale candidate under a newer revision.
      if(!await readDetail(row)||signal.aborted)return;
      if(revision.value!==expected||JSON.stringify(item.value)!==JSON.stringify(row)){
        decisionNotice.value='候选已变化，请核对当前详情后重新决定。';
        return;
      }
      const requestId=Array.from(crypto.getRandomValues(new Uint8Array(16)),byte=>byte.toString(16).padStart(2,'0')).join('');
      const body:SingleDecision={
        single_candidate:true,request_id:requestId,review_revision:expected,
        commit:false,commit_selected:false,accept_unmentioned:false,reject_unmentioned:false,label_mapping:{},
        decisions:[{image_id:address.imageId,accepted,...(accepted&&row.review_scope_policy==='per_image_required'
          ?{review_scope:[...reviewScope]}:{})}],
      };
      const record:DecisionRecovery={scope:address,body,status:'pending'};
      persist(record);
      let result;
      try{result=await sendSingleDecision(address,body,signal)}
      catch(cause){
        if(signal.aborted)return;
        const status=(cause as {httpStatus?:number}).httpStatus;
        if(status===409||status===400||status===422)
          await rejectDecision(record,status===409?`审核状态已变化，请核对当前候选后重新决定。 ${message(cause)}`:message(cause),signal);
        return;
      }
      if(!signal.aborted&&result.status==='completed')await confirmDecision(record,result,signal);
    });
  }
  async function recoverDecision(){
    const record=decision.value;
    if(record?.status!=='pending')return;
    await runDecision(async signal=>{
      let result;
      try{result=await getDecisionReceipt(record.scope,record.body.request_id,signal)}
      catch(cause){
        if(!signal.aborted&&(cause as {httpStatus?:number}).httpStatus===404)
          throw new Error('暂未查到原审核回执，请稍后核验。');
        throw cause;
      }
      if(signal.aborted)return;
      if(result.request_id!==record.body.request_id)throw new Error('原审核回执与请求身份不一致。');
      if(result.status==='completed')await confirmDecision(record,result.result,signal);
      if(result.status==='rejected')await rejectDecision(record,
        (typeof result.detail==='string'?result.detail:result.detail?.message)||'服务器拒绝了原审核操作。',signal);
    });
  }
  async function retryDecisionRefresh(){
    const record=decision.value;
    if(record&&record.status!=='pending')await runDecision(signal=>synchronizeDecision(record,signal));
  }

  const formalUnavailable=computed(()=>{
    if(task.value?.review_scope_policy!=='task_uniform_legacy')return '仅支持已核实的普通审核任务。';
    if(frozenSelection.value)return '正式入库仅支持显式选择。';
    if(explicitSelection.value.size>100)return '单次最多正式入库 100 张。';
    return '';
  });
  const canPrepareFormal=computed(()=>canSelect.value&&!formalUnavailable.value&&!decisionBusy.value
    &&!draftOutstanding.value&&!decision.value&&explicitSelection.value.size>0&&validRevision(page.value?.review_revision));

  async function runFormal(action:(address:Scope,signal:AbortSignal)=>Promise<void>){
    if(!scope||formalBusy.value)return;
    const address=scope, controller=formalRequest=new AbortController();
    formalBusy.value=true;
    try{await action(address,controller.signal)}
    catch(cause){if(!controller.signal.aborted)formalNotice.value=message(cause)}
    finally{if(!controller.signal.aborted)formalBusy.value=false}
  }
  function hasLocalReviewWork(address:Scope,imageId:string){
    const imageScope={...address,imageId};
    return sessionStorage.getItem(draftRecoveryKey(imageScope))!==null
      ||sessionStorage.getItem(decisionKey(imageScope))!==null;
  }
  async function prepareFormal(){
    if(!canPrepareFormal.value||!page.value)return;
    const ids=[...explicitSelection.value], expected=page.value.review_revision;
    formalNotice.value='';
    await runFormal(async(address,signal)=>{
      if(ids.some(id=>hasLocalReviewWork(address,id)))throw new Error('选中候选包含待核验的草稿或审核决定。');
      const labels=new Set((await getReviewLabels(address.projectId,signal)).map(label=>label.code));
      const selected=await readSelected(ids,id=>getReviewCandidateDetail(address,id,signal));
      if(signal.aborted)return;
      const validBox=(box:NonNullable<ReviewCandidate['boxes']>[number])=>labels.has(box.label??'')
        &&[box.x1,box.y1,box.x2,box.y2].every(Number.isFinite)
        &&box.x1>=0&&box.y1>=0&&box.x2>box.x1&&box.y2>box.y1;
      if(page.value?.review_revision!==expected||selected.some(row=>row.review_revision!==expected)){
        await readPage(filter.value,cursors.value,true,signal);
        if(!signal.aborted)explicitSelection.value.clear();
        throw new Error('审核修订已变化，请重新核对并选择。');
      }
      const invalid=selected.find(({item:row})=>row.gt_committed||row.review_state!=='active'
        ||row.accepted===false||!['success','empty'].includes(row.status)||row.review_scope_policy==='per_image_required'
        ||hasUnresolvedAmbiguity(row)||(row.manual_review_required&&!row.draft?.actor)
        ||!Array.isArray(row.boxes)||!row.boxes.every(validBox));
      if(invalid)throw new Error(`候选 ${invalid.item.filename||invalid.item.image_id} 不具备正式入库资格，整批未提交。`);
      formalPlan.value={ids,revision:expected,boxed:selected.filter(row=>row.item.boxes?.length).length};
    });
  }
  function cancelFormal(){if(!formalBusy.value)formalPlan.value=undefined}
  async function saveFormal(operation:FormalOperation,signal:AbortSignal,first=false){
    const saved=await withFormalStorage(operation.scope,signal,()=>{
      const key=formalKey(operation.scope),raw=localStorage.getItem(key);
      if(first?raw!==null:JSON.parse(raw??'null')?.digest!==operation.digest)return false;
      localStorage.setItem(key,JSON.stringify(operation));
      return true;
    });
    if(signal.aborted)return false;
    if(!saved)throw new Error('正式入库记录已在其他页面变化，请刷新后核验。');
    formalOperation.value=operation;
    return true;
  }
  async function confirmFormal(){
    const plan=formalPlan.value;
    if(!plan||formalOperation.value||formalStorageError.value)return;
    await runFormal(async(address,signal)=>{
      if(page.value?.review_revision!==plan.revision||plan.ids.some(id=>hasLocalReviewWork(address,id))){
        formalPlan.value=undefined;
        throw new Error('候选状态已变化，请重新核验并确认。');
      }
      if(localStorage.getItem(formalKey(address))!==null){
        const saved=await loadFormalOperation(address);
        if(signal.aborted)return;
        formalOperation.value=saved;
        formalPlan.value=undefined;
        formalNotice.value='请先核验原正式入库操作。';
        return;
      }
      const requestId=Array.from(crypto.getRandomValues(new Uint8Array(16)),byte=>byte.toString(16).padStart(2,'0')).join('');
      const body=formalBody(plan.ids,plan.revision,requestId);
      const digest=await bodyDigest(address,body);
      if(signal.aborted)return;
      const operation={scope:address,body,digest};
      if(!await saveFormal(operation,signal,true))return;
      formalPlan.value=undefined;
      formalNotice.value='';
      try{
        const result=await submitFormalDecision(address,body,signal);
        if((result as {status?:string})?.status==='pending')return;
      }catch(cause){
        if(signal.aborted||(cause as {httpStatus?:number}).httpStatus!==409)return;
      }
      if(!signal.aborted)await verifyFormal(operation,signal);
    });
  }
  async function refreshFormal(operation:FormalOperation,signal:AbortSignal){
    const receipt=operation.receipt;
    if(!receipt||receipt.status==='pending')return;
    const ids=operation.body.decisions.map(row=>row.image_id);
    if(receipt.status==='rejected'){
      const checks=await readSelected(ids,async id=>{
        const [candidate,gt]=await Promise.all([
          getReviewCandidateDetail(operation.scope,id,signal),getFormalAnnotation(operation.scope,id,signal),
        ]);
        return {accepted:candidate.item.accepted===true,version:gt.version};
      });
      if(signal.aborted)return;
      const adopted=checks.filter(row=>row.accepted).length;
      const reason=typeof receipt.detail==='string'?receipt.detail:receipt.detail?.message;
      const versions=checks.map(row=>row.version);
      formalNotice.value=`原操作未写入正式 GT。候选已采用 ${adopted}/${ids.length} 张，当前正式 GT 版本 ${Math.min(...versions)}～${Math.max(...versions)}。${reason||''}`;
    }
    const [pageOk,detailOk]=await Promise.all([
      readPage(filter.value,cursors.value,true,signal),item.value?readDetail(item.value):true,
    ]);
    if(signal.aborted)return;
    if(!pageOk||!detailOk){
      if(receipt.status==='completed')formalNotice.value='正式入库完成，候选或统计刷新失败。';
      return;
    }
    await withFormalStorage(operation.scope,signal,()=>{
      const key=formalKey(operation.scope);
      const saved=JSON.parse(localStorage.getItem(key)??'null') as FormalOperation|null;
      if(saved?.digest===operation.digest)localStorage.removeItem(key);
    });
    if(signal.aborted)return;
    formalOperation.value=undefined;
    if(receipt.status==='completed'){
      for(const id of ids)explicitSelection.value.delete(id);
      formalNotice.value=`正式入库完成 · ${ids.length} 张`;
    }else{
      explicitSelection.value.clear();
    }
  }
  async function verifyFormal(operation:FormalOperation,signal:AbortSignal){
    if(operation.receipt)return refreshFormal(operation,signal);
    let receipt;
    try{receipt=await getFormalReceipt(operation.scope,operation.body.request_id,signal)}
    catch(cause){
      if(!signal.aborted&&(cause as {httpStatus?:number}).httpStatus===404)
        formalNotice.value='暂未查到原回执，正式入库结果待核验。';
      else throw cause;
      return;
    }
    if(signal.aborted||receipt.status==='pending')return;
    if(!matchesFormalReceipt(operation,receipt))throw new Error('原回执未能证明本次操作的完整选中范围。');
    const confirmed={...operation,receipt};
    if(await saveFormal(confirmed,signal))await refreshFormal(confirmed,signal);
  }
  async function recoverFormal(){
    const operation=formalOperation.value;
    if(operation){
      formalNotice.value='';
      await runFormal((_,signal)=>verifyFormal(operation,signal));
    }
  }

  // ---- C2-B durable bulk formal GT (Vue wiring) ----
  function bulkFormalKey(address:Scope){
    return 'ai-review-bulk:v1:'+JSON.stringify([address.actorKey,address.projectId,address.taskId]);
  }
  type BulkRecord={request_id:string;selection_id:string;review_revision:number;excluded_image_ids:string[]};
  function readBulkRecord(address:Scope):BulkRecord|null{
    try{
      const raw=JSON.parse(sessionStorage.getItem(bulkFormalKey(address))??'null') as Partial<BulkRecord>|null;
      if(raw&&typeof raw.request_id==='string'&&typeof raw.selection_id==='string'
        &&Number.isInteger(raw.review_revision)&&Array.isArray(raw.excluded_image_ids)
        &&raw.excluded_image_ids.every(id=>typeof id==='string'))
        return raw as BulkRecord;
    }catch{/* storage unavailable or corrupt: degrade to no record */}
    return null;
  }
  function writeBulkRecord(address:Scope,record:BulkRecord){
    try{sessionStorage.setItem(bulkFormalKey(address),JSON.stringify(record))}catch{
      bulkNotice.value='浏览器无法保存本次操作身份，刷新后需重新预检。';
    }
  }
  function clearBulkRecord(address:Scope){
    try{sessionStorage.removeItem(bulkFormalKey(address))}catch{}
  }
  function stopBulkPoll(){if(bulkPoll!==undefined){window.clearInterval(bulkPoll);bulkPoll=undefined}}
  function startBulkPoll(){
    if(bulkPoll!==undefined||!scope||!bulkRequestId.value)return;
    bulkPoll=window.setInterval(()=>{void pollBulkFormal()},2500);
  }
  async function settleBulkFormal(address:Scope){
    stopBulkPoll();
    if(scope!==address)return;
    if(!bulkTerminal.value)return;
    // Terminal execution: release the sealed identity so a NEW operation can
    // start with a NEW request_id. The terminal execution stays visible.
    bulkIntent.value=undefined;bulkRequestId.value='';bulkPendingUnknown.value=false;
    clearBulkRecord(address);
    if(bulkStatus.value==='SUCCEEDED'){
      clearSelection();
      await readPage(filter.value,[null]);
    }else if(!pageError.value){
      await readPage(filter.value,cursors.value,true);
    }
  }
  async function readBulkExecution(address:Scope,signal:AbortSignal){
    const view=await getBulkFormalExecution(address,bulkRequestId.value,signal);
    if(scope===address)bulkExecution.value=view;
    return view;
  }
  async function pollBulkFormal(){
    const address=scope;
    if(!address||!bulkRequestId.value||bulkBusy.value||bulkTerminal.value)return;
    try{
      await readBulkExecution(address,new AbortController().signal);
      if(bulkTerminal.value)await settleBulkFormal(address);
    }catch{
      // Polling failures are not terminal; the next tick retries. The user can
      // always press 刷新, and the execution task remains the single truth.
    }
  }
  async function restoreBulk(address:Scope){
    const record=readBulkRecord(address);
    const requestId=record?.request_id??'';
    if(!/^[a-z0-9]{12,80}$/i.test(requestId))return;
    bulkRequestId.value=requestId;
    try{
      const intent=await getBulkFormalIntent(address,requestId,new AbortController().signal);
      if(scope!==address)return;
      if(intent.project_id!==address.projectId||intent.task_id!==address.taskId
        ||intent.request_id!==requestId||intent.selection_id!==record?.selection_id
        ||intent.review_revision!==record?.review_revision)
        throw new Error('后台正式入库记录与当前任务或范围不一致');
      bulkIntent.value=intent;bulkPendingUnknown.value=false;
    }catch(cause){
      if(scope!==address)return;
      if((cause as {httpStatus?:number}).httpStatus===404){
        // The seal may have reached the server while its response was lost.
        // Keep the SAME request_id; only an explicit abandon may replace it.
        bulkPendingUnknown.value=true;
        bulkNotice.value='上次预检结果未确认，可重试同一操作。';
        return;
      }
      bulkError.value=message(cause);
      return;
    }
    try{
      const view=await readBulkExecution(address,new AbortController().signal);
      if(scope!==address)return;
      if(bulkTerminal.value)await settleBulkFormal(address);
      else startBulkPoll();
      return view;
    }catch(cause){
      if((cause as {httpStatus?:number}).httpStatus!==404&&scope===address)
        bulkError.value=message(cause);
    }
  }
  function openBulkFormal(){
    if(!bulkIntent.value&&!bulkExecution.value&&!bulkPendingUnknown.value&&!bulkRequestId.value&&!canBulkFormal.value)return;
    bulkDialog.value=true;bulkError.value='';bulkNotice.value='';
  }
  function closeBulkFormal(){if(!bulkBusy.value)bulkDialog.value=false}
  async function runBulk(action:(address:Scope,signal:AbortSignal)=>Promise<void>){
    if(!scope||bulkBusy.value)return;
    const address=scope;
    bulkAbort?.abort();
    const controller=bulkAbort=new AbortController();
    bulkBusy.value=true;bulkError.value='';bulkNotice.value='';
    try{await action(address,controller.signal)}
    catch(cause){if(!controller.signal.aborted)bulkError.value=message(cause)}
    finally{if(!controller.signal.aborted)bulkBusy.value=false}
  }
  function newBulkRequestId(){
    const cryptoObject=globalThis.crypto;
    if(cryptoObject?.getRandomValues){
      return Array.from(cryptoObject.getRandomValues(new Uint8Array(16)),
        byte=>byte.toString(16).padStart(2,'0')).join('');
    }
    // HTTP (non-secure) fallback: identity only needs uniqueness, never secrecy.
    return Array.from({length:32},()=>Math.floor(Math.random()*16).toString(16)).join('');
  }
  async function preflightBulkFormal(){
    if(bulkIntent.value||bulkExecution.value)return;
    await runBulk(async(address,signal)=>{
      const stored=readBulkRecord(address);
      const snapshot=frozenSelection.value;
      let body:{request_id:string;selection_id:string;review_revision:number;excluded_image_ids:string[]};
      if(snapshot){
        const expected=page.value?.review_revision;
        if(expected===undefined||snapshot.review_revision!==expected||snapshot.purpose!=='gt')
          throw new Error('筛选快照已变化，请重新冻结');
        body={request_id:bulkRequestId.value||newBulkRequestId(),
          selection_id:snapshot.selection_id,review_revision:snapshot.review_revision,
          excluded_image_ids:[...excludedIds.value].sort()};
        if(stored&&stored.request_id===body.request_id
          &&(stored.selection_id!==body.selection_id||stored.review_revision!==body.review_revision
            ||JSON.stringify(stored.excluded_image_ids)!==JSON.stringify(body.excluded_image_ids)))
          throw new Error('原预检请求内容与当前选择不一致，请先放弃原预检再重新选择');
        if(stored&&stored.request_id!==body.request_id)
          throw new Error('浏览器仍有未完成的预检操作，请先放弃原预检');
      }else if(stored&&stored.request_id===bulkRequestId.value){
        // Refreshed page: replay the persisted identity instead of inventing a
        // second operation for a seal whose outcome is still unknown.
        body={request_id:stored.request_id,selection_id:stored.selection_id,
          review_revision:stored.review_revision,excluded_image_ids:stored.excluded_image_ids};
      }else{
        throw new Error('请先冻结服务端筛选范围');
      }
      if(!bulkRequestId.value)bulkRequestId.value=body.request_id;
      // Persist BEFORE the request: a lost response must never create a second
      // operation on retry.
      writeBulkRecord(address,body);
      const intent=await sealBulkFormalIntent(address,body,signal);
      if(signal.aborted)return;
      if(intent.request_id!==body.request_id||intent.project_id!==address.projectId
        ||intent.task_id!==address.taskId||intent.selection_id!==body.selection_id
        ||intent.review_revision!==body.review_revision)
        throw new Error('封存回执与所选范围不一致');
      bulkIntent.value=intent;bulkPendingUnknown.value=false;
      bulkNotice.value=`预检通过：可入库 ${intent.count} 张，已排除 ${intent.excluded_count} 张。`;
    });
  }
  function abandonBulkFormal(){
    if(bulkBusy.value||bulkRunning.value)return;
    const address=scope;
    stopBulkPoll();bulkAbort?.abort();
    bulkIntent.value=bulkExecution.value=undefined;bulkRequestId.value='';
    bulkPendingUnknown.value=false;bulkNotice.value='';bulkError.value='';bulkDialog.value=false;
    if(address)clearBulkRecord(address);
  }
  async function confirmBulkFormal(){
    if(!bulkIntent.value||bulkExecution.value)return;
    await runBulk(async(address,signal)=>{
      const view=await startBulkFormalExecution(address,bulkRequestId.value,signal);
      if(signal.aborted)return;
      if(view.operation_id!==bulkIntent.value?.operation_id||view.total_images!==bulkIntent.value?.count)
        throw new Error('后台任务身份与封存意图不一致');
      bulkExecution.value=view;
      if(!bulkTerminal.value)startBulkPoll();
    });
  }
  async function refreshBulkFormal(){
    if(!bulkRequestId.value)return;
    await runBulk(async(address,signal)=>{
      const view=await readBulkExecution(address,signal);
      if(view.blocked&&view.manual_review_required)bulkNotice.value='任务已阻断，需核验后人工恢复。';
      if(bulkTerminal.value)await settleBulkFormal(address);
      else startBulkPoll();
    });
  }
  async function cancelBulkFormal(){
    if(!bulkRequestId.value||!bulkExecution.value||bulkTerminal.value)return;
    await runBulk(async(address,signal)=>{
      bulkExecution.value=await cancelBulkFormalExecution(address,bulkRequestId.value,signal);
      startBulkPoll();
    });
  }
  async function recoverBulkFormal(){
    if(!bulkRequestId.value)return;
    await runBulk(async(address,signal)=>{
      bulkExecution.value=await recoverBulkFormalExecution(address,bulkRequestId.value,signal);
      bulkNotice.value='已重新排队，等待 Worker 按持久证据复核。';
      startBulkPoll();
    });
  }

  async function readDiagnostics(){
    if(!scope||!item.value||!imageRead||diagnosticsBusy.value)return;
    const {signal}=imageRead,epoch=generation;
    const current=()=>epoch===generation&&!signal.aborted;
    diagnosticsBusy.value=true;diagnosticsError.value='';
    try{
      const result=await getReviewDiagnostics(scope,item.value.image_id,signal);
      if(current())diagnostics.value=result;
    }catch(cause){if(current())diagnosticsError.value=message(cause)}
    finally{if(current())diagnosticsBusy.value=false}
  }
  return {task,page,filter,pageNumber,item,diagnostics,taskBusy,pageBusy,itemBusy,diagnosticsBusy,
    taskError,pageError,itemError,diagnosticsError,open,reset,setFilter,nextPage,previousPage,reloadPage,
    inspect,closeImage,readDiagnostics,refreshAfterDraft,revision,decision,decisionBusy,decisionNotice,
    decisionEligible,decisionStorageError,draftOutstanding,decisionOutsidePage,checkDraftOutstanding,
    decide,recoverDecision,retryDecisionRefresh,selectedCount,canSelect,frozenSelection,
    selectionBusy,selectionNotice,selectionReason,isSelected,selectCandidate,selectPage,freezeSelection,clearSelection,
    formalPlan,formalOperation,formalBusy,formalLocked,formalNotice,formalUnavailable,canPrepareFormal,
    prepareFormal,cancelFormal,confirmFormal,recoverFormal,
    bulkIntent,bulkExecution,bulkBusy,bulkNotice,bulkError,bulkDialog,bulkStatus,bulkTerminal,bulkRunning,
    bulkSealed,bulkPendingUnknown,
    canBulkFormal,openBulkFormal,closeBulkFormal,preflightBulkFormal,confirmBulkFormal,refreshBulkFormal,
    cancelBulkFormal,recoverBulkFormal,abandonBulkFormal};
});

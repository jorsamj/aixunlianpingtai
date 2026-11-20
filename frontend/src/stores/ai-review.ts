import {computed,ref,shallowRef} from 'vue';
import {defineStore} from 'pinia';
import {getReviewTask,getReviewPage,getReviewCandidateDetail,getReviewDiagnostics,sendSingleDecision,getDecisionReceipt,freezeReviewSelection} from '../api/ai-review';
import type {ReviewAddress,ReviewTask,ReviewPage,ReviewCandidate,ReviewDiagnostics,ReviewFilter,SingleDecision,CompletedDecision,ReviewSelection} from '../api/ai-review';

import {draftRecoveryKey} from '../app/ai-draft-recovery';
import {canAdopt,decisionKey,loadDecision,matchesCompletion,validRevision} from './ai-review-decision';
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
  const explicitSelection=ref(new Set<string>());
  const frozenSelection=shallowRef<ReviewSelection>();
  const excludedIds=ref(new Set<string>()),membershipId=ref<string>();
  const selectionBusy=ref(false),selectionNotice=ref('');
  let selectionRequest:AbortController|undefined;
  const selectedCount=computed(()=>frozenSelection.value
    ?frozenSelection.value.count-excludedIds.value.size:explicitSelection.value.size);
  const canSelect=computed(()=>task.value?.status.toUpperCase()==='AWAITING_CONFIRMATION'&&!!page.value
    &&!pageBusy.value&&!pageError.value&&!selectionBusy.value&&!page.value.task_error);
  let decisionRequest:AbortController|undefined;
  const decisionEligible=computed(()=>task.value?.status.toUpperCase()==='AWAITING_CONFIRMATION'
    &&revision.value!==undefined&&!itemBusy.value&&!itemError.value&&!draftOutstanding.value
    &&!decisionBusy.value&&!decision.value&&!decisionStorageError.value
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
    generation++;clearSelection();
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
        if(explicitSelection.value.size&&page.value?.review_revision!==result.review_revision)
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
      if(current()){task.value=result;await readPage('all',[null])}
    }catch(cause){if(current())taskError.value=message(cause)}
    finally{if(current())taskBusy.value=false}
  }
  function setFilter(value:ReviewFilter){
    if(value!==filter.value)clearSelection();
    return readPage(value,[null]);
  }
  function clearSelection(){
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
    const next=page.value?.next_cursor;
    if(next!=null)return readPage(filter.value,[...cursors.value,next]);
  }
  function previousPage(){if(pageNumber.value>1)return readPage(filter.value,cursors.value.slice(0,-1))}
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
    selectionBusy,selectionNotice,selectionReason,isSelected,selectCandidate,selectPage,freezeSelection,clearSelection};
});

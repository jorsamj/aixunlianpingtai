import {computed,ref,shallowRef} from 'vue';
import {defineStore} from 'pinia';
import {getReviewTask,getReviewPage,getReviewCandidateDetail,getReviewDiagnostics,sendSingleDecision,getDecisionReceipt} from '../api/ai-review';
import type {ReviewAddress,ReviewTask,ReviewPage,ReviewCandidate,ReviewDiagnostics,ReviewFilter,SingleDecision,CompletedDecision} from '../api/ai-review';

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
    generation++;
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
      let result=await getReviewPage(scope,nextFilter,nextCursors.at(-1)??null,controller.signal);
      if(preserveImage&&current()&&!result.task_error&&!result.items.length&&nextCursors.length>1){
        nextCursors=nextCursors.slice(0,-1);
        result=await getReviewPage(scope,nextFilter,nextCursors.at(-1)??null,controller.signal);
      }
      if(current()){
        if(preserveImage&&result.task_error)return false;
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
  function setFilter(value:ReviewFilter){return readPage(value,[null])}
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
    decide,recoverDecision,retryDecisionRefresh};
});

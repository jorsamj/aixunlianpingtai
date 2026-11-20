import {computed,ref,shallowRef} from 'vue';
import {defineStore} from 'pinia';
import {getReviewTask,getReviewPage,getReviewCandidate,getReviewDiagnostics} from '../api/ai-review';
import type {ReviewAddress,ReviewTask,ReviewPage,ReviewCandidate,ReviewDiagnostics,ReviewFilter} from '../api/ai-review';

type Scope=ReviewAddress&{actorKey:string};
export const useAiReviewStore=defineStore('ai-review-native',()=>{
  const task=shallowRef<ReviewTask>(),page=shallowRef<ReviewPage>(),filter=ref<ReviewFilter>('all');
  const cursors=ref<(string|null)[]>([null]);
  const pageNumber=computed(()=>cursors.value.length);
  const item=shallowRef<ReviewCandidate>(),diagnostics=shallowRef<ReviewDiagnostics>();
  const taskBusy=ref(false),pageBusy=ref(false),itemBusy=ref(false),diagnosticsBusy=ref(false);
  const taskError=ref(''),pageError=ref(''),itemError=ref(''),diagnosticsError=ref('');
  let scope:Scope|undefined, generation=0;
  let taskRead:AbortController|undefined,pageRead:AbortController|undefined,imageRead:AbortController|undefined;
  const message=(cause:unknown)=>cause instanceof Error?cause.message:'读取失败';

  function closeImage(){
    imageRead?.abort();
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
  async function readPage(nextFilter:ReviewFilter,nextCursors:(string|null)[]){
    if(!scope||!task.value)return;
    pageRead?.abort();closeImage();
    const controller=pageRead=new AbortController(),epoch=generation;
    const current=()=>generation===epoch&&!controller.signal.aborted;
    pageBusy.value=true;pageError.value='';
    try{
      const result=await getReviewPage(scope,nextFilter,nextCursors.at(-1)??null,controller.signal);
      if(current()){page.value=result;filter.value=nextFilter;cursors.value=nextCursors}
    }catch(cause){if(current())pageError.value=message(cause)}
    finally{if(current())pageBusy.value=false}
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
    const controller=imageRead=new AbortController(),epoch=generation;
    const current=()=>epoch===generation&&!controller.signal.aborted;
    itemBusy.value=true;
    try{
      const result=await getReviewCandidate(scope,row.image_id,controller.signal);
      if(current())item.value={...row,...result,filename:result.filename||row.filename};
    }catch(cause){if(current())itemError.value=message(cause)}
    finally{if(current())itemBusy.value=false}
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
    inspect,closeImage,readDiagnostics,refreshAfterDraft};
});

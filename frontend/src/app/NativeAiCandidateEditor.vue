<script setup lang="ts">
import {computed,onBeforeUnmount,onMounted,ref,shallowRef} from 'vue';
import AnnotationEditor from '../components/AnnotationEditor.vue';
import type {AiEditorBox,AiEditorContext,AiEditorSnapshot} from '../types/ai-editor';
import {getReviewCandidate,getReviewLabels,saveReviewDraft} from '../api/ai-review';
import type {CandidateDraft,ReviewAddress,ReviewCandidate,ReviewLabel} from '../api/ai-review';
import {createAnnotoriousEditor} from '../../../static/modules/annotorious-editor.js';
import {withLegacyBoxIdentities} from '../../../static/modules/annotation-geometry-adapter.js';

const props=defineProps<{scope:ReviewAddress;actorKey:string;imageId:string}>();
const emit=defineEmits<{close:[];saved:[imageId:string]}>();
const item=shallowRef<ReviewCandidate>(),labels=shallowRef<ReviewLabel[]>([]),imageLoadEpoch=ref(0);
const boxes=shallowRef<AiEditorBox[]>([]),baseline=shallowRef<AiEditorBox[]>([]);
const activeId=ref<string|null>(null),labelCode=ref(''),filterCode=ref('');
const view=ref({mode:'draw',visible:true,scale:1});
const loading=ref(false),saving=ref(false),suspended=ref(false),conflict=ref(false);
const refreshRequired=ref(false),error=ref(''),status=ref('');
const outstanding=shallowRef<CandidateDraft>();
const history:AiEditorBox[][]=[],redo:AiEditorBox[][]=[];
const dirty=computed(()=>JSON.stringify(boxes.value)!==JSON.stringify(baseline.value));
const locked=computed(()=>loading.value||saving.value||suspended.value||!!outstanding.value||refreshRequired.value);
const storageKey='ai-candidate-draft:v1:'+JSON.stringify([props.actorKey,props.scope.projectId,props.scope.taskId,props.imageId]);
const url='/api/v61/projects/'+encodeURIComponent(props.scope.projectId)+'/materials/'+encodeURIComponent(props.imageId)+'/content';
let apiRead:AbortController|undefined, mountController:AbortController|undefined,dead=false;
type Kernel=Awaited<ReturnType<typeof createAnnotoriousEditor>>;
let kernel:Kernel|undefined;

function message(cause:unknown){return cause instanceof Error?cause.message:'读取或保存失败'}
function sync(){
  kernel?.sync({label:labels.value.find(label=>label.code===labelCode.value)||null,locked:locked.value});
}
function loadBoxes(result:ReviewCandidate,working?:AiEditorBox[]){
  item.value=result;
  const normalized=(result.boxes||[]).map(box=>({...box,label:box.label||''}));
  baseline.value=withLegacyBoxIdentities(normalized,{imageId:props.imageId});
  boxes.value=working??baseline.value;
  activeId.value=null;history.length=redo.length=0;
}
function forget(){
  sessionStorage.removeItem(storageKey);
  outstanding.value=undefined;
}
function editable(candidate:ReviewCandidate){
  return ['success','empty'].includes(candidate.status)&&candidate.review_state==='active'&&!candidate.gt_committed;
}
async function load(restorePending=true){
  if(loading.value||suspended.value)return;
  const controller=apiRead=new AbortController(),current=()=>!dead&&!controller.signal.aborted;
  const pending=restorePending?outstanding.value:undefined;
  loading.value=true;error.value='';sync();
  try{
    const [candidate,catalog]=await Promise.all([
      getReviewCandidate(props.scope,props.imageId,controller.signal),getReviewLabels(props.scope.projectId,controller.signal),
    ]);
    if(!current())return false;
    labels.value=catalog;
    if(!catalog.some(label=>label.code===labelCode.value))labelCode.value=catalog[0]?.code||'';
    loadBoxes(candidate,pending?.boxes);
    conflict.value=!editable(candidate);
    status.value=pending?'原草稿保存结果待核验。':'草稿版本 '+candidate.draft_revision;
    if(conflict.value)error.value='当前候选已不可编辑，请核对重新读取的权威草稿。';
    refreshRequired.value=false;
    return true;
  }catch(cause){if(current())error.value=message(cause);return false}
  finally{if(!dead){loading.value=false;sync()}}
}
function update(next:AiEditorBox[]){
  if(locked.value||conflict.value||dead)return;
  if(next.length>300){error.value='单图最多保存 300 个候选框。';return}
  if(JSON.stringify(next)===JSON.stringify(boxes.value))return;
  history.push(boxes.value);
  if(history.length>50)history.shift();
  redo.length=0;
  boxes.value=next.map(box=>({...box,source:'ai_candidate_reviewed'}));
  error.value='';
}
function undo(){
  if(locked.value||conflict.value)return;
  kernel?.flush();
  const previous=history.pop();if(!previous)return;
  redo.push(boxes.value);boxes.value=previous;activeId.value=null;sync();
}
function redoEdit(){
  if(locked.value||conflict.value)return;
  const next=redo.pop();if(!next)return;
  history.push(boxes.value);boxes.value=next;activeId.value=null;sync();
}
function chooseLabel(code:string){labelCode.value=code;sync()}
function selectBox(index:number){
  const id=boxes.value[index]?.id;
  if(id==null||!kernel||locked.value||conflict.value)return false;
  if(view.value.mode==='pan')kernel.setMode('select');
  return kernel.select(id);
}
function canLeave(){
  if(saving.value)return false;
  kernel?.flush();
  return !dirty.value||confirm(outstanding.value
    ?'原保存结果待核验。离开后可在本标签页重新打开此图，核验同一请求。确定离开？'
    :'候选修改尚未保存，确定放弃修改？');
}
function suspend(value:boolean){
  suspended.value=value;
  if(value)apiRead?.abort();
  else if(!item.value)void load();
  sync();
}
function requestId(){
  return 'draft-'+Array.from(crypto.getRandomValues(new Uint8Array(16)),byte=>byte.toString(16).padStart(2,'0')).join('');
}
async function save(){
  const candidate=item.value;
  if(!candidate||dead||loading.value||saving.value||suspended.value||refreshRequired.value||conflict.value)return;
  kernel?.flush();
  const pending=outstanding.value;
  if(!pending&&(!dirty.value||!Number.isInteger(candidate.draft_revision)))return;
  let draft:CandidateDraft;
  try{
    draft=pending??{boxes:boxes.value,revision:candidate.draft_revision!,request_id:requestId(),
      source_content_sha256:candidate.source_content_sha256||candidate.content_sha256};
    if(!pending)sessionStorage.setItem(storageKey,JSON.stringify(draft));
    outstanding.value=draft;
  }catch(cause){error.value='无法记录草稿请求：'+message(cause);return}
  const controller=apiRead=new AbortController(),current=()=>!dead&&!controller.signal.aborted;
  saving.value=true;error.value='';sync();
  try{
    const receipt=await saveReviewDraft(props.scope,props.imageId,draft,controller.signal);
    if(!current())return;
    forget();
    refreshRequired.value=true;
    const latest=await getReviewCandidate(props.scope,props.imageId,controller.signal);
    if(!current())return;
    if(latest.draft_revision!==receipt.revision){
      conflict.value=true;
      error.value='原保存已确认，但远端草稿版本随后变化。请重新载入核对。';
    }else{
      loadBoxes(latest);
      status.value='已保存草稿 · 版本 '+latest.draft_revision;
      conflict.value=!editable(latest);
    }
    refreshRequired.value=false;
    emit('saved',props.imageId);
  }catch(cause){
    if(dead)return;
    const code=(cause as {httpStatus?:number})?.httpStatus;
    if(refreshRequired.value)error.value='草稿已保存，最新草稿读取失败。请重新载入。';
    else if(code===409){
      if(!pending)forget();
      conflict.value=true;
      error.value='草稿版本、任务或源素材已变化：'+message(cause)+'。请重新载入核对。';
    }else if([400,403,404,422].includes(code??0)){
      if(pending){conflict.value=true;error.value='原请求暂无法核验，请重新载入权威草稿：'+message(cause)}
      else{forget();error.value=message(cause)}
    }else error.value='保存结果待核验，请用原请求编号重试。';
  }finally{if(!dead){saving.value=false;sync()}}
}
async function reload(){
  if(saving.value||loading.value||suspended.value)return;
  if(outstanding.value&&!conflict.value)return;
  kernel?.flush();
  if((dirty.value||outstanding.value)&&!confirm('重新载入将采用服务端当前草稿，确定继续？'))return;
  // Read the current authority before dismissing an inconclusive recovery packet.
  if(await load(false)){
    imageLoadEpoch.value++;
    if(outstanding.value)forget();
    sync();
    emit('saved',props.imageId);
  }
}
const context:AiEditorContext={
  async mount(refs){
    const candidate=item.value;
    if(!candidate||refs.image.naturalWidth!==candidate.width||refs.image.naturalHeight!==candidate.height)
      throw new Error('原图方向或尺寸与服务端候选不一致，已阻止编辑。');
    mountController?.abort();
    const controller=mountController=new AbortController();
    const result=await createAnnotoriousEditor({...refs,signal:controller.signal,getBoxes:()=>boxes.value,
      getLabels:()=>labels.value,getLabel:()=>labels.value.find(label=>label.code===labelCode.value)||null,
      isActive:()=>!dead&&!suspended.value&&!conflict.value,
      onCommit:update,onSelect:id=>{activeId.value=id},onSave:()=>void save(),onUndo:undo,onRedo:redoEdit,
      onChooseLabel:label=>chooseLabel(label.code),onError:cause=>{error.value=message(cause)},
      onViewportChange:({scale})=>{view.value.scale=scale},onModeChange:mode=>{view.value.mode=mode},
      onVisibilityChange:visible=>{view.value.visible=visible},
    });
    if(dead||controller.signal.aborted){result.destroy();throw new Error('候选编辑已关闭。')}
    kernel=result;view.value={...result.snapshot()};sync();
    return result;
  },
  release(handle){
    if(handle&&handle!==kernel){(handle as Kernel).destroy();return}
    mountController?.abort();kernel?.destroy();kernel=undefined;
  },
  actions:{
    mode:value=>kernel?.setMode(value),label:chooseLabel,
    select:selectBox,
    reclass:(index,code)=>{if(selectBox(index))kernel?.reclassSelected(code)},
    remove:index=>{if(selectBox(index))kernel?.deleteSelected()},
    undo,redo:redoEdit,visibility:()=>kernel?.setVisibility(!view.value.visible),
    filter:code=>{filterCode.value=code;kernel?.setClassFilter(code?[code]:null)},
    zoom:delta=>kernel?.zoom(delta),fit:()=>kernel?.fit(),resetZoom:()=>kernel?.resetZoom(),
    save,reload,cancel:()=>{if(canLeave())emit('close')},
  },
};
const snapshot=computed<AiEditorSnapshot|undefined>(()=>{
  const row=item.value;if(!row)return;
  const index=boxes.value.findIndex(box=>String(box.id)===activeId.value);
  return {imageId:props.imageId,url,filename:(row.filename||props.imageId).split(/[\\/]/).at(-1)||props.imageId,
    width:row.width||0,height:row.height||0,boxes:boxes.value,labels:labels.value,activeBox:index<0?null:index,
    labelCode:labelCode.value,filterCode:filterCode.value,dirty:dirty.value,saving:saving.value,
    pending:locked.value,editingDisabled:conflict.value,retryPending:!!outstanding.value&&!suspended.value&&!loading.value&&!conflict.value,
    saveDisabled:conflict.value||refreshRequired.value||(!dirty.value&&!outstanding.value),
    error:error.value,status:status.value,revision:row.draft_revision,view:view.value,conflict:row.manual_review_required};
});
onMounted(()=>{
  try{
    const stored=sessionStorage.getItem(storageKey);
    if(stored)outstanding.value=JSON.parse(stored);
  }catch(cause){error.value=message(cause);return}
  void load();
});
onBeforeUnmount(()=>{dead=true;apiRead?.abort();context.release()});
defineExpose({canLeave,suspend,hasUnresolved:()=>dirty.value||saving.value||!!outstanding.value});
</script>

<template>
 <div class="native-review-editor">
  <AnnotationEditor v-if="snapshot" :key="imageLoadEpoch" :context="context" :snapshot="snapshot" native />
  <section v-else aria-label="候选编辑" class="editor-opening">
   <p v-if="error" role="alert">{{ error }}</p>
   <p v-else role="status">正在读取候选与标签…</p>
   <el-button v-if="error" @click="load()">重试</el-button>
   <el-button @click="emit('close')">返回审核列表</el-button>
  </section>
 </div>
</template>

<style scoped>
.native-review-editor{height:calc(100dvh - 132px);min-height:500px;background:white;border:1px solid #ddd;border-radius:8px;overflow:hidden}
.editor-opening{padding:20px}
.native-review-editor :deep(.editor-canvas){background:#ededed}
.native-review-editor :deep(.editor-world img){image-orientation:from-image}
.native-review-editor :deep(.editor-tools label){flex-wrap:wrap}
@media(max-width:900px){.native-review-editor{height:calc(100dvh - 120px)}}
</style>

<script setup lang="ts">
import {computed,onBeforeUnmount,onMounted,ref,shallowRef} from 'vue';
import AnnotationEditor from '../components/AnnotationEditor.vue';
import type {AiEditorBox,AiEditorContext,AiEditorSnapshot} from '../types/ai-editor';
import type {ReviewLabel} from '../api/ai-review';
import {readFormalAnnotation,sameFormalBoxes,writeFormalAnnotation,type FormalPayload} from '../api/formal-annotation';
import {createAnnotoriousEditor} from '../../../static/modules/annotorious-editor.js';
import {withLegacyBoxIdentities} from '../../../static/modules/annotation-geometry-adapter.js';
import {annotationSavePayload} from '../../../static/modules/annotation-workbench.js';
import {browseError} from '../api/model-browse';

const props=defineProps<{projectId:string;imageId:string;labels:ReviewLabel[];hasNext:boolean}>();
const emit=defineEmits<{back:[];navigate:[delta:number];settled:[imageId:string,advance:boolean]}>();
const controller=new AbortController();
const row=shallowRef<Awaited<ReturnType<typeof readFormalAnnotation>>>();
const boxes=shallowRef<AiEditorBox[]>([]),baseline=shallowRef<AiEditorBox[]>([]);
const busy=ref(false),saving=ref(false),error=ref(''),notice=ref(''),conflict=ref(false),epoch=ref(0);
const pending=shallowRef<{payload:FormalPayload;scope:string[];advance:boolean}>();
const active=ref<string|null>(null),selectedLabel=ref(props.labels[0]?.code||''),filter=ref(''),reviewed=ref<string[]>([]);
const view=ref({mode:'draw',visible:true,scale:1});
const dirty=computed(()=>JSON.stringify(boxes.value)!==JSON.stringify(baseline.value)||reviewed.value.length>0);
const usable=computed(()=>!!row.value&&row.value.image.source_available!==false&&/^[0-9a-f]{64}$/.test(row.value.image.content_sha256||''));
const locked=computed(()=>busy.value||saving.value||!!pending.value||conflict.value||!usable.value);
const history:AiEditorBox[][]=[],redo:AiEditorBox[][]=[];
type Kernel=Awaited<ReturnType<typeof createAnnotoriousEditor>>;
let kernel:Kernel|undefined,mountController:AbortController|undefined,geometryError=false;
const label=()=>props.labels.find(item=>item.code===selectedLabel.value)||null;
function sync(){kernel?.sync({label:label(),locked:locked.value})}
function apply(value:NonNullable<typeof row.value>){
  row.value=value;
  baseline.value=withLegacyBoxIdentities(value.annotation.boxes,{imageId:props.imageId});
  boxes.value=baseline.value;
  history.length=redo.length=0;
  active.value=null;
  reviewed.value=[];
}
function setBoxes(next:AiEditorBox[]){
  if(locked.value||JSON.stringify(next)===JSON.stringify(boxes.value))return;
  history.push(boxes.value);
  if(history.length>50)history.shift();
  redo.length=0;
  boxes.value=next;
}
function undo(){
  if(locked.value)return;
  kernel?.flush();
  const previous=history.pop();
  if(previous){redo.push(boxes.value);boxes.value=previous;active.value=null;sync()}
}
function redoEdit(){
  if(locked.value)return;
  const next=redo.pop();
  if(next){history.push(boxes.value);boxes.value=next;active.value=null;sync()}
}
function select(index:number){
  const id=boxes.value[index]?.id;
  return id!=null&&kernel?.select(id);
}
function chooseLabel(code:string){selectedLabel.value=code;sync()}
function mayLeave(){
  if(saving.value)return false;
  kernel?.flush();
  return !(dirty.value||pending.value)||confirm('当前标注有未保存或待核对的修改。确定离开？');
}
async function load(){
  if(saving.value||busy.value)return;
  busy.value=true;error.value='';sync();
  try{
    const fresh=await readFormalAnnotation(props.projectId,props.imageId,controller.signal);
    if(controller.signal.aborted)return;
    apply(fresh);pending.value=undefined;conflict.value=false;geometryError=false;notice.value='';epoch.value++;
  }catch(cause){if(!controller.signal.aborted)error.value=browseError(cause)}
  finally{busy.value=false;sync()}
}
async function verify(){
  const packet=pending.value;
  if(!packet||busy.value||saving.value)return;
  busy.value=true;error.value='';
  try{
    const fresh=await readFormalAnnotation(props.projectId,props.imageId,controller.signal);
    if(controller.signal.aborted)return;
    const {annotation,image}=fresh;
    if(image.content_sha256!==packet.payload.source_content_sha256){
      conflict.value=true;throw new Error('原图代际已变化，请重新载入核对');
    }
    if(annotation.version===packet.payload.expected_version){
      notice.value='当前版本未变化。请核对保留的修改，再决定是否保存。';
      pending.value=undefined;
      return;
    }
    const scope=[...new Set(annotation.annotation_scope||[])].sort();
    if(annotation.version!==packet.payload.expected_version+1||annotation.annotation_state!==packet.payload.annotation_state
      ||JSON.stringify(scope)!==JSON.stringify(packet.scope)||!sameFormalBoxes(annotation.boxes,packet.payload.boxes)){
      conflict.value=true;throw new Error('服务端标注已变化。当前修改仍保留，请重新载入核对');
    }
    apply(fresh);pending.value=undefined;notice.value='已核对当前正式标注';
    emit('settled',props.imageId,packet.advance);
  }catch(cause){if(!controller.signal.aborted)error.value=browseError(cause)}
  finally{busy.value=false;sync()}
}
async function save(confirmReview=false,advance=false){
  const current=row.value;
  if(!kernel||!current||locked.value)return;
  error.value='';
  kernel.flush();
  if(geometryError){error.value='框坐标转换有误，请重新载入核对后保存。';return}
  if(!confirmReview&&JSON.stringify(boxes.value)===JSON.stringify(baseline.value)){
    if(advance)emit('navigate',1);
    return;
  }
  if(confirmReview&&!reviewed.value.length){error.value='请选择本次确实已核对的标签';return}
  const payload=annotationSavePayload({annotation:current.annotation,image:current.image,boxes:boxes.value,
    reviewedLabelCodes:confirmReview?reviewed.value:[],confirmEmpty:confirmReview});
  const prior=payload.annotation_state==='annotated'?current.annotation.annotation_scope||[]:[];
  const scope=[...new Set([...prior,...payload.reviewed_label_codes])].sort();
  saving.value=true;sync();
  try{
    const result=await writeFormalAnnotation(props.projectId,props.imageId,payload);
    if(controller.signal.aborted)return;
    apply(result);notice.value='正式标注已保存';
    saving.value=false;
    emit('settled',props.imageId,advance);
  }catch(cause){
    if(controller.signal.aborted)return;
    const status=(cause as {httpStatus?:number}).httpStatus;
    if(status===409){conflict.value=true;error.value=browseError(cause)}
    else if(status&&[400,401,403,404,422].includes(status))error.value=browseError(cause);
    else{pending.value={payload,scope,advance};error.value='保存结果待核对，请读取当前正式标注。'}
  }finally{saving.value=false;sync()}
}
const context:AiEditorContext={
  async mount(refs){
    const image=row.value?.image;
    if(image?.width!==refs.image.naturalWidth||image.height!==refs.image.naturalHeight)
      throw new Error('原图尺寸和当前正式记录不一致');
    mountController?.abort();
    const signal=(mountController=new AbortController()).signal;
    const editor=await createAnnotoriousEditor({...refs,signal,getBoxes:()=>boxes.value,getLabels:()=>props.labels,getLabel:label,
      isActive:()=>!controller.signal.aborted,onCommit:setBoxes,onSelect:id=>{active.value=id},
      onSave:()=>void save(),onNavigate:delta=>emit('navigate',delta),onUndo:undo,onRedo:redoEdit,
      onChooseLabel:item=>chooseLabel(item.code),onError:cause=>{geometryError=true;error.value=browseError(cause)},
      onViewportChange:({scale})=>{view.value.scale=scale},onModeChange:mode=>{view.value.mode=mode},
      onVisibilityChange:visible=>{view.value.visible=visible},
    });
    if(signal.aborted||controller.signal.aborted){editor.destroy();return}
    kernel=editor;view.value={...editor.snapshot()};sync();return editor;
  },
  release(handle){
    if(handle&&handle!==kernel){(handle as Kernel).destroy();return}
    mountController?.abort();kernel?.destroy();kernel=undefined;
  },
  actions:{
    mode:value=>kernel?.setMode(value),label:chooseLabel,select,
    reclass:(index,code)=>{if(select(index))kernel?.reclassSelected(code)},
    remove:index=>{if(select(index))kernel?.deleteSelected()},
    undo,redo:redoEdit,visibility:()=>kernel?.setVisibility(!view.value.visible),
    filter:code=>{filter.value=code;kernel?.setClassFilter(code?[code]:null)},
    zoom:delta=>kernel?.zoom(delta),fit:()=>kernel?.fit(),resetZoom:()=>kernel?.resetZoom(),
    save:()=>save(),reload:()=>{if(mayLeave())void load()},cancel:()=>emit('back'),
  },
};
const snapshot=computed<AiEditorSnapshot|undefined>(()=>{
  const current=row.value;if(!current)return;
  const image=current.image,index=boxes.value.findIndex(box=>String(box.id)===active.value);
  return {imageId:props.imageId,filename:(image.filename||props.imageId).replaceAll('\\','/').split('/').at(-1)||props.imageId,
    url:`/api/v61/projects/${encodeURIComponent(props.projectId)}/materials/${encodeURIComponent(props.imageId)}/content?expected_sha256=${encodeURIComponent(image.content_sha256||'')}`,
    width:image.width||0,height:image.height||0,boxes:boxes.value,labels:props.labels,activeBox:index<0?null:index,
    labelCode:selectedLabel.value,filterCode:filter.value,dirty:dirty.value,saving:saving.value,
    pending:locked.value,view:view.value,revision:current.annotation.version};
});
const states:Record<string,string>={annotated:'已标注',unannotated:'待标注',confirmed_empty:'已确认无目标',partial:'部分已复核',needs_review:'待审核'};
function beforeUnload(event:BeforeUnloadEvent){
  kernel?.flush();
  if(dirty.value||saving.value||pending.value){event.preventDefault();event.returnValue=''}
}
onMounted(()=>{window.addEventListener('beforeunload',beforeUnload);void load()});
onBeforeUnmount(()=>{window.removeEventListener('beforeunload',beforeUnload);controller.abort();context.release()});
defineExpose({mayLeave});
</script>

<template>
  <AnnotationEditor v-if="snapshot" :key="epoch" :context="context" :snapshot="snapshot" native formal>
    <template #footer="{ready}">
      <div class="formal-review">
        <strong>{{ states[row?.image.annotation_state||row?.annotation.annotation_state||'']||'状态待核对' }}</strong>
        <small>已确认范围：{{ row?.annotation.annotation_scope?.join('、')||'无' }}</small>
        <small v-if="!usable">缺少可验证的原图身份，当前只读。</small>
        <small v-else-if="dirty">有未保存修改</small>
        <span v-if="error" role="alert">{{ error }}</span><span v-else-if="notice" role="status">{{ notice }}</span>
      </div>
      <div class="formal-save">
        <el-select v-model="reviewed" multiple filterable collapse-tags placeholder="选择实际核对的标签"
          aria-label="已核对标签" :disabled="locked||!ready">
          <el-option v-for="item in labels" :key="item.code" :label="item.display_name||item.code" :value="item.code"/>
        </el-select>
        <el-button v-if="pending&&!conflict" :loading="busy" @click="verify">核对保存结果</el-button>
        <el-button v-if="conflict||error" :disabled="saving||busy" @click="context.actions.reload()">重新载入</el-button>
        <el-button :disabled="locked||!ready" @click="save()">保存标注</el-button>
        <el-button v-if="hasNext" :disabled="locked||!ready" @click="save(false,true)">保存并继续</el-button>
        <el-button type="primary" :disabled="locked||!ready||!reviewed.length" :loading="saving" @click="save(true)">
          {{ snapshot.boxes.length?'保存并确认审核':'确认所选类别无目标' }}
        </el-button>
      </div>
    </template>
  </AnnotationEditor>
  <section v-else class="opening">
    <p v-if="error" role="alert">{{ error }}</p><p v-else role="status">正在读取正式标注…</p>
    <el-button v-if="error" :disabled="busy" @click="load">重试读取</el-button>
  </section>
</template>

<style scoped>
.opening{padding:24px}.formal-save{display:flex;gap:6px;flex-wrap:wrap}.formal-save .el-select{width:200px}
.formal-save :deep(.el-button){margin:0}.formal-review span{max-width:460px;overflow-wrap:anywhere}
</style>

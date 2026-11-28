<script setup lang="ts">
import {computed,onBeforeUnmount,onMounted,reactive,ref,shallowRef,watch} from 'vue';
import {onBeforeRouteLeave,useRoute,useRouter} from 'vue-router';
import AiAnnotationCreate from '../views/AiAnnotationCreate.vue';
import MaterialPreview from '../components/MaterialPreview.vue';
import {getReviewLabels,type ReviewLabel} from '../api/ai-review';
import {aiCreateInputs,aiMaterialMembership,createAiTask,previewAiImage,readAiCreateReceipt,summarizeAiMaterials,renderAiPrompt,
  type AiCreateBody,type AiCreateModel,type AiCreatePrompt,type CreatePreview} from '../api/ai-annotation-create';
import {useAiCreateMaterials} from '../composables/useAiCreateMaterials';
import {useReadScope} from '../composables/useReadScope';
import {browseError} from '../api/model-browse';
import type {AiAnnotationCreateContext,AiAnnotationCreateSnapshot} from '../types/ai-annotation-create';
import type {MaterialFilters} from '../types/materials';
import type {AiTask} from '../types/ai-tasks';
import {legacyUrl} from './navigation';
import {readWorkspaceSession,useWorkspace,workspaceActorKey} from './main';
import {request} from './http';

const route=useRoute(),router=useRouter(),projectId=String(route.params.projectId);
const controller=new AbortController(),reads=useReadScope(controller);
const project={projectId};
const taskList={name:'ai-tasks',params:project};
const workspace=useWorkspace(),actorKey=workspace.actorKey;
const journal='ai-create-operation:'+encodeURIComponent(projectId);
const rules=/^[A-Za-z0-9_-]{12,80}$/;
const pending=ref(''),journalProblem=ref(''),submitting=ref(false),recovering=ref(false),error=ref('');
const step=ref(1);
const configured=reactive({name:'AI自动标注-'+new Date().toLocaleString(),model:'',template:'',labels:[] as string[],
  threshold:0.45 as number|undefined,overwrite:false,prompt:'',instruction:''});
const models=shallowRef<AiCreateModel[]>([]),templates=shallowRef<AiCreatePrompt[]>([]),labels=shallowRef<ReviewLabel[]>([]);
const selectedModel=computed(()=>models.value.find(model=>model.id===configured.model));
const dedicated=computed(()=>(selectedModel.value?.provider_adapter||selectedModel.value?.provider_type)==='wevisone_vl');
const materialFilters:MaterialFilters={query:'',label:'',annotation_state:'',quality_status:'',storage_source_id:'',source_batch_id:'',created_from:'',created_to:''};
for(const key of Object.keys(materialFilters) as (keyof MaterialFilters)[]){
  const value=route.query[key];if(typeof value==='string')materialFilters[key]=value;
}
const batch=ref(typeof route.query.zip_batch==='string'&&/^[0-9a-f]{10}$/.test(route.query.zip_batch)?route.query.zip_batch:'');
const filters=reactive({...materialFilters});
const inherited=history.state?.aiCreateSelection;
const fromSelected=route.query.material_scope==='selected';
const initialIds:string[]=fromSelected&&actorKey&&inherited?.actorKey===actorKey&&inherited?.projectId===projectId
  &&Array.isArray(inherited.imageIds)&&inherited.imageIds.length<=50000
  &&inherited.imageIds.every((id:unknown)=>typeof id==='string'&&!!id)?inherited.imageIds:[];
const handoffMissing=ref(fromSelected&&!initialIds.length);
const materials=useAiCreateMaterials(projectId,controller,materialFilters,initialIds);
const {page,busy:scopeBusy,count,canFreeze,frozen,excluded,error:scopeError}=materials;
const referenceIds=shallowRef(new Set<string>()),previewId=ref(''),preview=shallowRef<CreatePreview>();
const trialOpen=ref(false),trialRoot=ref<HTMLElement>(),trialError=ref('');
watch([trialRoot,preview],async ([root,result],_,onCleanup)=>{
  if(!root||!result)return;
  const trial=new AbortController();
  let dispose:(()=>void)|undefined;
  onCleanup(()=>{trial.abort();dispose?.()});
  trialError.value='';
  try{
    const {mountTrial}=await import('../../../static/modules/annotation-trial.js');
    if(trial.signal.aborted)return;
    const project=encodeURIComponent(projectId);
    const image={...result.image,url:`/api/v61/projects/${project}/materials/${encodeURIComponent(result.image.id)}/content`};
    dispose=await mountTrial(root,{...result,image},{
      labels:labels.value.filter(label=>configured.labels.includes(label.code))
        .map(label=>({code:label.code,display_name_zh:label.display_name})),
      compareUrl:`/api/v60/projects/${project}/annotation-preview/compare`,
      active:()=>trialOpen.value&&preview.value===result&&workspace.actorKey===actorKey,
      signal:trial.signal,request,
    });
    if(trial.signal.aborted)dispose();
  }catch(cause){if(!trial.signal.aborted)trialError.value=browseError(cause)}
},{flush:'post'});
const configLocked=computed(()=>submitting.value||recovering.value||!!pending.value||!!journalProblem.value
  ||!actorKey||workspace.actorKey!==actorKey);
const confirmed=shallowRef<AiCreateBody>();
const scopeCount=ref<number>();
const stateCounts=shallowRef<Record<string,number>>();
const editable=computed(()=>!!selectedModel.value&&configured.labels.length>0&&configured.labels.length<=100
  &&configured.labels.every(code=>labels.value.some(label=>label.code===code))
  &&configured.threshold!==undefined&&Number.isFinite(configured.threshold)&&configured.threshold>=0&&configured.threshold<=1);
const stateNames:Record<string,string>={unannotated:'未标注',annotated:'已标注',partial:'范围不完整',confirmed_empty:'已确认无目标'};
function loadInputs(){
  return reads.run('inputs',async signal=>{
    const [[modelData,promptData],catalog]=await Promise.all([aiCreateInputs(signal),getReviewLabels(projectId,signal)]);
    return {models:modelData.items.filter(model=>model.enabled!==false),prompts:promptData.items,catalog};
  },data=>{
    models.value=data.models;templates.value=data.prompts;labels.value=data.catalog;
    if(!models.value.some(model=>model.id===configured.model))configured.model=(data.models.find(model=>model.default_for_annotation)||data.models[0])?.id||'';
  });
}
function chooseTemplate(value:string){
  const template=templates.value.find(item=>item.id===value);
  if(template?.model_config_id&&models.value.some(model=>model.id===template.model_config_id))configured.model=template.model_config_id;
  if(template?.labels?.length)configured.labels=template.labels.filter(code=>labels.value.some(label=>label.code===code));
  configured.prompt='';
}
const defaultPrompt=computed(()=>templates.value.find(item=>item.id===configured.template)?.prompt
  ||selectedModel.value?.annotation_prompt_template||'');
const effectivePrompt=computed(()=>configured.prompt.trim()||defaultPrompt.value);
const promptText=shallowRef('');
function renderPrompt(){
  if(configLocked.value||dedicated.value||!editable.value||!effectivePrompt.value)return;
  promptText.value='';
  const input={prompt:effectivePrompt.value,labels:labels.value.filter(label=>configured.labels.includes(label.code))
    .map(label=>({code:label.code,display_name_zh:label.display_name||label.code})),
    image_width:640,image_height:480,business_instruction:configured.instruction.trim()};
  void reads.run('prompt',signal=>renderAiPrompt(input,signal),value=>{promptText.value=value.rendered_prompt});
}
function scopedBatch(){
  return batch.value.trim()&&/^[0-9a-f]{10}$/.test(batch.value.trim())?batch.value.trim():'';
}
function loadMaterials(number=1){
  if(configLocked.value||scopeBusy.value)return;
  const source=scopedBatch();
  void materials.load(number,{...filters,source_batch_id:source||filters.source_batch_id,
    annotation_state:source?'unannotated':filters.annotation_state});
}
function toggleReference(id:string){
  if(configLocked.value)return;
  const next=new Set(referenceIds.value);
  if(next.has(id))next.delete(id);else next.add(id);
  referenceIds.value=next;
}
function build():AiCreateBody{
  if(!editable.value||configured.threshold===undefined)throw new Error('请选择启用的模型、有效标签和 0 到 1 的置信度。');
  const selection=materials.input(),source=scopedBatch();
  if(batch.value.trim()&&!source)throw new Error('请输入有效的 ZIP 导入批次编号。');
  if(source&&count.value)throw new Error('ZIP 批次与逐图或冻结选择不能同时提交，请先清除选择。');
  return {image_ids:source?[]:selection.image_ids,
    ...(source?{source_batch_id:source}:selection.previous_ref?{selection_ref:selection.previous_ref,excluded_image_ids:selection.excluded_image_ids}:{}),
    labels_text:configured.labels.join('、'),model_config_id:configured.model,
    prompt_template_id:dedicated.value?null:configured.template||null,
    prompt_override:dedicated.value?'':configured.prompt.trim(),
    business_instruction:dedicated.value?'':configured.instruction.trim(),
    threshold:configured.threshold,overwrite:configured.overwrite,
    reference_image_ids:dedicated.value?[]:[...referenceIds.value],task_name:configured.name.trim()||'AI自动标注任务'};
}
function readJournal(){
  try{
    const raw=localStorage.getItem(journal);
    if(!raw){pending.value='';journalProblem.value='';return}
    const saved=JSON.parse(raw);
    if(saved.project_id!==projectId||typeof saved.request_id!=='string'||!rules.test(saved.request_id))
      throw new Error('invalid journal');
    if(saved.actor_key&&saved.actor_key!==actorKey){
      pending.value='';
      journalProblem.value='此项目有其他操作者尚未核对的创建记录，请由原操作者核对。';
      return;
    }
    pending.value=saved.request_id;journalProblem.value='';
  }catch{journalProblem.value='创建记录无法核验，请恢复浏览器存储后重试。'}
}
function clearJournal(id:string){
  readJournal();
  if(journalProblem.value||pending.value!==id)throw new Error('创建记录已变化，请重新核对。');
  localStorage.removeItem(journal);
  readJournal();
  if(journalProblem.value||pending.value)throw new Error('创建记录暂未清除，请重新核对。');
}
function journalChanged(event:StorageEvent){if(event.key===journal||event.key===null)readJournal()}
async function verifyActor(){
  if(!actorKey||workspace.actorKey!==actorKey
      ||workspaceActorKey(await readWorkspaceSession(controller.signal))!==actorKey||controller.signal.aborted)
    throw new Error('登录账号已变化，请刷新页面后重新核对。');
}
function withJournalLock<T>(work:()=>T):Promise<T>{
  return navigator.locks?navigator.locks.request(journal,()=>work()):Promise.resolve(work());
}
async function finish(task:AiTask,id:string){
  await withJournalLock(()=>clearJournal(id));
  submitting.value=false;
  if(!controller.signal.aborted)await router.push({...taskList,query:{created:task.id}});
}
async function verify(){
  if(recovering.value||submitting.value)return;
  readJournal();
  const id=pending.value;
  if(!id||journalProblem.value)return;
  recovering.value=true;error.value='';
  try{
    await verifyActor();
    const task=await readAiCreateReceipt(projectId,id,controller.signal);
    if(!controller.signal.aborted)await finish(task,id);
  }catch(cause){
    if(controller.signal.aborted)return;
    error.value=(cause as {httpStatus?:number}).httpStatus===404
      ?'暂未找到原请求回执，请稍后再核对。':browseError(cause);
  }finally{recovering.value=false}
}
async function prepare(){
  if(configLocked.value||handoffMissing.value||scopeBusy.value||reads.busy.summary)return;
  error.value='';
  try{
    const body=build();
    if(!body.source_batch_id&&!count.value)throw new Error('请选择本次任务的素材。');
    if(body.source_batch_id){
      // The signed-off ZIP report and current GT decide the final scope on the server.
      scopeCount.value=undefined;stateCounts.value=undefined;confirmed.value=body;step.value=3;return;
    }
    const selection=materials.input();
    await reads.run('summary',signal=>summarizeAiMaterials(projectId,selection,signal),summary=>{
      if(JSON.stringify(build())!==JSON.stringify(body)||summary.count!==count.value||summary.count<1)
        throw new Error('配置或素材范围已变化，请重新核对。');
      scopeCount.value=summary.count;stateCounts.value=summary.state_counts;confirmed.value=body;step.value=3;
    });
  }catch(cause){error.value=browseError(cause)}
}
async function create(){
  if(configLocked.value||handoffMissing.value||!confirmed.value||scopeBusy.value||reads.busy.summary||reads.busy.preview)return;
  readJournal();
  if(configLocked.value)return;
  error.value='';
  let id='';
  let sent=false;
  submitting.value=true;
  try{
    await verifyActor();
    const current=build();
    if(JSON.stringify(current)!==JSON.stringify(confirmed.value))throw new Error('配置已变化，请重新核对。');
    id='ai-'+Array.from(crypto.getRandomValues(new Uint8Array(16)),byte=>byte.toString(16).padStart(2,'0')).join('');
    await withJournalLock(()=>{
      if(controller.signal.aborted)throw new Error('当前页面已退出，请重新核对。');
      readJournal();
      if(pending.value||journalProblem.value)throw new Error('已有创建记录，请先核对。');
      localStorage.setItem(journal,JSON.stringify({project_id:projectId,request_id:id,actor_key:actorKey}));
      readJournal();
      if(journalProblem.value||pending.value!==id)throw new Error('无法可靠保存创建记录，本次未提交。');
    });
    sent=true;
    const task=await createAiTask(projectId,{...current,request_id:id});
    if(!controller.signal.aborted)await finish(task,id);
  }catch(cause){
    if(controller.signal.aborted)return;
    const status=(cause as {httpStatus?:number}).httpStatus;
    if(sent&&[400,422].includes(status??0)){
      try{await withJournalLock(()=>clearJournal(id))}catch{/* The original record stays blocked. */}
      confirmed.value=undefined;
      error.value=browseError(cause);
    }else error.value=sent?'创建结果待核对，请读取原请求回执。':browseError(cause);
  }finally{submitting.value=false}
}
function runPreview(){
  if(configLocked.value||reads.busy.preview||!previewId.value)return;
  error.value='';preview.value=undefined;
  try{
    const body=build(),id=previewId.value;
    void reads.run('preview',async signal=>{
      await verifyActor();
      if(!body.source_batch_id&&!body.image_ids.includes(id)){
        const ref=body.selection_ref;
        if(!ref||body.excluded_image_ids?.includes(id)||!(await aiMaterialMembership(projectId,ref,[id],signal)).includes(id))
          throw new Error('请选择本次任务中的一张素材试跑。');
      }
      if(signal.aborted)throw new DOMException('已取消','AbortError');
      return previewAiImage(projectId,body,id,signal);
    },result=>{preview.value=result});
  }catch(cause){error.value=browseError(cause)}
}
const previewImage=computed(()=>preview.value?{...preview.value.image,
  content_url:`/api/v61/projects/${encodeURIComponent(projectId)}/materials/${encodeURIComponent(preview.value.image.id)}/content`}:undefined);
watch([()=>JSON.stringify(configured),frozen,count,excluded,batch,referenceIds,previewId],()=>{
  trialOpen.value=false;
  confirmed.value=undefined;scopeCount.value=undefined;stateCounts.value=undefined;
  reads.cancel('summary');reads.cancel('preview');reads.cancel('prompt');preview.value=undefined;promptText.value='';
});
const snapshot=computed<AiAnnotationCreateSnapshot>(()=>({
  projectId,step:step.value,taskName:configured.name,modelName:selectedModel.value?.name||selectedModel.value?.model_name,
  providerName:selectedModel.value?.provider_adapter||selectedModel.value?.provider_type,
  inferenceProtocol:selectedModel.value?(dedicated.value?'wevisone_detection':'generic_prompt'):'unknown',
  selectedCount:batch.value?undefined:count.value,confirmedCount:scopeCount.value,frozenCount:frozen.value?.count,
  excludedCount:excluded.value.size,labelCodes:configured.labels,threshold:configured.threshold,referenceCount:dedicated.value?0:referenceIds.value.size,
  busy:submitting.value||recovering.value,loading:scopeBusy.value||!!reads.busy.inputs,confirmationReady:!!confirmed.value,
  error:error.value||journalProblem.value||scopeError.value||reads.errors.inputs||reads.errors.summary||reads.errors.preview,
  pending:pending.value?{requestId:pending.value,message:'请核对原请求回执。'}:null,
  detectionQueries:dedicated.value?configured.labels.map(code=>({code,query:selectedModel.value?.wevisone_label_queries?.[code]||code})):undefined,
}));
function openLegacy(){
  if(!submitting.value)location.assign(legacyUrl(projectId,'自动标注及清洗','','','material-ai'));
}
const context:AiAnnotationCreateContext={signal:controller.signal,snapshot:()=>snapshot.value,
  subscribe:listener=>watch(snapshot,listener,{immediate:true}),
  actions:{step:value=>{step.value=value},close:()=>router.push(taskList),legacy:openLegacy}};
onBeforeRouteLeave(()=>!submitting.value);
onMounted(()=>{
  readJournal();if(pending.value)step.value=3;
  window.addEventListener('storage',journalChanged);
  void loadInputs();
  if(!configLocked.value)loadMaterials();
});
onBeforeUnmount(()=>{window.removeEventListener('storage',journalChanged);controller.abort()});
</script>

<template>
  <AiAnnotationCreate :context="context">
    <template #materials>
      <el-alert v-if="handoffMissing" title="无法读取原已选范围，请返回素材库重新进入。" type="warning" :closable="false"/>
      <p v-else-if="fromSelected">已从素材库带入 {{ initialIds.length }} 张已选素材。筛选只改变浏览范围。</p>
      <p v-else-if="route.query.material_scope==='filters'">已带入素材库筛选条件，请选择本次任务素材。</p>
      <p v-if="count||excluded.size||frozen" class="create-scope-summary" role="status">
        已选 {{count}} 张<template v-if="frozen">（冻结引用 {{frozen.count}} 张）</template><template v-if="excluded.size"> · 手动排除 {{excluded.size}} 张</template><template v-if="page"> · 当前页 {{page.items.length}} / 共 {{page.total}} 张</template>
      </p>
      <el-button v-if="handoffMissing" @click="handoffMissing=false">按当前筛选条件重新选择</el-button>
      <form class="create-fields" @submit.prevent="loadMaterials()">
        <label>图片名称<el-input v-model="filters.query" :disabled="configLocked"/></label>
        <label>素材标签<el-select v-model="filters.label" clearable filterable :disabled="configLocked">
          <el-option v-for="item in labels" :key="item.code" :label="item.display_name||item.code" :value="item.code"/>
        </el-select></label>
        <label>标注状态<el-select v-model="filters.annotation_state" clearable :disabled="configLocked">
          <el-option v-for="(name,state) in stateNames" :key="state" :label="name" :value="state"/>
        </el-select></label>
        <label>ZIP 导入批次（可选）<el-input v-model="batch" maxlength="10" :disabled="configLocked" placeholder="已完成的导入批次编号"/></label>
        <el-button native-type="submit" :disabled="configLocked||scopeBusy">查询素材</el-button>
      </form>
      <p v-if="batch">按批次创建只处理导入报告中的待标注素材。</p>
      <p v-else-if="!canFreeze">当前来源或质量筛选只支持逐张或本页选取。</p>
      <div class="create-actions">
        <el-button :disabled="configLocked||scopeBusy||!page?.items.length||!!batch" @click="materials.selectPage">选本页</el-button>
        <el-button :disabled="configLocked||scopeBusy||!page?.total||!canFreeze||!!batch" @click="materials.freeze">冻结全部筛选结果</el-button>
        <el-button :disabled="configLocked||scopeBusy||!count&&!frozen" @click="materials.clear">清除选择</el-button>
      </div>
      <div class="material-choice">
        <article v-for="item in page?.items" :key="item.id">
          <MaterialPreview :image="item" :project-id="projectId" :show-boxes="false"/>
          <el-checkbox :model-value="materials.isSelected(item.id)" :disabled="configLocked||scopeBusy||!!batch"
            @change="(value:unknown)=>materials.setSelected(item.id,value===true)">{{ item.filename }}</el-checkbox>
          <el-button link :disabled="configLocked||scopeBusy||(!batch&&!materials.isSelected(item.id))" @click="previewId=item.id;step=2">试跑此图</el-button>
          <el-button v-if="!dedicated&&item.annotation_state==='annotated'" link :disabled="configLocked"
            @click="toggleReference(item.id)">{{ referenceIds.has(item.id)?'移除参考':'设为参考' }}</el-button>
        </article>
      </div>
      <p v-if="!dedicated && referenceIds.size" role="status">参考素材只记录在任务配置中，当前模型接口不会读取这些图片。</p>
      <div v-if="page" class="create-actions"><el-button :disabled="configLocked||scopeBusy||page.page<=1" @click="materials.load(page.page-1)">上一页</el-button>
        <span>第 {{ page.page }} 页 / {{ page.total_pages }} 页</span>
        <el-button :disabled="configLocked||scopeBusy||!page.has_next" @click="materials.load(page.page+1)">下一页</el-button></div>
    </template>
    <template #configuration>
      <div class="create-fields">
        <label>任务名称<el-input v-model="configured.name" :disabled="configLocked"/></label>
        <label>视觉模型<el-select v-model="configured.model" aria-label="视觉模型" :disabled="configLocked" @change="configured.prompt=''">
          <el-option v-for="item in models" :key="item.id" :label="item.name||item.model_name||item.id" :value="item.id"/>
        </el-select></label>
        <label>审核标签<el-select v-model="configured.labels" aria-label="审核标签" multiple collapse-tags filterable :multiple-limit="100" :disabled="configLocked">
          <el-option v-for="item in labels" :key="item.code" :label="`${item.display_name||item.code} · ${item.code}`" :value="item.code"/>
        </el-select></label>
        <label>置信度阈值<el-input-number v-model="configured.threshold" :min="0" :max="1" :step="0.05" :disabled="configLocked"/></label>
        <label v-if="!dedicated">提示词模板<el-select v-model="configured.template" aria-label="提示词模板" clearable placeholder="使用模型默认提示词" :disabled="configLocked" @change="chooseTemplate">
          <el-option v-for="item in templates" :key="item.id" :label="`${item.name} · v${item.version||1}`" :value="item.id"/>
        </el-select></label>
        <el-checkbox v-model="configured.overwrite" :disabled="configLocked">允许为已有标注素材生成候选</el-checkbox>
      </div>
      <el-button v-if="reads.errors.inputs" :disabled="configLocked" @click="loadInputs">重试配置读取</el-button>
    </template>
    <template #advanced>
      <details v-if="!dedicated" class="advanced-prompt">
        <summary>提示词和业务要求</summary>
        <label>提示词覆盖<el-input v-model="configured.prompt" type="textarea" :rows="4" maxlength="12000" :placeholder="defaultPrompt||'使用默认提示词'" :disabled="configLocked"/></label>
        <label>业务要求<el-input v-model="configured.instruction" type="textarea" :rows="2" :disabled="configLocked"/></label>
        <el-button :loading="reads.busy.prompt" :disabled="configLocked||!editable||!effectivePrompt" @click="renderPrompt">渲染提示词</el-button>
        <p v-if="!effectivePrompt">任务将使用服务端默认提示词。</p>
        <p v-if="reads.errors.prompt" role="alert">{{ reads.errors.prompt }}</p>
        <pre v-if="promptText" class="rendered-prompt">{{ promptText }}</pre>
      </details>
      <div v-if="previewId" class="create-actions">
        <el-button :loading="reads.busy.preview" :disabled="configLocked||!editable" @click="runPreview">运行单图试跑</el-button>
        <el-button v-if="reads.busy.preview" @click="reads.cancel('preview')">取消等待</el-button>
      </div>
      <section v-if="preview&&previewImage" aria-label="单图试跑结果">
        <p>{{ preview.boxes.length }} 个候选框 · {{ preview.latency_ms }} ms</p>
        <MaterialPreview :image="previewImage" :boxes="preview.boxes" :project-id="projectId" full/>
        <el-button @click="trialOpen=true">打开高级试跑对比</el-button>
        <el-dialog v-model="trialOpen" title="高级试跑对比" width="min(1120px, 96vw)" destroy-on-close>
          <el-alert v-if="trialError" type="error" :closable="false" :title="trialError" />
          <div v-if="trialOpen" ref="trialRoot" class="advanced-trial" />
        </el-dialog>
      </section>
    </template>
    <template #confirmation>
      <div v-if="confirmed">
        <p v-if="confirmed.source_batch_id">来源 ZIP 批次 {{ confirmed.source_batch_id }}。创建时按原导入报告与正式标注确定范围。</p>
        <ul v-else><li v-for="(total,state) in stateCounts" :key="state">{{ stateNames[state]||state }} {{ total }} 张</li></ul>
        <p v-if="confirmed.overwrite">已有标注素材也可能生成候选，正式标注仍须人工审核。</p>
      </div>
    </template>
    <template #footer>
      <div class="create-actions">
        <el-button v-if="journalProblem" @click="readJournal">重新读取创建记录</el-button>
        <el-button v-if="pending" type="primary" :loading="recovering" :disabled="submitting||!!journalProblem" @click="verify">核对原请求</el-button>
        <template v-else>
          <el-button :loading="reads.busy.summary" :disabled="configLocked||handoffMissing||scopeBusy||!editable" @click="prepare">核对配置和范围</el-button>
          <el-button v-if="step===3" type="primary" :disabled="configLocked||!confirmed||!!reads.busy.preview" @click="create">确认创建任务</el-button>
        </template>
      </div>
    </template>
  </AiAnnotationCreate>
</template>

<style scoped>
.create-fields{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;align-items:end}
.create-fields label,.advanced-prompt label{display:grid;gap:6px;font-size:13px}.create-fields .el-select{width:100%}
.create-actions{display:flex;align-items:center;flex-wrap:wrap;gap:8px;margin:12px 0;font-size:13px}
.create-actions :deep(.el-button){margin:0}.create-scope-summary{margin:0 0 8px;padding:8px 12px;border-radius:6px;background:var(--el-fill-color-lighter,#f5f7fa);font-size:12px;color:var(--el-text-color-regular,#52525b);overflow-wrap:anywhere}.material-choice{display:grid;grid-template-columns:repeat(auto-fill,minmax(152px,1fr));gap:10px}
.material-choice article{min-width:0;border:1px solid var(--el-border-color);border-radius:6px;padding:8px}
.material-choice :deep(.el-checkbox){max-width:100%}.material-choice :deep(.el-checkbox__label){overflow:hidden;text-overflow:ellipsis}
.rendered-prompt{max-height:240px;overflow:auto;white-space:pre-wrap}.advanced-prompt{margin-top:16px}.advanced-prompt label{margin-top:10px}
.advanced-trial{max-height:70vh;overflow:auto}.advanced-trial :deep(.row){display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}
.advanced-trial :deep(.btn){background:#fff;border:1px solid #d4d4d4;border-radius:5px;color:#252525;padding:5px 9px;cursor:pointer}
</style>

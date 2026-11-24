<script setup lang="ts">
import {computed,onBeforeUnmount,onMounted,ref,watch} from 'vue';
import {useRoute,useRouter} from 'vue-router';
import {legacyUrl} from './navigation';
import {useReadScope} from '../composables/useReadScope';
import ReadOnlyFacts from '../components/ReadOnlyFacts.vue';
import {browseError} from '../api/model-browse';
import {createConversionJob,findConversionByRequest,loadConversionCatalog,loadConversionResources,loadConversionSources,newConversionRequestId,resolveConversion} from '../api/conversion-jobs';
import type {ConversionCatalog,ConversionContractResult,ConversionJobRequest,ConversionSource,DeployResource} from '../types/conversion-job';
const props=defineProps<{projectId:string}>();
const projectId=props.projectId,route=useRoute(),router=useRouter(),controller=new AbortController();
const reads=useReadScope(controller);
const catalog=ref<ConversionCatalog|null>(null),sources=ref<ConversionSource[]>([]),resources=ref<DeployResource[]>([]);
const sourceId=ref(''),vendorId=ref(''),chipId=ref(''),resourceId=ref(''),precision=ref(''),inputSize=ref('');
const precisionEdited=ref(false),advanced=ref<Record<string,string|number|boolean>>({}),confirmed=ref(false);
const contract=ref<ConversionContractResult|null>(null),contractError=ref(''),contractSignature=ref(''),resolving=ref(false);
const submitting=ref(false),error=ref(''),notice=ref('');
let contractController:AbortController|null=null,contractTimer:number|undefined,contractTicket=0;
let mutationController:AbortController|null=null;
const pendingKey=`native-conversion-pending:${projectId}`;
interface PendingConversion {requestId:string;payload:ConversionJobRequest;createdAt:number}
const pending=ref<PendingConversion|null>(readPending()),verifying=ref(false),retrying=ref(false);
const query=(name:string)=>typeof route.query[name]==='string'?String(route.query[name]):'';
const algorithmId=query('algorithm'),versionId=query('version');
const legacy=legacyUrl(projectId,'算法列表',algorithmId,versionId,'conversion');
onBeforeUnmount(()=>{
  contractController?.abort();
  mutationController?.abort();
  window.clearTimeout(contractTimer);
  controller.abort();
});
function readPending():PendingConversion|null{
  try{
    const value=JSON.parse(sessionStorage.getItem(pendingKey)||'null') as PendingConversion|null;
    return value?.requestId&&value?.payload?.request_id===value.requestId?value:null;
  }catch{return null}
}
function savePending(body:ConversionJobRequest){pending.value={requestId:String(body.request_id),payload:body,createdAt:Date.now()};try{sessionStorage.setItem(pendingKey,JSON.stringify(pending.value))}catch{/* private mode keeps the in-memory guard */}}
function clearPending(){pending.value=null;try{sessionStorage.removeItem(pendingKey)}catch{/* nothing to clear */}}
const vendor=computed(()=>catalog.value?.vendors.find(row=>row.id===vendorId.value));
const template=computed(()=>catalog.value?.templates.find(row=>row.id===vendor.value?.template_id));
const target=computed(()=>String(template.value?.adapter||''));
const source=computed(()=>sources.value.find(row=>row.id===sourceId.value));
const resource=computed(()=>resources.value.find(row=>row.id===resourceId.value));
const chip=computed(()=>catalog.value?.chips.find(row=>row.id===chipId.value));
const chipCapability=computed(()=>chipId.value?catalog.value?.chip_capabilities?.[chipId.value]:undefined);
const advancedFields=computed(()=>template.value?.advanced_fields||[]);
const vendorOptions=computed(()=>(catalog.value?.vendors||[]).filter(row=>row.enabled!==false));
const chipOptions=computed(()=>(catalog.value?.chips||[]).filter(row=>row.vendor_id===vendorId.value));
const resourceOptions=computed(()=>resources.value.filter(row=>target.value&&((row.targets||[]).includes(target.value)||String(row.kind||'')===target.value)));
const precisionOptions=computed(()=>contract.value?.allowed_precisions?.length?contract.value.allowed_precisions:(chipCapability.value?.allowed_precisions||[]));
const cscCapability=computed(()=>contract.value?.csc_capabilities||(target.value?catalog.value?.csc_capabilities_by_target?.[target.value]:undefined));
const inputSizeError=computed(()=>{
  const raw=inputSize.value.trim();
  if(!raw)return '';
  const value=Number(raw);
  return Number.isInteger(value)&&value>=32&&value<=8192&&value%32===0?'':'输入尺寸必须为 32 的倍数，范围 32 到 8192；留空则按版本/ONNX 推断';
});
const formSignature=()=>JSON.stringify([sourceId.value,target.value,vendorId.value,chipId.value,resourceId.value,precisionEdited.value?precision.value:'',inputSize.value.trim(),advanced.value]);
const canSubmit=computed(()=>!!contract.value?.ready&&contractSignature.value===formSignature()&&confirmed.value&&!submitting.value&&!resolving.value);
const parameterFacts=computed<[string,unknown][]>(()=>Object.entries(contract.value?.params||{}).slice(0,80).map(([key,value])=>[key,fact(value)]));
const parameterSourceFacts=computed<[string,unknown][]>(()=>Object.entries(contract.value?.parameter_sources||{}));
const contractErrorFacts=computed(()=>contract.value?.errors||[]);
const resourceFacts=computed<[string,unknown][]>(()=>resource.value?[
  ['资源名称',resource.value.name||resource.value.id],['资源类型',resource.value.kind],['执行模式',resource.value.mode],
  ['资源状态',resource.value.status],['SDK 检测状态',resource.value.detection?.state],['检测时间',resource.value.detection?.checked_at],
  ['检测说明',resource.value.detection?.reason||resource.value.detection?.error],['支持芯片',(resource.value.supported_chips||[]).join(' / ')],
  ['支持精度',(resource.value.supported_precisions||[]).join(' / ')],
]:[]);
function chipOptionLabel(row:{id:string;name:string}){
  const label=catalog.value?.chip_capabilities?.[row.id]?.status_label;
  return label?`${row.name} · ${label}`:row.name;
}
function fact(value:unknown):string{
  if(value===null||value===undefined||value==='')return '未提供';
  if(Array.isArray(value)||typeof value==='object'){
    try{const text=JSON.stringify(value);return text.length>400?`${text.slice(0,400)}…`:text}catch{return String(value)}
  }
  return String(value);
}
function resetAdvanced(){
  const next:Record<string,string|number|boolean>={};
  for(const field of template.value?.advanced_fields||[])if(field.default!==undefined&&field.default!==null)next[field.key]=field.default;
  advanced.value=next;
}
function setAdvanced(key:string,value:string|number|boolean){advanced.value={...advanced.value,[key]:value};confirmed.value=false}
function toggleAdvanced(key:string,event:unknown){setAdvanced(key,event===true)}
function inputAdvanced(key:string,type:string,event:unknown){
  const text=String(event??'');
  setAdvanced(key,type==='number'?(text===''?'':Number(text)):text);
}
function chipPrecisionText(){
  const values=chipCapability.value?.allowed_precisions||[];
  return values.length?`SDK 可用精度：${values.join(' / ')}`:'芯片能力尚未确认';
}
function params(){
  const values:Record<string,unknown>={};
  if(vendorId.value)values.local_vendor_id=vendorId.value;
  if(chipId.value)values.local_chip_id=chipId.value;
  if(precisionEdited.value&&precision.value)values.precision=precision.value;
  const size=inputSize.value.trim();
  if(size&&!inputSizeError.value)values.input_size=Number(size);
  for(const [key,value] of Object.entries(advanced.value))if(value!==''&&value!==null&&value!==undefined)values[key]=value;
  return values;
}
function requiredReady(){return !!(sourceId.value&&vendorId.value&&chipId.value&&resourceId.value&&target.value&&!inputSizeError.value)}
function scheduleResolve(){
  window.clearTimeout(contractTimer);
  contract.value=null;contractSignature.value='';contractError.value='';confirmed.value=false;
  if(!requiredReady())return;
  contractTimer=window.setTimeout(()=>void resolveNow(),300);
}
async function resolveNow(){
  if(!requiredReady())return;
  const signature=formSignature();
  contractController?.abort();
  const current=new AbortController();
  contractController=current;
  const ticket=++contractTicket;
  resolving.value=true;contractError.value='';confirmed.value=false;
  try{
    const result=await resolveConversion(projectId,{source_id:sourceId.value,target:target.value,resource_id:resourceId.value,params:params()},current.signal);
    if(current.signal.aborted||ticket!==contractTicket||signature!==formSignature())return;
    contract.value=result;contractSignature.value=signature;
    const resolved=String(result.params?.precision||'');
    if(result.ready&&!precisionEdited.value&&resolved&&precisionOptions.value.includes(resolved))precision.value=resolved;
  }catch(cause){
    if(current.signal.aborted||ticket!==contractTicket)return;
    contractError.value=browseError(cause);
  }finally{if(ticket===contractTicket)resolving.value=false}
}
function mutationSignal(){
  mutationController?.abort();
  mutationController=new AbortController();
  return mutationController.signal;
}
function detailTarget(jobId:string){
  const values:Partial<ConversionSource>=source.value||{};
  return {name:'conversion-detail-native',params:{projectId,jobId},query:{
    ...(values.algorithm_id?{algorithm:values.algorithm_id}:{}),...(values.version_id?{version:values.version_id}:{}),
    ...(values.algorithm_name?{algorithm_name:values.algorithm_name}:{}),...(values.version_name?{version_name:values.version_name}:{}),
  }};
}
function back(){void router.push(algorithmId&&versionId?{name:'version-conversions',params:{projectId,algorithmId,versionId}}:{name:'algorithms',params:{projectId}})}
async function submit(){
  if(!canSubmit.value)return;
  const body:ConversionJobRequest={source_id:sourceId.value,target:target.value,resource_id:resourceId.value,
    params:params(),dataset_id:'default',calibration_split:'train',calibration_count:100,request_id:newConversionRequestId()};
  error.value='';notice.value='';
  savePending(body);
  submitting.value=true;
  try{
    const job=await createConversionJob(projectId,body,mutationSignal());
    if(controller.signal.aborted)return;
    clearPending();
    await router.push(detailTarget(job.id));
  }catch(cause){
    if(controller.signal.aborted)return;
    const status=(cause as {httpStatus?:number}).httpStatus;
    const code=(cause as {code?:unknown}).code;
    if(code==='CONVERSION_CREATE_IN_PROGRESS'){
      notice.value='相同转换请求正在创建：请按原请求 ID 核验结果，不要换用新的请求 ID 重复提交。';
    }else if(status!==undefined&&status>=400&&status<500){
      clearPending();
      error.value=`转换任务未受理：${browseError(cause)}`;
    }else{
      notice.value='转换创建结果待核验：未收到有效回执，原请求 ID 已保留；请先核验，不要重复创建。';
    }
  }finally{submitting.value=false}
}
async function verifyPending(){
  const value=pending.value;
  if(!value||verifying.value)return;
  verifying.value=true;error.value='';notice.value='';
  try{
    const result=await findConversionByRequest(projectId,value.requestId,mutationSignal());
    if(controller.signal.aborted)return;
    if(result.found&&result.job?.id){
      clearPending();
      const values=result.job;
      await router.push({name:'conversion-detail-native',params:{projectId,jobId:result.job.id},query:{
        ...(values.source_trace?.algorithm_id?{algorithm:String(values.source_trace.algorithm_id)}:{}),
        ...(values.source_trace?.version_id?{version:String(values.source_trace.version_id)}:{})}});
      return;
    }
    notice.value=result.pending?'服务器正在准备该转换请求，请稍后继续核验。':'尚未查到原转换请求；可保留原请求 ID 继续核验，或按原请求安全重试。';
  }catch(cause){
    if(!controller.signal.aborted)notice.value=`核验失败：${browseError(cause)}。原请求可能仍在执行，不要使用新的请求 ID。`;
  }finally{verifying.value=false}
}
async function retryPending(){
  const value=pending.value;
  if(!value||retrying.value)return;
  retrying.value=true;error.value='';notice.value='';
  try{
    const job=await createConversionJob(projectId,value.payload,mutationSignal());
    if(controller.signal.aborted)return;
    clearPending();
    await router.push(detailTarget(job.id));
  }catch(cause){
    if(!controller.signal.aborted)notice.value=`原请求仍未确认：${browseError(cause)}。已保留原请求 ID。`;
  }finally{retrying.value=false}
}
onMounted(()=>{
  void (async()=>{
    await Promise.all([reads.run('catalog',loadConversionCatalog,value=>{catalog.value=value}),
      reads.run('resources',loadConversionResources,value=>{resources.value=value}),
      reads.run('sources',signal=>loadConversionSources(projectId,signal),value=>{sources.value=value})]);
    if(controller.signal.aborted)return;
    const wanted=algorithmId&&versionId?`version::${algorithmId}::${versionId}`:query('source');
    if(wanted&&!sources.value.some(row=>row.id===wanted)){
      sourceId.value='';
      error.value='指定的源模型版本没有可转换的模型文件，请选择其他源模型，或回到算法库检查该版本产物。';
      return;
    }
    sourceId.value=wanted||sources.value[0]?.id||'';
  })();
});
watch(vendorId,()=>{chipId.value='';precision.value='';precisionEdited.value=false;confirmed.value=false;resetAdvanced()});
watch(chipId,()=>{precision.value='';precisionEdited.value=false;confirmed.value=false});
watch(resourceOptions,rows=>{if(resourceId.value&&!rows.some(row=>row.id===resourceId.value))resourceId.value=''});
watch(()=>[sourceId.value,precision.value,inputSize.value,resourceId.value].join('\0'),()=>{confirmed.value=false});
watch(formSignature,scheduleResolve);
</script>
<template>
<section class="conversion-create-page">
 <header class="create-head"><div><button class="back" @click="back">返回转换记录</button><h2>创建模型转换</h2><p>目标厂商、芯片、资源与模板参数均来自现有转换字典和合同校验接口；提交只调用既有转换创建任务接口。ONNX / Paddle / TensorRT 直出仍使用原完整转换界面。</p></div><div><a :href="legacy">原完整转换界面</a></div></header>
 <el-alert v-if="pending" type="warning" :closable="false" title="存在待确认的转换创建请求"><p>请求 ID {{ pending.requestId }} · 提交于 {{ new Date(pending.createdAt).toLocaleString() }}</p><p>请先核验原请求；核验前不允许用新请求 ID 重复创建。</p><el-button size="small" :loading="verifying" @click="verifyPending">核验原请求</el-button> <el-button size="small" :loading="retrying" @click="retryPending">按原请求安全重试</el-button></el-alert>
 <el-alert v-if="error" :title="error" type="error" :closable="false"/>
 <el-alert v-if="notice" :title="notice" type="info" :closable="false"/>
 <el-alert v-if="reads.errors.catalog" :title="reads.errors.catalog" type="error" :closable="false"/>
 <el-alert v-if="reads.errors.resources" :title="reads.errors.resources" type="error" :closable="false"/>
 <el-alert v-if="reads.errors.sources" :title="reads.errors.sources" type="error" :closable="false"/>
 <div class="create-layout">
  <main>
   <section class="card">
    <h3>源模型与目标</h3>
    <div v-if="!sources.length" class="empty-note">当前项目没有可转换的源模型；请先完成训练并生成模型版本。</div>
    <div v-else class="form-grid">
     <label>源模型<el-select v-model="sourceId" filterable placeholder="选择源模型或算法版本" aria-label="源模型"><el-option v-for="row in sources" :key="row.id" :label="row.label||row.name||row.id" :value="row.id"/></el-select><small v-if="source">{{ source.kind==='algorithm_version'?'算法版本来源':'项目模型来源' }} · {{ source.framework||'框架未提供' }} · {{ source.size_mb?source.size_mb+' MB':'大小未提供' }}</small></label>
     <label>目标厂商<el-select v-model="vendorId" placeholder="选择转换厂商" aria-label="目标厂商"><el-option v-for="row in vendorOptions" :key="row.id" :label="row.name" :value="row.id" :disabled="!catalog?.templates.find(item=>item.id===row.template_id)?.implemented"/></el-select></label>
     <label>目标芯片<el-select v-model="chipId" :disabled="!vendorId" placeholder="选择目标芯片" aria-label="目标芯片"><el-option v-for="row in chipOptions" :key="row.id" :label="chipOptionLabel(row)" :value="row.id" :disabled="row.enabled===false"/></el-select><small v-if="chipCapability">{{ chipPrecisionText() }}</small></label>
     <label>转换资源<el-select v-model="resourceId" :disabled="!target" placeholder="选择对应 SDK 的转换资源" aria-label="转换资源"><el-option v-for="row in resourceOptions" :key="row.id" :label="`${row.name||row.id} · ${row.status||'状态未提供'}`" :value="row.id" :disabled="row.status!=='ready'"/></el-select><small v-if="!resourceOptions.length&&target">没有与 {{ target }} 模板匹配的转换资源，请先在原“模型转换环境”登记并检测资源。</small></label>
     <label>转换精度<el-select v-model="precision" :disabled="!precisionOptions.length" placeholder="由后端按芯片与源训练精度推荐" aria-label="转换精度" @change="precisionEdited=true"><el-option v-for="value in precisionOptions" :key="value" :label="value.toUpperCase()" :value="value"/></el-select><small>未手动修改时由后端按芯片能力与源训练实际精度推断。</small></label>
     <label>输入尺寸（可选）<el-input v-model="inputSize" inputmode="numeric" placeholder="如 640；留空由版本/ONNX 推断" aria-label="输入尺寸"/><small :class="{invalid:!!inputSizeError}">{{ inputSizeError||'后端会按版本训练尺寸或真实 ONNX 输入核验。' }}</small></label>
    </div>
    <p v-if="vendorId&&!target" class="hint">所选厂商模板尚无可执行 Adapter，不能创建转换。</p>
   </section>
   <section v-if="advancedFields.length" class="card">
    <h3>模板高级参数（后端字典）</h3>
    <div class="form-grid">
     <label v-for="field in advancedFields" :key="field.key">{{ field.label }}<el-checkbox v-if="field.type==='checkbox'" :model-value="advanced[field.key]===true" :disabled="field.locked" @change="toggleAdvanced(field.key,$event)">{{ field.locked?'（模板锁定）':'启用' }}</el-checkbox><el-input v-else :model-value="String(advanced[field.key]??'')" :disabled="field.locked" @update:model-value="inputAdvanced(field.key,field.type,$event)"/><small>{{ field.locked?'由模板锁定，仅展示后端默认值。':'修改后会重新执行合同校验。' }}</small></label>
    </div>
   </section>
   <section class="card" aria-label="转换合同校验">
    <header class="card-head"><h3>转换合同校验</h3><el-button :loading="resolving" :disabled="!requiredReady()" @click="resolveNow">重新校验</el-button></header>
    <el-skeleton v-if="resolving&&!contract" :rows="4" animated/>
    <p v-else-if="!requiredReady()" class="hint">选择源模型、厂商、芯片与转换资源后自动执行后端合同校验。</p>
    <template v-else>
     <el-alert v-if="contractError" :title="`合同校验失败：${contractError}`" type="error" :closable="false"/>
     <el-alert v-else-if="contract" :type="contract.ready?'success':'warning'" :closable="false" :title="contract.ready?`合同校验通过（${contract.status}）`:`合同未通过（${contract.status}）`"/>
     <el-alert v-if="contract?.precision_adjustment_reason" :title="contract.precision_adjustment_reason" type="info" :closable="false"/>
     <ul v-if="contractErrorFacts.length" class="contract-errors"><li v-for="(message,index) in contractErrorFacts" :key="index">{{ message }}</li></ul>
     <template v-if="contract">
      <h4>后端解析后的真实参数</h4>
      <ReadOnlyFacts :fields="parameterFacts"/>
      <p v-if="!parameterFacts.length" class="hint">合同未通过，没有可提交的参数。</p>
      <h4 v-if="parameterSourceFacts.length">参数来源</h4>
      <ReadOnlyFacts :fields="parameterSourceFacts"/>
      <h4 v-if="contract.source_input_shapes?.length">真实 ONNX 输入 Shape</h4>
      <pre v-if="contract.source_input_shapes?.length">{{ JSON.stringify(contract.source_input_shapes) }}</pre>
     </template>
    </template>
   </section>
  </main>
  <aside class="summary">
   <h3>当前事实</h3>
   <ReadOnlyFacts :fields="[['源模型',source?.label||source?.name||'未选择'],['厂商',vendor?.name||'未选择'],['目标格式',target||'未选择'],['模板',template?.name],['芯片',chip?.name||'未选择'],['SDK 芯片编码',chip?.sdk_code],['转换资源',resource?.name||'未选择'],['项目',projectId]]"/>
   <h4>资源与能力</h4>
   <ReadOnlyFacts :fields="resourceFacts"/>
   <h4>颜色转换（只读能力）</h4>
   <ReadOnlyFacts :fields="[['部署合同能力',cscCapability?.capability],['执行位置',cscCapability?.execution_location],['板端验证',cscCapability?.board_verification]]"/>
   <p class="evidence-note">能力声明不等于板端验证；本页不提供颜色转换、发布或板端激活操作。</p>
   <el-checkbox v-model="confirmed" :disabled="!contract?.ready||contractSignature!==formSignature()">我已确认源模型、目标芯片、资源与后端解析参数，提交后将创建真实转换任务。</el-checkbox>
   <p v-if="!contract?.ready||contractSignature!==formSignature()" class="hint">合同通过且配置未变化后才能提交。配置变化会自动重新校验。</p>
   <div class="submit-row"><el-button type="primary" :loading="submitting" :disabled="!canSubmit" @click="submit">{{ submitting?'正在创建转换任务…':'创建转换任务' }}</el-button></div>
   <p class="evidence-note">提交只调用既有转换创建接口；页面不提供执行转换、外部发布或设备激活操作。</p>
  </aside>
 </div>
</section>
</template>
<style scoped>
.conversion-create-page{padding:24px;min-width:0}.create-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;margin-bottom:16px}.create-head h2{margin:8px 0 6px;font-size:22px}.create-head p{margin:0;color:#64748b;line-height:1.7;max-width:860px}.back{border:0;background:transparent;color:#2563eb;cursor:pointer;padding:0}.create-layout{display:grid;grid-template-columns:minmax(0,1fr) minmax(280px,340px);gap:16px;align-items:start}.card{background:white;border:1px solid #e2e8f0;border-radius:12px;padding:16px;margin-bottom:16px;min-width:0}.card h3{margin:0 0 14px;font-size:17px}.card h4{margin:18px 0 10px;font-size:14px}.card-head{display:flex;justify-content:space-between;align-items:center;gap:12px}.form-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:14px}.form-grid label{display:grid;gap:6px;font-size:13px;color:#334155;min-width:0}.form-grid small{color:#64748b;line-height:1.5}.form-grid small.invalid{color:#b91c1c}.form-grid :deep(.el-select),.form-grid :deep(.el-input){width:100%}.summary{position:sticky;top:16px;background:white;border:1px solid #e2e8f0;border-radius:12px;padding:16px;min-width:0}.summary h3{margin:0 0 14px;font-size:17px}.summary h4{margin:18px 0 10px;font-size:14px}.summary :deep(.readonly-facts){grid-template-columns:minmax(96px,.9fr) minmax(0,1.4fr);font-size:12px;gap:8px}.evidence-note,.hint{color:#64748b;font-size:12px;line-height:1.7}.empty-note{padding:22px;border:1px dashed #cbd5e1;border-radius:10px;color:#475569}.contract-errors{margin:10px 0;padding-left:20px;color:#b91c1c;font-size:13px;line-height:1.7;overflow-wrap:anywhere}.submit-row{margin:14px 0;display:flex}.submit-row :deep(.el-button){width:100%}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f8fafc;padding:12px;border-radius:8px;font-size:12px}@media(max-width:960px){.create-layout{grid-template-columns:minmax(0,1fr)}.summary{position:static}}
</style>

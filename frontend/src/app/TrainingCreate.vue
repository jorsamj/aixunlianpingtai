<script setup lang="ts">
import {computed,reactive,ref,onBeforeUnmount,watch} from 'vue';
import {useRoute,useRouter} from 'vue-router';
import {request} from './http';
import {useWorkspace} from './main';
import TrainingMaterials from './TrainingMaterials.vue';
import {removeResolvedTrainingMaterials} from '../../../static/modules/training-material-summary-runtime.js';
import {createTrainingDraft,trainingConfigurationDefaults,trainingInheritedDefaults,trainingBaseVersionFromAlgorithm,trainingDraftToRequest} from '../../../static/modules/training-draft.js';
import {trainingModePreset,buildTrainingStartPayload} from '../../../static/modules/training-submit.js';
import * as trainingApi from './training-api';
import {isDigest,readIteration,readTrainingSource,type IterationSource} from '../api/training-iteration';
const router=useRouter();
const route=useRoute(),projectId=String(route.params.projectId),algorithmId=String(route.params.algorithmId||route.query.algorithm||'');
const username=useWorkspace().username;
const sourceQuery=(key:string)=>typeof route.query[key]==='string'?String(route.query[key]):'';
const requestedSource=sourceQuery('source_version')||sourceQuery('action')||sourceQuery('evaluation')||sourceQuery('supplement');
const source:IterationSource|undefined=requestedSource?{projectId,algorithmId,versionId:sourceQuery('source_version'),
 actionId:sourceQuery('action'),evaluationId:sourceQuery('evaluation'),candidateSetId:sourceQuery('supplement')}:undefined;
const draftScope=JSON.stringify(source?[username,projectId,algorithmId,source.actionId,source.candidateSetId]:[username,projectId,algorithmId]);
const draftStorageKey='native-training:'+draftScope;
const unionStorageKey='training-selection-union:'+JSON.stringify([useWorkspace().username,projectId,algorithmId]);
let savedDraft:any=null;try{savedDraft=JSON.parse(sessionStorage.getItem(draftStorageKey)||'null')}catch{}
const algorithmOptions=ref<any[]>([]),algorithmQuery=ref(''),algorithmPage=ref(1),algorithmTotal=ref(0);
async function searchAlgorithms(epoch=loadEpoch){try{const r=await request<any>(`/api/v12/projects/${encodeURIComponent(projectId)}/algorithms?summary_only=true&asset_view=true&page=${algorithmPage.value}&page_size=20&query=${encodeURIComponent(algorithmQuery.value)}`,{signal:controller.signal});if(epoch!==loadEpoch)return;algorithmOptions.value=r.items||[];algorithmTotal.value=r.total||0;}catch(e){if(epoch===loadEpoch)error.value=(e as Error).message}}
function switchAlgorithm(id:string){void router.push({path:`/projects/${encodeURIComponent(projectId)}/training/create`,query:{algorithm:id}});}
const controller=new AbortController();onBeforeUnmount(()=>controller.abort());
const asset=ref<any>(null),targets=ref<any[]>([]),devices=ref<any[]>([]),targetId=ref(''),engineKey=ref(''),busy=ref(false),error=ref(''),ready=ref(false),picker=ref<'train'|'test'|'negative'|'robustness'|null>(null),taskId=ref(''),stage=ref('idle'),result=ref<any>(null);
const draft=reactive(createTrainingDraft({algorithmId})),train=ref<any>({ids:[],count:0}),test=ref<any>({ids:[],count:0}),labels=ref<string[]>([]);
type PickerSelection={ids:string[];count:number;reference?:string;summary?:any;revision?:any};
const positive=ref<PickerSelection>({ids:[],count:0}),negative=ref<PickerSelection>({ids:[],count:0});
const poolEvidence=ref<Awaited<ReturnType<typeof trainingApi.previewTrainingNegatives>>|null>(null);
const target=computed(()=>targets.value.find(row=>String(row.id)===targetId.value)),engine=computed(()=>target.value?.algorithms?.find((row:any)=>String(row.key)===engineKey.value)),base=computed(()=>trainingBaseVersionFromAlgorithm(asset.value||{})),preset=computed(()=>trainingModePreset(draft.trainingMode,Boolean(draft.baseVersionId)));
const identity=computed(()=>({algorithm_asset_id:algorithmId,base_version_id:draft.baseVersionId,train_labels:draft.newLabelCodes,framework:target.value?.framework||'ultralytics',model:draft.config.model||engine.value?.base_model||'',history_policy:draft.history_policy}));
const numericFields=[['epochs','Epochs'],['imgsz','图像尺寸'],['patience','早停耐心'],['time','最长训练小时'],['lr0','初始学习率'],['lrf','最终学习率系数'],['momentum','动量'],['weight_decay','权重衰减'],['warmup_epochs','预热轮数'],['close_mosaic','关闭 Mosaic 轮数'],['mosaic','Mosaic'],['mixup','MixUp'],['hsv_h','HSV H'],['hsv_s','HSV S'],['hsv_v','HSV V'],['degrees','旋转'],['translate','平移'],['scale','缩放'],['shear','剪切'],['perspective','透视'],['flipud','上下翻转'],['fliplr','左右翻转'],['freeze','冻结层数'],['multi_scale','多尺度'],['save_period','保存周期'],['seed','随机种子'],['val_max_samples','验证样本上限'],['eval_interval','评测间隔'],['continue_threshold','继续阈值'],['stop_threshold','停止阈值']];
const booleanFields=[['early_stopping_enabled','启用早停'],['pretrained','预训练'],['amp','AMP'],['single_cls','单类别'],['rect','矩形训练'],['cos_lr','余弦学习率'],['deterministic','确定性']];
const defaults=trainingConfigurationDefaults(),recommendation=ref<any>(null);
void trainingApi.loadTrainingRecommendation(controller.signal).then(value=>{if(!controller.signal.aborted)recommendation.value=value}).catch(()=>{});
function robustnessMode(){if(draft.robustness_policy.mode==='enabled'){draft.robustness_policy={selection:{mode:'ratio',ratio:20,count:100,image_ids:[]},copies:1,seed:0,presets:['bt601_limited','bt601_full','bt709_limited','bt709_full'],...draft.robustness_policy};}}

function changeMode(){Object.assign(draft,createTrainingDraft({...draft,trainingMode:draft.trainingMode}));if(preset.value)Object.assign(draft.config,preset.value,trainingInheritedDefaults(asset.value));else{draft.resource.batch??=draft.config.batch;draft.resource.workers??=draft.config.workers;draft.resource.cache??=draft.config.cache;}}
const diagnosis=ref<any>(null),diagnosisSelected=ref<string[]>([]),resolvedExclusion=ref<any>(null),exclusionConfirmed=ref(false),diagnosisSignature=ref('');
const previewSignature=ref('');
const fixedSources=ref<any[]>([]),fixedNext=ref<number|null>(0),fixedPreview=ref<any>(null),fixedSignature=ref(''),fixedRequestId=ref(''),projectLabels=ref<string[]>([]);
const fixedRoleRows=computed(()=>[['train','Train'],['validation','Val'],['test','Test']].map(([key,role])=>{const row=fixedPreview.value?.roles?.[key]||{};return {role,total:row.total||0,positive:row.positive||0,negative:row.confirmed_negative||0,pending:row.pending_confirmation||0,ineligible:row.ineligible||0}}));
const fixedScope=computed(()=>({...identity.value,zip_source_job_ids:draft.zipSourceJobIds,review_all_training_backgrounds:backgroundConfirmed.value}));
async function loadFixedSources(){if(fixedNext.value===null)return;try{const r=await trainingApi.fixedZipSources(projectId,fixedNext.value,controller.signal);fixedSources.value.push(...r.items);fixedNext.value=r.next_offset??null}catch(e){error.value=(e as Error).message}}
async function loadProjectLabels(){try{const r=await request<any>(`/api/v12/projects/${encodeURIComponent(projectId)}/labels`,{signal:controller.signal});projectLabels.value=(r.items||[]).map((x:any)=>typeof x==='string'?x:x.code).filter(Boolean)}catch(e){error.value=(e as Error).message}}
async function previewFixed(){busy.value=true;error.value='';try{const signature=JSON.stringify(fixedScope.value);const result=await trainingApi.previewFixedZip(projectId,fixedScope.value,controller.signal);if(signature!==JSON.stringify(fixedScope.value))throw new Error('选择已变化，请重新预览');fixedPreview.value=result;fixedSignature.value=signature;const key='fixed-freeze:'+draftScope;let saved:any=null;try{saved=JSON.parse(sessionStorage.getItem(key)||'null')}catch{};fixedRequestId.value=saved?.signature===signature&&saved?.digest===result.preview_digest?saved.id:trainingApi.trainingSelectionRequestId();sessionStorage.setItem(key,JSON.stringify({signature,digest:result.preview_digest,id:fixedRequestId.value}));}catch(e){error.value=(e as Error).message}finally{busy.value=false}}

const benchmark=ref<any>(null),backgroundConfirmed=ref(false),negativePreview=ref<any>(null),negativeConfirmed=ref(false),finalConfirm=ref(false),preview=ref<any>(null);
watch(()=>JSON.stringify(fixedScope.value),()=>{fixedPreview.value=null;fixedSignature.value='';finalConfirm.value=false});
function chooseTarget(){engineKey.value=target.value?.algorithms?.[0]?.key||'';draft.config.model=engine.value?.base_model||'';if(draft.config.imgsz==null)draft.config.imgsz=engine.value?.default_imgsz||640;}
async function mergeSelections(nextPositive:PickerSelection,nextNegative:PickerSelection){
 if(!nextNegative.count)return nextPositive;
 const ids=[...new Set([...nextPositive.ids,...nextNegative.ids])];
 const revision=await trainingApi.trainingMaterialRevision(projectId,algorithmId,controller.signal);
 let references:Awaited<ReturnType<typeof trainingApi.combineTrainingSelections>>|undefined;
 if(nextPositive.reference||nextNegative.reference){
  const scope={...identity.value,train_labels:[...identity.value.train_labels].sort(),
    positive_ref:nextPositive.reference,positive_ids:[...nextPositive.ids].sort(),
    negative_ref:nextNegative.reference,negative_ids:[...nextNegative.ids].sort(),
    test_image_ids:[...draft.testMaterialIds].sort(),expected_revisions:revision};
  const key=JSON.stringify(scope);
  const previous=JSON.parse(sessionStorage.getItem(unionStorageKey)||'null');
  const id=previous?.key===key?previous.id:trainingApi.trainingSelectionRequestId();
  // Save before POST so a lost response or reload can reuse the server receipt.
  sessionStorage.setItem(unionStorageKey,JSON.stringify({key,id}));
  references=await trainingApi.combineTrainingSelections(projectId,{...scope,request_id:id},controller.signal);
 }
 const scope=references?{train_selection_ref:references.selection_ref}:{image_ids:ids};
 const summary=await trainingApi.summarizeTrainingSelection(projectId,{...identity.value,...scope,role:'train',summary_only:true},controller.signal);
 const count=references?.count??ids.length;
 if(summary.matched_count!==count||summary.requested_count!==count)throw new Error('合并素材数量已变化，请重新选择');
 return {ids:references?[]:ids,reference:references?.selection_ref,count,summary,revision};
}
function setTrain(value:PickerSelection){
 train.value=value;
 draft.materialIds=value.ids;
 draft.trainSelectionRef=value.reference||'';
 draft.trainSelectionCount=value.count;
 labels.value=value.summary?.positive_label_codes||[];
 draft.newLabelCodes=draft.newLabelCodes.filter((code:string)=>labels.value.includes(code));
}
async function selected(value:PickerSelection){
 if(controller.signal.aborted)return;
 if(picker.value==='robustness'){draft.robustness_policy.selection.image_ids=value.ids;picker.value=null;return}
 if(picker.value==='test'){test.value=value;draft.testMaterialIds=value.ids;picker.value=null;return}
 if(busy.value)return;
 busy.value=true;
 error.value='';
 try{
  const nextPositive=picker.value==='train'?value:positive.value;
  const nextNegative=picker.value==='negative'?value:negative.value;
  const combined=await mergeSelections(nextPositive,nextNegative);
  if(controller.signal.aborted)return;
  positive.value=nextPositive;
  negative.value=nextNegative;
  setTrain(combined);
  picker.value=null;
 }catch(cause){if(!controller.signal.aborted)error.value=(cause as Error).message}
 finally{busy.value=false}
}
async function checkPool(){
 busy.value=true;
 poolEvidence.value=null;
 try{
  const verified=await trainingApi.previewTrainingNegatives(projectId,{...identity.value,image_ids:negative.value.ids},controller.signal);
  if(!controller.signal.aborted)poolEvidence.value=verified;
 }catch(cause){if(!controller.signal.aborted)error.value=(cause as Error).message}
 finally{busy.value=false}
}
function payload(){return buildTrainingStartPayload({draft,target:target.value,algorithm:engine.value,trainingDraftToRequest});}
async function loadSource(epoch=loadEpoch){
 if(!source)return;
 if(!source.versionId||!isDigest(source.actionId)||!isDigest(source.evaluationId)
    ||(source.candidateSetId&&!isDigest(source.candidateSetId))||source.versionId!==draft.baseVersionId)
  throw new Error('训练来源链接不完整或当前版本已变化，请返回原评测');
 const view=await readIteration(source,controller.signal);if(epoch!==loadEpoch)return;
 readTrainingSource(view,source);
 if(benchmark.value?.available&&benchmark.value.source_version_id===source.versionId){
  draft.benchmarkReuseEnabled=true;
  if(draft.splitMode==='fixed_zip_train_val_test'||draft.testMaterialIds.length)
    throw new Error('来源基准与当前草稿 Test 条件冲突，请从评测重新进入');
 }
 if(!source.candidateSetId)return;
 const candidates=view.candidate_set!.material_ids;
 if(draft.trainSelectionRef)throw new Error('来源补数需要显式素材选择');
 const ids=[...new Set([...positive.value.ids,...candidates])];
 const next={ids,count:ids.length};
 const value=await mergeSelections(next,negative.value);
 if(epoch!==loadEpoch)return;
 positive.value=next;
 setTrain(value);
}

let loadEpoch=0;
async function load(){const epoch=++loadEpoch;busy.value=true;try{await searchAlgorithms(epoch);if(epoch!==loadEpoch||!algorithmId)return;const response=await request<any>(`/api/v12/projects/${encodeURIComponent(projectId)}/algorithms/${encodeURIComponent(algorithmId)}`,{signal:controller.signal});if(epoch!==loadEpoch)return;asset.value=response.algorithm;const initial=trainingBaseVersionFromAlgorithm(asset.value);if(initial.blocked)throw new Error('当前版本尚未满足可核验迭代条件');draft.baseVersionId=initial.versionId;Object.assign(draft.config,defaults,{imgsz:null},trainingInheritedDefaults(asset.value));const options:any=await trainingApi.loadTrainingOptions(projectId,controller.signal);if(epoch!==loadEpoch)return;targets.value=options.targets||[];targetId.value=targets.value.find(row=>row.status==='ready')?.id||'';chooseTarget();const deviceResult:any=await trainingApi.loadTrainingDevices(controller.signal);if(epoch!==loadEpoch)return;devices.value=deviceResult.options||[];changeMode();const benchmarkView=await trainingApi.loadTrainingBenchmark(projectId,algorithmId,controller.signal).catch(cause=>({available:false,reason:'固定 Test 基准读取失败，请刷新后再启用复用：'+cause.message}));if(epoch!==loadEpoch)return;benchmark.value=benchmarkView;try{const saved=savedDraft;if(saved?.draft?.algorithmId===algorithmId){Object.assign(draft,createTrainingDraft(saved.draft));if(saved.targetId){targetId.value=targets.value.some(t=>t.id===saved.targetId)?saved.targetId:'';engineKey.value=target.value?.algorithms?.some((a:any)=>a.key===saved.engineKey)?saved.engineKey:'';}train.value=saved.train||train.value;positive.value=saved.positive||train.value;negative.value=saved.negative||negative.value;test.value=saved.test||test.value;labels.value=train.value.summary?.positive_label_codes||[];}}catch{}await loadSource(epoch);if(epoch!==loadEpoch)return;if(trainingApi.pendingTrainingCreation(projectId,draftScope))stage.value='unknown';ready.value=true;}catch(e){if(epoch===loadEpoch)error.value=(e as Error).message}finally{if(epoch===loadEpoch)busy.value=false}}
async function inspect(){try{if(source&&benchmark.value?.available&&benchmark.value.source_version_id===source.versionId&&(!draft.benchmarkReuseEnabled||draft.splitMode==='fixed_zip_train_val_test'||draft.testMaterialIds.length))throw new Error('请保留来源版本的固定 Test 基准');if(draft.splitMode==='fixed_zip_train_val_test'&&(!fixedPreview.value||fixedSignature.value!==JSON.stringify(fixedScope.value)||fixedPreview.value.issue_count||fixedPreview.value.conflict_count))throw new Error('请先完成无问题的固定 ZIP 划分预览');preview.value=payload();previewSignature.value=JSON.stringify(draft);finalConfirm.value=true;error.value='';}catch(e){error.value=(e as Error).message}}
async function diagnose(){busy.value=true;try{const signature=JSON.stringify(draft);const response=await trainingApi.trainingCompatibility(projectId,{...payload(),...identity.value,limit:50},controller.signal);if(controller.signal.aborted||JSON.stringify(draft)!==signature)return;diagnosis.value=response;diagnosisSignature.value=signature;diagnosisSelected.value=[];}catch(e){error.value=(e as Error).message}finally{busy.value=false}}
async function resolveExclusion(){if(draft.trainSelectionRef||!diagnosisSelected.value.length)return;if((diagnosis.value?.items||[]).some((row:any)=>row.issue_type==='content_hash_leakage'&&diagnosisSelected.value.includes(row.image_id))){error.value='内容重叠需要审核 Train / Test 角色调整';return;}busy.value=true;try{if(JSON.stringify(draft)!==diagnosisSignature.value)throw new Error('草稿已变化，请重新诊断');const response:any=await trainingApi.trainingCompatibility(projectId,{...payload(),...identity.value,selection_action:'RESOLVE_SELECTION',expected_material_revision:diagnosis.value.material_revision,expected_annotation_revision:diagnosis.value.annotation_revision,selection:{image_ids:diagnosisSelected.value}},controller.signal);if(controller.signal.aborted||JSON.stringify(draft)!==diagnosisSignature.value)return;resolvedExclusion.value=response;exclusionConfirmed.value=false;}catch(e){error.value=(e as Error).message}finally{busy.value=false}}
async function applyExclusion(){if(!resolvedExclusion.value||!exclusionConfirmed.value)return;busy.value=true;try{if(JSON.stringify(draft)!==diagnosisSignature.value)throw new Error('草稿已变化，请重新诊断');removeResolvedTrainingMaterials({update:(patch:any)=>Object.assign(draft,patch)},draft,resolvedExclusion.value.matching_image_ids,resolvedExclusion.value);for(const selection of [positive,negative]){const ids=selection.value.ids.filter(id=>draft.materialIds.includes(id));selection.value={...selection.value,ids,count:ids.length};}train.value={...train.value,ids:[...draft.materialIds],count:draft.materialIds.length,summary:null};test.value={...test.value,ids:[...draft.testMaterialIds],count:draft.testMaterialIds.length,summary:null};resolvedExclusion.value=null;for(const role of ['train','test'] as const){const selection=role==='train'?train:test;if(!selection.value.count)continue;const revision=await trainingApi.trainingMaterialRevision(projectId,algorithmId,controller.signal);const summary=await trainingApi.verifyTrainingSelection(projectId,{...identity.value,algorithm_asset_id:algorithmId,role,image_ids:selection.value.ids},revision,selection.value.count,controller.signal);if(controller.signal.aborted)return;selection.value={...selection.value,revision,summary};}diagnosis.value=null;error.value='已审计调整本次选择；创建前将重新执行全部准入核验';}catch(e){error.value=(e as Error).message}finally{busy.value=false}}
function negativeScope(){
 return {...identity.value,test_image_ids:draft.testMaterialIds,
   image_ids:draft.trainSelectionRef?negative.value.ids:draft.materialIds,
   rebind_train_reference:negative.value.count?positive.value.reference:undefined};
}
async function previewNegatives(){
 busy.value=true;
 try{negativePreview.value=await trainingApi.previewTrainingNegatives(projectId,negativeScope(),controller.signal);negativeConfirmed.value=false}
 catch(cause){error.value=(cause as Error).message}
 finally{busy.value=false}
}
async function confirmNegatives(){
 if(!negativeConfirmed.value||!negativePreview.value)return;
 busy.value=true;
 try{
  const receipt=await trainingApi.confirmTrainingNegatives(projectId,negativeScope(),negativePreview.value.proof_digest,controller.signal);
  negativePreview.value=null;
  if(positive.value.reference){
   if(!receipt.selection_ref||receipt.count!==positive.value.count)throw new Error('确认已保存，旧冻结引用已失效。请重新冻结正样本范围后合并。');
   positive.value={...positive.value,reference:receipt.selection_ref};
  }
  setTrain(await mergeSelections(positive.value,negative.value));
  error.value='';
 }catch(cause){error.value=(cause as Error).message}
 finally{busy.value=false}
}
async function submit(){if(!finalConfirm.value)return;if(JSON.stringify(draft)!==previewSignature.value){finalConfirm.value=false;error.value='草稿已变化，请重新预览确认';return;}busy.value=true;const signature=JSON.stringify(draft);try{stage.value='checking';result.value=await trainingApi.submitNativeTraining({projectId,receiptScope:draftScope,source,asset:asset.value,draft:JSON.parse(signature),target:target.value,engine:engine.value,devices:devices.value,trainSummary:train.value.summary,trainRevision:train.value.revision,testSummary:test.value.summary,testRevision:test.value.revision,backgroundConfirmed:backgroundConfirmed.value,benchmark:benchmark.value,fixedPreview:fixedPreview.value,fixedRequestId:fixedRequestId.value,stillCurrent:()=>!controller.signal.aborted&&JSON.stringify(draft)===signature,signal:controller.signal});taskId.value=result.value.task_id;stage.value='created';finalConfirm.value=false;}catch(e){error.value=(e as Error).message;try{stage.value=trainingApi.pendingTrainingCreation(projectId,draftScope)?'unknown':'idle';}catch(journalError){stage.value='unknown';error.value=(journalError as Error).message;}}finally{busy.value=false}}
async function recover(){busy.value=true;try{result.value=await trainingApi.recoverNativeTraining(projectId,controller.signal,draftScope);if(result.value){taskId.value=result.value.task_id;stage.value='created';}}catch(e){error.value=(e as Error).message}finally{busy.value=false}}
watch(()=>draft.splitMode,()=>{const normalized=createTrainingDraft(draft);draft.testMaterialIds=normalized.testMaterialIds;draft.experimentPercent=normalized.experimentPercent;draft.validationPercent=normalized.validationPercent;if(draft.splitMode!=='independent_test_set')test.value={ids:[],count:0};if(draft.splitMode==='fixed_zip_train_val_test'){if(!fixedSources.value.length)void loadFixedSources();if(!projectLabels.value.length)void loadProjectLabels();}});
watch(()=>JSON.stringify(draft),()=>{negativePreview.value=null;negativeConfirmed.value=false;poolEvidence.value=null;if(finalConfirm.value&&JSON.stringify(draft)!==previewSignature.value)finalConfirm.value=false;});
watch(()=>JSON.stringify({draft,train:train.value,positive:positive.value,negative:negative.value,test:test.value,targetId:targetId.value,engineKey:engineKey.value}),value=>{if(!ready.value)return;try{sessionStorage.setItem(draftStorageKey,value)}catch{} });
void load();
</script>
<template><main class="native-training-create"><header><h1>新建训练 · {{asset?.name||algorithmId}}</h1><p>{{base.hasPrevious?'继承当前已核验版本：'+draft.baseVersionId:'首次训练：选择母模型、正式标注素材及目标标签'}}</p><p v-if="source">来源版本 {{source.versionId}} · 冻结评测 {{source.evaluationId}}<template v-if="source.candidateSetId"> · 补数回执 {{source.candidateSetId}}</template></p></header><section><h2>选择训练算法</h2><form @submit.prevent="algorithmPage=1;searchAlgorithms()"><el-input v-model="algorithmQuery" placeholder="搜索算法"/><el-button native-type="submit">搜索</el-button></form><el-select :model-value="algorithmId" :disabled="!!source" @change="switchAlgorithm"><el-option v-for="row in algorithmOptions" :key="row.id" :value="row.id" :label="row.name||row.id"/></el-select><el-button :disabled="algorithmPage<=1" @click="algorithmPage--;searchAlgorithms()">上一页算法</el-button><el-button :disabled="algorithmPage*20>=algorithmTotal" @click="algorithmPage++;searchAlgorithms()">下一页算法</el-button></section><el-alert v-if="error" :title="error" type="error" :closable="false"/><el-skeleton v-if="busy&&!ready" :rows="8" animated/><template v-if="ready"><el-form :disabled="busy" label-position="top" @submit.prevent="inspect"><section class="form-grid"><el-form-item label="训练资源"><el-select v-model="targetId" @change="chooseTarget"><el-option v-for="row in targets" :key="row.id" :value="row.id" :label="row.name||row.id" :disabled="row.status!=='ready'"/></el-select></el-form-item><el-form-item label="算法引擎"><el-select v-model="engineKey" :disabled="base.hasPrevious"><el-option v-for="row in target?.algorithms||[]" :key="row.key" :value="row.key" :label="row.name||row.key"/></el-select></el-form-item><el-form-item label="母模型" v-if="!base.hasPrevious"><el-select v-model="draft.config.model"><el-option v-for="row in target?.base_models||[]" :key="row.value" :value="row.value" :label="row.name||row.value" :disabled="row.model_status!=='FOUND'||row.trainable===false"/></el-select></el-form-item><el-form-item label="训练模式"><el-select v-model="draft.trainingMode" @change="changeMode"><el-option value="quick" label="快速"/><el-option value="full" label="完整"/><el-option value="complex" label="复杂"/><el-option value="custom" label="自定义"/></el-select></el-form-item><el-form-item label="资源策略档位"><el-select v-model="draft.resource.profile" :disabled="draft.trainingMode!=='custom'"><el-option value="performance" label="性能优先"/><el-option value="balanced" label="均衡"/><el-option value="stability" label="稳定优先"/></el-select></el-form-item><el-form-item label="设备"><el-select v-model="draft.resource.device"><el-option value="auto" label="自动"/><el-option v-for="row in devices" :key="row.id" :value="row.id" :label="row.label" :disabled="row.available===false"/></el-select></el-form-item><el-form-item label="精度"><el-select v-model="draft.config.precision"><el-option value="auto" label="自动"/><el-option value="fp16" label="FP16"/><el-option value="fp32" label="FP32"/></el-select></el-form-item><el-form-item label="队列优先级"><el-input-number v-model="draft.priority" :min="1" :max="999"/></el-form-item></section><section><h2>Train / Val / Test</h2><el-form-item label="划分模式"><el-select v-model="draft.splitMode"><el-option value="random_test_from_training_pool" label="训练池随机 Test"/><el-option value="independent_test_set" label="独立 Test"/><el-option value="fixed_zip_train_val_test" label="按 ZIP 来源固定划分"/></el-select></el-form-item><template v-if="draft.splitMode==='fixed_zip_train_val_test'"><p>选择已归集的 ZIP 来源；未指定用途素材不会参与训练。</p><el-checkbox-group v-model="draft.zipSourceJobIds"><div v-for="source in fixedSources" :key="source.job_id"><el-checkbox :value="source.job_id">{{source.job_id}} · {{source.image_count}} 张</el-checkbox></div></el-checkbox-group><el-button v-if="fixedNext!==null" @click="loadFixedSources">加载更多来源</el-button><h3>正式 GT 标签</h3><el-checkbox-group v-model="draft.newLabelCodes"><el-checkbox v-for="code in projectLabels" :key="code" :value="code">{{code}}</el-checkbox></el-checkbox-group><el-checkbox v-model="backgroundConfirmed">我确认审核本次训练范围内全部背景素材</el-checkbox><el-button @click="previewFixed" :disabled="!draft.zipSourceJobIds.length">预览固定划分</el-button><div v-if="fixedPreview" aria-label="固定划分核验结果"><el-table :data="fixedRoleRows"><el-table-column prop="role" label="角色"/><el-table-column prop="total" label="素材"/><el-table-column prop="positive" label="正样本"/><el-table-column prop="negative" label="已确认负样本"/><el-table-column prop="pending" label="待确认"/><el-table-column prop="ineligible" label="资格不足"/></el-table><p>未指定 {{fixedPreview.unassigned}} 张 · 问题 {{fixedPreview.issue_count}} · 冲突 {{fixedPreview.conflict_count}}</p><ul v-if="fixedPreview.problems?.length"><li v-for="(problem,index) in fixedPreview.problems" :key="index">{{problem}}</li></ul></div></template><template v-else><el-button @click="picker='train'">选择训练素材 · 正样本组 {{positive.count}} 张</el-button><el-button @click="picker='negative'">从公共池添加负样本 · {{negative.count}} 张</el-button><p>合并后 {{train.count}} 张（去重）；正式角色以当前目标标签核验为准。</p><el-button v-if="negative.count&&!negative.reference" @click="checkPool">核验公共池负样本资格</el-button><p v-if="negative.reference">已通过角色筛选并冻结 {{negative.count}} 张负样本；提交时复核引用证据。</p><p v-if="poolEvidence">目标正样本 {{poolEvidence.counts.positive}} · 已确认负样本 {{poolEvidence.counts.confirmed_negative}} · 待确认 {{poolEvidence.pending_count}} · 待审核 {{poolEvidence.counts.pending_review}}</p><el-form-item label="历史素材复用"><el-select v-model="draft.history_policy" :disabled="train.count>0"><el-option value="new_for_algorithm" label="仅本算法新素材"/><el-option value="include_history" label="包含历史"/></el-select></el-form-item><el-form-item label="Val 比例 %"><el-input-number v-model="draft.validationPercent" :min="1" :max="99"/></el-form-item><el-form-item v-if="draft.splitMode==='random_test_from_training_pool'" label="Test 比例 %"><el-input-number v-model="draft.experimentPercent" :min="1" :max="99"/></el-form-item><el-button v-else @click="picker='test'">选择独立 Test · {{test.count}} 张</el-button><p>Train 比例 {{100-draft.validationPercent-(draft.splitMode==='random_test_from_training_pool'?draft.experimentPercent:0)}}%；独立 Test 与训练素材不得重叠。</p><h3>正式 GT 标签</h3><p>标签来自已选素材的服务器正式标注摘要；选择素材后可选。</p><el-checkbox-group v-model="draft.newLabelCodes"><el-checkbox v-for="code in labels" :key="code" :value="code">{{code}}</el-checkbox></el-checkbox-group></template></section><details><summary>高级参数 · {{draft.trainingMode==='custom'?'自定义值生效':'预设模式由正式策略决定参数'}}</summary><div class="form-grid"><el-form-item v-for="[key,label] in numericFields" :key="key" :label="label"><el-input-number v-model="draft.config[key]" :disabled="draft.trainingMode!=='custom'"/></el-form-item><el-form-item label="Batch"><el-input-number v-model="draft.resource.batch" :disabled="draft.trainingMode!=='custom'"/></el-form-item><el-form-item label="Workers"><el-input-number v-model="draft.resource.workers" :disabled="draft.trainingMode!=='custom'"/></el-form-item><el-form-item label="Cache"><el-select v-model="draft.resource.cache" :disabled="draft.trainingMode!=='custom'"><el-option v-for="value in ['False','True','ram','disk']" :key="value" :value="value" :label="value"/></el-select></el-form-item><el-form-item label="评测指标"><el-select v-model="draft.config.eval_metric" :disabled="draft.trainingMode!=='custom'"><el-option value="map50" label="mAP50"/><el-option value="map50_95" label="mAP50-95"/></el-select></el-form-item><el-form-item label="Optimizer"><el-input v-model="draft.config.optimizer" :disabled="draft.trainingMode!=='custom'"/></el-form-item><el-checkbox v-for="[key,label] in booleanFields" :key="key" v-model="draft.config[key]" :disabled="draft.trainingMode!=='custom'">{{label}}</el-checkbox></div></details><section><h2>跨设备颜色鲁棒性</h2><p v-if="draft.splitMode==='fixed_zip_train_val_test'">固定 ZIP 划分使用已确认的原始成员。若全局启用了增强，请关闭本任务的跨设备颜色鲁棒性。</p><p v-else>仅训练集生成增强副本，Val 与 Test 保留原图；实际增强数量以 Worker 回执为准。</p><el-select v-model="draft.robustness_policy.mode" @change="robustnessMode"><el-option value="inherit" label="继承全局默认"/><el-option value="enabled" label="本任务启用"/><el-option value="disabled" label="本任务禁用"/></el-select><template v-if="draft.robustness_policy.mode==='enabled'"><el-select v-model="draft.robustness_policy.selection.mode"><el-option value="ratio" label="按训练集比例"/><el-option value="count" label="按数量"/><el-option value="manual" label="手动选图"/></el-select><el-input-number v-if="draft.robustness_policy.selection.mode==='ratio'" v-model="draft.robustness_policy.selection.ratio" :min="1" :max="100"/><el-input-number v-if="draft.robustness_policy.selection.mode==='count'" v-model="draft.robustness_policy.selection.count" :min="1"/><div v-if="draft.robustness_policy.selection.mode==='manual'"><el-button :disabled="!train.count" @click="picker='robustness'">选择训练范围内增强原图</el-button><span>已选 {{draft.robustness_policy.selection.image_ids?.length||0}} 张</span></div><el-form-item label="每图副本数"><el-input-number v-model="draft.robustness_policy.copies" :min="1" :max="3"/></el-form-item><el-form-item label="随机种子"><el-input-number v-model="draft.robustness_policy.seed" :min="0"/></el-form-item><el-checkbox-group v-model="draft.robustness_policy.presets"><el-checkbox v-for="value in ['bt601_limited','bt601_full','bt709_limited','bt709_full']" :key="value" :value="value">{{value}}</el-checkbox></el-checkbox-group></template></section><section><h2>训练结束自动转换</h2><el-checkbox-group v-model="draft.config.auto_convert_targets"><el-checkbox value="ascend">华为 Atlas</el-checkbox><el-checkbox value="rockchip">瑞芯微</el-checkbox><el-checkbox value="sophon">算能</el-checkbox></el-checkbox-group></section><section v-if="draft.splitMode!=='fixed_zip_train_val_test'"><h2>正式素材诊断</h2><el-button :disabled="busy||!train.count" @click="diagnose">执行正式素材诊断</el-button><template v-if="diagnosis"><p>问题 {{diagnosis.issue_count||0}} 项；每次最多展示 50 项。内容重叠须回到 Train / Test 选择调整，不提供直接排除。</p><el-checkbox-group v-model="diagnosisSelected"><div v-for="row in (diagnosis.items||[])" :key="row.image_id+':'+row.issue_type"><el-checkbox :value="row.image_id" :disabled="!!draft.trainSelectionRef||(diagnosis.items||[]).some((item:any)=>item.image_id===row.image_id&&item.issue_type==='content_hash_leakage')">{{row.filename||row.image_id}} · {{row.issue_type}}</el-checkbox></div></el-checkbox-group><el-button :disabled="busy||!!draft.trainSelectionRef||!diagnosisSelected.length" @click="resolveExclusion">核验人工选择的排除范围</el-button></template><el-dialog :model-value="!!resolvedExclusion" title="确认仅调整本次训练选择" :close-on-click-modal="false" @close="resolvedExclusion=null"><p>将从本次 Train / Test 选择排除 {{resolvedExclusion?.matching_image_ids?.length||0}} 张；保留素材库、正式 GT 与历史证据。</p><el-checkbox v-model="exclusionConfirmed">我已审核上述问题，确认仅从本次训练选择中排除</el-checkbox><template #footer><el-button @click="resolvedExclusion=null">取消</el-button><el-button :disabled="!exclusionConfirmed||busy" @click="applyExclusion">确认排除并重新核验</el-button></template></el-dialog></section><section v-if="draft.splitMode!=='fixed_zip_train_val_test'"><h2>评测与背景核验</h2><p v-if="recommendation">实时建议仅作参考，不覆盖当前草稿：{{ recommendation.recommendation||recommendation }}</p><el-checkbox v-model="draft.benchmarkReuseEnabled" :disabled="!benchmark?.available||!!source">复用当前版本基准 Test · {{benchmark?.test_image_count||0}} 张</el-checkbox><p>{{benchmark?.reason}}</p><el-checkbox v-model="backgroundConfirmed">我确认审核本次训练范围内全部背景素材，允许后台正式资格核验</el-checkbox><el-button @click="previewNegatives" :disabled="busy||!train.count||(!!draft.trainSelectionRef&&(!negative.count||!!negative.reference))">预览待确认负样本证据</el-button><template v-if="negativePreview"><p>待确认 {{negativePreview.pending_count}} 张</p><ul><li v-for="row in negativePreview.pending_preview" :key="row.image_id">{{row.filename||row.image_id}}</li></ul><el-checkbox v-model="negativeConfirmed">我已人工核对当前标签目标不存在，确认以上负样本证据</el-checkbox><el-button :disabled="busy||!negativeConfirmed" @click="confirmNegatives">确认负样本</el-button></template></section><el-dialog v-model="finalConfirm" title="确认本次训练" :close-on-click-modal="false"><p>素材 {{train.count}} 张；标签 {{draft.newLabelCodes.join('、')||'继承版本合同'}}；实际 Worker 与冻结划分在任务创建后确认。</p><details class="training-confirm-evidence"><summary>查看本次核验证据</summary><pre>{{JSON.stringify(preview,null,2)}}</pre></details><template #footer><el-button @click="finalConfirm=false" :disabled="busy">返回修改</el-button><el-button type="primary" @click="submit" :loading="busy">确认核验并创建</el-button></template></el-dialog><footer><el-button v-if="stage==='unknown'" :disabled="busy" @click="recover">核验原任务结果</el-button><el-button type="primary" native-type="submit" :disabled="busy||stage==='unknown'||stage==='created'">核验并创建训练</el-button><a v-if="stage==='created'" :href="'/app/#/projects/'+encodeURIComponent(projectId)+'/training/tasks?task='+encodeURIComponent(taskId)">查看训练任务</a><span v-if="taskId">任务 {{taskId}} · {{stage}}</span></footer></el-form><el-dialog :model-value="!!picker" width="90%" :close-on-click-modal="false" @close="picker=null"><TrainingMaterials v-if="picker" :key="picker" :project-id="projectId" :identity="identity" :role="picker==='test'?'test':'train'" :pool-only="picker==='negative'" :positive-only="picker==='train'" :explicit-only="picker==='robustness'" :allowed-reference="picker==='robustness'?draft.trainSelectionRef:undefined" :allowed-ids="picker==='robustness'&&!draft.trainSelectionRef?draft.materialIds:undefined" :initial="picker==='robustness'?{ids:draft.robustness_policy.selection.image_ids||[],count:draft.robustness_policy.selection.image_ids?.length||0}:picker==='train'?positive:picker==='negative'?negative:test" @confirm="selected" @cancel="picker=null"/></el-dialog></template></main></template>
<style scoped>
.native-training-create { max-width: 1440px; margin: auto; min-width: 0; }
.native-training-create header { padding-block: 0 8px; }
.native-training-create h1 { margin: 0 0 5px; font-size: 21px; }
.native-training-create h2 { font-size: 16px; margin: 0 0 12px; }
.native-training-create p { color: var(--workspace-muted); overflow-wrap: anywhere; }
.native-training-create > section > form { display: flex; gap: 8px; flex-wrap: wrap; }
.native-training-create > section > form :deep(.el-input) { width: min(100%, 260px); }
.form-grid { display: grid; grid-template-columns: repeat(auto-fit,minmax(min(100%,205px),1fr)); gap: 4px 16px; }
.form-grid :deep(.el-select) { width: 100%; }
.native-training-create section, .native-training-create details {
  min-width: 0; background: var(--workspace-surface); padding: 16px;
  margin-block: 0 12px; border-radius: var(--workspace-radius);
}
.native-training-create section details { border-top: 1px solid var(--workspace-line); padding-inline: 0; margin-block-end: 0; border-radius: 0; }
.native-training-create summary { font-weight: 600; cursor: pointer; }
.native-training-create footer { display: flex; flex-wrap: wrap; gap: 8px 12px; align-items: center; padding: 10px 0; }
.training-confirm-evidence summary { color: var(--workspace-muted); }
.training-confirm-evidence pre { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12px; }
</style>

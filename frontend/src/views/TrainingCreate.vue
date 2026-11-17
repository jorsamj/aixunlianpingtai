<script setup lang="ts">
import {computed,onBeforeUnmount,onMounted,ref,shallowRef} from 'vue';
import type {TrainingCreateContext} from '../types/training-create';
import ReadOnlyFacts from '../components/ReadOnlyFacts.vue';
const props=defineProps<{context:TrainingCreateContext}>();
const s=shallowRef(props.context.snapshot()),stepOne=ref<HTMLElement>(),stepTwo=ref<HTMLElement>(),stepThree=ref<HTMLElement>(),footer=ref<HTMLElement>();
const steps=[{id:1,title:'算法与数据',detail:'算法、母版本、素材与训练标签'},{id:2,title:'方案与参数',detail:'训练模式、精度、资源和分组参数'},{id:3,title:'核对与创建',detail:'核对原提交预览并明确确认'}];
const modes:Record<string,string>={quick:'快速训练',full:'完整训练',complex:'复杂训练',custom:'自定义配置'};
const precisions:Record<string,string>={auto:'自动',fp16:'FP16',bf16:'BF16',fp32:'FP32'};
const mode=computed(()=>s.value.trainingMode?(modes[s.value.trainingMode]||s.value.trainingMode):undefined);
const precision=computed(()=>s.value.precision?(precisions[s.value.precision]||s.value.precision):undefined);
const split=computed(()=>s.value.splitMode==='independent_test_set'?'独立 Test':s.value.splitMode==='random_test_from_training_pool'?'从训练素材抽取 Test':s.value.splitMode);
const disabled=computed(()=>Boolean(s.value.busy||s.value.loading||props.context.signal.aborted));
let stop:(()=>void)|undefined,alive=true;
const mountedNodes:HTMLElement[]=[];
function detach(){stop?.();stop=undefined;for(const node of mountedNodes){if([stepOne.value,stepTwo.value,stepThree.value,footer.value].some(host=>host?.contains(node)))node.remove()}mountedNodes.length=0;props.context.signal.removeEventListener('abort',detach)}
onMounted(()=>{
 if(props.context.signal.aborted)return;
 const hosts=[stepOne.value,stepTwo.value,stepThree.value];
 props.context.slots.steps.forEach((node,index)=>{const host=hosts[index];if(host){host.appendChild(node);mountedNodes.push(node)}});
 if(footer.value){footer.value.appendChild(props.context.slots.footer);mountedNodes.push(props.context.slots.footer)}
 stop=props.context.subscribe(value=>{if(alive&&!props.context.signal.aborted)s.value=value});
 props.context.signal.addEventListener('abort',detach,{once:true});
});
onBeforeUnmount(()=>{alive=false;detach()});
</script>
<template><section class="vue-training-create" aria-label="Vue 三步训练创建工作台" :aria-busy="s.busy||s.loading">
 <header class="create-header"><div><small>训练管理 / 创建任务</small><h2>{{ s.algorithmName||'创建训练任务' }}</h2><p>项目 {{ s.projectId }}<span v-if="s.algorithmId"> · 算法 {{ s.algorithmId }}</span></p></div><el-button :disabled="disabled" @click="context.actions.legacy()">使用原创建界面</el-button></header>
 <nav class="create-steps" aria-label="训练创建步骤"><el-button v-for="item in steps" :key="item.id" :type="s.step===item.id?'primary':'default'" :aria-current="s.step===item.id?'step':undefined" :disabled="disabled" @click="context.actions.step(item.id)"><span class="step-number">{{ item.id }}</span><span><strong>{{ item.title }}</strong><small>{{ item.detail }}</small></span></el-button></nav>
 <el-alert v-if="s.error" :title="s.error" type="error" :closable="false"/>
 <div v-if="s.loading" class="create-loading" role="status">正在读取原训练配置…</div>
 <div class="create-body"><main class="create-panels">
  <section v-show="s.step===1" class="create-step" aria-label="算法与数据"><div class="step-intro"><h3>选择算法、数据与标签</h3><p>原训练草稿保留母版本、素材选择及标签合同。</p></div><div ref="stepOne" class="owner-step-slot" data-training-create-slot="1"></div></section>
  <section v-show="s.step===2" class="create-step" aria-label="训练方案与分组参数"><div class="step-intro"><h3>配置训练方案与资源</h3><p>快速、完整、复杂与自定义方案继续使用原预设和参数校验。</p><div class="current-plan"><span>当前方案：{{ mode||'未提供' }}</span><span>请求精度：{{ precision||'未提供' }}</span></div></div><div ref="stepTwo" class="owner-step-slot" data-training-create-slot="2"></div></section>
  <section v-show="s.step===3" class="create-step" aria-label="最终训练确认"><div class="step-intro"><h3>核对本次训练</h3><p>以下为原草稿及提交预览；实际执行参数与 Train / Val / Test 划分以原任务结果为准。</p></div><div ref="stepThree" class="owner-step-slot" data-training-create-slot="3"></div></section>
 </main><aside class="create-summary" aria-label="当前训练事实摘要"><h3>本次训练</h3><ReadOnlyFacts :fields="[['任务名称',s.taskName],['算法',s.algorithmName||s.algorithmId],['母版本',s.baseVersionName],['模型',s.model],['框架',s.framework],['训练方案',mode],['请求精度',precision]]"/>
  <h4>数据与标签</h4><ReadOnlyFacts :fields="[['训练素材选中数量',s.trainCount],['服务器冻结选择数量',s.frozenCount],['Test 划分方式',split],['独立 Test 选中数量',s.testCount],['Val 比例（%）',s.validationPercent],['随机 Test 比例（%）',s.experimentPercent],['本次训练标签',s.labels===undefined?undefined:s.labels.length?s.labels.join('、'):'尚未选择']]"/>
  <h4>资源事实</h4><ReadOnlyFacts :fields="[['资源',s.resource?.name],['资源状态',s.resource?.status],['请求设备',s.resource?.device],['资源说明',s.resource?.detail]]"/><p class="summary-note">请求精度与资源选择不代表 Worker 已分配或实际执行已通过。</p>
  <details v-if="s.parameters?.length"><summary>训练参数摘要</summary><dl class="parameter-summary"><template v-for="(row,index) in s.parameters" :key="index"><dt>{{ row.name }}<small v-if="row.source">{{ row.source }}</small></dt><dd>{{ row.value??'未提供' }}</dd></template></dl></details>
 </aside></div>
 <div v-if="s.status&&s.status!=='idle'" class="create-state" role="status" aria-live="polite"><strong v-if="s.submit?.state">{{ s.submit.state }}</strong><span>{{ s.submit?.message||s.status }}</span><small v-if="s.submit?.requestId">请求 {{ s.submit.requestId }}</small></div>
 <footer ref="footer" class="owner-footer-slot" data-training-create-slot="footer" aria-label="原训练提交操作"></footer>
</section></template>
<style scoped>
.vue-training-create{height:100%;overflow:hidden;display:flex;flex-direction:column;min-width:0;min-height:0;width:100%;color:var(--el-text-color-primary,#303133);background:var(--el-bg-color,#fff)}.create-header{display:flex;justify-content:space-between;align-items:center;gap:16px;padding:18px 20px;border-bottom:1px solid var(--el-border-color-lighter,#ebeef5)}.create-header h2{margin:4px 0;font-size:20px}.create-header small,.create-header p{margin:0;color:var(--el-text-color-secondary,#909399);font-size:12px;overflow-wrap:anywhere}.create-steps{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;padding:16px 20px;border-bottom:1px solid var(--el-border-color-lighter,#ebeef5)}.create-steps :deep(.el-button){margin:0;height:auto;padding:12px;text-align:left;justify-content:flex-start}.create-steps :deep(.el-button>span){white-space:normal;display:flex;align-items:center;gap:10px}.create-steps strong{display:block}.create-steps small{display:block;font-size:11px;margin-top:5px;line-height:1.4;font-weight:400}.step-number{font-size:18px;min-width:20px}.create-body{flex:1;min-height:0;overflow-y:auto;overscroll-behavior:contain;display:grid;grid-template-columns:minmax(0,1fr) minmax(240px,300px);align-items:start;gap:20px;padding:20px;background:var(--el-fill-color-lighter,#fafafa)}.create-panels{min-width:0}.step-intro{margin-bottom:14px}.step-intro h3{font-size:17px;margin:0 0 6px}.step-intro p{font-size:13px;line-height:1.6;color:var(--el-text-color-secondary,#777);margin:0}.current-plan{display:flex;gap:16px;flex-wrap:wrap;font-size:13px;margin-top:10px}.owner-step-slot{min-width:0}.owner-step-slot :deep(.training-workbench-panel){min-width:0}.create-summary{padding:16px;border:1px solid var(--el-border-color-lighter,#ebeef5);border-radius:8px;background:var(--el-bg-color,#fff);overflow-wrap:anywhere}.create-summary h3{font-size:15px;margin:0 0 14px}.create-summary h4{font-size:13px;margin:18px 0 10px}.create-summary :deep(.readonly-facts){grid-template-columns:minmax(90px,.8fr) minmax(0,1.2fr);font-size:12px}.summary-note{font-size:12px;line-height:1.6;color:var(--el-text-color-secondary,#777)}.parameter-summary{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:9px;font-size:12px}.parameter-summary dt small{display:block;color:var(--el-text-color-secondary,#777);margin-top:3px}.parameter-summary dd{margin:0;overflow-wrap:anywhere}.owner-footer-slot{flex:0 0 auto;border-top:1px solid var(--el-border-color-lighter,#ebeef5);padding:12px 20px;background:var(--el-bg-color,#fff)}.owner-footer-slot :deep(.train428-footer){margin:0;padding:0;border:0;flex-wrap:wrap}.create-state{display:flex;gap:10px;flex-wrap:wrap;padding:10px 20px;font-size:13px;border-top:1px solid var(--el-border-color-lighter,#ebeef5);overflow-wrap:anywhere}.create-loading{padding:12px 20px;font-size:13px}
@media(max-width:1000px){.create-body{grid-template-columns:minmax(0,1fr) 245px;gap:12px;padding:14px}.create-summary{padding:12px}.create-steps{padding:12px}.create-steps small{display:none}}
@media(max-width:760px){.create-body{grid-template-columns:minmax(0,1fr)}.create-summary{margin-top:4px}.create-header{padding:12px;align-items:flex-start}.create-header h2{font-size:17px}.create-steps{gap:6px;padding:10px}.create-steps :deep(.el-button){padding:10px 5px}.create-steps :deep(.el-button>span){gap:5px}.step-number{font-size:15px;min-width:14px}.create-steps strong{font-size:12px}.owner-footer-slot{padding:10px}}
</style>

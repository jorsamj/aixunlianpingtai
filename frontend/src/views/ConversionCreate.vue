<script setup lang="ts">
import {computed,onBeforeUnmount,onMounted,ref,shallowRef} from 'vue';
import type {ConversionCreateContext} from '../types/conversion-create';
import ReadOnlyFacts from '../components/ReadOnlyFacts.vue';
const props=defineProps<{context:ConversionCreateContext}>(),s=shallowRef(props.context.snapshot());
const body=ref<HTMLElement>(),footer=ref<HTMLElement>();
const targets:Record<string,string>={onnx:'ONNX',paddle_inference:'Paddle Inference',tensorrt:'TensorRT',rockchip:'RKNN',sophon:'Sophon BMODEL',ascend:'Ascend OM'};
const target=computed(()=>s.value.target?(targets[s.value.target]||s.value.target):undefined);
const evidence=(value:boolean|null|undefined,yes:string,no:string)=>value===true?yes:value===false?no:'尚未提供';
let alive=true,stop:(()=>void)|undefined;
const ownedNodes:HTMLElement[]=[];
function detach(){stop?.();stop=undefined;for(const node of ownedNodes){if(body.value?.contains(node)||footer.value?.contains(node))node.remove()}ownedNodes.length=0;props.context.signal.removeEventListener('abort',detach)}
onMounted(()=>{
 if(props.context.signal.aborted)return;
 if(body.value){body.value.appendChild(props.context.slots.body);ownedNodes.push(props.context.slots.body)}
 if(footer.value&&props.context.slots.footer){footer.value.appendChild(props.context.slots.footer);ownedNodes.push(props.context.slots.footer)}
 stop=props.context.subscribe(value=>{if(alive&&!props.context.signal.aborted)s.value=value});
 props.context.signal.addEventListener('abort',detach,{once:true});
});
onBeforeUnmount(()=>{alive=false;detach()});
</script>
<template><section class="vue-conversion-create" aria-label="Vue 模型转换创建工作台" :aria-busy="s.busy">
 <header class="create-header"><div><small>模型管理 / 版本转换</small><h2>新建模型转换</h2><p>项目 {{ s.projectId }}<span v-if="s.algorithmName||s.algorithmId"> · 算法 {{ s.algorithmName||s.algorithmId }}</span><span v-if="s.versionName||s.versionId"> · 版本 {{ s.versionName||s.versionId }}</span></p></div><div class="header-actions"><el-button :disabled="s.busy||context.signal.aborted" @click="context.actions.legacy()">使用原转换界面</el-button><el-button :disabled="context.signal.aborted" @click="context.actions.close()">关闭</el-button></div></header>
 <div v-if="s.error" class="create-error" role="alert">{{ s.error }}</div>
 <div v-if="s.pending" class="pending-request" role="status" aria-live="polite"><strong>原转换请求结果待核验</strong><span v-if="s.pending.requestId">请求 {{ s.pending.requestId }}</span><span v-if="s.pending.state">{{ s.pending.state }}</span><p>{{ s.pending.message||'继续使用原请求核验与安全重试入口，不据此认定转换创建成功。' }}</p></div>
 <div class="create-layout"><main class="configuration-main" aria-label="原转换配置与能力校验"><div class="section-intro"><h3>转换配置</h3><p>源版本、目标格式、厂商芯片、资源与模板参数沿用原转换合同。</p></div><div ref="body" class="owner-body-slot" data-conversion-create-slot="body"></div></main>
 <aside class="conversion-summary" aria-label="当前转换事实摘要"><h3>当前配置</h3><ReadOnlyFacts :fields="[['源模型',s.sourceName],['版本',s.versionName||s.versionId],['源版本引用',evidence(s.sourceReady,'源引用已读取，完整性由原提交核验','源版本引用尚未就绪')],['目标格式',target],['请求精度',s.precision],['输入尺寸',s.inputSize],['目标芯片',s.chip]]"/>
  <h4>资源与 SDK</h4><ReadOnlyFacts :fields="[['转换资源',s.resourceName],['资源状态',s.resourceStatus],['SDK 版本',s.sdkVersion],['资源事实时效',evidence(s.resourcesCurrent,'已读取当前资源事实','当前资源事实尚未确认')],['厂商目录',s.catalogState]]"/>
  <h4>配置合同</h4><ReadOnlyFacts :fields="[['配置校验',evidence(s.contractReady,'原合同允许提交','原合同尚未允许提交')]]"/><ul v-if="s.contractErrors?.length" class="contract-errors"><li v-for="(message,index) in s.contractErrors" :key="index">{{ message }}</li></ul>
  <template v-if="s.parameters?.length"><h4>原参数与来源</h4><dl class="parameter-facts"><template v-for="(row,index) in s.parameters" :key="index"><dt>{{ row.name }}<small v-if="row.source">{{ row.source }}</small></dt><dd>{{ row.value??'未提供' }}</dd></template></dl></template>
  <h4>独立证据</h4><ReadOnlyFacts :fields="[['产物状态',s.artifactStatus],['数值验证',s.numericStatus],['目标硬件验证',s.hardwareStatus],['发布状态',s.publicationStatus]]"/><p class="evidence-note">配置允许提交、任务受理、产物生成、数值一致性、目标硬件运行与发布分别记录，不互相代替。</p>
 </aside></div>
 <div v-if="s.status" class="create-status" role="status" aria-live="polite">{{ s.status }}</div>
 <footer ref="footer" class="owner-footer-slot" data-conversion-create-slot="footer" aria-label="原转换提交与刷新操作"></footer>
</section></template>
<style scoped>
.vue-conversion-create{height:min(74dvh,850px);overflow:hidden;display:flex;flex-direction:column;min-width:0;width:100%;background:var(--el-bg-color,#fff);color:var(--el-text-color-primary,#303133)}.create-header{flex:0 0 auto;display:flex;justify-content:space-between;align-items:center;gap:16px;padding:18px 20px;border-bottom:1px solid var(--el-border-color-lighter,#ebeef5)}.create-header h2{margin:5px 0;font-size:20px}.create-header small,.create-header p{margin:0;font-size:12px;line-height:1.6;color:var(--el-text-color-secondary,#777);overflow-wrap:anywhere}.header-actions{display:flex;gap:8px;flex-shrink:0}.header-actions :deep(.el-button){margin:0}.create-layout{flex:1;min-height:0;overflow-y:auto;overscroll-behavior:contain;display:grid;grid-template-columns:minmax(0,1fr) minmax(250px,300px);gap:20px;align-items:start;padding:20px;background:var(--el-fill-color-lighter,#fafafa)}.configuration-main,.owner-body-slot{min-width:0}.section-intro{margin-bottom:14px}.section-intro h3{font-size:17px;margin:0 0 6px}.section-intro p{font-size:13px;line-height:1.6;margin:0;color:var(--el-text-color-secondary,#777)}.owner-body-slot :deep(section){min-width:0}.owner-body-slot :deep(.form){min-width:0}.owner-body-slot :deep(input),.owner-body-slot :deep(select){max-width:100%;box-sizing:border-box}.owner-body-slot :deep(pre){white-space:pre-wrap;overflow-wrap:anywhere;max-width:100%}.conversion-summary{min-width:0;padding:16px;border:1px solid var(--el-border-color-lighter,#ebeef5);border-radius:8px;background:var(--el-bg-color,#fff);overflow-wrap:anywhere}.conversion-summary h3{font-size:15px;margin:0 0 14px}.conversion-summary h4{font-size:13px;margin:18px 0 10px}.conversion-summary :deep(.readonly-facts){grid-template-columns:minmax(80px,.8fr) minmax(0,1.2fr);font-size:12px;gap:8px}.evidence-note{font-size:12px;line-height:1.6;color:var(--el-text-color-secondary,#777)}.parameter-facts{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:9px;font-size:12px}.parameter-facts dt small{display:block;margin-top:3px;color:var(--el-text-color-secondary,#777)}.parameter-facts dd{margin:0;overflow-wrap:anywhere}.contract-errors{padding-left:18px;font-size:12px;line-height:1.7}.create-error{padding:12px 20px;color:var(--el-color-danger,#f56c6c);overflow-wrap:anywhere}.pending-request{display:flex;gap:10px;flex-wrap:wrap;padding:12px 20px;background:var(--el-color-warning-light-9,#fdf6ec);font-size:13px;overflow-wrap:anywhere}.pending-request p{flex-basis:100%;margin:0;line-height:1.6}.create-status{flex:0 0 auto;padding:10px 20px;border-top:1px solid var(--el-border-color-lighter,#ebeef5);font-size:13px;overflow-wrap:anywhere}.owner-footer-slot{flex:0 0 auto;padding:12px 20px;border-top:1px solid var(--el-border-color-lighter,#ebeef5);background:var(--el-bg-color,#fff)}.owner-footer-slot:empty{display:none}.owner-footer-slot :deep(.row){margin:0;flex-wrap:wrap}
@media(max-width:1000px){.create-layout{grid-template-columns:minmax(0,1fr) 245px;gap:12px;padding:14px}.conversion-summary{padding:12px}.create-header{padding:14px}.create-header h2{font-size:18px}}
@media(max-width:760px){.create-layout{grid-template-columns:minmax(0,1fr);padding:12px}.create-header{align-items:flex-start;flex-wrap:wrap;padding:12px}.header-actions{flex-wrap:wrap}.owner-body-slot :deep(.form.two),.owner-body-slot :deep(.form.three){grid-template-columns:minmax(0,1fr)}.owner-footer-slot{flex:0 0 auto;padding:10px 12px}}
</style>

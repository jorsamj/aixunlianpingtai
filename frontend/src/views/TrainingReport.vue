<script setup lang="ts">
import {onMounted,ref} from 'vue';
import type {BrowseContext} from '../types/model-browse';
import {trainingReaderApi,type TrainingReport} from '../api/training-reader';
import {useReadScope} from '../composables/useReadScope';
import PageHeader from '../components/PageHeader.vue';
import ReadOnlyFacts from '../components/ReadOnlyFacts.vue';
const props=defineProps<{context:BrowseContext}>(),api=trainingReaderApi(props.context),reads=useReadScope(props.context),selection=props.context.memory.report,report=ref<TrainingReport|null>(null);
const stateLabels:Record<string,string>={AVAILABLE:'已有报告摘要',PARTIAL:'仅有已记录训练结果',NOT_GENERATED:'报告尚未生成',NOT_FOUND:'报告或任务记录不存在',ERROR:'报告记录读取异常',DEFERRED:'报告超出摘要读取边界'};
function load(){if(!selection)return;report.value=null;return reads.run('report',signal=>api.report(selection,signal),value=>{report.value=value})}
function back(){if(selection?.returnPage==='tasks')props.context.openTasks?.();else props.context.returnToAssets()}
function legacy(){if(selection)props.context.legacyReport?.({...selection,algorithmId:report.value?.algorithm_id||selection.algorithmId,versionId:report.value?.version_id||selection.versionId})}
onMounted(()=>void load());
</script>
<template><section class="catalog-preview" aria-label="训练报告与模型质量"><PageHeader title="训练报告与模型质量" eyebrow="训练管理 / 报告阅读" description="只展示已有训练与评测证据，Val 和独立 Test 分开。" badge="只读报告" @back="back"/>
<div class="browse-context"><div><strong>{{ selection?.jobId||'尚未选择任务或版本' }}</strong><small>项目 {{ context.projectId }} · 算法 {{ report?.algorithm_id||selection?.algorithmId||'未提供' }} · 版本 {{ report?.version_id||selection?.versionId||'未提供' }}</small></div><div class="preview-actions"><el-button @click="back">返回来源列表</el-button><el-button :disabled="!selection||reads.busy.report" @click="load">重新读取报告</el-button></div></div>
<el-alert v-if="reads.errors.report" :title="reads.errors.report" type="error" :closable="false"/><el-skeleton v-if="reads.busy.report" :rows="10" animated/>
<template v-else-if="report"><div class="report-state"><el-tag type="info" effect="plain">{{ stateLabels[report.state]||report.state }}</el-tag><span>{{ report.source||'来源未提供' }}</span><p v-if="report.message">{{ report.message }}</p></div>
<div v-if="report.val_metrics||report.test_metrics" class="report-metrics"><section class="browse-panel"><header><h2>Val 指标</h2></header><ReadOnlyFacts :fields="Object.entries(report.val_metrics||{})"/></section><section class="browse-panel"><header><h2>独立 Test 指标</h2></header><ReadOnlyFacts :fields="[['评测状态',report.test_status],...Object.entries(report.test_metrics||{})]"/></section></div>
<section v-if="report.configuration||report.result" class="browse-panel report-section"><h2>配置与执行结果</h2><ReadOnlyFacts :fields="Object.entries(report.configuration||{})"/><ReadOnlyFacts :fields="Object.entries(report.result||{})"/></section>
<section v-if="report.credibility||report.warnings?.length" class="browse-panel report-section"><h2>质量与预警</h2><ReadOnlyFacts :fields="Object.entries(report.credibility||{})"/><ul v-if="report.warnings?.length"><li v-for="(warning,index) in report.warnings" :key="index">{{ warning }}</li></ul><p v-else class="evidence-note">没有提供预警证据，不能据此认定质量验收通过。</p></section>
<section v-if="report.history?.length" class="browse-panel report-section"><h2>已保存训练过程</h2><el-table :data="report.history" max-height="360"><el-table-column v-for="key in ['epoch','map50','precision','recall','box_loss','val_box_loss']" :key="key" :prop="key" :label="key" min-width="80" :formatter="(_row:any,_column:any,value:any)=>value??'未提供'"/></el-table><p v-if="report.history_truncated" class="evidence-note">摘要仅展示最后200条记录，完整过程见原报告。</p></section>
</template><el-empty v-else-if="!selection" description="请从训练任务或算法版本选择报告"/>
<div v-if="selection" class="management-actions"><el-button @click="legacy">原完整报告：PR 曲线 / 混淆矩阵 / 错误样本</el-button></div></section></template>

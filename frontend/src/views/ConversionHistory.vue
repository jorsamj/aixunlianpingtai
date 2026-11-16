<script setup lang="ts">
import {onMounted,reactive,ref} from 'vue';
import type {BrowseContext,ConversionPage,ConversionRecord} from '../types/model-browse';
import {modelBrowseApi,shownValue} from '../api/model-browse';
import {useReadScope} from '../composables/useReadScope';
import PageHeader from '../components/PageHeader.vue';
import ReadOnlyFacts from '../components/ReadOnlyFacts.vue';
const props=defineProps<{context:BrowseContext}>(),api=modelBrowseApi(props.context),reads=useReadScope(props.context);
const selection=props.context.memory.selection;
const filters=reactive<Record<string,string|number>>({page:1,status:'',target:'',chip:'',precision:'',csc:'',created_from:'',created_to:'',...props.context.memory.history});
const history=ref<ConversionPage|null>(null),record=ref<ConversionRecord|null>(null);
const filterFields=[['status','状态'],['target','目标'],['chip','芯片'],['precision','精度'],['csc','颜色配置']];
function close(){record.value=null}
function load(force=false){if(!selection?.algorithmId||!selection.versionId)return;close();props.context.memory.history={...filters};return reads.run('history',signal=>api.history(selection.algorithmId,selection.versionId,{...filters,...(force?{force:'true'}:{})},signal),value=>{history.value=value})}
function search(){filters.page=1;void load()}
function changePage(value:number){filters.page=value;void load()}
const evidence=(value:boolean|undefined)=>value===true?'已有通过字段':value===false?'未记录通过':'未提供证据';
onMounted(()=>void load());
</script>
<template><section class="catalog-preview conversion-history" aria-label="版本转换历史与诊断只读中心">
 <PageHeader title="转换记录与诊断" eyebrow="模型管理 / 版本转换历史" description="只读取选中版本的转换记录与已有证据。" badge="只读历史" @back="context.returnToManagement"/>
 <div class="browse-context"><div><strong>{{ selection?.algorithmName||selection?.algorithmId||'尚未选择算法' }}</strong><span>{{ selection?.versionName||selection?.versionId||'尚未选择版本' }}</span><small>项目 {{ context.projectId }}</small></div><div class="preview-actions"><el-button @click="context.returnToAssets">返回版本浏览</el-button><el-button v-if="selection?.versionId" @click="context.openLegacy(selection)">原版本转换 / 验证</el-button></div></div>
 <el-empty v-if="!selection?.versionId" description="尚未选择版本，请从模型资产页进入"/>
 <template v-else><form class="browse-filters history-filters" @submit.prevent="search"><el-select v-for="[key,label] in filterFields" :key="key" v-model="filters[key]" :aria-label="'转换'+label" :placeholder="'全部'+label"><el-option :label="'全部'+label" value=""/><el-option v-for="value in history?.filter_options?.[key]||[]" :key="value" :label="value" :value="value"/></el-select><el-input v-model="filters.created_from" type="date" aria-label="转换开始日期"/><el-input v-model="filters.created_to" type="date" aria-label="转换结束日期"/><el-button native-type="submit" type="primary" :disabled="reads.busy.history">查询记录</el-button><el-button :disabled="reads.busy.history" @click="load(true)">刷新记录</el-button></form>
 <el-alert v-if="reads.errors.history" :title="reads.errors.history" type="error" :closable="false"/><p v-if="reads.errors.history&&history" class="evidence-note">以下为上次成功读取的快照，不能作为最新状态。</p><el-alert v-if="history?.complete===false" title="历史投影不完整，部分任务状态或记录未能核验。" type="warning" :closable="false"/>
 <section class="browse-panel" aria-label="版本转换记录列表" :aria-busy="reads.busy.history"><el-skeleton v-if="reads.busy.history&&!history" :rows="8" animated/><el-table v-else-if="history" :data="history.items" max-height="620" row-key="id" empty-text="当前条件下没有转换记录">
  <el-table-column label="任务 / 时间" min-width="175"><template #default="{row}"><strong>{{ row.id }}</strong><small class="browse-secondary">{{ row.created_at||'创建时间未提供' }}</small><small class="browse-secondary">完成：{{ row.finished_at||'未提供' }}</small></template></el-table-column>
  <el-table-column label="目标 / 参数" min-width="150"><template #default="{row}">{{ row.target_name||row.target||'目标未提供' }}<small class="browse-secondary">芯片 {{ shownValue(row.params?.chip||row.params?.soc_version) }} · {{ shownValue(row.params?.precision) }}</small><small class="browse-secondary">SDK {{ shownValue(row.params?.sdk_version) }}</small></template></el-table-column>
  <el-table-column label="执行状态" min-width="145"><template #default="{row}"><el-tag type="info" effect="plain">{{ row.status||'未提供' }}</el-tag><small class="browse-secondary">{{ row.stage||'阶段未提供' }} · {{ shownValue(row.progress) }}{{ typeof row.progress==='number'?'%':'' }}</small><small class="browse-secondary">{{ row.resource_name||row.worker_id||'执行资源未提供' }}</small></template></el-table-column>
  <el-table-column label="产物 / 诊断" min-width="180"><template #default="{row}"><small>{{ row.outputs?.length?row.outputs.map((item:any)=>item.file_name||'名称未提供').join(' / '):'没有提供输出产物' }}</small><small class="browse-secondary">{{ row.error||row.message||row.resource_wait_reason||'诊断未提供' }}</small></template></el-table-column>
  <el-table-column label="" width="65"><template #default="{row}"><el-button link type="primary" :aria-label="`查看转换${row.id}详情`" @click="record=row">详情</el-button></template></el-table-column>
 </el-table><footer v-if="history" class="preview-pagination"><span>共 {{ history.total }} 条 · 当前版本范围</span><el-pagination layout="prev, pager, next" :pager-count="5" :page-size="20" :total="history.total" :current-page="history.page" @current-change="changePage"/></footer></section></template>
 <el-drawer :model-value="!!record" title="转换任务诊断与证据" size="min(700px, 100vw)" :append-to-body="false" :lock-scroll="false" :before-close="close"><div v-if="record" class="evidence-details">
  <h3>任务身份</h3><ReadOnlyFacts :fields="[['转换记录 ID',record.id],['Durable Task ID',record.task_id],['算法 ID',selection?.algorithmId],['版本 ID',selection?.versionId],['来源模型',record.source_name]]"/><ReadOnlyFacts :fields="Object.entries(record.source_identity||{})"/>
  <h3>独立状态证据</h3><ReadOnlyFacts :fields="[['转换执行状态',record.status],['转换阶段状态',record.conversion_status],['产物完整性状态',record.validation_status||'未提供完整性证据'],['数值一致性状态',record.numeric_status||'未提供数值验证证据'],['目标硬件验证',evidence(record.hardware_verified)],['Runtime 验证字段',evidence(record.runtime_verified)],['发布状态',record.publication_status||'未提供发布证据']]"/>
  <h3>实际转换参数</h3><ReadOnlyFacts :fields="Object.entries(record.params||{})"/><details><summary>原请求参数</summary><ReadOnlyFacts :fields="Object.entries(record.requested_params||{})"/></details>
  <h3>执行信息</h3><ReadOnlyFacts :fields="[['任务状态',record.task_status],['Durable 状态',record.durable_status],['当前阶段',record.stage],['进度',record.progress],['执行资源',record.resource_name],['Worker',record.worker_id],['创建',record.created_at],['开始',record.started_at],['完成',record.finished_at]]"/><ReadOnlyFacts :fields="Object.entries(record.execution_evidence||{})"/>
  <h3>输出产物</h3><p v-if="!record.outputs?.length" class="evidence-note">没有提供产物证据，不能据此生成下载链接。</p><article v-for="(output,index) in record.outputs||[]" :key="index" class="artifact-evidence"><strong>{{ output.file_name||'文件名未提供' }}</strong><ReadOnlyFacts :fields="[['文件存在',output.exists===true?'文件存在（不代表完整性通过）':output.exists===false?'文件不存在':'未核验'],['SHA256',output.sha256],['大小（MB）',output.size_mb],['大小（字节）',output.size_bytes],['完整性记录',output.validation_status]]"/></article><p v-if="record.outputs_truncated">仅展示前20个输出，完整记录请使用原管理入口。</p>
  <h3>诊断</h3><ReadOnlyFacts :fields="[['错误代码',record.error_code],['错误',record.error],['消息',record.message],['建议',record.solution],['等待原因',record.resource_wait_reason]]"/><ReadOnlyFacts :fields="Object.entries(record.hardware_verification||{})"/>
 </div><template #footer><el-button @click="close">返回当前记录列表</el-button></template></el-drawer>
</section></template>

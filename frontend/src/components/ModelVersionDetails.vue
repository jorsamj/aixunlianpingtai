<script setup lang="ts">
import {computed} from 'vue';
import type {VersionDetail} from '../types/model-browse';
import ReadOnlyFacts from './ReadOnlyFacts.vue';
import {shownValue} from '../api/model-browse';
const props=defineProps<{detail:VersionDetail;versionNames?:Record<string,string>;projectId?:string}>();
// Lineage identity is never guessed from version names: a parent/base version is
// resolved only when the server returned its id and the caller already loaded that
// page; otherwise the raw id is shown as unresolved.
const resolve=(id?:string)=>id?(props.versionNames?.[id]||''):'';
const lineageFacts=computed(()=>Object.entries(props.detail.version.training_lineage||{}));
</script>
<template><div class="evidence-details">
 <h3>基本信息</h3><ReadOnlyFacts :fields="[['版本',detail.version.version_name],['稳定版本 ID',detail.version.id],['归属算法 ID',detail.algorithm_id],['训练状态',detail.version.training_status],['版本状态',detail.version.status],['创建时间',detail.version.created_at],['完成时间',detail.version.finished_at],['来源',detail.version.source_type],['框架',detail.version.framework]]"/>
 <h3>模型文件</h3><ReadOnlyFacts :fields="[['文件名',detail.version.model_file?.file_name],['记录格式',detail.version.model_file?.format],['文件后缀（不代表兼容）',detail.version.model_file?.extension],['大小（MB）',detail.version.model_file?.size_mb],['大小（字节）',detail.version.model_file?.size_bytes],['SHA256',detail.version.model_file?.sha256||detail.version.model_file?.model_sha256],['文件可下载性','未核验，请使用原授权入口'],['原版本产物校验字段',detail.version.artifact_verified===true?'已记录校验':detail.version.artifact_verified===false?'未记录通过':'未提供']]"/>
 <h3>模型元数据</h3><ReadOnlyFacts :fields="[['输入宽度',detail.version.model_metadata?.image_width],['输入高度',detail.version.model_metadata?.image_height],['框架版本',detail.version.model_metadata?.framework_version],['类别数',detail.version.class_count??detail.version.model_metadata?.class_count],['类别证据',detail.version.model_metadata?.label_validation_status],['类别',detail.version.classes?.join(' / ')||null]]"/><p v-if="detail.version.classes_truncated" class="evidence-note">类别仅展示前256项，数量来自正式记录。</p>
 <h3>训练配置摘要</h3><ReadOnlyFacts :fields="Object.entries(detail.version.training_parameters||{})"/>
 <h3>已有质量指标（记录原值）</h3><div v-for="[key,label] in [['metrics','版本保存指标'],['val_metrics','Val 指标'],['test_metrics','Test / 独立评测指标']] as const" :key="key" class="metric-group"><h4>{{ label }}</h4><ReadOnlyFacts :fields="Object.entries(detail.version[key]||{})"/></div>
 <h3>版本关联与血缘</h3>
 <ReadOnlyFacts :fields="[['训练任务 ID',detail.version.training_job_id],['父版本 ID',detail.version.parent_version_id],['父版本名称',resolve(detail.version.parent_version_id)||'未在当前页或未提供'],['基础版本 ID',detail.version.base_version_id],['基础版本名称',resolve(detail.version.base_version_id)||'未在当前页或未提供'],['ModelArtifact ID',detail.version.artifact_id]]"/>
 <ReadOnlyFacts v-if="lineageFacts.length" :fields="lineageFacts"/>
 <p v-else class="evidence-note">服务端未记录该版本的血缘字段；不根据版本名称推断父子关系。</p>
 <p class="evidence-note">血缘、冻结快照、独立评测、困难样本与转换/交付是独立证据链，可分别核对：</p>
 <p class="evidence-links">
  <router-link v-if="projectId&&detail.version.training_job_id" :to="{name:'training-report',params:{projectId,jobId:detail.version.training_job_id}}">训练报告</router-link>
  <router-link v-if="projectId&&detail.version.has_evaluation" :to="{name:'version-report',params:{projectId,algorithmId:detail.algorithm_id,versionId:detail.version.id},query:{tab:'evaluation'}}">独立评测</router-link>
  <router-link v-if="projectId" :to="{name:'version-conversions',params:{projectId,algorithmId:detail.algorithm_id,versionId:detail.version.id}}">转换记录</router-link>
  <router-link v-if="projectId&&detail.version.has_model" :to="{name:'external-publish-native',params:{projectId},query:{algorithm:detail.algorithm_id,version:detail.version.id}}">交付记录</router-link>
 </p>
 <h3>已登记模型资产 · {{ detail.artifacts.total }}</h3><p v-if="!detail.artifacts.total" class="evidence-note">没有匹配的登记记录；未执行存储扫描。</p><article v-for="artifact in detail.artifacts.items" :key="artifact.artifact_id" class="artifact-evidence"><strong>{{ artifact.file_name||artifact.artifact_id }}</strong><ReadOnlyFacts :fields="[['资产 ID',artifact.artifact_id],['资产类型',artifact.artifact_kind],['目标',artifact.target],['芯片',artifact.chip_code],['转换记录 ID',artifact.conversion_job_id],['SHA256',artifact.sha256],['大小（字节）',artifact.size_bytes],['存储来源 ID',artifact.storage_source_id],['存储状态（非发布状态）',artifact.storage_status],['上传时间',artifact.uploaded_at]]"/></article><p v-if="detail.artifacts.truncated">共{{ detail.artifacts.total }}项，本次详情展示前20项。</p>
 <p class="evidence-note">登记记录、文件校验、OSS 上传和发布是独立证据。版本发布字段：{{ shownValue(detail.version.external_publish_status) }}。</p>
</div></template>

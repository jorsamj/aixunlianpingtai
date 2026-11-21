<script setup lang="ts">
import {computed,onBeforeUnmount,ref} from 'vue';
import type {ConfigurationCenterContext,ConfigurationEntry,ConfigurationGroup} from '../types/configuration-center';
import PageHeader from '../components/PageHeader.vue';

const props=defineProps<{context:ConfigurationCenterContext}>();
const query=ref(''),selectedGroup=ref<ConfigurationGroup|''>(''),opening=ref(''),error=ref('');
const categories:{name:ConfigurationGroup;description:string}[]=[
  {name:'计算资源',description:'服务节点与训练、转换资源。'},
  {name:'模型与标注',description:'模型服务、Prompt 以及算法相关配置。'},
  {name:'模型交付与存储',description:'平台连接、模型交付与文件存储。'},
  {name:'基础字典',description:'厂商、芯片及其他已接入的基础配置。'},
];
const groups=computed(()=>{
  const text=query.value.trim().toLocaleLowerCase();
  return categories.filter(group=>!selectedGroup.value||group.name===selectedGroup.value).map(group=>({...group,
    entries:props.context.entries.filter(entry=>entry.group===group.name&&(!text||`${entry.title} ${entry.description} ${entry.group}`.toLocaleLowerCase().includes(text))),
  })).filter(group=>group.entries.length>0);
});
let alive=true;
onBeforeUnmount(()=>{alive=false});
async function open(entry:ConfigurationEntry){
  if(!alive||props.context.signal.aborted||entry.enabled!==true||opening.value)return;
  opening.value=entry.id;error.value='';
  try{await props.context.open(entry.id)}
  catch(_){if(alive&&!props.context.signal.aborted)error.value=`暂时无法打开“${entry.title}”，请重试。`}
  finally{if(alive)opening.value=''}
}
function reset(){query.value='';selectedGroup.value=''}
</script>
<template><section class="catalog-preview configuration-center" aria-label="统一配置中心">
 <PageHeader title="配置中心" eyebrow="资源与配置 / 分类入口" description="按类别打开现有资源、模型服务与平台配置。" badge="配置管理" @back="context.back()"/>
 <div class="configuration-toolbar"><el-input v-model="query" aria-label="搜索配置入口" placeholder="搜索资源、模型、存储或字典" clearable/><small class="project-context">当前项目 {{ context.projectId||'未选择' }}</small></div>
 <nav class="configuration-categories" aria-label="配置分类"><el-button :type="selectedGroup===''?'primary':'default'" :aria-pressed="selectedGroup===''" @click="selectedGroup=''">全部配置</el-button><el-button v-for="category in categories" :key="category.name" :type="selectedGroup===category.name?'primary':'default'" :aria-pressed="selectedGroup===category.name" @click="selectedGroup=category.name">{{ category.name }}</el-button></nav>
 <el-alert v-if="error" :title="error" type="error" :closable="false"/>
 <section v-for="group in groups" :key="group.name" class="configuration-group" :aria-label="group.name"><header class="group-header"><h2>{{ group.name }}</h2><p>{{ group.description }}</p></header><div class="configuration-grid"><article v-for="entry in group.entries" :key="entry.id" class="configuration-entry" :class="{unavailable:!entry.enabled}" :data-config-entry="entry.id"><div class="entry-heading"><h3>{{ entry.title }}</h3><el-tag v-if="!entry.enabled" size="small" type="info" effect="plain">当前不可用</el-tag></div><p class="entry-description">{{ entry.description }}</p><p v-if="!entry.enabled&&entry.reason" class="entry-reason">{{ entry.reason }}</p><div class="entry-action"><el-button :disabled="entry.enabled!==true||Boolean(opening)||context.signal.aborted" :loading="opening===entry.id" :aria-label="'打开'+entry.title" @click="open(entry)">打开{{ entry.title }}</el-button></div></article></div></section>
 <el-empty v-if="!groups.length" description="没有匹配的配置入口"><el-button @click="reset">清除筛选</el-button><el-button @click="context.back()">返回</el-button></el-empty>
</section></template>
<style scoped>
.configuration-center{min-width:0}.configuration-toolbar{display:flex;align-items:center;justify-content:space-between;gap:16px;margin:18px 0 12px}.configuration-toolbar :deep(.el-input){max-width:440px}.project-context{font-size:12px;line-height:1.6;color:var(--el-text-color-secondary,#777);overflow-wrap:anywhere}.configuration-categories{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 20px}.configuration-categories :deep(.el-button){margin:0}.configuration-group{margin:0 0 26px;min-width:0}.group-header{margin-bottom:12px}.group-header h2{font-size:17px;line-height:1.5;margin:0 0 4px}.group-header p{font-size:13px;line-height:1.7;color:var(--el-text-color-secondary,#777);margin:0}.configuration-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.configuration-entry{display:flex;flex-direction:column;min-width:0;padding:18px;border:1px solid var(--el-border-color-lighter,#ebeef5);border-radius:9px;background:var(--el-bg-color,#fff)}.entry-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:8px}.entry-heading h3{font-size:15px;line-height:1.6;margin:0;overflow-wrap:anywhere}.entry-description{font-size:13px;line-height:1.8;color:var(--el-text-color-regular,#606266);margin:10px 0 16px;overflow-wrap:anywhere}.entry-reason{font-size:12px;line-height:1.7;color:var(--el-text-color-secondary,#777);margin:0 0 14px;overflow-wrap:anywhere}.entry-action{margin-top:auto}.entry-action :deep(.el-button){white-space:normal;min-height:32px;height:auto;max-width:100%;line-height:1.6}.configuration-entry.unavailable{background:var(--el-fill-color-lighter,#fafafa)}
@media(min-width:1600px){.configuration-grid{grid-template-columns:repeat(4,minmax(0,1fr))}}
@media(max-width:1100px){.configuration-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.configuration-entry{padding:15px}}
@media(max-width:650px){.configuration-grid{grid-template-columns:minmax(0,1fr)}.configuration-toolbar{align-items:flex-start;flex-direction:column;gap:8px}.configuration-toolbar :deep(.el-input){max-width:none}.configuration-categories{gap:6px}.configuration-categories :deep(.el-button){padding:8px 10px}.configuration-group{margin-bottom:20px}}
</style>

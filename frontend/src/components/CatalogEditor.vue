<script setup lang="ts">
import {computed} from 'vue';
import {useCatalogView} from '../stores/catalog';
import CatalogReferences from './CatalogReferences.vue';
import PendingOperation from './PendingOperation.vue';
const view=useCatalogView();
const form=computed(()=>view.editor);
const name=computed(()=>form.value?.entity==='vendors'?'厂商':'芯片');
const title=computed(()=>`${({create:'新增',update:'编辑',delete:'删除',enable:'启用',disable:'停用'} as const)[form.value?.action||'create']}${name.value}`);
const locked=computed(()=>view.saving||!!view.pending);
const allowed=computed(()=>form.value?.action!=='delete'||form.value.detail?.references.can_delete===true);
</script>
<template>
 <el-drawer :model-value="view.editing" :title="title" size="min(520px, 100vw)" :append-to-body="false" :lock-scroll="false" :close-on-click-modal="!view.saving" :close-on-press-escape="!view.saving" :show-close="!view.saving" :before-close="view.closeEditor">
  <el-skeleton v-if="!form && !view.writeError" :rows="5" animated/>
  <template v-if="form">
   <CatalogReferences v-if="form.id" :references="form.detail?.references"/>
   <form id="catalog-editor-form" class="preview-editor" @submit.prevent="view.save">
    <template v-if="form.action==='create'||form.action==='update'">
     <label class="preview-field">{{ name }}名称<el-input v-model="form.record.name" :aria-label="`${name}名称`" :disabled="locked" maxlength="120" required/></label>
     <label v-if="form.entity==='vendors'" class="preview-field">SDK 模板<el-select v-model="form.record.template_id" aria-label="SDK 模板" :disabled="locked||!form.mutableIdentity"><el-option v-for="item in view.pages.vendors?.templates||[]" :key="item.id" :label="item.name" :value="item.id"/></el-select></label>
     <p v-else>所属厂商：{{ form.detail?.item.vendor_name || view.selectedName || form.record.vendor_id }}</p>
     <el-checkbox v-model="form.record.enabled" :disabled="locked">启用</el-checkbox>
     <details><summary>身份与 SDK 配置</summary><p v-if="!form.id">稳定 ID 由后端生成。</p><p v-else>稳定 ID：{{ form.id }}</p>
      <template v-if="form.entity==='chips'"><label class="preview-field">本地编码<el-input v-model="form.record.code" aria-label="本地编码" :disabled="locked||!form.mutableIdentity"/></label><label class="preview-field">SDK 目标编码<el-input v-model="form.record.sdk_code" aria-label="SDK 目标编码" :disabled="locked||!form.mutableIdentity"/></label><p>留空使用后端建议；未知型号可登记为待配置，转换资格仍由后端判断。</p></template>
      <p v-if="!form.mutableIdentity">历史身份受到保护，名称和启停仍可编辑。</p>
     </details>
    </template>
    <template v-else><p>确认{{ title }}「{{ form.record.name }}」？</p><p v-if="form.action==='delete'">删除后不可恢复，后端将再次检查引用。</p><el-alert v-if="!allowed" title="当前记录不可删除，可停用以保留历史。" type="warning" :closable="false"/></template>
   </form>
   <el-button v-if="form.conflict" @click="view.reloadEditor">重新读取当前记录</el-button>
  </template>
  <el-alert v-if="view.writeError" :title="view.writeError" type="error" :closable="false" class="preview-write-error"/>
  <PendingOperation/>
  <template #footer><el-button :disabled="view.saving" @click="view.closeEditor">{{ view.pending?'返回列表':'取消' }}</el-button><el-button v-if="form" form="catalog-editor-form" native-type="submit" :type="form.action==='delete'?'danger':'primary'" :disabled="locked||!allowed||form.conflict" :loading="view.saving">{{ form.action==='delete'?'确认删除':['enable','disable'].includes(form.action)?'确认'+title:'保存'+name }}</el-button></template>
 </el-drawer>
</template>

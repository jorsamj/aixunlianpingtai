<script setup lang="ts">
import {useCatalogView} from '../stores/catalog';
const view=useCatalogView();
</script>
<template><section v-if="view.pending" class="preview-pending" aria-label="待确认的字典操作"><el-alert title="提交结果待确认，原请求已保留。请先核验回执，避免重复新增。" type="warning" :closable="false"/><small>操作 ID：{{ view.pending.operation_id }}</small><div class="preview-actions"><el-button :disabled="view.saving" @click="view.commit(true)">查询原操作回执</el-button><el-button :disabled="view.saving" @click="view.commit(true,true)">使用原请求恢复</el-button></div></section></template>

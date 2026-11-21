<script setup lang="ts">
import type {CatalogReferences} from '../types/catalog';
defineProps<{references?:CatalogReferences}>();
</script>
<template><section class="preview-reference" aria-label="历史业务引用">
 <el-alert v-if="references?.check_status==='UNVERIFIED'" title="历史引用未核验，不能据此判断可删除或改挂。" type="warning" :closable="false"/>
 <p v-else>引用核验：{{ references?.check_status || '未核验' }} · {{ references?.reference_count ?? '数量未知' }} 项</p>
 <p v-if="references?.solution">{{ references.solution }}</p>
 <ul v-if="references?.references?.length"><li v-for="(item,index) in references.references" :key="index">{{ item.kind || item.type }} · {{ item.id || item.identity }}</li></ul>
 <details v-if="references?.diagnostic || references?.diagnostics?.length"><summary>引用诊断详情</summary><p v-if="references.diagnostic">{{ references.diagnostic.code }} · {{ references.diagnostic.detail }} · {{ references.diagnostic.solution }}</p><p v-for="(item,index) in references.diagnostics" :key="index">{{ item.code }} · {{ item.task_id }} · {{ item.resolved_path || item.original_path }}</p></details>
</section></template>

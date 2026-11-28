<script setup lang="ts">
defineProps<{title:string;eyebrow:string;description:string;badge:string}>();
defineEmits<{back:[]}>();
</script>
<template><header class="preview-heading"><div><p class="preview-eyebrow">{{ eyebrow }}</p><h1>{{ title }}</h1><p>{{ description }}</p></div><div class="preview-actions"><el-tag type="info" effect="plain">{{ badge }}</el-tag><el-button @click="$emit('back')">返回完整管理</el-button></div></header></template>

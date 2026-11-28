<script setup lang="ts">
// Shared task-status label and tone. Pages keep their own business wording only
// when a workflow really differs; the canonical map keeps one vocabulary across
// the overview, quality centre and training task wall.
const labels:Record<string,string>={
  ACCEPTED:'已受理',QUEUED:'排队中',WAITING_RESOURCE:'等待资源',PREPARING:'准备中',RUNNING:'运行中',
  PAUSED:'已暂停',AWAITING_CONFIRMATION:'等待确认',CANCEL_REQUESTED:'已请求取消',CANCELLED:'已取消',
  FAILED:'失败',SUCCEEDED:'已完成',PARTIAL_SUCCESS:'部分成功',
  BLOCKED_BY_ENVIRONMENT:'环境阻断',BLOCKED_BY_HARDWARE:'硬件阻断',
};
const tones:Record<string,'success'|'warning'|'danger'|'info'|undefined>={
  SUCCEEDED:'success',PARTIAL_SUCCESS:'warning',FAILED:'danger',
  BLOCKED_BY_ENVIRONMENT:'warning',BLOCKED_BY_HARDWARE:'warning',AWAITING_CONFIRMATION:'warning',
  QUEUED:'info',WAITING_RESOURCE:'info',PAUSED:'info',CANCEL_REQUESTED:'info',CANCELLED:'info',
};
defineProps<{status:string}>();
</script>

<template><el-tag :type="tones[status]" effect="plain">{{ labels[status]||status||'未提供' }}</el-tag></template>

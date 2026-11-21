<script setup lang="ts">
import {shownValue} from '../api/model-browse';
defineProps<{fields:[string,unknown][]}>();
</script>
<template><dl class="readonly-facts"><template v-for="([label,value],index) in fields" :key="index"><dt>{{ label }}</dt><dd>{{ typeof value==='boolean'?(value?'是':'否'):shownValue(value) }}</dd></template></dl></template>

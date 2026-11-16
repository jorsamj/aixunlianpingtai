<script setup lang="ts">
import {computed} from 'vue';
const props=defineProps<{label:string;value?:number;detail?:string}>();
const percent=computed(()=>typeof props.value==='number'&&Number.isFinite(props.value)&&props.value>=0&&props.value<=100?props.value:null);
</script>
<template><div class="node-meter"><div><span>{{ label }}</span><strong>{{ percent===null?'未上报':percent.toFixed(0)+'%' }}</strong></div><div class="node-meter-track" :role="percent===null?undefined:'meter'" :aria-label="label" :aria-valuenow="percent??undefined" :aria-valuemin="0" :aria-valuemax="100"><i :style="{width:(percent??0)+'%'}"/></div><small>{{ detail }}</small></div></template>

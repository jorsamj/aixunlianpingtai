<script setup lang="ts">
import {onMounted,onUnmounted,ref,watch} from 'vue';
import type {init} from './echarts';
const props=defineProps<{scores:Record<string,number>}>();
const host=ref<HTMLElement>();
let chart:ReturnType<typeof init>|undefined,observer:ResizeObserver|undefined,active=true;
function draw(){
  const rows=Object.entries(props.scores).filter(([,value])=>Number.isFinite(value));
  chart?.setOption({
    animation:false,
    grid:{left:12,right:28,top:10,bottom:25,containLabel:true},
    xAxis:{type:'value'},yAxis:{type:'category',inverse:true,data:rows.map(([label])=>label)},
    series:[{type:'bar',data:rows.map(([,value])=>value),itemStyle:{color:'#3f4650'},label:{show:true,position:'right'}}]
  });
}
onMounted(async()=>{
  const {init}=await import('./echarts');
  if(!active||!host.value)return;
  chart=init(host.value);draw();
  observer=new ResizeObserver(()=>chart?.resize());observer.observe(host.value);
});
watch(()=>props.scores,draw);
onUnmounted(()=>{active=false;observer?.disconnect();chart?.dispose()});
</script>

<template>
  <div ref="host" class="scores" role="img" :aria-label="Object.entries(scores).map(([label,value])=>label+' '+value).join('，')"/>
</template>

<style scoped>
.scores{width:100%;height:220px}
</style>

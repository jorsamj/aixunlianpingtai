<script setup lang="ts">
import {nextTick,onBeforeUnmount,ref,watch} from 'vue';
type Row=Record<string,unknown>;
interface Reports {trainingCharts(history:Row[]):string;evaluationChartGroups(data:Row):{key:string;title:string}[];mountReportCharts(root:HTMLElement,history:Row[]):Promise<unknown>;mountEvaluationCharts(root:HTMLElement,data:Row):Promise<unknown>;disposeReportViews(root:HTMLElement):void}
const props=defineProps<{history?:Row[];evaluation?:Row}>(),root=ref<HTMLElement>(),html=ref(''),groups=ref<{key:string;title:string}[]>([]),error=ref('');
const owner=()=> (window as unknown as {PlatformCore?:{reports?:Reports}}).PlatformCore?.reports;
let epoch=0,alive=true;
watch([()=>props.history,()=>props.evaluation],async()=>{const ticket=++epoch,host=root.value;error.value='';if(host)owner()?.disposeReportViews(host);const api=owner();if(!api){error.value='原报告图表组件尚未就绪';return}html.value=props.history?api.trainingCharts(props.history):'';groups.value=props.evaluation?api.evaluationChartGroups(props.evaluation):[];await nextTick();if(!alive||ticket!==epoch||!root.value)return;try{if(props.history)await api.mountReportCharts(root.value,props.history);else if(props.evaluation)await api.mountEvaluationCharts(root.value,props.evaluation)}catch(_){if(alive&&ticket===epoch)error.value='已有曲线读取失败，请重新读取；表格原值仍可查看。'}},{immediate:true,flush:'post'});
onBeforeUnmount(()=>{alive=false;epoch++;if(root.value)owner()?.disposeReportViews(root.value)});
</script>
<template><div ref="root" class="report-charts"><p v-if="error" role="alert">{{ error }}</p><div v-if="history" v-html="html"></div><template v-else><section v-for="group in groups" :key="group.key"><h4>{{ group.title }}</h4><div :data-report-chart="group.key" class="chart" :aria-label="group.title" role="img"></div></section><p v-if="!groups.length&&!error">当前页没有可绘制的已记录曲线。</p></template></div></template>
<style scoped>.chart,.report-charts :deep(.report-interactive-chart){height:320px;min-width:0;width:100%}.report-charts{min-width:0}.report-charts :deep(.report-chart-groups){display:grid;grid-template-columns:minmax(0,1fr);gap:16px}.report-charts section{min-width:0}</style>

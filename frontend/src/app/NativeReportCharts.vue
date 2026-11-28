<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import type { init } from './echarts'

const props = withDefaults(defineProps<{ history?: Record<string, unknown>[]; evaluation?: Record<string, unknown> }>(), { history: () => [], evaluation: () => ({}) })
const root = ref<HTMLElement>()
const error = ref('')
const selectedClass = ref<number>()
let charts: ReturnType<typeof init>[] = []
let observer: ResizeObserver | undefined
let generation = 0
const number = (x: unknown): number | null => typeof x === 'number' && Number.isFinite(x) ? x : null
type Row = Record<string, unknown>
const obj = (x: unknown): Row => x && typeof x === 'object' ? x as Row : {}
const rowsOf = (x: unknown): Row[] => Array.isArray(x) ? x.map(obj) : []
const classes = computed(() => rowsOf(props.evaluation.per_class))
const curveClasses = computed(() => rowsOf(props.evaluation.confidence_curves).flatMap(row => {
  const id = number(row.class_id)
  return id === null ? [] : [{id,label:String(classes.value.find(c=>c.class_id===id)?.label || id)}]
}))
const groups = computed(() => {
  const result: { key: string; title: string; options: Row }[] = []
  const rows = props.history.filter(r => number(r.epoch) !== null).sort((a,b) => Number(a.epoch)-Number(b.epoch))
  const definitions = [
    ['quality','Val 指标（原记录数值）', [['precision','Precision','metrics','metrics/precision(B)'],['recall','Recall','metrics','metrics/recall(B)'],['map50','mAP50','metrics','metrics/mAP50(B)'],['map50_95','mAP50-95','metrics','metrics/mAP50-95(B)']]],
    ['train','训练损失', [['box_loss','Box','losses','train/box_loss'],['cls_loss','Class','losses','train/cls_loss'],['dfl_loss','DFL','losses','train/dfl_loss']]],
    ['val','验证损失', [['val_box_loss','Box','metrics','val/box_loss'],['val_cls_loss','Class','metrics','val/cls_loss'],['val_dfl_loss','DFL','metrics','val/dfl_loss']]],
  ] as const
  for (const [key,title,fields] of definitions) {
    const series = fields.map(([field,name,container,alias]) => ({ name, type:'line', connectNulls:false, data: rows.map(r => number(r[field]) ?? (field==='map50_95'?number(r.mAP50_95)??number(r.map5095):null) ?? number(obj(r[container])[field]) ?? number(obj(r[container])[alias])) })).filter(s => s.data.some(v => v !== null))
    if (series.length) result.push({key,title,options:{animation:false,tooltip:{trigger:'axis'},legend:{top:0},grid:{top:55,bottom:45},xAxis:{type:'category',name:'Epoch',data:rows.map(r=>r.epoch)},yAxis:{type:'value',scale:true},series}})
  }
  const e = props.evaluation
  const label = (id: number | null) => id === null ? '背景（无目标）' : `${classes.value.find(c=>c.class_id===id)?.label || '类别'} [${id}]`
  const matrix = obj(e.confusion_matrix)
  if (matrix.protocol === 'confidence_first_class_agnostic_iou_0.5' && Array.isArray(matrix.cells)) {
    const validId = (v: unknown): v is number|null => v === null || (typeof v==='number'&&Number.isSafeInteger(v)&&v>=0)
    const cells = rowsOf(matrix.cells).flatMap(({actual,predicted,count}) =>
      validId(actual)&&validId(predicted)&&typeof count==='number'&&Number.isSafeInteger(count)&&count>=0 ? [{actual,predicted,count}] : [])
    const axes = [...new Set(cells.flatMap(c => [c.actual,c.predicted]))]
    if (cells.length) result.push({key:'matrix',title:'已记录空间混淆矩阵（当前页）',options:{animation:false,tooltip:{},grid:{left:100,bottom:100},xAxis:{type:'category',name:'预测',data:axes.map(label),axisLabel:{rotate:35}},yAxis:{type:'category',name:'真实',data:axes.map(label)},visualMap:{min:0,max:Math.max(1,...cells.map(c=>c.count)),orient:'horizontal',bottom:0},series:[{type:'heatmap',label:{show:true},data:cells.map(c=>[axes.indexOf(c.predicted),axes.indexOf(c.actual),c.count])}]}})
  }
  const selected = curveClasses.value.find(row=>row.id===selectedClass.value)??curveClasses.value[0]
  if (selected && e.confidence_curve_protocol === 'same_class_confidence_first_iou_0.5_grid_0.05') {
    const curve = rowsOf(e.confidence_curves).find(c=>c.class_id===selected.id)
    const score = (v:unknown) => { const n=number(v); return n!==null && n>=0 && n<=1 ? n : null }
    const points = rowsOf(curve?.points).filter(p=>score(p.confidence)!==null).sort((a,b)=>Number(a.confidence)-Number(b.confidence))
    const series = ['precision','recall','f1'].map(field=>({name:field,type:'line',connectNulls:false,data:points.map(p=>[p.confidence,score(p[field])])})).filter(s=>s.data.some(p=>p[1]!==null))
    const common = {animation:false,tooltip:{trigger:'axis'},legend:{top:0},grid:{top:55,bottom:50},xAxis:{type:'value',min:0,max:1,name:'Confidence'},yAxis:{type:'value',min:0,max:1}}
    if(series.length) result.push({key:'threshold',title:`${label(selected.id)} · Confidence 阈值采样`,options:{...common,series}})
    const pr=points.filter(p=>score(p.precision)!==null&&score(p.recall)!==null).map(p=>[p.recall,p.precision,p.confidence])
    if(pr.length) result.push({key:'pr',title:`${label(selected.id)} · PR 阈值采样（非 AP 积分曲线）`,options:{...common,xAxis:{type:'value',min:0,max:1,name:'Recall'},yAxis:{type:'value',min:0,max:1,name:'Precision'},series:[{type:'scatter',data:pr}]}})
  }
  return result
})
function dispose() { observer?.disconnect(); observer=undefined; charts.forEach(c=>c.dispose()); charts=[] }
watch(groups, async () => {
  const current=++generation
  dispose()
  await nextTick()
  if(current!==generation||!root.value) return
  error.value=''
  try {
    const hosts = root.value.querySelectorAll<HTMLElement>('.chart')
    if(!hosts.length)return
    const {init}=await import('./echarts')
    if(current!==generation)return
    hosts.forEach((host,index)=>{
      const chart=init(host)
      charts.push(chart)
      chart.setOption(groups.value[index].options)
    })
    if(hosts.length&&typeof ResizeObserver !== 'undefined') {
      const resize=new ResizeObserver(()=>charts.forEach(chart=>chart.resize()))
      observer=resize
      hosts.forEach(host=>resize.observe(host))
    }
  } catch {
    if(current!==generation)return
    dispose()
    error.value='图表读取失败，仍可查看已记录数据。'
  }
}, {immediate:true, flush:'post'})
onBeforeUnmount(()=>{ generation++; dispose() })
</script>

<template>
  <div ref="root" class="native-report-charts">
    <p v-if="error" role="alert">{{error}}</p>
    <label v-if="curveClasses.length>1">曲线类别
      <select v-model="selectedClass"><option :value="undefined">当前页首个类别</option><option v-for="row in curveClasses" :key="row.id" :value="row.id">{{row.label}}</option></select>
    </label>
    <p v-if="!groups.length">暂无已记录的图表数据</p>
    <section v-for="group in groups" :key="group.key">
      <h3>{{ group.title }}</h3>
      <div class="chart" :aria-label="group.title" role="img"></div>
    </section>
  </div>
</template>

<style scoped>
.native-report-charts { display: grid; gap: 1rem; }
.chart { width: 100%; height: 340px; }
h3 { font-size: 1rem; margin: 0 0 .5rem; }
</style>

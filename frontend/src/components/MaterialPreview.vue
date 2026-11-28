<script setup lang="ts">
import {computed,ref,watch} from 'vue';
import type {MaterialRow,MaterialBox} from '../types/materials';
import {materialMediaUrl} from '../api/materials';
const props=withDefaults(defineProps<{image:MaterialRow;projectId:string;boxes?:MaterialBox[];full?:boolean;showBoxes?:boolean;framed?:boolean}>(),{full:false,showBoxes:true,framed:false});
const failed=ref(false),retry=ref(0),zoom=ref(1),natural=ref({width:0,height:0});
const url=computed(()=>materialMediaUrl(props.full?props.image.content_url:props.image.thumbnail_url,props.projectId,props.image.id,props.full?'content':'thumbnail'));
const width=computed(()=>props.full&&natural.value.width?natural.value.width:Number(props.image.width)||0),height=computed(()=>props.full&&natural.value.height?natural.value.height:Number(props.image.height)||0);
const ratio=computed(()=>{
  const {width:w,height:h}=natural.value;
  return w&&h?w/h:width.value>0&&height.value>0?width.value/height.value:1;
});
const validBoxes=computed(()=>(props.boxes||[]).filter(b=>[b.x1,b.y1,b.x2,b.y2].every(Number.isFinite)&&b.x2>b.x1&&b.y2>b.y1));
watch(()=>[props.image.id,url.value],()=>{failed.value=false;natural.value={width:0,height:0};zoom.value=1});
function loaded(event:Event){const img=event.target as HTMLImageElement;natural.value={width:img.naturalWidth,height:img.naturalHeight}}
</script>
<template><div class="material-media" :class="{full,framed:framed&&!full}" :style="{'--media-ratio':ratio}"><div v-if="full" class="zoom-tools"><button aria-label="缩小图片" @click="zoom=Math.max(.25,zoom/1.25)">−</button><span>{{ Math.round(zoom*100) }}%</span><button aria-label="放大图片" @click="zoom=Math.min(8,zoom*1.25)">+</button><button @click="zoom=1">适应</button></div><div class="media-scroll"><div v-if="url&&!failed" class="media-world" :style="full?{width:`${zoom*100}%`}:undefined"><img :key="`${url}:${retry}`" :src="url" :alt="image.filename" :loading="full?'eager':'lazy'" decoding="async" @load="loaded" @error="failed=true"><svg v-if="showBoxes&&width>0&&height>0" class="box-layer" :viewBox="`0 0 ${width} ${height}`" preserveAspectRatio="none" aria-label="标注框预览"><g v-for="(box,index) in validBoxes" :key="index"><rect :x="box.x1" :y="box.y1" :width="box.x2-box.x1" :height="box.y2-box.y1" vector-effect="non-scaling-stroke"/><text v-if="full" :x="box.x1" :y="Math.max(14,box.y1-3)" :font-size="Math.max(12,width/60)">{{ box.label||'目标' }}</text></g></svg></div><div v-else class="media-failed"><span>{{ failed?'图片读取失败':'缩略图未提供' }}</span><button v-if="url" @click="failed=false;retry++">重试图片</button></div></div></div></template>
<style scoped>
.material-media{background:#eef2f7;border-radius:10px;overflow:hidden}.media-scroll{overflow:auto;max-height:65vh}.media-world{position:relative;line-height:0;margin:auto}.media-world img{width:100%;height:auto;display:block}.material-media:not(.full) .media-world img{aspect-ratio:auto}.box-layer{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}.box-layer rect{fill:transparent;stroke:#16a34a;stroke-width:2}.box-layer text{fill:#14532d;stroke:white;stroke-width:2;paint-order:stroke}.media-failed{min-height:130px;display:grid;place-content:center;gap:12px;color:#475569}.zoom-tools{display:flex;gap:10px;align-items:center;padding:8px;background:white}.zoom-tools button,.media-failed button{border:1px solid #cbd5e1;background:white;border-radius:6px;padding:6px 12px;cursor:pointer}.full .media-scroll{min-height:180px}
.material-media.framed { background: #edeef0; }
.framed .media-scroll {
  display: grid;
  place-items: center;
  aspect-ratio: var(--media-frame, 4 / 3);
  container-type: size;
  overflow: hidden;
}
.framed .media-world { width: min(100cqi, calc(100cqb * var(--media-ratio))); }
.framed .media-failed { min-height: 0; padding: 6px; text-align: center; }
</style>

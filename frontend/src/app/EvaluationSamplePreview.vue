<script setup lang="ts">
import {computed,ref} from 'vue';
import {toAnno} from '../../../static/modules/annotation-geometry-adapter.js';

const props=defineProps<{src:string;sample:Record<string,unknown>;expanded:boolean}>();
const loaded=ref(false),failed=ref(false),sizeMatches=ref(false);
const showGt=ref(true),showPredictions=ref(true);
const width=computed(()=>Number(props.sample.image_width??props.sample.width));
const height=computed(()=>Number(props.sample.image_height??props.sample.height));
const name=computed(()=>String(props.sample.filename||props.sample.image_id||'冻结样本'));

function imageLoaded(event:Event){
  const image=event.currentTarget as HTMLImageElement;
  sizeMatches.value=image.naturalWidth===width.value&&image.naturalHeight===height.value;
  loaded.value=true;
}

const rectangles=computed(()=>['gt_boxes','pred_boxes'].flatMap(layer=>{
  const rows=props.sample[layer];
  if(!Array.isArray(rows)||!sizeMatches.value)return [];
  return rows.flatMap((row,index)=>{
    if(!Array.isArray(row?.box)||row.box.length!==4)return [];
    const [x1,y1,x2,y2]=row.box;
    const id=layer+index,label=String(row.label||'未记录类别');
    try{
      const {x,y,w,h}=toAnno({id,x1,y1,x2,y2,label},{width:width.value,height:height.value}).target.selector.geometry;
      const prediction=layer==='pred_boxes';
      const status=row.matched===true?'已匹配':row.matched===false?(prediction?'误检':'漏检'):'匹配状态未记录';
      const confidence=prediction&&typeof row.confidence==='number'&&Number.isFinite(row.confidence)?` · ${(row.confidence*100).toFixed(1)}%`:'';
      return [{id,prediction,label:`${label} · ${status}${confidence}`,style:{
        left:`${x/width.value*100}%`,top:`${y/height.value*100}%`,width:`${w/width.value*100}%`,height:`${h/height.value*100}%`,
      }}];
    }catch{return []}
  });
}));
</script>

<template>
  <p v-if="!src||failed">冻结图片未提供或读取失败</p>
  <template v-else>
    <div class="image-frame" :class="{expanded}">
      <img :src="src" loading="lazy" :alt="name" @load="imageLoaded" @error="failed=true">
      <template v-if="expanded">
        <span v-for="box in rectangles" v-show="box.prediction?showPredictions:showGt" :key="box.id"
          class="box" :class="{prediction:box.prediction}" :style="box.style" aria-hidden="true"/>
      </template>
    </div>
    <template v-if="expanded&&loaded">
      <fieldset v-if="rectangles.length">
        <legend>冻结框叠加</legend>
        <label><input v-model="showGt" type="checkbox"> 正式 GT（实线）</label>
        <label><input v-model="showPredictions" type="checkbox"> 模型预测（虚线）</label>
      </fieldset>
      <p v-else>{{sizeMatches?'当前没有可叠加的框。':'冻结尺寸缺失或与原图不一致，叠加不可用。'}}</p>
      <ul v-if="rectangles.length" aria-label="框级诊断">
        <template v-for="box in rectangles" :key="box.id">
          <li v-if="box.prediction?showPredictions:showGt">{{box.prediction?'预测':'GT'}} · {{box.label}}</li>
        </template>
      </ul>
    </template>
  </template>
</template>

<style scoped>
.image-frame{position:relative;display:table;max-width:100%}
.image-frame img{display:block;max-width:100%;max-height:300px}
.expanded img{max-height:none}
.box{position:absolute;box-sizing:border-box;border:2px solid #087f5b;pointer-events:none}
.box.prediction{border:2px dashed #b45309}
fieldset{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px}
ul{max-height:12rem;overflow:auto}
</style>

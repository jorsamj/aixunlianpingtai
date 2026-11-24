<script setup lang="ts">
import {onBeforeUnmount} from 'vue';
import {useRoute,useRouter} from 'vue-router';
import type {BrowseContext,BrowseMemory} from '../types/model-browse';
import PilotConversionHistory from '../views/ConversionHistory.vue';
import {request} from './http';
import {legacyUrl} from './navigation';
import '../styles/theme.css';
// Native wrapper: reuse the existing read-only pilot view/owner instead of
// duplicating conversion-history reads, filters, pagination or the drawer.
const props=defineProps<{projectId:string;algorithmId:string;versionId:string}>();
const route=useRoute(),router=useRouter(),controller=new AbortController();
onBeforeUnmount(()=>controller.abort());
const query=(key:string)=>typeof route.query[key]==='string'?String(route.query[key]):undefined;
const memory:BrowseMemory={selection:{algorithmId:props.algorithmId,versionId:props.versionId,
  algorithmName:query('algorithm_name'),versionName:query('version_name')}};
const context:BrowseContext={
  projectId:props.projectId,memory,signal:controller.signal,
  get:<T,>(url:string,options?:{signal?:AbortSignal})=>request<T>(url,options),
  returnToManagement:()=>void router.push({name:'algorithms',params:{projectId:props.projectId}}),
  returnToAssets:()=>void router.push({name:'algorithms',params:{projectId:props.projectId},
    query:{algorithm:props.algorithmId,version:props.versionId}}),
  openLegacy:()=>{window.location.assign(legacyUrl(props.projectId,'算法列表',props.algorithmId,props.versionId,'conversion'))},
  openConversionCreate:(selection)=>void router.push({name:'conversion-create-native',params:{projectId:props.projectId},
    query:{algorithm:selection.algorithmId,version:selection.versionId,
      ...(selection.algorithmName?{algorithm_name:selection.algorithmName}:{}),
      ...(selection.versionName?{version_name:selection.versionName}:{})}}),
  openConversionDetail:(jobId)=>void router.push({name:'conversion-detail-native',params:{projectId:props.projectId,jobId},
    query:{algorithm:props.algorithmId,version:props.versionId,
      ...(query('algorithm_name')?{algorithm_name:String(query('algorithm_name'))}:{}),
      ...(query('version_name')?{version_name:String(query('version_name'))}:{})}}),
  openHistory:(selection)=>void router.push({name:'version-conversions',params:{projectId:props.projectId,
    algorithmId:selection.algorithmId,versionId:selection.versionId},
    query:{algorithm_name:selection.algorithmName,version_name:selection.versionName}}),
};
</script>
<template><PilotConversionHistory :context="context"/></template>

<script setup lang="ts">
import {onBeforeUnmount} from 'vue';
import {useRouter} from 'vue-router';
import type {PreviewContext} from '../types/catalog';
import PilotServiceNodes from '../views/ServiceNodesOverview.vue';
import {request} from './http';
import '../styles/theme.css';
// Native wrapper around the existing read-only node overview. It keeps the
// pilot's manual refresh, local filters and request cancellation; no node
// connectivity test, token rotation or other write action is exposed.
const props=defineProps<{projectId:string}>();
const router=useRouter(),controller=new AbortController();
onBeforeUnmount(()=>controller.abort());
const context:PreviewContext={
  signal:controller.signal,
  projectId:props.projectId,
  get:<T,>(url:string,options?:{signal?:AbortSignal})=>request<T>(url,options),
  returnToManagement:()=>void router.push({name:'legacy',params:{projectId:props.projectId,page:'服务节点'}}),
};
</script>
<template><PilotServiceNodes :context="context"/></template>

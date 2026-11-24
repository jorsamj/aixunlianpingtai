<script setup lang="ts">
import {computed,ref,onMounted} from 'vue';
import {useRoute,useRouter} from 'vue-router';
import {useWorkspace} from './main';
import {request,login} from './http';
import {menus,legacyUrl} from './navigation';
const store=useWorkspace(),route=useRoute(),router=useRouter(),error=ref(''),advanced=ref(false);
const projectId=computed(()=>String(route.params.projectId||store.projects[0]?.id||''));
const immersive=computed(()=>route.meta.immersive===true);
const title=computed(()=>route.name==='ai-tasks'?'AI 标注任务':route.name==='ai-review-native'?'AI 候选审核':route.name==='public-negative-pool'?'项目公共负样本池':route.name==='materials'?'素材库':route.name==='material-upload'?'上传图片':route.name==='material-zip-import'?'ZIP 数据集导入':route.name==='upload-tasks'?'上传任务':route.name==='training-tasks'?'训练任务':route.name==='training-create'?'创建训练任务':route.name==='training-report'||route.name==='version-report'?'训练报告与评测':route.name==='version-conversions'?'转换记录与诊断':route.name==='service-nodes-native'?'服务节点与算力':route.name==='algorithms'?'算法库':menus.flatMap(group=>group.pages).find(([,page])=>page===route.params.page)?.[0]||'畅联云算法训练平台');
function projectChange(id:string){void router.push({name:route.name==='public-negative-pool'?'public-negative-pool':route.name==='materials'?'materials':'algorithms',params:{projectId:id}})}
function target(page:string){
 const project={projectId:projectId.value};
 if(page==='算法列表')return {name:'algorithms',params:project};
 if(page==='数据集')return {name:'materials',params:project};
 if(page==='训练任务')return {name:'training-tasks',params:project};
 return {name:'legacy',params:{...project,page}};
}
async function logout(){if(immersive.value&&!window.dispatchEvent(new Event('workspace-before-logout',{cancelable:true})))return;try{await request('/api/auth/logout',{method:'POST'});store.actorKey='';login()}catch(cause){error.value=(cause as Error).message}}
onMounted(()=>{void store.load().catch(cause=>{error.value=cause.message})});
</script>
<template><div class="application-shell">
 <aside v-if="!immersive" class="sidebar"><a class="brand" href="/app/">畅联云<span>算法训练平台</span></a>
  <nav v-if="projectId" aria-label="主导航"><template v-for="(group,index) in menus" :key="group.name"><section v-if="index<3||advanced"><h2>{{ group.name }}</h2><router-link v-for="[label,page] in group.pages" :key="page" :to="target(page)" :aria-current="title===label?'page':undefined">{{ label }}<small v-if="page!=='算法列表'&&page!=='训练任务'&&page!=='数据集'">原系统</small></router-link></section><el-button v-if="index===2" text @click="advanced=!advanced">{{ advanced?'收起高级功能':'展开高级功能' }}</el-button></template></nav>
  <a class="demo-link" :href="legacyUrl(projectId,'AI算法底座')">AI算法底座 · 独立业务演示系统</a>
 </aside>
 <div class="application-main"><header class="app-header"><div><small>畅联云 / {{ store.projects.find(p=>p.id===projectId)?.name||'项目' }}</small><h1>{{ title }}</h1></div><div class="session-tools"><el-select :model-value="projectId" aria-label="当前项目" @change="projectChange"><el-option v-for="project in store.projects" :key="project.id" :label="project.name" :value="project.id"/></el-select><span>{{ store.username }}</span><el-button @click="logout">退出</el-button></div></header>
  <main class="app-content" :class="{immersive}"><el-alert v-if="error" :title="error" type="error" :closable="false"/>
   <section v-if="route.name==='legacy'" class="legacy-page"><h2>{{ title }}</h2><router-link v-if="route.params.page==='训练任务'" :to="{name:'training-create',params:{projectId}}">原生创建训练任务</router-link><router-link v-if="route.params.page==='自动标注及清洗'" :to="{name:'ai-tasks',params:{projectId}}">原生 AI 标注任务列表（只读）</router-link><router-link v-if="route.params.page==='服务节点'" :to="{name:'service-nodes-native',params:{projectId}}">原生服务节点只读总览</router-link><p>本模块尚未迁移，继续使用完整原功能。</p><el-button tag="a" :href="legacyUrl(projectId,String(route.params.page))" type="primary">进入原{{ title }}</el-button><router-link :to="target('算法列表')">返回算法库</router-link></section>
   <router-view v-else :key="route.name==='training-create'?route.fullPath:route.path"/>
  </main>
 </div>
</div></template>

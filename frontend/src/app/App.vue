<script setup lang="ts">
import {computed,ref,onMounted} from 'vue';
import {useRoute,useRouter} from 'vue-router';
import {useWorkspace} from './main';
import {request,login} from './http';
import {menus,legacyUrl} from './navigation';
const store=useWorkspace(),route=useRoute(),router=useRouter(),error=ref(''),advanced=ref(false);
const projectId=computed(()=>String(route.params.projectId||store.projects[0]?.id||''));
const title=computed(()=>route.name==='algorithms'?'算法库':menus.flatMap(group=>group.pages).find(([,page])=>page===route.params.page)?.[0]||'畅联云算法训练平台');
function projectChange(id:string){void router.push({name:'algorithms',params:{projectId:id}})}
function target(page:string){return {name:page==='算法列表'?'algorithms':'legacy',params:{projectId:projectId.value,...(page==='算法列表'?{}:{page})}}}
async function logout(){try{await request('/api/auth/logout',{method:'POST'});login()}catch(cause){error.value=(cause as Error).message}}
onMounted(()=>{void store.load().catch(cause=>{error.value=cause.message})});
</script>
<template><div class="application-shell">
 <aside class="sidebar"><a class="brand" href="/app/">畅联云<span>算法训练平台</span></a>
  <nav v-if="projectId" aria-label="主导航"><template v-for="(group,index) in menus" :key="group.name"><section v-if="index<3||advanced"><h2>{{ group.name }}</h2><router-link v-for="[label,page] in group.pages" :key="page" :to="target(page)" :aria-current="title===label?'page':undefined">{{ label }}<small v-if="page!=='算法列表'">原系统</small></router-link></section><el-button v-if="index===2" text @click="advanced=!advanced">{{ advanced?'收起高级功能':'展开高级功能' }}</el-button></template></nav>
  <a class="demo-link" :href="legacyUrl(projectId,'AI算法底座')">AI算法底座 · 独立业务演示系统</a>
 </aside>
 <div class="application-main"><header class="app-header"><div><small>畅联云 / {{ store.projects.find(p=>p.id===projectId)?.name||'项目' }}</small><h1>{{ title }}</h1></div><div class="session-tools"><el-select :model-value="projectId" aria-label="当前项目" @change="projectChange"><el-option v-for="project in store.projects" :key="project.id" :label="project.name" :value="project.id"/></el-select><span>{{ store.username }}</span><el-button @click="logout">退出</el-button></div></header>
  <main class="app-content"><el-alert v-if="error" :title="error" type="error" :closable="false"/>
   <section v-if="route.name==='legacy'" class="legacy-page"><h2>{{ title }}</h2><p>本模块尚未迁移，继续使用完整原功能。</p><el-button tag="a" :href="legacyUrl(projectId,String(route.params.page))" type="primary">进入原{{ title }}</el-button><router-link :to="target('算法列表')">返回算法库</router-link></section>
   <router-view v-else :key="route.path"/>
  </main>
 </div>
</div></template>

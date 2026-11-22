import {createApp,ref,h} from 'vue';
import {createPinia,defineStore} from 'pinia';
import {createRouter,createWebHashHistory} from 'vue-router';
import ElementPlus from 'element-plus';
import zhCn from 'element-plus/es/locale/lang/zh-cn';
import 'element-plus/dist/index.css';
import {request,login} from './http';
import App from './App.vue';
import './style.css';
interface Project {id:string;name:string}
interface WorkspaceSession {authenticated:boolean;provider?:string;user?:{username:string}}
export function readWorkspaceSession(signal?:AbortSignal){
  return request<WorkspaceSession>('/api/auth/session',{signal,cache:'no-store'});
}
export function workspaceActorKey(session:WorkspaceSession){
  return session.authenticated&&session.user?.username
    ? JSON.stringify([session.provider||'',session.user.username]) : '';
}
export const useWorkspace=defineStore('workspace',()=>{
  const projects=ref<Project[]>([]),username=ref(''),actorKey=ref('');
  let ready:Promise<void>|undefined;
  function load(){return ready??=(async()=>{
    const session=await readWorkspaceSession();
    if(!session.authenticated){login();throw new Error('请先登录')}
    // Reuse the existing session renewal owner instead of adding another timer.
    void import('../../../static/auth-session.js');
    username.value=session.user?.username||'';
    actorKey.value=workspaceActorKey(session);
    projects.value=await request<Project[]>('/api/projects');
  })().catch(error=>{ready=undefined;throw error})}
  return {projects,username,actorKey,load};
});
export const router=createRouter({history:createWebHashHistory('/app/'),routes:[
  {path:'/',component:{render:()=>h('p','当前账号没有可用项目。')}},
  {path:'/projects/:projectId/algorithms',name:'algorithms',component:()=>import('./Algorithms.vue')},
  {path:'/projects/:projectId/materials/negative-pool',name:'public-negative-pool',props:true,component:()=>import('./PublicNegativePool.vue')},
  {path:'/projects/:projectId/materials',name:'materials',component:()=>import('./Materials.vue')},
  {path:'/projects/:projectId/materials/upload',name:'material-upload',component:()=>import('./MaterialUpload.vue')},
  {path:'/projects/:projectId/materials/zip',name:'material-zip-import',component:()=>import('./ZipImport.vue')},
  {path:'/projects/:projectId/materials/tasks',name:'upload-tasks',component:()=>import('./UploadTasks.vue')},
  {path:'/projects/:projectId/training/tasks',name:'training-tasks',component:()=>import('./TrainingTasks.vue')},
  {path:'/projects/:projectId/training/reports/:jobId',name:'training-report',component:()=>import('./NativeTrainingReport.vue')},
  {path:'/projects/:projectId/algorithms/:algorithmId/versions/:versionId/report',name:'version-report',component:()=>import('./NativeTrainingReport.vue')},
  {path:'/projects/:projectId/training/create',name:'training-create',component:()=>import('./TrainingCreate.vue')},
  {path:'/projects/:projectId/ai/tasks/:taskId/review',name:'ai-review-native',props:true,meta:{immersive:true},component:()=>import('./AiReview.vue')},
  {path:'/projects/:projectId/legacy/:page',name:'legacy',component:{render:()=>null}},
  {path:'/:pathMatch(.*)*',name:'not-found',component:{render:()=>h('p','页面不存在，请从侧栏选择业务入口。')}},
]});
// Root layout is outside RouterView; each project/route gets a fresh page scope.
router.beforeEach(async to=>{
  const store=useWorkspace();
  try{await store.load()}catch{return false}
  if(to.path==='/')return store.projects.length?{name:'algorithms',params:{projectId:store.projects[0].id}}:true;
  if(to.params.projectId&&!store.projects.some(project=>project.id===to.params.projectId))return {name:'not-found',params:{pathMatch:['unknown-project']}};
});
createApp(App).use(createPinia()).use(router).use(ElementPlus,{locale:zhCn}).mount('#app');

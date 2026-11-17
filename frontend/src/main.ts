import {createApp,h} from 'vue';
import {createPinia} from 'pinia';
import {createRouter,createMemoryHistory,RouterView} from 'vue-router';
import {ElConfigProvider,ElButton,ElInput,ElSelect,ElOption,ElTable,ElTableColumn,ElTag,ElPagination,ElDrawer,ElAlert,ElEmpty,ElSkeleton,ElCheckbox,ElDropdown,ElDropdownMenu,ElDropdownItem} from 'element-plus';
import zhCn from 'element-plus/es/locale/lang/zh-cn';
import 'element-plus/theme-chalk/base.css';
import 'element-plus/theme-chalk/el-button.css';
import 'element-plus/theme-chalk/el-input.css';
import 'element-plus/theme-chalk/el-select.css';
import 'element-plus/theme-chalk/el-option.css';
import 'element-plus/theme-chalk/el-table.css';
import 'element-plus/theme-chalk/el-table-column.css';
import 'element-plus/theme-chalk/el-tag.css';
import 'element-plus/theme-chalk/el-pagination.css';
import 'element-plus/theme-chalk/el-drawer.css';
import 'element-plus/theme-chalk/el-overlay.css';
import 'element-plus/theme-chalk/el-alert.css';
import 'element-plus/theme-chalk/el-empty.css';
import 'element-plus/theme-chalk/el-skeleton.css';
import 'element-plus/theme-chalk/el-checkbox.css';
import 'element-plus/theme-chalk/el-dropdown.css';
import 'element-plus/theme-chalk/el-dropdown-menu.css';
import 'element-plus/theme-chalk/el-dropdown-item.css';
import CatalogPreview from './views/CatalogPreview.vue';
import TrainingCreate from './views/TrainingCreate.vue';
import ConversionCreate from './views/ConversionCreate.vue';
import type {ConversionCreateContext} from './types/conversion-create';
import type {TrainingCreateContext} from './types/training-create';
import ServiceNodesOverview from './views/ServiceNodesOverview.vue';
import MaterialLibrary from './views/MaterialLibrary.vue';
import NegativePool from './views/NegativePool.vue';
import TrainingMaterialPicker from './views/TrainingMaterialPicker.vue';
import type {PoolContext} from './types/negative-pool';
import type {PickerContext} from './types/training-picker';
import type {MaterialContext} from './types/materials';
import TrainingTasks from './views/TrainingTasks.vue';
import AiAnnotationTasks from './views/AiAnnotationTasks.vue';
import AiReviewWorkbench from './views/AiReviewWorkbench.vue';
import type {AiReviewContext} from './types/ai-review';
import type {AiTaskContext} from './types/ai-tasks';
import TrainingReport from './views/TrainingReport.vue';
import ModelAssets from './views/ModelAssets.vue';
import ConversionHistory from './views/ConversionHistory.vue';
import type {BrowseContext} from './types/model-browse';
import type {Component} from 'vue';
import './styles/theme.css';
import type {PreviewContext} from './types/catalog';
export async function mountCatalogPreview(host:HTMLElement,context:PreviewContext){
  return mountView(host,context,CatalogPreview);
}
export async function mountServiceNodes(host:HTMLElement,context:PreviewContext){
  return mountView(host,context,ServiceNodesOverview);
}
export async function mountModelAssets(host:HTMLElement,context:BrowseContext){return mountView(host,context,ModelAssets)}
export async function mountConversionHistory(host:HTMLElement,context:BrowseContext){return mountView(host,context,ConversionHistory)}
export async function mountTrainingTasks(host:HTMLElement,context:BrowseContext){return mountView(host,context,TrainingTasks)}
export async function mountTrainingReport(host:HTMLElement,context:BrowseContext){return mountView(host,context,TrainingReport)}
export async function mountMaterialLibrary(host:HTMLElement,context:MaterialContext){return mountView(host,context,MaterialLibrary)}
export async function mountNegativePool(host:HTMLElement,context:PoolContext){return mountView(host,context,NegativePool)}
export async function mountTrainingMaterialPicker(host:HTMLElement,context:PickerContext){return mountView(host,context,TrainingMaterialPicker)}
export async function mountAiAnnotationTasks(host:HTMLElement,context:AiTaskContext){return mountView(host,context,AiAnnotationTasks)}
export async function mountAiReviewWorkbench(host:HTMLElement,context:AiReviewContext){return mountView(host,context,AiReviewWorkbench)}
export async function mountTrainingCreate(host:HTMLElement,context:TrainingCreateContext){return mountView(host,context,TrainingCreate)}
export async function mountConversionCreate(host:HTMLElement,context:ConversionCreateContext){return mountView(host,context,ConversionCreate)}
async function mountView(host:HTMLElement,context:PreviewContext|PickerContext|AiReviewContext|TrainingCreateContext|ConversionCreateContext,component:Component){
  const router=createRouter({history:createMemoryHistory(),routes:[{path:'/',component,props:{context}}]});
  const app=createApp({render:()=>h(ElConfigProvider,{locale:zhCn},()=>h(RouterView))});
  app.use(createPinia()).use(router);
  for(const [name,component] of Object.entries({ElButton,ElInput,ElSelect,ElOption,ElTable,ElTableColumn,ElTag,ElPagination,ElDrawer,ElAlert,ElEmpty,ElSkeleton,ElCheckbox,ElDropdown,ElDropdownMenu,ElDropdownItem}))app.component(name,component);
  await router.push('/');await router.isReady();
  host.textContent='';app.mount(host);
  return ()=>{app.unmount();router.options.history.destroy()};
}

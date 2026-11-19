import {createApp,h} from 'vue';
import {createPinia} from 'pinia';
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
import type {ProductWorkbenchContext} from './types/product-workbench';
import type {ConfigurationCenterContext} from './types/configuration-center';
import type {AiAnnotationCreateContext} from './types/ai-annotation-create';
import type {MaterialImportGovernanceContext} from './types/material-import-governance';
import type {ModelDeliveryContext} from './types/model-delivery';
import type {ConversionCreateContext} from './types/conversion-create';
import type {TrainingCreateContext} from './types/training-create';
import type {PoolContext} from './types/negative-pool';
import type {PickerContext} from './types/training-picker';
import type {MaterialContext} from './types/materials';
import type {AiReviewContext} from './types/ai-review';
import type {AiTaskContext} from './types/ai-tasks';
import type {BrowseContext} from './types/model-browse';
import type {Component} from 'vue';
import './styles/theme.css';
import type {PreviewContext} from './types/catalog';
export async function mountCatalogPreview(host:HTMLElement,context:PreviewContext){
  return mountView(host,context,()=>import('./views/CatalogPreview.vue'));
}
export async function mountServiceNodes(host:HTMLElement,context:PreviewContext){
  return mountView(host,context,()=>import('./views/ServiceNodesOverview.vue'));
}
export async function mountModelAssets(host:HTMLElement,context:BrowseContext){return mountView(host,context,()=>import('./views/ModelAssets.vue'))}
export async function mountConversionHistory(host:HTMLElement,context:BrowseContext){return mountView(host,context,()=>import('./views/ConversionHistory.vue'))}
export async function mountTrainingTasks(host:HTMLElement,context:BrowseContext){return mountView(host,context,()=>import('./views/TrainingTasks.vue'))}
export async function mountTrainingReport(host:HTMLElement,context:BrowseContext){return mountView(host,context,()=>import('./views/TrainingReport.vue'))}
export async function mountMaterialLibrary(host:HTMLElement,context:MaterialContext){return mountView(host,context,()=>import('./views/MaterialLibrary.vue'))}
export async function mountNegativePool(host:HTMLElement,context:PoolContext){return mountView(host,context,()=>import('./views/NegativePool.vue'))}
export async function mountTrainingMaterialPicker(host:HTMLElement,context:PickerContext){return mountView(host,context,()=>import('./views/TrainingMaterialPicker.vue'))}
export async function mountAiAnnotationTasks(host:HTMLElement,context:AiTaskContext){return mountView(host,context,()=>import('./views/AiAnnotationTasks.vue'))}
export async function mountAiReviewWorkbench(host:HTMLElement,context:AiReviewContext){return mountView(host,context,()=>import('./views/AiReviewWorkbench.vue'))}
export async function mountTrainingCreate(host:HTMLElement,context:TrainingCreateContext){return mountView(host,context,()=>import('./views/TrainingCreate.vue'))}
export async function mountConversionCreate(host:HTMLElement,context:ConversionCreateContext){return mountView(host,context,()=>import('./views/ConversionCreate.vue'))}
export async function mountModelDelivery(host:HTMLElement,context:ModelDeliveryContext){return mountView(host,context,()=>import('./views/ModelDelivery.vue'))}
export async function mountMaterialImportGovernance(host:HTMLElement,context:MaterialImportGovernanceContext){return mountView(host,context,()=>import('./views/MaterialImportGovernance.vue'))}
export async function mountAiAnnotationCreate(host:HTMLElement,context:AiAnnotationCreateContext){return mountView(host,context,()=>import('./views/AiAnnotationCreate.vue'))}
export async function mountConfigurationCenter(host:HTMLElement,context:ConfigurationCenterContext){return mountView(host,context,()=>import('./views/ConfigurationCenter.vue'))}
export async function mountProductWorkbench(host:HTMLElement,context:ProductWorkbenchContext){return mountView(host,context,()=>import('./views/ProductWorkbench.vue'))}
async function mountView(host:HTMLElement,context:PreviewContext|MaterialContext|PickerContext|AiReviewContext|TrainingCreateContext|ConversionCreateContext|ModelDeliveryContext|MaterialImportGovernanceContext|AiAnnotationCreateContext|ConfigurationCenterContext|ProductWorkbenchContext,load:()=>Promise<{default:Component}>){
  if('signal' in context&&context.signal.aborted)return ()=>{};
  const {default:component}=await load();
  if('signal' in context&&context.signal.aborted)return ()=>{};
  const app=createApp({render:()=>h(ElConfigProvider,{locale:zhCn},()=>h(component,{context}))});
  app.use(createPinia());
  for(const [name,component] of Object.entries({ElButton,ElInput,ElSelect,ElOption,ElTable,ElTableColumn,ElTag,ElPagination,ElDrawer,ElAlert,ElEmpty,ElSkeleton,ElCheckbox,ElDropdown,ElDropdownMenu,ElDropdownItem}))app.component(name,component);
  host.textContent='';app.mount(host);
  return ()=>{app.unmount()};
}

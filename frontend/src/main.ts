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
import ServiceNodesOverview from './views/ServiceNodesOverview.vue';
import type {Component} from 'vue';
import './styles/theme.css';
import type {PreviewContext} from './types/catalog';
export async function mountCatalogPreview(host:HTMLElement,context:PreviewContext){
  return mountView(host,context,CatalogPreview);
}
export async function mountServiceNodes(host:HTMLElement,context:PreviewContext){
  return mountView(host,context,ServiceNodesOverview);
}
async function mountView(host:HTMLElement,context:PreviewContext,component:Component){
  const router=createRouter({history:createMemoryHistory(),routes:[{path:'/',component,props:{context}}]});
  const app=createApp({render:()=>h(ElConfigProvider,{locale:zhCn},()=>h(RouterView))});
  app.use(createPinia()).use(router);
  for(const [name,component] of Object.entries({ElButton,ElInput,ElSelect,ElOption,ElTable,ElTableColumn,ElTag,ElPagination,ElDrawer,ElAlert,ElEmpty,ElSkeleton,ElCheckbox,ElDropdown,ElDropdownMenu,ElDropdownItem}))app.component(name,component);
  await router.push('/');await router.isReady();
  host.textContent='';app.mount(host);
  return ()=>{app.unmount();router.options.history.destroy()};
}

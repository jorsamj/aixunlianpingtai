import {readFileSync} from 'node:fs';
// Existing API owner, session, navigation and complete legacy dictionary runtime.
// Only HTTP data is synthetic; no FastAPI startup, SDK scan or business database.
const originalApi=readFileSync('../static/app.js','utf8').split('// Shared request identity')[0];
export const fixture=`<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><link rel="stylesheet" href="/static/styles.css"><style>body{background:#f5f7fb;margin:0}#view{padding:24px;max-width:1640px;margin:auto}</style></head><body><span id="authUsername"></span><main id="view"></main><script src="/static/auth-session.js"></script><script type="module">
import {installNavigationStability} from '/static/modules/navigation-stability.js';
import {installPageRequestScope} from '/static/modules/page-request-scope.js';
import {installPollRegistry} from '/static/modules/poll-registry.js';
import {installConversionCatalogRuntime,catalogOperationId} from '/static/modules/conversion-catalog-runtime.js';
import {installCatalogPreview,PREVIEW_PAGE,MANAGEMENT_PAGE,NODES_PAGE,ASSETS_PAGE,HISTORY_PAGE,TASKS_PAGE,REPORT_PAGE} from '/static/modules/catalog-preview-runtime.js';
${originalApi}
const state={page:'部署资源',project:{id:'p'}};window.state=state;
const scope=installPageRequestScope({getPage:()=>state.page});
const polls=installPollRegistry({getState:()=>state});
const old=installConversionCatalogRuntime({api,getState:()=>state,modal(){},closeModal(){}});
let preview;
function legacy(){document.querySelector('#view').innerHTML='<div id="conversion-catalog-host"></div>';return old.mount(document.querySelector('#conversion-catalog-host'))}
const nav=installNavigationStability({getState:()=>state,requestScope:scope,pollRegistry:polls,knownPages:['部署资源','服务节点','算法列表',PREVIEW_PAGE,MANAGEMENT_PAGE,NODES_PAGE,ASSETS_PAGE,HISTORY_PAGE,TASKS_PAGE,REPORT_PAGE],performNavigation:page=>{preview?.leave();old.leave();state.page=page;return [PREVIEW_PAGE,MANAGEMENT_PAGE,NODES_PAGE,ASSETS_PAGE,HISTORY_PAGE,TASKS_PAGE,REPORT_PAGE].includes(page)?nav.renderPage(page):legacy()}});
preview=installCatalogPreview({enabled:new URLSearchParams(location.search).get('vue_catalog_preview')==='1',managementEnabled:new URLSearchParams(location.search).get('vue_catalog_manage')==='1',nodesEnabled:new URLSearchParams(location.search).get('vue_service_nodes')==='1',assetsEnabled:new URLSearchParams(location.search).get('vue_model_assets')==='1',algorithmEnabled:new URLSearchParams(location.search).get('vue_algorithm_manage')==='1',tasksEnabled:new URLSearchParams(location.search).get('vue_training_tasks')==='1',reportsEnabled:new URLSearchParams(location.search).get('vue_training_report')==='1',createOperationId:()=>catalogOperationId(window.crypto),navigation:nav,getState:()=>state,request:api,deadline:(await import('/static/modules/api.js')).withRequestDeadline});
window.preview=preview;await legacy();window.fixtureReady=true;
</script></body></html>`;

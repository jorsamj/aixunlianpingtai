// Presentation metadata only. Original page names remain lifecycle/async owners.
export const ADVANCED_MENUS = Object.freeze([
  {title:'算力与节点',page:'服务节点',description:'节点运行状态、训练环境与组件诊断',tabs:[
    {id:'nodes',page:'服务节点',label:'服务节点'},
    {id:'training',page:'训练资源',label:'训练环境'},
    {id:'diagnostics',page:'组件检测',label:'环境诊断'},
  ]},
  {title:'模型转换环境',page:'部署资源',description:'管理转换资源、工具链与厂商芯片字典',tabs:[
    {id:'resources',page:'部署资源',label:'转换资源'},
    {id:'catalog',page:'部署资源',label:'厂商与芯片字典'},
  ]},
  {title:'AI 辅助配置',page:'模型配置',description:'配置辅助标注模型及提示词，与训练模型版本分开管理',tabs:[
    {id:'models',page:'模型配置',label:'AI 模型'},
    {id:'prompts',page:'模型配置',label:'提示词模板'},
  ]},
  {title:'存储管理',page:'存储配置',description:'存储资源、可核验的空间与缓存信息及兼容维护',tabs:[
    {id:'resources',page:'存储配置',label:'存储资源'},
    {id:'cache',page:'存储配置',label:'空间与缓存'},
    {id:'compatibility',page:'旧素材兼容迁移',label:'旧素材兼容迁移'},
  ]},
]);

export function advancedPageInfo(page) {
  return ADVANCED_MENUS.find(menu=>menu.tabs.some(tab=>tab.page===page)) || null;
}

export function advancedTab(page, section) {
  const tabs=advancedPageInfo(page)?.tabs || [];
  return tabs.find(tab=>tab.page===page && tab.id===section) || tabs.find(tab=>tab.page===page) || null;
}

export function installAdvancedNavigation({getState,storage=globalThis.localStorage,document:doc=globalThis.document,navigate}={}) {
  const key='mc_train_ui_state_v34';
  const tabs=doc.getElementById('advancedPageTabs');
  const view=doc.getElementById('view');
  const summary=doc.getElementById('summary');
  function read() {try{return JSON.parse(storage?.getItem(key)||'{}') || {}}catch(_){return {}}}
  function selected() {const page=getState().page;return advancedTab(page,read().advancedSections?.[page]);}
  function render() {
    const page=getState().page, menu=advancedPageInfo(page), tab=selected();
    tabs.hidden=!menu;
    view.classList.toggle('advanced-content',Boolean(menu));
    view.classList.toggle('integration-content',['平台对接','畅联云数据'].includes(page));
    view.dataset.advancedSection=tab?.id || '';
    view.dataset.advancedPage=page;
    if(summary)summary.classList.toggle('advanced-summary',Boolean(menu));
    if(!menu){tabs.replaceChildren();view.removeAttribute('aria-labelledby');view.removeAttribute('role');return;}
    view.setAttribute('role','tabpanel');
    // Only navigation updates this strip; business polling cannot replace it.
    tabs.innerHTML=menu.tabs.map(item=>`<button type="button" role="tab" id="advanced-tab-${item.id}" aria-controls="view" aria-selected="${item===tab}" tabindex="${item===tab?0:-1}" data-advanced-tab="${item.id}">${item.label}</button>`).join('');
    tabs.setAttribute('aria-label',menu.title);
    view.setAttribute('aria-labelledby',`advanced-tab-${tab.id}`);
  }
  function select(section) {
    const page=getState().page, menu=advancedPageInfo(page), tab=menu?.tabs.find(item=>item.id===section);
    if(!tab)return;
    const current=read();
    try{storage?.setItem(key,JSON.stringify({...current,advancedSections:{...current.advancedSections,[tab.page]:tab.id}}));}catch(_){}
    if(tab.page!==page)return navigate(tab.page);
    render();
  }
  const click=event=>{const button=event.target.closest('[data-advanced-tab]');if(button)select(button.dataset.advancedTab);};
  const keydown=event=>{
    if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
    const buttons=[...tabs.querySelectorAll('[role="tab"]')],index=buttons.indexOf(doc.activeElement);
    if(index<0)return;
    event.preventDefault();
    const next=event.key==='Home'?0:event.key==='End'?buttons.length-1:(index+(event.key==='ArrowRight'?1:-1)+buttons.length)%buttons.length;
    buttons[next].click();
    doc.getElementById(buttons[next].id)?.focus();
  };
  tabs.addEventListener('click',click);tabs.addEventListener('keydown',keydown);
  return {render,select,description:()=>advancedPageInfo(getState().page)?.description || '',destroy(){tabs.removeEventListener('click',click);tabs.removeEventListener('keydown',keydown);}};
}

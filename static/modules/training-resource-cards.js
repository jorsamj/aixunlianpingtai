/* Extracted presentation only; must load before classic app.js. No app state, API, or event owners. */
(function (global) {
  'use strict';
function renderTrainingResourceCards(targets,{escape,familySummary}){
  return (targets||[]).map(t=>`<div class="res-card ${t.status==='ready'?'ready':'warn'}">
    <div class="res-main"><div class="res-icon">${t.framework==='paddle'?'桨':t.type==='server'?'服':'U'}</div><div><div class="item-title">${escape(t.name)}</div><div class="item-sub">${t.framework==='paddle'?'飞桨 PaddleDetection':t.framework==='ultralytics'?'Ultralytics':'未知'} · ${t.type==='server'?'训练服务器':'本机环境'} ${t.version?'· '+escape(t.version):''}</div>${t.framework==='paddle'?`<div class="item-sub">${escape(familySummary(t)||t.scan?.error||'未扫描到 configs，请确认 PaddleDetection 目录')}</div>`:''}</div></div>
    <div class="res-meta"><span class="pill ${t.status==='ready'?'ok':'warn'}">${t.status==='ready'?'可用':t.status==='offline'?'不可用':'待确认'}</span><span class="pill blue">${(t.algorithms||[]).length} 个算法</span><span class="pill">${(t.base_models||[]).length} 个权重</span>${t.id?.startsWith('server:')&&!t.scheduler_owned?`<button class="btn mini" onclick='testSavedTrainServer(${escape(JSON.stringify(String(t.server_id||'')))},this)'>检测</button>`:''}${t.framework==='paddle'?`<button class="btn mini" onclick="viewResourceAlgorithms('${escape(t.id)}')">查看算法</button>`:''}</div>
  </div>`).join('');
}
  global.TrainingResourceCardsRuntime = Object.freeze({render: renderTrainingResourceCards});
})(window);

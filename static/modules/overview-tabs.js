// Canonical overview tabs: reuse the production dashboard and existing telemetry
// sources. A missing metric is unknown; never manufacture "0%" accuracy or cloud bytes.
export const OVERVIEW_TABS = Object.freeze([
  {id:'algorithm',label:'算法一张图'},
  {id:'compute',label:'算力一张图'},
]);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const number = value => value === null || value === undefined || value === '' ? null :
  (Number.isFinite(Number(value)) ? Number(value) : null);
const percent = value => number(value) == null ? null : Math.max(0,Math.min(100,number(value)));
const ratio = value => number(value) == null ? null : (Number(value) <= 1 ? Number(value)*100 : Number(value));
const fmt = value => value === null || value === undefined ? '—' : Number(value).toLocaleString('zh-CN');
const pct = value => number(value) == null ? '—' : ratio(value).toFixed(1)+'%';
const bytes = value => {
  if (number(value) == null) return '—';
  const units=['B','KB','MB','GB','TB','PB'];
  let n=Number(value),index=0;
  while(n>=1024&&index<units.length-1){n/=1024;index++}
  // Memory and disk figures are bytes, not estimated.
  return n.toFixed(index===0?0:1)+' '+units[index];
};
const empty = message => '<div class="ov348-empty">'+esc(message)+'</div>';
const metric = (name,value,note) => '<div class="ov348-stat"><span>'+esc(name)+'</span><strong>'+esc(value)+'</strong><small>'+esc(note||'')+'</small></div>';
const panel = (title,body,note,cls='') => '<section class="ov348-panel '+cls+'"><div class="ov348-panel-head"><h3>'+esc(title)+'</h3><span>'+esc(note||'')+'</span></div>'+body+'</section>';
const bar = (name,amount,max,meta) => '<div class="ov348-bar"><div class="ov348-bar-title"><span>'+esc(name)+'</span><b>'+esc(meta==null?fmt(amount):meta)+'</b></div><i><em style="width:'+Math.max(0,Math.min(100,max>0?amount/max*100:0)).toFixed(1)+'%"></em></i></div>';
const gauge = (name,value,extra) => '<div class="ov348-gauge"><span>'+esc(name)+'</span><b>'+esc(value==null?'—':percent(value).toFixed(1)+'%')+'</b><i><em style="width:'+(value==null?0:percent(value).toFixed(1))+'%"></em></i><small>'+esc(extra||'')+'</small></div>';
const rows = (items,fn) => '<div class="ov348-rows">'+items.map(fn).join('')+'</div>';

export function buildAlgorithmMap(algorithms=[],quality=null) {
  const list=Array.isArray(algorithms)?algorithms:[];
  const types=new Map(),industries=new Map();
  for(const item of list) {
    const type=String(item?.algorithm_type||'未分类').trim()||'未分类';
    const industry=String(item?.industry||'未分类').trim()||'未分类';
    types.set(type,(types.get(type)||0)+1);
    industries.set(industry,(industries.get(industry)||0)+1);
  }
  const sorted=m=>[...m].map(([name,count])=>({name,count})).sort((a,b)=>b.count-a.count||a.name.localeCompare(b.name,'zh'));
  const lookup=new Map((Array.isArray(quality?.algorithms)?quality.algorithms:[])
    .map(x=>[String(x?.id||''),x?.metrics||{}]));
  const scores=list.map(a=>{
    const m=lookup.get(String(a.id))||{};
    const v=key=>{const n=number(m[key]);return n==null?null:Math.max(0,Math.min(100,ratio(n)))};
    return {id:a.id,name:String(a.name||a.id||'未命名算法'),
      precision:v('precision'),recall:v('recall'),map50:v('map50')};
  }).sort((a,b)=>(b.map50??-1)-(a.map50??-1));
  const measured=scores.filter(x=>x.map50!==null||x.precision!==null||x.recall!==null).length;
  const withVersions=list.filter(a=>Array.isArray(a?.versions)&&a.versions.length>0).length;
  const versionCount=list.reduce((sum,a)=>sum+(Array.isArray(a?.versions)?a.versions.length:0),0);
  return {total:list.length,withVersions,versionCount,types:sorted(types),industries:sorted(industries),scores,measured,
    // No authoritative production inference counters, policy adjudications, or unit
    // bindings exist in the current project data contract. Never use training count.
    usage:[],units:[],strategyAccuracy:null};
}

export function buildComputeMap(nodes=[],storage=[],gpuRuntime=null) {
  const list=Array.isArray(nodes)?nodes:[],sources=Array.isArray(storage)?storage:[];
  const online=list.filter(n=>n?.status==='ONLINE'&&n?.online===true);
  const placement={center:[],edge:[],unclassified:[]};
  for(const n of list)placement[['center','edge'].includes(n?.placement)?n.placement:'unclassified'].push(n);
  const activeGpus=online.flatMap(n=>(Array.isArray(n?.resources?.gpu?.gpus)?n.resources.gpu.gpus:[])
    .map(g=>({...g,nodeId:String(n.node_id||''),nodeName:String(n.display_name||n.node_id||'未命名节点'),placement:n.placement||'unclassified'})));
  const inventory=Array.isArray(gpuRuntime?.gpus)?gpuRuntime.gpus:[];
  const runtimeGpus=new Map(inventory.filter(x=>x?.metrics_fresh===true&&x?.telemetry_available===true)
    .map(x=>[String(x.node_id||'')+'|'+String(x.gpu_uuid||''),x]));
  const known=activeGpus.map(g=>{
    const t=runtimeGpus.get(g.nodeId+'|'+String(g.uuid||''));
    // /api/v62/gpu-runtime is a telemetry snapshot, NOT a reservation summary.
    // Missing active_tasks/reserved_bytes/policy must not be silently treated as zero.
    const evidence=!!t&&['active_tasks','reserved_bytes','free_bytes','total_bytes'].every(k=>number(t[k])!==null)
      &&number(gpuRuntime?.memory_safety_bytes)!==null
      &&number(gpuRuntime?.max_concurrent_per_gpu)!==null;
    const candidate=evidence&&Number(t.active_tasks)===0&&Number(t.reserved_bytes)===0
      &&Number(gpuRuntime.max_concurrent_per_gpu)>0
      &&Number(t.free_bytes)>Number(gpuRuntime.memory_safety_bytes);
    return {...g,admission:!evidence?'unknown':candidate?'candidate':'occupied'};
  });
  const avg=key=>{const v=online.map(n=>percent(n?.resources?.[key]?.usage_percent)).filter(x=>x!==null);return v.length?v.reduce((a,b)=>a+b,0)/v.length:null;};
  const onlineIds=new Set(online.map(n=>String(n.node_id)));
  const byNode=list.map(n=>{
    const live=onlineIds.has(String(n.node_id));
    const r=live?n.resources||{}:{};
    return {id:n.node_id,name:String(n.display_name||n.node_id||'节点'),
      placement:n.placement||'unclassified',status:String(n.status||'UNKNOWN'),live,
      cpu:percent(r.cpu?.usage_percent),mem:percent(r.memory?.usage_percent),
      disk:percent(r.disk?.usage_percent),memoryUsed:r.memory?.used_bytes,
      memoryTotal:r.memory?.total_bytes,diskUsed:r.disk?.used_bytes,
      diskTotal:r.disk?.total_bytes,gpuCount:live?(r.gpu?.gpus||[]).length:null};
  });
  const warningNodes=new Set(byNode.filter(x=>[x.cpu,x.mem,x.disk].some(v=>v!==null&&v>=85)).map(x=>x.id));
  for(const n of list)if(n?.status==='OFFLINE')warningNodes.add(n.node_id);
  const warnings=warningNodes.size;
  const monitoredNodeCount=list.filter(n=>['ONLINE','OFFLINE'].includes(String(n?.status||''))).length;
  const typeCounts={local:0,oss:0,s3:0,remote:0};
  for(const x of sources)if(Object.hasOwn(typeCounts,String(x?.type||'')))typeCounts[x.type]++;
  return {nodesKnown:Array.isArray(nodes),nodeCount:list.length,online:online.length,offline:list.filter(n=>n?.status==='OFFLINE').length,
    disabled:list.filter(n=>n?.status==='DISABLED').length,
    neverConnected:list.filter(n=>n?.status==='NEVER_CONNECTED').length,
    placement,gpus:known,gpuCount:known.length,
    gpuFreeCandidates:known.filter(g=>g.admission==='candidate').length,
    gpuMeasured:known.filter(g=>g.admission!=='unknown').length,
    gpuByPlacement:{center:known.filter(g=>g.placement==='center').length,edge:known.filter(g=>g.placement==='edge').length,
      unclassified:known.filter(g=>g.placement!=='center'&&g.placement!=='edge').length},
    cpuAvg:avg('cpu'),memoryAvg:avg('memory'),diskAvg:avg('disk'),
    nodes:byNode,warnings,monitoredNodeCount,warningRatio:monitoredNodeCount?warnings/monitoredNodeCount*100:null,
    storageTypes:typeCounts,storageCount:sources.length,
    // Cloud provider configuration is not provider usage telemetry.
    storageBytes:null,cloudBytes:null};
}
function overviewAlgorithm(m) {
  const biggest=Math.max(1,...m.types.map(x=>x.count));
  const industryMax=Math.max(1,...m.industries.map(x=>x.count));
  const typePanel=panel('算法类型数量排行',m.types.length?
    rows(m.types,(x,i)=>bar((i+1)+'. '+x.name,x.count,biggest,null)):
    empty('暂无已登记的算法类型'),'按算法类型统计');
  const industryPanel=panel('行业场景分布',m.industries.length?
    rows(m.industries,x=>bar(x.name,x.count,industryMax,null)):
    empty('暂无行业分类记录'),'按行业归属统计');
  const scored=m.scores.filter(x=>x.map50!==null||x.precision!==null||x.recall!==null);
  const accuracy=panel('模型质量排行',scored.length?
    rows(scored,x=>'<div class="ov348-accuracy"><button type="button" class="ov348-algo-link" data-overview-algorithm-id="'+esc(x.id)+'">'+esc(x.name)+'</button><div>'+
       '<span>mAP50 '+pct(x.map50)+'</span><span>Precision '+pct(x.precision)+'</span><span>Recall '+pct(x.recall)+'</span><span>策略准确率 —</span></div></div>'):
    empty(m.total?'暂未取得已完成的真实模型评测':'暂无算法资产'),'已评测算法优先 · 仅展示真实指标');
  return '<div class="ov348-stack ov351-algorithm"><div class="ov351-algorithm-intro"><div><span>ALGORITHM INTELLIGENCE</span><h3>算法资产全景</h3><p>模型质量 · 算法类型 · 场景分布 · 生产运行</p></div><strong>'+fmt(m.measured)+' <small>已评测算法</small></strong></div><div class="ov348-kpis">'+
    metric('算法总数',fmt(m.total),'当前空间已登记算法')+
    metric('算法类型',fmt(m.types.length),'按 algorithm_type 归类')+
    metric('有版本算法',fmt(m.withVersions),'累计 '+fmt(m.versionCount)+' 个版本')+
    metric('模型评测覆盖',fmt(m.measured)+' / '+fmt(m.total),'具备 Precision / Recall / mAP')+
    metric('策略准确率','—','尚无策略判定结果事实源')+'</div>'+
    '<div class="ov350-section"><h3>算法资产与模型表现</h3><span>有效数据优先</span></div>'+
    '<div class="ov348-grid ov350-leader-grid">'+accuracy+typePanel+'</div>'+
    '<div class="ov348-grid">'+industryPanel+panel('算法资产清单',m.scores.length?rows(m.scores.slice(0,30),x=>'<div class="ov348-accuracy"><button type="button" class="ov348-algo-link" data-overview-algorithm-id="'+esc(x.id)+'">'+esc(x.name)+'</button><div><span>'+((x.map50!==null||x.precision!==null||x.recall!==null)?'已有模型评测':'待评测')+'</span></div></div>'):empty('尚无算法资产'),'含待评测算法 · 最多显示 30 项')+'</div>'+
    '<div class="ov350-section"><h3>运行与应用</h3><span>待接入数据源</span></div>'+
    '<details class="ov351-pending"><summary>待接入指标 <span>高频排行、单位运行与部署 · 展开</span></summary><div class="ov348-grid">'+
      panel('高频使用算法排行',empty('尚未接入生产推理调用次数'),'生产运行次数 · 待接入')+
      panel('各单位算法运行状况',empty('尚未接入单位与部署实例运行数据'),'单位维度 · 待接入')+'</div>'+
    '<div class="ov348-grid">'+panel('单位算法数量排行',empty('尚无可信的单位归属记录'),'单位维度 · 待接入')+'</div></details>'+
    '</div><div class="ov348-footnote">统计口径：算法数量来自当前空间算法资产；模型指标来自质量概览。策略准确率、调用量及单位运行数据没有可信来源时显示“—”，不会以训练成功率或模型精度冒充。</div></div>';
}
function overviewCompute(m,placementFilter='all',controller=null,demo=false) {
  const statusName={ONLINE:'在线',OFFLINE:'心跳超时',DISABLED:'已禁用',NEVER_CONNECTED:'未连接'};
  const chosen=m.nodes.filter(n=>placementFilter==='all'||n.placement===placementFilter);
  const selector='<div class="ov348-switches" role="group" aria-label="筛选服务器部署位置">'+
    [['all','全部'],['center','中心端'],['edge','边缘端'],['unclassified','未分类']].map(([key,name])=>
      '<button type="button" data-overview-placement="'+key+'" class="'+(key===placementFilter?'active':'')+'">'+name+'</button>').join('')+'</div>';
  const nodeList=chosen.length?rows(chosen,n=>'<div class="ov348-node"><header><b>'+esc(n.name)+'</b><span>'+esc(n.placement==='center'?'中心端':n.placement==='edge'?'边缘端':'未标注')+' · '+esc(statusName[n.status]||'状态未知')+' · '+(n.gpuCount===null?'GPU 未知':n.gpuCount+' GPU')+'</span></header>'+
    (n.live?'<div class="ov348-gauges">'+gauge('CPU',n.cpu,'')+gauge('内存',n.mem,bytes(n.memoryUsed)+' / '+bytes(n.memoryTotal))+gauge('磁盘',n.disk,bytes(n.diskUsed)+' / '+bytes(n.diskTotal))+'</div>':
      '<div class="ov348-node-unavailable">非在线节点，不展示历史资源占用作为实时采样</div>')+'</div>'):empty('当前筛选无服务节点');
  const gpuRows=m.gpus.length?rows(m.gpus,(g,i)=>'<div class="ov348-gpu"><b>'+esc(g.nodeName)+'</b><span>'+esc(g.name||'GPU '+g.index)+'</span><small>'+esc(g.placement==='center'?'中心端':g.placement==='edge'?'边缘端':'未标注')+'</small><div>'+gauge('GPU 使用率',percent(g.utilization_percent),'')+gauge('显存',number(g.memory_total_bytes)>0&&number(g.memory_used_bytes)!=null?Number(g.memory_used_bytes)/Number(g.memory_total_bytes)*100:null,bytes(g.memory_used_bytes)+' / '+bytes(g.memory_total_bytes))+'</div></div>'):empty('暂无在线 GPU 设备数据');
  const placementNames=[['center','中心端'],['edge','边缘端'],['unclassified','未标注']];
  const topology=panel('GPU 部署分布',rows(placementNames,([key,name])=>bar(name,m.gpuByPlacement[key],Math.max(m.gpuCount,1),m.gpuByPlacement[key]+' 块'))+
    '<div class="ov348-help">位置由「服务节点 → 编辑 → 部署位置」显式配置，不能通过 Agent 连接方式推断。</div>','中心 / 边缘 / 未分类');
  const availability=panel('GPU 可用情况',
    '<div class="ov348-kpis ov348-kpis-small">'+metric('在线 GPU',m.nodesKnown?fmt(m.gpuCount):'—','有实时心跳的 Agent 设备')+
    metric('候选空闲 GPU',m.gpuMeasured?fmt(m.gpuFreeCandidates):'—','需要预约账本与调度政策，不把采样当准入')+
    metric('调度证据覆盖',fmt(m.gpuMeasured)+' / '+fmt(m.gpuCount),'无法核验预约时显示未知')+'</div>',
    '最终可用性以任务调度器准入为准');
  const storage=panel('文件存储与云存储',
    '<div class="ov348-kpis ov348-kpis-small">'+metric('文件存储用量',demo?'820.5 GB':'—',demo?'演示数据 · 非真实容量':'容量暂未接入')+
    metric('普通云存储用量',demo?'236.2 GB':'—',demo?'演示数据 · 非真实容量':'OSS/S3 Bucket 容量暂未接入')+
    metric('已配置存储源',fmt(m.storageCount),'本地 '+m.storageTypes.local+' · 云 '+(m.storageTypes.oss+m.storageTypes.s3))+'</div>'+
    '<div class="ov348-help">服务器磁盘已使用量仅代表节点挂载盘，不等于对象存储 Bucket 占用量。</div>','已配置来源 ≠ 容量');
  const resources=panel('资源风险节点占比',m.monitoredNodeCount?
    '<div class="ov348-alert-head"><b>'+pct(m.warningRatio/100)+'</b><span>'+fmt(m.warnings)+' / '+fmt(m.monitoredNodeCount)+' 监测节点存在当前资源风险</span></div>'+
    bar('CPU / 内存 / 磁盘 ≥ 85%，或 Agent 心跳超时',m.warnings,m.monitoredNodeCount,fmt(m.warnings)+' 节点'):
    empty(m.nodesKnown?'暂无服务节点，无法计算风险占比':'服务节点状态未取得'),'当前快照 · 阈值 85%');
  const host=controller?.resources;
  const localPanel=panel('控制端 · 本机资源',host?
    '<div class="ov350-controller-head"><b>'+esc(controller.name||'控制端（本机）')+'</b><span>'+esc(controller.sampled_at||'')+'</span></div>'+
    '<div class="ov348-gauges">'+gauge('CPU',percent(host.cpu?.usage_percent),'')+
    gauge('内存',percent(host.memory?.usage_percent),bytes(host.memory?.used_bytes)+' / '+bytes(host.memory?.total_bytes))+
    gauge('磁盘',percent(host.disk?.usage_percent),bytes(host.disk?.used_bytes)+' / '+bytes(host.disk?.total_bytes))+'</div>'+
    '<div class="ov350-local-gpus">'+(Array.isArray(host.gpu?.gpus)&&host.gpu.gpus.length?
      rows(host.gpu.gpus,g=>'<span>'+esc(g.name||'GPU')+' · 使用率 '+esc(percent(g.utilization_percent)==null?'—':percent(g.utilization_percent)+'%')+' · 显存 '+esc(bytes(g.memory_used_bytes))+' / '+esc(bytes(g.memory_total_bytes))+'</span>'):
      '<span>本机无可探测 NVIDIA GPU</span>')+'</div>':
    empty('本机资源尚未采样'),'独立观察 · 不计入 Agent 节点或训练可调度 GPU');
  const trend=demo?'<section class="ov351-trend-panel"><div class="ov351-trend-heading"><div><b>算力负载趋势</b><span>GPU-A / GPU-B / GPU-C · 过去 12 个采样点（模拟）</span></div><strong>实时演示</strong></div><svg viewBox="0 0 900 160" preserveAspectRatio="none" role="img" aria-label="模拟 GPU 负载走势"><defs><linearGradient id="ov351-trend-fill" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stop-color="#5b9cff" stop-opacity=".20"/><stop offset="100%" stop-color="#5b9cff" stop-opacity="0"/></linearGradient></defs><path d="M0 35H900M0 77H900M0 119H900" stroke="#dce8f4" stroke-dasharray="5 7"/><path d="M0 110L82 103L164 99L246 83L328 96L410 70L492 73L574 48L656 60L738 37L820 52L900 31L900 160L0 160Z" fill="url(#ov351-trend-fill)"/><polyline points="0,110 82,103 164,99 246,83 328,96 410,70 492,73 574,48 656,60 738,37 820,52 900,31" fill="none" stroke="#427cde" stroke-width="3"/><polyline points="0,128 82,116 164,120 246,110 328,112 410,105 492,112 574,99 656,104 738,92 820,94 900,87" fill="none" stroke="#21b7a6" stroke-width="3"/><polyline points="0,140 82,143 164,138 246,143 328,137 410,139 492,130 574,134 656,136 738,130 820,132 900,125" fill="none" stroke="#f5a85b" stroke-width="3"/></svg><div class="ov351-trend-legend"><span>● GPU-A 72%</span><span>● GPU-B 23%</span><span>● GPU-C 4%</span></div></section>':'';
  return '<div class="ov348-stack">'+trend+'<div class="ov348-kpis">'+
    metric('服务节点',m.nodesKnown?fmt(m.nodeCount):'—',m.nodesKnown?fmt(m.online)+' 在线 · '+fmt(m.offline)+' 超时 · '+fmt(m.disabled)+' 禁用 · '+fmt(m.neverConnected)+' 未连接':'节点状态尚未取得')+
    metric('在线 GPU',m.nodesKnown?fmt(m.gpuCount):'—','离线 GPU 不计入')+
    metric('平均 CPU',m.cpuAvg==null?'—':m.cpuAvg.toFixed(1)+'%','仅统计在线且有采样的节点')+
    metric('平均内存',m.memoryAvg==null?'—':m.memoryAvg.toFixed(1)+'%','仅统计在线且有采样的节点')+
    metric('平均磁盘',m.diskAvg==null?'—':m.diskAvg.toFixed(1)+'%','仅统计在线且有采样的节点')+
    '</div><div class="ov348-grid">'+localPanel+'</div><div class="ov348-grid">'+topology+availability+'</div>'+
    '<div class="ov348-grid">'+panel('服务器运行情况',selector+nodeList,'CPU / 内存 / 磁盘 · Agent 心跳快照','ov348-wide')+'</div>'+
    '<div class="ov348-grid">'+panel('GPU 设备明细',gpuRows,'型号 / 使用率 / 显存 · 当前在线设备')+resources+'</div>'+
    '<div class="ov348-grid">'+storage+'</div>'+
    '<div class="ov348-footnote">数据口径：GPU/CPU/内存/磁盘来自现有服务节点 Agent；闲置候选仅在调度记录与设备采样均新鲜时显示。云存储实际用量和历史告警率未采集时保持未知，避免虚构实时数据。</div></div>';
}

// Display-only fixture. Never write demo values to telemetry, scheduler or API caches.
function demoComputeSnapshot() {
  const GB=1024**3;
  const node=(id,name,placement,cpu,mem,disk,gpus)=>({
    node_id:id,display_name:name,placement,status:'ONLINE',online:true,
    resources:{cpu:{usage_percent:cpu},
      memory:{usage_percent:mem,used_bytes:Math.round(mem/100*128*GB),total_bytes:128*GB},
      disk:{usage_percent:disk,used_bytes:Math.round(disk/100*2048*GB),total_bytes:2048*GB},
      gpu:{gpus:gpus.map(([uuid,name,util,used,total],index)=>({uuid,index,name,utilization_percent:util,memory_used_bytes:used*GB,memory_total_bytes:total*GB}))}
    }
  });
  const nodes=[
    node('demo-central-a','GPU 训练服务器 A','center',38,62,47,[['demo-gpu-a1','NVIDIA RTX 4090',72,17,24],['demo-gpu-a2','NVIDIA RTX 4090',23,6,24]]),
    node('demo-central-b','GPU 训练服务器 B','center',20,36,31,[['demo-gpu-b1','NVIDIA RTX 4090',4,2,24]]),
    node('demo-edge-a','边缘分析服务器','edge',31,49,88,[])
  ];
  const gpus=[
    {node_id:'demo-central-a',gpu_uuid:'demo-gpu-a1',metrics_fresh:true,telemetry_available:true,active_tasks:1,reserved_bytes:17*GB,free_bytes:7*GB,total_bytes:24*GB},
    {node_id:'demo-central-a',gpu_uuid:'demo-gpu-a2',metrics_fresh:true,telemetry_available:true,active_tasks:0,reserved_bytes:0,free_bytes:18*GB,total_bytes:24*GB},
    {node_id:'demo-central-b',gpu_uuid:'demo-gpu-b1',metrics_fresh:true,telemetry_available:true,active_tasks:0,reserved_bytes:0,free_bytes:22*GB,total_bytes:24*GB}
  ];
  return {nodes,storage:[{type:'local'},{type:'oss'}],
    gpuRuntime:{gpus,memory_safety_bytes:2*GB,max_concurrent_per_gpu:1},
    local:{name:'控制端（演示）',sampled_at:'演示快照 · 非真实采样',
      resources:{cpu:{usage_percent:16},memory:{usage_percent:32,used_bytes:10*GB,total_bytes:32*GB},
        disk:{usage_percent:42,used_bytes:210*GB,total_bytes:500*GB},gpu:{gpus:[]}}}};
}
export function installOverviewTabsRuntime({
  getState,renderProduction,request=async url=>{
    const response=await fetch(url,{credentials:'same-origin',cache:'no-store'});
    if(!response.ok)throw new Error('HTTP '+response.status);
    return response.json();
  },
}={}) {
  if(typeof document==='undefined')return null;
  let active='algorithm',placementFilter='all',demoMode=false,computeClicks=0,lastComputeClick=0,cache={project:'',algorithms:null,quality:null,nodes:null,storage:null,gpuRuntime:null,local:null,loadedAt:{},errors:{}},loading={};
  const ttl=60000;
  const state=()=>getState?.()||{};
  const project=()=>String(state().project?.id||'');
  function resetIfProjectChanged() {
    if(cache.project===project())return;
    cache={project:project(),algorithms:null,quality:null,nodes:null,storage:null,gpuRuntime:null,local:null,loadedAt:{},errors:{}};
    loading={};demoMode=false;computeClicks=0;lastComputeClick=0;
  }
  function render({load=true}={}) {
    const view=document.getElementById('view');
    if(!view||state().page!=='总览')return false;
    resetIfProjectChanged();
    const algorithm=active==='algorithm',has=algorithm?cache.algorithms!==null:cache.nodes!==null;
    // Keep existing production dashboard owner and prepend algorithm intelligence.
    if(algorithm)renderProduction?.();
    const sample=demoMode&&!algorithm?demoComputeSnapshot():null;
    let content=algorithm?(has?overviewAlgorithm(buildAlgorithmMap(cache.algorithms.items,cache.quality)):empty('算法资产尚未取得')):
      overviewCompute(buildComputeMap(sample?sample.nodes:(cache.nodes ? cache.nodes.items : null),sample?sample.storage:cache.storage?.items,sample?sample.gpuRuntime:cache.gpuRuntime),placementFilter,sample?sample.local:cache.local,!!sample);
    if(sample)content='<div class="ov351-demo-banner" data-overview-demo="true"><b>演示数据模式</b><span>所有服务器、GPU、利用率、容量均为模拟；不参与资源调度和真实统计。</span><button type="button" data-overview-demo-exit="1">退出演示</button></div>'+content;
    if(!sample&&!has&&!cache.loadedAt[algorithm?'algorithms':'nodes'])content='<div class="ov348-loading">正在读取'+(algorithm?'算法资产':'算力资源')+'数据…</div>'+content;
    const errors=Object.entries(cache.errors).filter(([key,value])=>
      (algorithm?['quality','algorithms'].includes(key):!['quality','algorithms'].includes(key))&&value);
    if(errors.length&&!sample)content='<div class="ov348-error">部分数据读取失败：'+esc(errors.map(([key,value])=>key+': '+value).join(' · '))+'</div>'+content;
    if(algorithm)view.insertAdjacentHTML('afterbegin',content+'<div class="ov350-section ov350-production-heading"><h3>生产运行</h3></div>');
    else view.innerHTML=content;
    view.querySelectorAll?.('[data-overview-placement]').forEach(button=>button.addEventListener('click',()=>{
      placementFilter=button.dataset.overviewPlacement;render({load:false});
    }));
    view.querySelectorAll?.('[data-overview-algorithm-id]').forEach(button=>button.addEventListener('click',()=>{
      const id=button.dataset.overviewAlgorithmId;
      if((state().algorithms||[]).some(a=>String(a.id)===id))window.viewAlgorithm428?.(id);
      else window.setPage?.('算法列表');
    }));
    view.insertAdjacentHTML('afterbegin','<div class="ov348-header" data-overview-tabs="1">'+
      '<div class="ov348-title"><span>ALGORITHM & CAPACITY INTELLIGENCE</span><h2>'+esc(algorithm?'算法一张图':'算力一张图')+'</h2></div>'+
      '<div class="ov348-toolbar" role="tablist" aria-label="总览类型">'+OVERVIEW_TABS.map(x=>
        '<button type="button" role="tab" data-overview-tab="'+x.id+'" aria-selected="'+(active===x.id)+'"'+
        ' class="'+(active===x.id?'active':'')+'">'+esc(x.label)+'</button>').join('')+
      '</div><button type="button" class="ov348-refresh" data-overview-refresh="1" title="刷新当前视图">刷新</button></div>');
    const tabs=view.querySelector('[data-overview-tabs]');
    tabs.addEventListener('click',event=>{
      const selected=event.target.closest('[data-overview-tab]');
      if(selected){
        const tab=selected.dataset.overviewTab;
        if(tab==='compute'){
          const now=Date.now();computeClicks=now-lastComputeClick<=2000?computeClicks+1:1;lastComputeClick=now;
          if(computeClicks>=3){demoMode=!demoMode;computeClicks=0;}
        }else{computeClicks=0;lastComputeClick=0;demoMode=false;}
        active=tab;render({load:!demoMode});return;
      }
      if(event.target.closest('[data-overview-refresh]')){if(demoMode){demoMode=false;computeClicks=0;render();}void loadTab(active,true);}
    });
        view.querySelector('[data-overview-demo-exit]')?.addEventListener('click',()=>{demoMode=false;computeClicks=0;render();});
    if(load&&!demoMode)void loadTab(active);
    return true;
  }
  async function loadTab(tab,force=false) {
    resetIfProjectChanged();
    const id=project();if(!id||state().page!=='总览')return;
    const fetchOne=async(key,url)=>{
      if(!force&&cache.loadedAt[key]&&Date.now()-cache.loadedAt[key]<ttl)return;
      if(loading[key])return loading[key];
      const target=cache; // Identity fence also rejects old A requests after A→B→A.
      const task=(async()=>{
        try{
          const result=await request(url);
          if(['algorithms','nodes','storage'].includes(key)&&!Array.isArray(result?.items))throw new Error('接口未返回有效 items');
          if(key==='quality'&&!Array.isArray(result?.algorithms))throw new Error('质量接口缺少算法列表');
          if(key==='gpuRuntime'&&!Array.isArray(result?.gpus))throw new Error('GPU 运行态接口无效');
          if(key==='local'&&(!result?.resources||!result?.sampled_at))throw new Error('本机资源采样接口无效');
          if(project()!==id||cache!==target)return;
          cache[key]=result;cache.loadedAt[key]=Date.now();delete cache.errors[key];
        }catch(error){
          if(project()!==id||cache!==target)return;
          cache[key]=null; // Never display a previous successful response as live after a failure.
          cache.errors[key]=String(error?.message||error);
          cache.loadedAt[key]=Date.now(); // Bounded retry; don't hammer failing APIs.
        }
      })().finally(()=>{if(loading[key]===task)delete loading[key]});
      loading[key]=task;return task;
    };
    const mergedQuality=async()=>{
      // Production dashboard already owns this quality GET and its 60s cache.
      // Reuse that completed or pending request instead of double-reading it.
      const owner=state(),target=cache;
      const reuse=()=>{
        if(project()!==id||cache!==target)return false;
        const quality=state().v42?.quality;
        if(String(state().dashboard422ExtrasProjectId||'')!==id||!Array.isArray(quality?.algorithms))return false;
        cache.quality=quality;cache.loadedAt.quality=Date.now();delete cache.errors.quality;
        return true;
      };
      if(!force&&reuse())return;
      const inFlight=owner.dashboard422ExtrasRefreshPromise;
      if(inFlight){
        try{await inFlight}catch(_){}
        if(project()!==id||cache!==target)return;
        if(reuse())return;
        // An already failed production owner must not induce a second
        // immediate quality GET. Keep its source unavailable for this view.
        cache.quality=null;cache.loadedAt.quality=Date.now();
        cache.errors.quality='生产质量概览读取失败';
        return;
      }
      await fetchOne('quality','/api/v42/projects/'+encodeURIComponent(id)+'/quality-overview');
    };
    if(tab==='algorithm')await Promise.all([
      fetchOne('algorithms','/api/v12/projects/'+encodeURIComponent(id)+'/algorithms'),
      mergedQuality(),
    ]);
    if(tab==='compute')await Promise.all([
      fetchOne('nodes','/api/v63/service-nodes'),
      fetchOne('storage','/api/v61/storage-sources'),
      fetchOne('gpuRuntime','/api/v62/gpu-runtime'),
      fetchOne('local','/api/v63/service-nodes/controller-snapshot'),
    ]);
    if(state().page==='总览'&&active===tab&&project()===id)render({load:false});
  }
  return Object.freeze({render,select(tab){const target=tab==='production'?'algorithm':tab;if(OVERVIEW_TABS.some(x=>x.id===target)){active=target;demoMode=false;computeClicks=0;return render()}return false},
    get activeTab(){return active},refresh(){return loadTab(active,true)}});
}

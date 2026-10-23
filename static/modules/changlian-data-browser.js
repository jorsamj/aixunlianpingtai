const PAGE = '畅联云数据';
const BASE = '/api/v63/external-algorithm-platform/provider';
const ENABLED_PRODUCTS_ENDPOINT = '/api/v63/external-algorithm-platform/provider/products?status=1';
const DISABLED_PRODUCTS_ENDPOINT = '/api/v63/external-algorithm-platform/provider/products?status=0';

function valueOf(row, ...keys) {
  for (const key of keys) {
    const value = row?.[key];
    if (value !== undefined && value !== null && String(value).trim() !== '') return value;
  }
  return '';
}

export function providerItems(value) {
  const root = value?.response ?? value;
  const visit = current => {
    if (Array.isArray(current)) return current.filter(item => item && typeof item === 'object');
    if (!current || typeof current !== 'object') return [];
    for (const key of ['items', 'records', 'rows', 'list']) {
      if (Array.isArray(current[key])) return current[key].filter(item => item && typeof item === 'object');
    }
    if (current.data !== undefined && current.data !== current) return visit(current.data);
    return [];
  };
  return visit(root);
}

export function productIdentity(row) {
  return String(valueOf(row, 'productId', 'product_id', 'id')).trim();
}
export function versionIdentity(row) {
  return String(valueOf(row, 'algoVersionId', 'algorithmVersionId', 'versionId', 'id')).trim();
}
export function weightIdentity(row) {
  return String(valueOf(row, 'weightId', 'algorithmWeightId', 'id')).trim();
}

export function weightRemoteLink(row) {
  const value = String(valueOf(row, 'downloadUrl', 'fileUrl', 'publicUrl', 'url', 'filePath')).trim();
  if(!/^https?:\/\//i.test(value)||/[\\\s]/.test(value))return '';
  try{const url=new URL(value);return ['http:','https:'].includes(url.protocol)&&url.hostname?value:''}catch{return ''}
}

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[char]));
}

function text(value, fallback = '-') {
  const result = String(value ?? '').trim();
  return result || fallback;
}

const DETAIL_GROUPS = [
  ['模型基本信息', ['weightId','productId','analysisId','algoVersionId','versionName','versionNo','fileName','yoloVersion','imageWidth','imageHeight']],
  ['算力环境', ['computePlatformId','computePlatformName','computePlatformCode','chipCode']],
  ['文件属性', ['filePath','fileSize','fileSha256']],
  ['创建与更新', ['createBy','createTime','updateBy','updateTime','delFlag']],
  ['备注', ['remark']],
];
const FIELD_NAMES = {tags:'标签',weightId:'权重文件 ID',productId:'算法产品 ID',analysisId:'分析方式 ID',algoVersionId:'算法版本 ID',versionName:'版本名称',versionNo:'版本号',computePlatformId:'算力环境 ID',computePlatformName:'算力环境名称',computePlatformCode:'算力环境编号',chipCode:'芯片标识',fileName:'文件名称',filePath:'文件地址',imageWidth:'输入宽度',imageHeight:'输入高度',yoloVersion:'YOLO 版本',fileSize:'文件大小',fileSha256:'SHA256',remark:'备注',createBy:'创建人',createTime:'创建时间',updateBy:'更新人',updateTime:'更新时间',delFlag:'删除标志'};
const has = (row,key) => Object.prototype.hasOwnProperty.call(row||{},key);
function validId(value) {
  const id=String(value??'');
  return /^[1-9][0-9]{0,18}$/.test(id)&&BigInt(id)<=9223372036854775807n;
}
export function providerDetail(raw) {
  if(raw?.ok===false)throw new Error(raw.message||raw.detail||'详情查询失败');
  const response=raw?.response??raw;
  if(response?.code!==undefined&&![0,200,'0','200'].includes(response.code))throw new Error(response.msg||response.message||`远端业务错误 ${response.code}`);
  return response;
}
export function remoteField(row,key) {
  if(!has(row,key))return '未返回';
  const value=row[key];
  if(value===null)return 'null（无具体值）';
  if(value==='')return '空字符串';
  if(Array.isArray(value))return value.length?JSON.stringify(value):'[]（空数组）';
  if(typeof value==='object')return JSON.stringify(value);
  if(key==='delFlag')return `${String(value)==='0'?'正常':String(value)==='2'?'已删除':'未知状态'}（${value}）`;
  if(key==='fileSize'&&/^\d+$/.test(String(value))){
    const bytes=BigInt(value),units=['B','KB','MB','GB','TB'];let unit=0,scale=1n;
    while(unit<units.length-1&&bytes>=scale*1024n){scale*=1024n;unit++}
    return `${Number(bytes*100n/scale)/100} ${units[unit]}（${value} 字节）`;
  }
  return String(value);
}
export function tagsView(row) {
  if(!has(row,'tags'))return {state:'missing',label:'本次接口未返回 Tags',items:[]};
  if(row.tags===null)return {state:'null',label:'远端返回 null，未提供具体标签值',items:[]};
  if(Array.isArray(row.tags)&&row.tags.every(x=>typeof x==='string'))return {state:row.tags.length?'returned':'empty',label:row.tags.length?'已从新畅联接口读取':'远端返回空标签列表',items:row.tags};
  return {state:'invalid',label:'远端 Tags 类型异常',items:[]};
}
function identityIssues(data,context) {
  return [['weightId',context.weightId],['algoVersionId',context.versionId],['productId',context.productId]].filter(([key,expected])=>expected&&has(data,key)&&String(data[key])!==String(expected)).map(([key,expected])=>`${FIELD_NAMES[key]} 不一致：列表 ${expected}，详情 ${String(data[key])}`);
}

async function mapLimit(rows, limit, worker) {
  const result = new Array(rows.length);
  let cursor = 0;
  const runners = Array.from({length: Math.min(Math.max(1, limit), Math.max(1, rows.length))}, async () => {
    while (cursor < rows.length) {
      const index = cursor++;
      result[index] = await worker(rows[index], index);
    }
  });
  await Promise.all(runners);
  return result;
}

function mergeProducts(...groups) {
  const seen = new Set();
  const rows = [];
  for (const row of groups.flat()) {
    const id = productIdentity(row);
    const key = id || JSON.stringify(row);
    if (seen.has(key)) continue;
    seen.add(key);
    rows.push(row);
  }
  return rows;
}

export function installChangLianDataBrowserRuntime({
  getState = () => ({}),
  request,
  notify = () => {},
  document: doc = globalThis.document,
  modal = globalThis.window?.modal,
  closeModal = () => globalThis.window?.closeModal?.(),
  copyText = value => {if(!globalThis.navigator?.clipboard?.writeText)throw new Error('浏览器剪贴板不可用');return globalThis.navigator.clipboard.writeText(value)},
} = {}) {
  if (typeof request !== 'function') throw new Error('畅联云数据浏览器缺少 request 依赖');

  let destroyed = false;
  let refreshPromise = null;
  let refreshEpoch = 0;
  const detailCache=new Map(),detailPending=new Map();
  let detail=null,boundView=null;
  const onPage=()=>!destroyed&&String(getState?.()?.page||'')===PAGE;
  const liveDetail=current=>Boolean(current)&&onPage()&&detail===current&&(!doc||current.root?.isConnected&&doc.querySelector('[data-cldb-detail]')===current.root);

  function leave() {
    const owned=detail?.root?.isConnected&&doc?.querySelector('[data-cldb-detail]')===detail.root;
    detail=null;
    if(owned)closeModal();
  }
  function paintDetail(current) {
    if(!liveDetail(current)||!current.root)return;
    const result=current.result,data=result?.data||{},context=current.context;
    const field=key=>`<div class="cldb-detail-field" data-field="${key}"><dt>${FIELD_NAMES[key]}</dt><dd>${esc(remoteField(data,key))}${['weightId','filePath','fileSha256'].includes(key)&&['string','number'].includes(typeof data[key])&&String(data[key])?` <button class="btn mini" data-cldb-copy="${key}" aria-label="复制${FIELD_NAMES[key]}">复制</button>`:''}</dd></div>`;
    const tags=tagsView(result?.tagsEvidence?.data||data),issues=result?.issues||[],link=weightRemoteLink({filePath:data.filePath});
    const title=has(data,'fileName')?remoteField(data,'fileName'):'权重文件详情';
    current.root.innerHTML=`<header class="cldb-detail-hero"><div><small>列表位置 · ${esc(context.productName||context.productId||'产品未提供')} / ${esc(context.versionName||context.versionId||'版本未提供')}</small><h2>${esc(title)}</h2><p>Weight ID · ${esc(context.weightId)}</p>${current.result?.data?`<div class="cldb-detail-facts"><span>版本 ${esc(remoteField(data,'versionNo'))}</span><span>${esc(remoteField(data,'computePlatformName'))}</span><span>${esc(remoteField(data,'chipCode'))}</span><span>${esc(remoteField(data,'delFlag'))}</span></div>`:''}</div><div class="row">${link?`<a class="btn" href="${esc(link)}" target="_blank" rel="noopener noreferrer">下载 / 打开</a>`:''}<button class="btn" data-cldb-close>关闭详情</button></div></header>
      ${current.loading?'<div class="cldb-detail-loading" role="status">正在读取远端权重详情…</div>':current.error?`<div class="cldb-error" role="alert"><b>详情查询失败</b><span>${esc(current.error)}</span><button class="btn" data-cldb-retry>重新加载</button></div>`:!result?.data?'<div class="cldb-empty compact">远端返回 data=null，暂无详情数据</div>':`
      ${result.listDifferences?.length?`<div class="cldb-error"><b>列表信息已变化</b><span>${result.listDifferences.map(esc).join('<br>')}；请手动刷新列表。</span></div>`:''}
      ${issues.length?`<div class="cldb-error" role="alert"><b>身份不一致</b><span>${issues.map(esc).join('<br>')}；请手动刷新列表核对。</span></div>`:''}
      <section class="cldb-detail-tags" data-field="tags"><header><h3>标签信息</h3><span>${esc(result.tagsEvidence?.source||'getInfo')}</span></header><p data-tags-state="${tags.state}">${esc(tags.label)}${Array.isArray((result.tagsEvidence?.data||data).tags)?` · ${tags.items.length} 项`:''}</p><div class="cldb-tags">${tags.items.map(t=>`<span>${t===''?'空字符串':esc(t)}</span>`).join('')}</div>${result.tagsError?`<div class="cldb-error" role="alert">标签查询失败：${esc(result.tagsError)}<button class="btn mini" data-cldb-retry>重新加载</button></div>`:''}</section>
      <div class="cldb-detail-grid">${DETAIL_GROUPS.map(([label,keys])=>`<section><h3>${label}</h3>${label==='模型基本信息'?`<p class="cldb-dimensions">输入尺寸 · ${esc(remoteField(data,'imageWidth'))} × ${esc(remoteField(data,'imageHeight'))}</p>`:''}<dl>${keys.map(field).join('')}</dl></section>`).join('')}</div>
      <details class="cldb-raw"><summary>完整原始数据</summary><button class="btn mini" data-cldb-copy="raw">复制原始数据</button><pre>${esc(JSON.stringify({getInfo:result.raw,tagsQuery:result.tagsEvidence?.pages||[]},null,2))}</pre></details>`}`;
  }
  async function readTags(data,context,epoch,key) {
    if(has(data,'tags'))return {source:'getInfo',data,pages:[]};
    const versionId=data.algoVersionId??context.versionId;
    if(!validId(versionId))return {source:'getInfo（缺少可信版本 ID，未执行分页查询）',data,pages:[]};
    const pages=[],seen=new Set(),pageSize=50;
    for(let page=1;page<=1000;page++){
      if(!liveDetail(detail)||detail.key!==key||epoch!==refreshEpoch)throw new Error('详情查询已失效');
      const query=new URLSearchParams({pageNum:String(page),pageSize:String(pageSize),algoVersionId:String(versionId),withTags:'true'});
      const response=providerDetail(await request(`${BASE}/weights/page?${query}`));
      const rows=providerItems(response),fingerprint=JSON.stringify(rows);
      pages.push(response);
      const matches=rows.filter(row=>weightIdentity(row)===context.weightId);
      if(matches.length>1)throw new Error('分页返回重复 Weight ID，无法唯一确认标签');
      if(matches.length){const issues=identityIssues(matches[0],{...context,versionId});if(issues.length)throw new Error(issues.join('；'));return {source:'list · withTags=true',data:matches[0],pages}}
      const total=response?.total??response?.data?.total;
      if(total!==undefined&&(!/^\d+$/.test(String(total))))throw new Error('分页 total 类型异常');
      if(rows.length===0){if(total!==undefined&&BigInt(total)>BigInt((page-1)*pageSize))throw new Error('分页提前返回空页，尚未读取完整结果');return {source:'list · withTags=true（未找到该 Weight）',data:{},pages}}
      if(seen.has(fingerprint))throw new Error('分页重复返回相同结果，已停止查询');
      seen.add(fingerprint);
      if(total!==undefined?BigInt(page*pageSize)>=BigInt(total):rows.length<pageSize)return {source:'list · withTags=true（未找到该 Weight）',data:{},pages};
    }
    throw new Error('分页超过安全读取上限，未确认完整结果');
  }
  async function openWeightDetails(context,{withTags=null,force=false}={}) {
    if(!onPage())return null;
    const id=String(context.weightId??'');
    if(!validId(id))throw new Error('Weight ID 必须为完整的正 int64');
    context={...context,weightId:id};
    const epoch=refreshEpoch,key=`${epoch}:${id}:${withTags}:${context.productId||''}:${context.versionId||''}`;
    if(detail?.key===key&&liveDetail(detail)&&detail.loading)return detail.promise;
    let root=liveDetail(detail)?detail?.root:null;
    const current={key,context,root,loading:true,error:'',result:null};detail=current;
    if(doc&&!root){modal?.('算法权重文件详情','<article class="cldb-detail" data-cldb-detail></article>',true);root=doc.querySelector('[data-cldb-detail]');current.root=root;
      root?.addEventListener('click',event=>{
        const action=event.target.closest('[data-cldb-close],[data-cldb-retry],[data-cldb-copy]');if(!action)return;
        if(action.hasAttribute('data-cldb-close')){leave();return}
        if(action.hasAttribute('data-cldb-retry')){void openWeightDetails(detail.context,{withTags:detail.withTags,force:true}).catch(()=>{});return}
        const key=action.dataset.cldbCopy,value=key==='raw'?JSON.stringify({getInfo:detail.result.raw,tagsQuery:detail.result.tagsEvidence?.pages||[]},null,2):detail.result?.data?.[key];
        if(value!==undefined)Promise.resolve().then(()=>copyText(String(value))).then(()=>{if(onPage())notify('已复制')},()=>{if(onPage())notify('复制失败，请检查浏览器剪贴板权限')});
      });
    }
    current.withTags=withTags;paintDetail(current);
    const task=(!force&&detailCache.has(key)?Promise.resolve(detailCache.get(key)):detailPending.get(key))|| (async()=>{
      const raw=providerDetail(await request(`${BASE}/weights/${encodeURIComponent(id)}${withTags===null?'':`?withTags=${withTags?'true':'false'}`}`));
      const data=raw?.data;
      if(data!==null&&(!data||typeof data!=='object'||Array.isArray(data)))throw new Error('远端详情 data 不是有效对象');
      const listDifferences=['fileName','filePath','computePlatformId','chipCode','tags'].filter(field=>has(context.listWeight,field)&&has(data,field)&&(field==='tags'?JSON.stringify(context.listWeight[field])!==JSON.stringify(data[field]):String(context.listWeight[field])!==String(data[field]))).map(field=>`${FIELD_NAMES[field]}：列表 ${String(context.listWeight[field])}，详情 ${String(data[field])}`);
      const result={raw,data,listDifferences,issues:identityIssues(data,context)};
      if(data&&!result.issues.length){try{result.tagsEvidence=await readTags(data,context,epoch,key)}catch(error){result.tagsError=String(error.message||error)}}
      if(epoch===refreshEpoch&&!destroyed&&!result.tagsError)detailCache.set(key,result);
      return result;
    })();
    // Cached success is snapshot-bound; failures are never cached as a fresh result.
    if(!detailPending.has(key)&&(!detailCache.has(key)||force))detailPending.set(key,task);
    const pending=!force&&detailCache.has(key)?Promise.resolve(detailCache.get(key)):task;
    current.promise=pending.then(result=>{if(liveDetail(current)&&epoch===refreshEpoch){current.loading=false;current.result=result;paintDetail(current)}return result}).catch(error=>{if(liveDetail(current)){current.loading=false;current.error=String(error.message||error);paintDetail(current)}throw error}).finally(()=>{if(detailPending.get(key)===task)detailPending.delete(key)});
    return current.promise;
  }
  function onViewClick(event) {
    const button=event.target.closest('[data-cldb-refresh],[data-cldb-weight]');
    if(!button||!boundView?.contains(button))return;
    if(button.hasAttribute('data-cldb-refresh')){void refresh().catch(error=>notify(error.message||error));return}
    const product=snapshot.products.find(p=>productIdentity(p)===button.dataset.cldbProduct),version=product?.versions?.find(v=>versionIdentity(v)===button.dataset.cldbVersion),weight=version?.weights?.find(w=>weightIdentity(w)===button.dataset.cldbWeight);
    if(!weight)return;
    if(!validId(weightIdentity(weight))){notify('Weight ID 必须为完整的正 int64');return}
    void openWeightDetails({weightId:weightIdentity(weight),listWeight:weight,productId:productIdentity(product),versionId:versionIdentity(version),productName:valueOf(product,'productName','name'),versionName:valueOf(version,'versionName','versionNo')}).catch(()=>{}); // Owned error panel reports live failures.
  }
  let snapshot = {
    loaded: false,
    loading: false,
    loadedAt: '',
    products: [],
    error: '',
  };

  function counts() {
    const products = snapshot.products.length;
    const versions = snapshot.products.reduce((sum, row) => sum + (row.versions?.length || 0), 0);
    const weights = snapshot.products.reduce((sum, row) => sum + (row.versions || []).reduce((n, version) => n + (version.weights?.length || 0), 0), 0);
    return {products, versions, weights};
  }

  function weightHtml(row,version,product) {
    const fileName = text(valueOf(row, 'fileName', 'file_name', 'name'));
    const filePath = text(valueOf(row, 'filePath', 'file_path', 'downloadUrl', 'fileUrl', 'publicUrl', 'url'));
    const link = weightRemoteLink(row);
    const platform = text(valueOf(row, 'computePlatformName', 'compute_platform_name', 'computePlatformId', 'compute_platform_id'));
    const chip = text(valueOf(row, 'chipCode', 'chip_code'));
    const id = text(weightIdentity(row));
    return `<div class="cldb-weight">
      <div><b>${esc(fileName)}</b><span>ID ${esc(id)}</span></div>
      <div><span>算力环境</span><b>${esc(platform)}</b></div>
      <div><span>芯片</span><b>${esc(chip)}</b></div>
      <div class="cldb-weight-path"><span>文件地址</span><code title="${esc(filePath)}">${esc(filePath)}</code></div>
      <div class="cldb-weight-link"><button class="btn mini" data-cldb-weight="${esc(weightIdentity(row))}" data-cldb-version="${esc(versionIdentity(version))}" data-cldb-product="${esc(productIdentity(product))}">查看详情</button>${link ? `<a class="btn mini" href="${esc(link)}" target="_blank" rel="noopener noreferrer">下载 / 打开</a>` : '<span class="cldb-muted">未返回可直接访问链接</span>'}</div>
    </div>`;
  }

  function versionHtml(row,product) {
    const versionId = versionIdentity(row);
    const versionName = text(valueOf(row, 'versionName', 'version_name', 'name'), '未命名版本');
    const versionNo = text(valueOf(row, 'versionNo', 'version_no'));
    const analysisId = text(valueOf(row, 'analysisId', 'analysis_id'));
    const status = text(valueOf(row, 'status', 'versionStatus', 'version_status'));
    const weights = row.weights || [];
    return `<section class="cldb-version">
      <header>
        <div><b>${esc(versionName)}</b><span>版本号 ${esc(versionNo)} · ID ${esc(versionId)}</span></div>
        <div class="cldb-version-meta"><span>分析方式 ${esc(analysisId)}</span><em>${esc(status)}</em><strong>${weights.length} 个权重/转换结果</strong></div>
      </header>
      <div class="cldb-weights">${weights.map(weight=>weightHtml(weight,row,product)).join('') || '<div class="cldb-empty compact">该版本未返回权重/转换结果</div>'}</div>
    </section>`;
  }

  function productHtml(row) {
    const productId = productIdentity(row);
    const name = text(valueOf(row, 'productName', 'product_name', 'name'), '未命名算法产品');
    const code = text(valueOf(row, 'productCode', 'product_code', 'code'));
    const category = text(valueOf(row, 'categoryName', 'category_name', 'categoryId', 'category_id'));
    const status = String(valueOf(row, 'status')).trim();
    const versions = row.versions || [];
    const weightCount = versions.reduce((sum, version) => sum + (version.weights?.length || 0), 0);
    return `<details class="cldb-product">
      <summary>
        <div class="cldb-product-name"><span class="cldb-product-mark">CL</span><div><b>${esc(name)}</b><small>${esc(code)} · ID ${esc(productId)}</small></div></div>
        <div class="cldb-product-facts"><span>品目 <b>${esc(category)}</b></span><span>状态 <b>${esc(status || '-')}</b></span><span>版本 <b>${versions.length}</b></span><span>权重/转换 <b>${weightCount}</b></span></div>
        <i>⌄</i>
      </summary>
      <div class="cldb-product-body">
        <div class="cldb-product-raw"><span>远端产品 ID</span><code>${esc(productId)}</code><span>产品类型</span><code>${esc(text(valueOf(row, 'productType', 'product_type')))}</code></div>
        <div class="cldb-versions">${versions.map(version=>versionHtml(version,row)).join('') || '<div class="cldb-empty compact">该算法产品未返回版本</div>'}</div>
      </div>
    </details>`;
  }

  function render() {
    if (destroyed || !doc) return false;
    const state = getState?.() || {};
    if (String(state.page || '') !== PAGE) return false;
    const view = doc.getElementById?.('view');
    if (!view) return false;
    if(boundView!==view){boundView?.removeEventListener('click',onViewClick);boundView=view;view.addEventListener?.('click',onViewClick)}
    const summary = counts();
    const status = snapshot.loading
      ? '正在从畅联云读取'
      : snapshot.loaded
        ? `上次手动刷新：${new Date(snapshot.loadedAt).toLocaleString()}`
        : '尚未读取远端数据';
    view.innerHTML = `<section class="cldb-shell" data-changlian-data-browser="1">
      <header class="cldb-hero">
        <div><span class="cldb-eyebrow">CHANG LIAN REMOTE DATA</span><h2>畅联云数据</h2><p>只读查看畅联云算法产品、算法版本以及版本下权重/转换结果。进入页面不会自动请求，只有手动刷新才访问畅联云。</p></div>
        <button class="btn primary" data-cldb-refresh ${snapshot.loading ? 'disabled' : ''}>${snapshot.loading ? '正在读取…' : '手动刷新畅联云'}</button>
      </header>
      <div class="cldb-summary">
        <div><span>算法产品</span><b>${summary.products}</b></div>
        <div><span>算法版本</span><b>${summary.versions}</b></div>
        <div><span>权重 / 转换结果</span><b>${summary.weights}</b></div>
        <div><span>读取状态</span><b class="small">${esc(status)}</b></div>
      </div>
      ${snapshot.error ? `<div class="cldb-error"><b>读取失败</b><span>${esc(snapshot.error)}</span></div>` : ''}
      <div class="cldb-note"><b>只读模式</b><span>本页面不会新增、修改、删除畅联云数据，也不会触发现有主数据同步；下载地址直接采用畅联云接口返回的文件地址。</span></div>
      <div class="cldb-list">
        ${snapshot.loaded
          ? snapshot.products.map(productHtml).join('') || '<div class="cldb-empty"><b>畅联云未返回算法产品</b><span>请确认远端数据库中存在 productType=3 的算法产品。</span></div>'
          : '<div class="cldb-empty"><b>点击“手动刷新畅联云”读取数据</b><span>页面不会自动读取远端数据库。</span></div>'}
      </div>
    </section>`;
    return true;
  }

  async function refresh() {
    if (destroyed) throw new Error('畅联云数据浏览器已销毁');
    if (refreshPromise) return refreshPromise;
    leave();
    detailCache.clear();detailPending.clear();
    const epoch = ++refreshEpoch;
    snapshot = {...snapshot, loading: true, error: ''};
    render();
    refreshPromise = (async () => {
      const [enabledRaw, disabledRaw] = await Promise.all([
        request(ENABLED_PRODUCTS_ENDPOINT),
        request(DISABLED_PRODUCTS_ENDPOINT),
      ]);
      const products = mergeProducts(providerItems(enabledRaw), providerItems(disabledRaw));
      const hydrated = await mapLimit(products, 4, async product => {
        const productId = productIdentity(product);
        if (!productId) return {...product, versions: []};
        const versionsRaw = await request(`${BASE}/versions/by-product/${encodeURIComponent(productId)}`);
        const versions = providerItems(versionsRaw);
        const hydratedVersions = await mapLimit(versions, 4, async version => {
          const versionId = versionIdentity(version);
          if (!versionId) return {...version, weights: []};
          const weightsRaw = await request(`${BASE}/weights/by-version/${encodeURIComponent(versionId)}`);
          return {...version, weights: providerItems(weightsRaw)};
        });
        return {...product, versions: hydratedVersions};
      });
      if (destroyed || epoch !== refreshEpoch) return snapshot;
      snapshot = {loaded: true, loading: false, loadedAt: new Date().toISOString(), products: hydrated, error: ''};
      render();
      notify?.(`已读取畅联云：${hydrated.length} 个算法产品`);
      return snapshot;
    })().catch(error => {
      if (!destroyed && epoch === refreshEpoch) {
        snapshot = {...snapshot, loading: false, error: String(error?.message || error || '读取失败')};
        render();
      }
      throw error;
    }).finally(() => {
      refreshPromise = null;
    });
    return refreshPromise;
  }

  const runtime = {
    build: 'changlian-data-browser-63001',
    page: PAGE,
    render,
    refresh,
    snapshot: () => snapshot,
    openWeightDetails,
    detailSnapshot: () => detail,
    leave,
    destroy() {
      leave();
      boundView?.removeEventListener('click',onViewClick);
      detailCache.clear();detailPending.clear();
      destroyed = true;
      refreshEpoch += 1;
    },
  };
  const host = globalThis.window || globalThis;
  host.ChangLianDataBrowserRuntime = runtime;
  return runtime;
}

const PAGE = '服务节点';
const API_ROOT = '/api/v63/service-nodes';
const POLL_KEY = 'service-node-runtime';
const POLL_MS = 5000;

export const CAPABILITY_LABELS = Object.freeze({
  training: '训练',
  'material-import': '素材导入',
  cleaning: '数据清洗',
  annotation: '标注',
  video: '视频抽帧',
  conversion: '模型转换',
  'conversion.rknn': '瑞芯微 RKNN 转换',
  'deployment-test': '部署测试',
  'deployment-test.rknn': '瑞芯微板端验证',
  'model-upload': '模型上传',
});

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[char]));
}

function rawFetch() {
  const scoped = window.fetch;
  return scoped?.__pageRequestScopeOriginal || scoped;
}

async function requestJson(url, options = {}, fetchImpl = rawFetch()) {
  const response = await fetchImpl(url, {
    ...options,
    headers: {'Accept': 'application/json', ...(options.headers || {})},
  });
  const text = await response.text();
  let body = {};
  try { body = text ? JSON.parse(text) : {}; } catch (_) { body = {detail: text}; }
  if (!response.ok) {
    const nested = typeof body?.detail === 'object' && body.detail ? body.detail : {};
    const message = body?.message || nested?.message || body?.detail || `请求失败（HTTP ${response.status}）`;
    const error = new Error(String(message));
    error.code = body?.code || nested?.code || `HTTP_${response.status}`;
    error.httpStatus = response.status;
    throw error;
  }
  return body;
}

export function formatBytes(value) {
  const bytes = Number(value);
  if (!Number.isFinite(bytes) || bytes < 0) return '-';
  if (bytes < 1024) return `${Math.round(bytes)} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let amount = bytes / 1024;
  let index = 0;
  while (amount >= 1024 && index < units.length - 1) {
    amount /= 1024;
    index += 1;
  }
  const digits = amount >= 100 ? 0 : amount >= 10 ? 1 : 2;
  return `${amount.toFixed(digits)} ${units[index]}`;
}

export function safePercent(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return null;
  return Math.max(0, Math.min(100, number));
}

export function capabilityLabel(value) {
  return CAPABILITY_LABELS[String(value || '')] || String(value || '');
}

export function nodeStatusMeta(status) {
  const key = String(status || '').toUpperCase();
  return ({
    ONLINE: {label: 'Agent 在线', className: 'ok'},
    OFFLINE: {label: '心跳超时', className: 'err'},
    DISABLED: {label: '已停用', className: 'warn'},
    NEVER_CONNECTED: {label: '未收到心跳', className: 'warn'},
  })[key] || {label: key || '未知', className: 'warn'};
}

export function buildAgentCommands({origin, nodeId, token, capabilities = []}) {
  const base = String(origin || '').replace(/\/$/, '');
  const id = String(nodeId || '');
  const secret = String(token || '');
  const rows = capabilities.map(String);
  const cap = rows.join(',');
  const rockchipBoard = rows.includes('deployment-test.rknn');
  return {
    linux: `MC_CONTROL_PLANE_URL='${base}' MC_NODE_ID='${id}' MC_NODE_AGENT_TOKEN='${secret}' MC_NODE_CAPABILITIES='${cap}' python node_agent.py`,
    windows: `$env:MC_CONTROL_PLANE_URL='${base}'; $env:MC_NODE_ID='${id}'; $env:MC_NODE_AGENT_TOKEN='${secret}'; $env:MC_NODE_CAPABILITIES='${cap}'; python node_agent.py`,
    rockchipDoctor: rockchipBoard
      ? `MC_NODE_CAPABILITIES='deployment-test.rknn' MC_AGENT_RKNN_LITE_PYTHON='/path/to/rknn-lite/python' python node_agent.py --doctor`
      : '',
    rockchipInstall: rockchipBoard
      ? `sudo bash tools/install_rockchip_agent.sh --control-plane '${base}' --node-id '${id}' --app-root "$PWD" --rknn-lite-python '/path/to/rknn-lite/python'`
      : '',
  };
}

function timeAgo(seconds) {
  const value = Number(seconds);
  if (!Number.isFinite(value)) return '从未';
  if (value < 2) return '刚刚';
  if (value < 60) return `${Math.round(value)} 秒前`;
  if (value < 3600) return `${Math.round(value / 60)} 分钟前`;
  return `${Math.round(value / 3600)} 小时前`;
}

function meter(label, percent, detail) {
  const value = safePercent(percent);
  return `<div class="node633-meter"><div><span>${escapeHtml(label)}</span><b>${value == null ? '-' : `${Math.round(value)}%`}</b></div><i><em style="width:${value == null ? 0 : value}%"></em></i><small>${escapeHtml(detail || '-')}</small></div>`;
}

function capabilityChips(values, kind = '') {
  const rows = Array.isArray(values) ? values : [];
  if (!rows.length) return '<span class="node633-empty-inline">无</span>';
  return rows.map(value => `<span class="node633-cap ${kind}">${escapeHtml(capabilityLabel(value))}</span>`).join('');
}

function gpuCards(node) {
  const gpu = node?.resources?.gpu || {};
  const rows = Array.isArray(gpu.gpus) ? gpu.gpus : [];
  if (!rows.length) return `<div class="node633-no-gpu">${gpu.error ? `GPU 探测失败：${escapeHtml(gpu.error)}` : '未检测到 NVIDIA GPU'}</div>`;
  return rows.map(item => {
    const total = Number(item.memory_total_bytes || 0);
    const used = Number(item.memory_used_bytes || 0);
    const vram = total > 0 ? used / total * 100 : null;
    return `<div class="node633-gpu-card"><div class="node633-gpu-head"><b>${escapeHtml(item.name || `GPU ${item.index}`)}</b><span>${escapeHtml(item.id || `cuda:${item.index}`)}</span></div>${meter('GPU 利用率', item.utilization_percent, item.temperature_c == null ? '温度 -' : `温度 ${item.temperature_c}℃`)}${meter('显存', vram, `${formatBytes(used)} / ${formatBytes(total)} · 空闲 ${formatBytes(item.memory_free_bytes)}`)}</div>`;
  }).join('');
}

function workerRows(node) {
  const workers = Array.isArray(node.workers) ? node.workers : [];
  if (!workers.length) return '<div class="node633-empty-inline">暂无运行中的 Worker</div>';
  return workers.map(worker => `<div class="node633-worker"><b>${escapeHtml(worker.worker_id || '-')}</b><span>${escapeHtml((worker.roles || []).join(' / ') || '-')}</span><span>${worker.online ? '在线' : '离线'} · PID ${escapeHtml(worker.pid ?? '-')}</span></div>`).join('');
}

function taskRows(node) {
  const tasks = Array.isArray(node.durable_tasks) ? node.durable_tasks : [];
  if (!tasks.length) return '<div class="node633-empty-inline">当前无执行中的持久任务</div>';
  return tasks.map(task => `<div class="node633-task"><div><b>${escapeHtml(task.kind || '-')}</b><span>${escapeHtml(task.task_id || '-')}</span></div><div><span>${escapeHtml(task.stage || task.status || '-')}</span><b>${Math.round(Number(task.progress || 0))}%</b></div></div>`).join('');
}

export function renderNodeCard(node) {
  const status = nodeStatusMeta(node?.status);
  const cpu = node?.resources?.cpu || {};
  const memory = node?.resources?.memory || {};
  const disk = node?.resources?.disk || {};
  const process = node?.process || {};
  const runtime = node?.runtime || {};
  const rknnBoard = runtime?.rknn_board && typeof runtime.rknn_board === 'object' ? runtime.rknn_board : null;
  const rknnToolkit = runtime?.rknn_toolkit2 && typeof runtime.rknn_toolkit2 === 'object' ? runtime.rknn_toolkit2 : null;
  const rockchipRuntime = [
    rknnBoard ? `<div><span>Rockchip 板卡</span><b>${rknnBoard.available ? escapeHtml(String(rknnBoard.chip || '-').toUpperCase()) : '未就绪'} · RKNNLite ${escapeHtml(rknnBoard.rknn_lite_version || '-')}</b></div>` : '',
    rknnToolkit ? `<div><span>RKNN-Toolkit2</span><b>${rknnToolkit.available ? escapeHtml(rknnToolkit.version || '-') : '未就绪'} · ${escapeHtml((rknnToolkit.supported_chips || []).map(x => String(x).toUpperCase()).join(' / ') || '-')}</b></div>` : '',
  ].join('');
  const memoryPercent = safePercent(memory.usage_percent) ?? (Number(memory.total_bytes) > 0 ? Number(memory.used_bytes || 0) / Number(memory.total_bytes) * 100 : null);
  const diskPercent = safePercent(disk.usage_percent) ?? (Number(disk.total_bytes) > 0 ? Number(disk.used_bytes || 0) / Number(disk.total_bytes) * 100 : null);
  return `<article class="node633-card" data-node-card="${escapeHtml(node?.node_id || '')}">
    <header class="node633-card-head"><div><div class="node633-title"><b>${escapeHtml(node?.display_name || node?.node_id || '未命名节点')}</b><span class="pill ${status.className}">${escapeHtml(status.label)}</span></div><p>${escapeHtml(node?.node_id || '-')} · ${escapeHtml(node?.hostname || '尚未上报主机名')}</p></div><div class="node633-actions"><button class="btn small" data-node-action="test" data-node-id="${escapeHtml(node?.node_id || '')}">测试联通</button><button class="btn small" data-node-action="edit" data-node-id="${escapeHtml(node?.node_id || '')}">编辑</button><button class="btn small ${node?.enabled ? 'soft' : 'primary'}" data-node-action="toggle" data-node-id="${escapeHtml(node?.node_id || '')}">${node?.enabled ? '停用' : '启用'}</button><button class="btn small" data-node-action="rotate" data-node-id="${escapeHtml(node?.node_id || '')}">轮换 Token</button><button class="btn small danger" data-node-action="delete" data-node-id="${escapeHtml(node?.node_id || '')}">删除</button></div></header>
    <div class="node633-meta-grid"><div><span>连接方式</span><b>${node?.connection_mode === 'local' ? '本机 Agent' : '远程 Agent'}</b></div><div><span>最后心跳</span><b>${escapeHtml(timeAgo(node?.heartbeat_age_seconds))}</b></div><div><span>系统</span><b>${escapeHtml([node?.os_name, node?.architecture].filter(Boolean).join(' / ') || '-')}</b></div><div><span>Agent / Build</span><b>${escapeHtml([node?.agent_version, node?.build_id].filter(Boolean).join(' / ') || '-')}</b></div></div>
    <section class="node633-cap-section"><div><span>允许能力</span>${capabilityChips(node?.allowed_capabilities, 'allowed')}</div><div><span>已上报能力</span>${capabilityChips(node?.reported_capabilities, 'reported')}</div><div><span>当前可调度能力</span>${capabilityChips(node?.effective_capabilities, 'effective')}</div></section>
    <div class="node633-resource-grid">${meter('CPU', cpu.usage_percent, `${cpu.physical_cores ?? '-'} 物理核 / ${cpu.logical_cores ?? '-'} 逻辑核`)}${meter('内存', memoryPercent, `${formatBytes(memory.used_bytes)} / ${formatBytes(memory.total_bytes)} · 可用 ${formatBytes(memory.available_bytes)}`)}${meter('磁盘', diskPercent, `${disk.path || '-'} · ${formatBytes(disk.used_bytes)} / ${formatBytes(disk.total_bytes)} · 空闲 ${formatBytes(disk.free_bytes)}`)}</div>
    <div class="node633-gpus">${gpuCards(node)}</div>
    <div class="node633-runtime-grid"><div><span>PyTorch</span><b>${escapeHtml(runtime.torch_version || '-')}</b></div><div><span>CUDA</span><b>${escapeHtml(runtime.cuda_version || '-')}</b></div><div><span>CUDA 可用</span><b>${runtime.cuda_available === true ? '是' : runtime.cuda_available === false ? '否' : '-'}</b></div>${rockchipRuntime}<div><span>Agent 进程</span><b>PID ${escapeHtml(process.pid ?? '-')} · RSS ${formatBytes(process.rss_bytes)} · ${escapeHtml(process.threads ?? '-')} 线程</b></div><div><span>文件句柄</span><b>open files ${escapeHtml(process.open_files ?? '-')} · fd/handle ${escapeHtml(process.file_descriptors ?? process.handles ?? '-')}</b></div><div><span>Agent 地址</span><b>${escapeHtml(node?.agent_url || '-')}</b></div></div>
    <details class="node633-detail"><summary>Worker 与当前任务</summary><div class="node633-detail-grid"><section><h4>Worker</h4>${workerRows(node)}</section><section><h4>执行中任务</h4>${taskRows(node)}</section></div></details>
    ${node?.last_error ? `<div class="alert warn node633-error"><b>最近上报错误</b><div>${escapeHtml(node.last_error)}</div></div>` : ''}
  </article>`;
}

function nodeFormHtml(node, capabilities) {
  const edit = Boolean(node);
  const selected = new Set(node?.allowed_capabilities || []);
  const rockchipPreset = capabilities.includes('deployment-test.rknn')
    ? '<div class="field full"><label>快捷配置</label><div class="row"><button type="button" class="btn small" data-node-preset="rockchip-board">Rockchip 板端节点</button></div><small>自动使用远程 Agent，并只启用瑞芯微板端验证能力。</small></div>'
    : '';
  return `<div class="form node633-form" data-node-form="1"><div class="field"><label>节点 ID</label><input id="node633Id" class="input" ${edit ? 'disabled' : ''} value="${escapeHtml(node?.node_id || '')}" placeholder="例如 gpu-a800-01"></div><div class="field"><label>节点名称</label><input id="node633Name" class="input" value="${escapeHtml(node?.display_name || '')}" placeholder="例如 A800 训练节点"></div><div class="field"><label>连接方式</label><select id="node633Mode" class="select"><option value="agent" ${node?.connection_mode !== 'local' ? 'selected' : ''}>远程 Agent</option><option value="local" ${node?.connection_mode === 'local' ? 'selected' : ''}>本机 Agent</option></select></div><div class="field"><label>Agent 地址</label><input id="node633Url" class="input" value="${escapeHtml(node?.agent_url || '')}" placeholder="可选，例如 http://10.0.0.20:8030"></div><label class="field check"><input id="node633Enabled" type="checkbox" ${node?.enabled !== false ? 'checked' : ''}> 启用该节点</label>${rockchipPreset}<div class="field full"><label>允许执行的能力</label><div class="node633-cap-picker">${capabilities.map(capability => `<label><input type="checkbox" value="${escapeHtml(capability)}" ${selected.has(capability) ? 'checked' : ''}><span>${escapeHtml(capabilityLabel(capability))}</span><small>${escapeHtml(capability)}</small></label>`).join('')}</div></div><div class="row end"><button class="btn soft" data-node-form-cancel>取消</button><button class="btn primary" id="node633Save">${edit ? '保存修改' : '创建节点'}</button></div></div>`;
}

function tokenModalHtml(node, token) {
  const commands = buildAgentCommands({origin: window.location.origin, nodeId: node.node_id, token, capabilities: node.allowed_capabilities || []});
  const rockchip = commands.rockchipDoctor
    ? `<div class="field"><label>Rockchip 板端预检</label><div class="node633-command"><code id="node633RockchipDoctor">${escapeHtml(commands.rockchipDoctor)}</code><button class="btn small" data-copy-target="node633RockchipDoctor">复制</button></div><small>先把 /path/to/rknn-lite/python 替换为板端实际 RKNNLite Python；doctor 未通过时不要安装服务。</small></div><div class="field"><label>Rockchip systemd 安装</label><div class="node633-command"><code id="node633RockchipInstall">${escapeHtml(commands.rockchipInstall)}</code><button class="btn small" data-copy-target="node633RockchipInstall">复制</button></div><small>安装脚本会再次执行 strict doctor，并静默提示输入上方 Token；Token 不进入 systemd ExecStart。</small></div>`
    : '';
  return `<div class="node633-token" data-node-token="1"><div class="alert warn"><b>Agent Token 只显示这一次</b><div>关闭后平台不会再返回明文 Token；如遗失，请执行“轮换 Token”。</div></div><div class="field"><label>节点</label><div class="node633-secret-row"><code>${escapeHtml(node.node_id)}</code></div></div><div class="field"><label>Agent Token</label><div class="node633-secret-row"><code id="node633TokenValue">${escapeHtml(token)}</code><button class="btn small" data-copy-target="node633TokenValue">复制</button></div></div>${rockchip}<div class="field"><label>Linux 启动命令</label><div class="node633-command"><code id="node633LinuxCommand">${escapeHtml(commands.linux)}</code><button class="btn small" data-copy-target="node633LinuxCommand">复制</button></div></div><div class="field"><label>Windows PowerShell 启动命令</label><div class="node633-command"><code id="node633WindowsCommand">${escapeHtml(commands.windows)}</code><button class="btn small" data-copy-target="node633WindowsCommand">复制</button></div></div><div class="row end"><button class="btn primary" data-node-token-close>我已保存 Token</button></div></div>`;
}

export function installServiceNodeRuntime({notify = message => window.toast?.(message)} = {}) {
  if (typeof window === 'undefined' || typeof document === 'undefined') return null;
  if (window.__serviceNodeRuntimeInstalled) return window.ServiceNodeRuntime;

  let nodes = [];
  let capabilities = Object.keys(CAPABILITY_LABELS);
  let loading = false;
  let destroyed = false;
  let navObserver = null;
  let unregisterPageOwner = null;

  const currentPage = () => String(window.NavigationStability?.currentPage?.() || '').trim();
  const findNode = nodeId => nodes.find(node => String(node.node_id) === String(nodeId));

  function clearPoll() { window.PollRegistryRuntime?.clear?.(POLL_KEY); }
  function armPoll() {
    clearPoll();
    if (destroyed || currentPage() !== PAGE) return;
    window.PollRegistryRuntime?.startTimeout?.(POLL_KEY, PAGE, async () => {
      if (destroyed || currentPage() !== PAGE) return;
      try { await refresh({paint: true, silent: true}); } catch (_) {}
      finally { armPoll(); }
    }, POLL_MS);
  }

  async function load({silent = false} = {}) {
    try {
      const body = await requestJson(API_ROOT);
      nodes = Array.isArray(body?.items) ? body.items : [];
      if (Array.isArray(body?.supported_capabilities) && body.supported_capabilities.length) capabilities = body.supported_capabilities;
      return nodes;
    } catch (error) {
      if (!silent) notify?.(error?.message || error);
      throw error;
    }
  }

  function paintSummary() {
    const summary = document.getElementById('summary');
    if (!summary) return;
    const online = nodes.filter(node => node.status === 'ONLINE').length;
    const disabled = nodes.filter(node => node.status === 'DISABLED').length;
    const gpuCount = nodes.reduce((sum, node) => sum + (node?.resources?.gpu?.gpus?.length || 0), 0);
    const tasks = nodes.reduce((sum, node) => sum + (node?.durable_tasks?.length || 0), 0);
    summary.innerHTML = `<div class="stat"><div class="k">服务节点</div><div class="v">${nodes.length}</div></div><div class="stat"><div class="k">在线</div><div class="v">${online}</div></div><div class="stat"><div class="k">已停用</div><div class="v">${disabled}</div></div><div class="stat"><div class="k">GPU</div><div class="v">${gpuCount}</div></div><div class="stat"><div class="k">执行中任务</div><div class="v">${tasks}</div></div>`;
  }

  function pageHtml() {
    return `<section class="node633-shell" data-service-node-page="1"><div class="node633-page-head"><div><h2>服务节点</h2><p>统一查看各节点实时资源、Agent/Worker 状态和可执行能力。节点启停只改变中央允许状态，不会绕过现有任务 lease/fencing。</p></div><div class="row"><button class="btn" data-node-page-refresh>刷新</button><button class="btn primary" data-node-page-create>＋ 新增服务节点</button></div></div><div class="node633-list">${nodes.length ? nodes.map(renderNodeCard).join('') : '<div class="empty node633-empty">暂无服务节点。新增节点后，在目标服务器运行 Node Agent 完成注册心跳。</div>'}</div></section>`;
  }

  function invokeCardAction(button) {
    const nodeId = button.dataset.nodeId || '';
    const action = button.dataset.nodeAction || '';
    if (action === 'test') void testConnectivity(nodeId, button);
    if (action === 'edit') openForm(findNode(nodeId));
    if (action === 'toggle') void toggleNode(nodeId);
    if (action === 'rotate') void rotateToken(nodeId);
    if (action === 'delete') void deleteNode(nodeId);
  }

  function bindPage() {
    const view = document.getElementById('view');
    if (!view) return;
    view.querySelector('[data-node-page-refresh]')?.addEventListener('click', () => void refresh({paint: true}));
    view.querySelector('[data-node-page-create]')?.addEventListener('click', () => openForm());
    view.querySelectorAll('[data-node-action]').forEach(button => {
      button.addEventListener('click', () => invokeCardAction(button));
    });
  }

  async function render({reload = true, silent = false} = {}) {
    if (destroyed || currentPage() !== PAGE) return false;
    const view = document.getElementById('view');
    if (!view) return false;
    if (loading) {
      paintSummary();
      view.innerHTML = nodes.length
        ? pageHtml()
        : '<section class="node633-shell" data-service-node-page="1" data-service-node-skeleton="1"><div class="empty">正在读取服务节点…</div></section>';
      if (nodes.length) bindPage();
      return false;
    }
    loading = true;
    const hadCache = nodes.length > 0;
    const before = hadCache ? JSON.stringify(nodes) : '';
    if (hadCache) {
      paintSummary();
      view.innerHTML = pageHtml();
      bindPage();
      armPoll();
    } else if (reload) {
      paintSummary();
      view.innerHTML = '<section class="node633-shell" data-service-node-page="1" data-service-node-skeleton="1"><div class="empty">正在读取服务节点…</div></section>';
    }
    try {
      if (reload) await load({silent});
      if (currentPage() !== PAGE) return false;
      if (!hadCache || JSON.stringify(nodes) !== before || !view.querySelector('[data-service-node-page]')) {
        paintSummary();
        view.innerHTML = pageHtml();
        bindPage();
      }
      armPoll();
      return true;
    } catch (error) {
      if (!hadCache && currentPage() === PAGE) view.innerHTML = `<div class="alert err">${escapeHtml(error?.message || error)}</div>`;
      return hadCache;
    } finally {
      loading = false;
    }
  }

  async function refresh({paint = true, silent = false} = {}) {
    const before = JSON.stringify(nodes);
    await load({silent});
    if (paint && currentPage() === PAGE && (JSON.stringify(nodes) !== before || !document.querySelector('[data-service-node-page]'))) {
      paintSummary();
      const view = document.getElementById('view');
      if (view) { view.innerHTML = pageHtml(); bindPage(); }
    }
    return nodes;
  }

  const selectedCapabilities = root => [...root.querySelectorAll('.node633-cap-picker input:checked')].map(input => input.value);

  function openForm(node = null) {
    window.modal?.(node ? '编辑服务节点' : '新增服务节点', nodeFormHtml(node, capabilities), true);
    const root = document.querySelector('[data-node-form]');
    if (!root) return;
    root.querySelector('[data-node-form-cancel]')?.addEventListener('click', () => window.closeModal?.());
    root.querySelector('[data-node-preset="rockchip-board"]')?.addEventListener('click', () => {
      const mode = root.querySelector('#node633Mode');
      if (mode) mode.value = 'agent';
      root.querySelectorAll('.node633-cap-picker input').forEach(input => {
        input.checked = input.value === 'deployment-test.rknn';
      });
      const name = root.querySelector('#node633Name');
      if (name && !String(name.value || '').trim()) name.value = 'Rockchip 板端节点';
    });
    root.querySelector('#node633Save')?.addEventListener('click', async event => {
      const button = event.currentTarget;
      const nodeId = String(root.querySelector('#node633Id')?.value || '').trim();
      const payload = {
        display_name: String(root.querySelector('#node633Name')?.value || '').trim(),
        connection_mode: root.querySelector('#node633Mode')?.value || 'agent',
        agent_url: String(root.querySelector('#node633Url')?.value || '').trim(),
        enabled: Boolean(root.querySelector('#node633Enabled')?.checked),
        allowed_capabilities: selectedCapabilities(root),
      };
      if (!node && !nodeId) return notify?.('请填写节点 ID');
      button.disabled = true;
      button.textContent = node ? '正在保存…' : '正在创建…';
      try {
        if (node) {
          await requestJson(`${API_ROOT}/${encodeURIComponent(node.node_id)}`, {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
          window.closeModal?.();
          await refresh({paint: true});
          notify?.('服务节点配置已保存');
        } else {
          const created = await requestJson(API_ROOT, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({node_id: nodeId, ...payload})});
          await refresh({paint: true, silent: true});
          showToken(created.node, created.agent_token);
        }
      } catch (error) {
        notify?.(error?.message || error);
        button.disabled = false;
        button.textContent = node ? '保存修改' : '创建节点';
      }
    });
  }

  function showToken(node, token) {
    if (!node || !token) return notify?.('节点已保存，但服务器未返回 Agent Token');
    window.modal?.('保存 Agent Token', tokenModalHtml(node, token), true);
    const root = document.querySelector('[data-node-token]');
    if (!root) return;
    root.querySelectorAll('[data-copy-target]').forEach(button => button.addEventListener('click', async () => {
      const text = document.getElementById(button.dataset.copyTarget)?.textContent || '';
      try { await navigator.clipboard.writeText(text); notify?.('已复制'); }
      catch (_) { notify?.('浏览器未允许自动复制，请手动选择文本复制'); }
    }));
    root.querySelector('[data-node-token-close]')?.addEventListener('click', () => window.closeModal?.());
  }

  async function testConnectivity(nodeId, button = null) {
    const node = findNode(nodeId);
    if (!node) return notify?.('服务节点不存在，请刷新后重试');
    const originalText = button?.textContent || '测试联通';
    if (button) {
      button.disabled = true;
      button.textContent = '测试中…';
    }
    try {
      const result = await requestJson(`${API_ROOT}/${encodeURIComponent(nodeId)}/connectivity-test`, {method: 'POST'});
      const ageText = Number.isFinite(Number(result?.heartbeat_age_seconds))
        ? ` · 最近心跳 ${timeAgo(result.heartbeat_age_seconds)}`
        : '';
      const heartbeatText = result?.heartbeat_online
        ? `Agent 心跳在线${ageText}`
        : `${result?.heartbeat_message || '尚未收到有效 Agent 心跳'}${ageText}`;
      const networkText = result?.network_reachable === true
        ? `网络可达（${result?.network_target || node.agent_url || 'Agent 地址'}）`
        : result?.network_reachable === false
          ? `网络不可达（${result?.network_target || node.agent_url || 'Agent 地址'}）`
          : (result?.network_error || '未配置 Agent 地址，无法测试网络可达性');
      notify?.(`${networkText} · ${heartbeatText}`);
      await refresh({paint: true, silent: true});
      return result;
    } catch (error) {
      notify?.(error?.message || error);
      return null;
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent = originalText;
      }
    }
  }

  async function toggleNode(nodeId) {
    const node = findNode(nodeId);
    if (!node) return;
    try {
      await requestJson(`${API_ROOT}/${encodeURIComponent(nodeId)}`, {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({enabled: !node.enabled})});
      await refresh({paint: true});
      notify?.(node.enabled ? '节点已停用' : '节点已启用');
    } catch (error) { notify?.(error?.message || error); }
  }

  async function rotateToken(nodeId) {
    const node = findNode(nodeId);
    if (!node || !window.confirm?.(`确认轮换 ${node.display_name || nodeId} 的 Agent Token？旧 Token 会立即失效。`)) return;
    try {
      const body = await requestJson(`${API_ROOT}/${encodeURIComponent(nodeId)}/rotate-token`, {method: 'POST'});
      await refresh({paint: true, silent: true});
      showToken(body.node, body.agent_token);
    } catch (error) { notify?.(error?.message || error); }
  }

  async function deleteNode(nodeId) {
    const node = findNode(nodeId);
    if (!node || !window.confirm?.(`确认删除服务节点“${node.display_name || nodeId}”？运行中的 Worker/任务存在时服务器会拒绝删除。`)) return;
    try {
      await requestJson(`${API_ROOT}/${encodeURIComponent(nodeId)}`, {method: 'DELETE'});
      await refresh({paint: true});
      notify?.('服务节点已删除');
    } catch (error) { notify?.(error?.message || error); }
  }

  function decorateNavigation() {
    if (destroyed) return;
    const nav = document.getElementById('nav');
    if (!nav) return;
    const groups = [...nav.querySelectorAll('.nav-group')];
    const preferred = groups.find(group => group.querySelector('.nav-group-title')?.textContent.trim() === '配置中心') || groups.at(-1);
    const owner = preferred || nav;
    let button = nav.querySelector('[data-service-node-nav="1"]');
    if (!button) {
      button = document.createElement('button');
      button.dataset.serviceNodeNav = '1';
      button.className = 'nav-btn';
      button.innerHTML = '<span class="nav-left"><i>◆</i><b>服务节点</b></span><span class="nav-arrow">›</span>';
      button.addEventListener('click', () => window.setPage?.(PAGE));
      owner.appendChild(button);
    }
    button.classList.toggle('active', currentPage() === PAGE);
  }

  const nav = document.getElementById('nav');
  if (nav) {
    navObserver = new MutationObserver(decorateNavigation);
    navObserver.observe(nav, {childList: true, subtree: true});
  }
  unregisterPageOwner = window.NavigationStability?.registerPageOwner?.(PAGE, () => {
    decorateNavigation();
    return render();
  }) || null;
  decorateNavigation();

  const runtime = {
    build: 'service-node-runtime-422535',
    page: PAGE,
    load,
    render,
    refresh,
    openForm,
    showToken,
    testConnectivity,
    toggleNode,
    rotateToken,
    deleteNode,
    nodes: () => [...nodes],
    capabilities: () => [...capabilities],
    destroy() {
      destroyed = true;
      clearPoll();
      navObserver?.disconnect();
      unregisterPageOwner?.();
      document.querySelector('[data-service-node-nav="1"]')?.remove();
      if (window.ServiceNodeRuntime === runtime) window.ServiceNodeRuntime = null;
      window.__serviceNodeRuntimeInstalled = false;
    },
  };
  window.ServiceNodeRuntime = runtime;
  window.__serviceNodeRuntimeInstalled = true;
  return runtime;
}

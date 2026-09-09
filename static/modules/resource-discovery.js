const ACTIVE_TASK_STATUSES = new Set(['QUEUED', 'RUNNING', 'CANCEL_REQUESTED']);
const SUCCESS_TASK_STATUSES = new Set(['SUCCEEDED', 'PARTIAL_SUCCESS']);

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[character]);
}

function status(value) {
  return String(value || '').trim().toUpperCase();
}

function moduleLine(name, value, includeOps = false) {
  const module = value && typeof value === 'object' ? value : {};
  const error = module.error?.message || module.ops_error?.message || '';
  const state = module.ok && (!includeOps || module.ops_ok) ? 'ok' : 'err';
  const version = module.version ? ` ${escapeHtml(module.version)}` : '';
  return `<span class="rd-module ${state}"><b>${escapeHtml(name)}</b>${version}${error ? `<em>${escapeHtml(error)}</em>` : ''}</span>`;
}

function environmentReason(candidate, index) {
  if (status(candidate.status) !== 'AVAILABLE') return '环境未通过完整导入与 TorchVision Ops 检测';
  if (candidate.cuda_available) return index === 0 ? '推荐：CUDA 可用且环境完整' : 'CUDA 可用环境';
  return index === 0 ? '推荐：当前可用环境中排序最高' : '可用于 CPU 训练与普通验证';
}

function bytes(value) {
  const size = Number(value) || 0;
  if (size < 1024) return `${size} B`;
  if (size < 1024 ** 2) return `${(size / 1024).toFixed(1)} KB`;
  if (size < 1024 ** 3) return `${(size / 1024 ** 2).toFixed(1)} MB`;
  return `${(size / 1024 ** 3).toFixed(1)} GB`;
}

function dateText(value) {
  if (!value) return '尚未检测';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN');
}

function abortableDelay(milliseconds, signal) {
  return new Promise((resolve, reject) => {
    if (signal.aborted) return reject(new DOMException('Aborted', 'AbortError'));
    const timer = setTimeout(resolve, milliseconds);
    signal.addEventListener('abort', () => {
      clearTimeout(timer);
      reject(new DOMException('Aborted', 'AbortError'));
    }, {once: true});
  });
}

export function installResourceDiscoveryRuntime(dependencies = {}) {
  if (window.ResourceDiscoveryRuntime?.installed) return window.ResourceDiscoveryRuntime;

  const request = dependencies.request;
  const notify = dependencies.notify || (() => {});
  const showModal = dependencies.modal;
  const refreshApplication = dependencies.refresh || (async () => {});
  const getPage = dependencies.getPage || (() => '');
  if (typeof request !== 'function' || typeof showModal !== 'function') return null;

  const previousRenderResources = window.renderResources;
  const runtime = {
    installed: true,
    environments: [],
    activeEnvironment: {},
    environmentMeta: {},
    officialModels: [],
    models: [],
    modelMeta: {},
    modelCursor: null,
    modelNextCursor: null,
    modelCursorStack: [],
    cacheGeneration: 0,
    pollControllers: new Set()
  };

  function environmentCards() {
    const activePath = String(runtime.activeEnvironment?.python_path || '').toLocaleLowerCase();
    if (!runtime.environments.length) return '<div class="empty">缓存中尚未发现 Python / Ultralytics 环境。点击“一键检测”启动后台发现。</div>';
    return runtime.environments.map((candidate, index) => {
      const available = status(candidate.status) === 'AVAILABLE';
      const candidatePath = String(candidate.python_path || candidate.python_executable || '');
      const selected = activePath && candidatePath.toLocaleLowerCase() === activePath;
      const gpuNames = Array.isArray(candidate.gpu_names) ? candidate.gpu_names.join('、') : '';
      return `<article class="rd-env-card ${available ? 'available' : 'unavailable'} ${selected ? 'selected' : ''}">
        <header><div><b>Python ${escapeHtml(candidate.python_version || '-')}</b><span>${escapeHtml(environmentReason(candidate, index))}</span></div><span class="pill ${available ? 'ok' : 'err'}">${available ? 'AVAILABLE' : '不可用'}</span></header>
        <code title="${escapeHtml(candidatePath)}">${escapeHtml(candidatePath || '未返回 Python 路径')}</code>
        <div class="rd-runtime-facts"><span><b>${candidate.cuda_available ? 'CUDA' : 'CPU'}</b>${candidate.cuda_available ? ` · ${Number(candidate.gpu_count) || 0} 张 GPU` : ' · 未检测到 CUDA'}</span><span>${escapeHtml(gpuNames || '无 GPU 信息')}</span></div>
        <div class="rd-modules">${moduleLine('Ultralytics', candidate.ultralytics)}${moduleLine('Torch', candidate.torch)}${moduleLine('TorchVision', candidate.torchvision, true)}</div>
        <footer><span>${selected ? '当前训练环境' : escapeHtml((candidate.sources || []).join('、') || '本机发现')}</span>${available && !selected ? `<button class="btn mini primary" onclick="selectResourceEnvironment(${index})">确认使用此环境</button>` : ''}</footer>
      </article>`;
    }).join('');
  }

  function officialModelRows() {
    if (!runtime.officialModels.length) return '';
    return `<div class="rd-official-models"><b>官方基础模型</b>${runtime.officialModels.map(model => {
      const found = status(model.model_status) === 'FOUND' || Boolean(model.found);
      const failed = Boolean(model.download_error || model.error);
      const text = found ? '已发现' : failed ? '下载失败' : model.downloadable ? '未下载 · 可自动下载' : '未发现';
      return `<span class="pill ${found ? 'ok' : failed ? 'err' : 'warn'}" title="${escapeHtml(model.note || model.download_error || model.error || '')}">${escapeHtml(model.value || model.label || '')} · ${text}</span>`;
    }).join('')}</div>`;
  }

  function modelRows() {
    if (!runtime.models.length) return '<div class="empty">缓存中尚未发现模型文件。可指定目录扫描，或启动全机扫描。</div>';
    return `<div class="table-wrap"><table class="table rd-model-table"><thead><tr><th>模型</th><th>格式</th><th>大小</th><th>来源</th><th>修改时间</th></tr></thead><tbody>${runtime.models.map(model => `<tr><td><b>${escapeHtml(model.name || '')}</b><code title="${escapeHtml(model.path || '')}">${escapeHtml(model.path || '')}</code></td><td>${escapeHtml(model.format || '')}</td><td>${bytes(model.size_bytes)}</td><td>${escapeHtml(model.volume || '-')}</td><td>${escapeHtml(model.modified_at || model.updated_at || '-')}</td></tr>`).join('')}</tbody></table></div>`;
  }

  function renderCachePanel() {
    const root = document.getElementById('resourceDiscoveryCache');
    if (!root) return;
    root.innerHTML = `<div class="rd-cache-head"><div><b>本机资源发现</b><span>读取上次成功缓存；刷新页面不会重新扫描全机。</span></div><button class="btn small" onclick="refreshResourceDiscoveryCache()">刷新缓存</button></div>
      <section class="rd-cache-section"><header><div><b>Ultralytics 环境</b><span>上次检测：${escapeHtml(dateText(runtime.environmentMeta.updated_at))} · 来源 ${escapeHtml(runtime.environmentMeta.scan_id || '历史配置')}</span></div><button class="btn small" onclick="deepDetectResourceEnvironment()">全机深度检测</button></header>${environmentCards()}${officialModelRows()}</section>
      <section class="rd-cache-section"><header><div><b>本机模型</b><span>共 ${Number(runtime.modelMeta.total) || 0} 个 · 上次检测：${escapeHtml(dateText(runtime.modelMeta.updated_at))} · 来源 ${escapeHtml(runtime.modelMeta.scan_id || '历史缓存')}</span></div></header>${modelRows()}<footer class="rd-pager"><button class="btn mini" ${runtime.modelCursorStack.length ? '' : 'disabled'} onclick="resourceModelsPage(-1)">上一页</button><span>本页 ${runtime.models.length} 个</span><button class="btn mini" ${runtime.modelNextCursor ? '' : 'disabled'} onclick="resourceModelsPage(1)">下一页</button></footer></section>`;
  }

  async function loadEnvironmentCache() {
    const [environment, baseModels] = await Promise.all([
      request('/api/ultralytics_env'),
      request('/api/base_models')
    ]);
    runtime.environments = [...(environment?.candidates || environment?.items || [])];
    runtime.activeEnvironment = environment?.active || {};
    const activePath = String(runtime.activeEnvironment.python_path || runtime.activeEnvironment.python_executable || '').toLocaleLowerCase();
    if (activePath && !runtime.environments.some(candidate => String(candidate.python_path || candidate.python_executable || '').toLocaleLowerCase() === activePath)) runtime.environments.unshift(runtime.activeEnvironment);
    runtime.environmentMeta = environment || {};
    runtime.officialModels = (baseModels?.items || []).filter(model => model.source === 'official');
  }

  async function loadModelCache(cursor = runtime.modelCursor) {
    const query = new URLSearchParams({limit: '100'});
    if (cursor) query.set('cursor', cursor);
    const response = await request(`/api/local_models?${query}`);
    runtime.models = response?.items || [];
    runtime.modelMeta = response || {};
    runtime.modelCursor = cursor || null;
    runtime.modelNextCursor = response?.next_cursor || null;
  }

  async function refreshCache(resetModels = true) {
    const generation = ++runtime.cacheGeneration;
    if (resetModels) {
      runtime.modelCursor = null;
      runtime.modelCursorStack = [];
    }
    try {
      await Promise.all([loadEnvironmentCache(), loadModelCache(runtime.modelCursor)]);
      if (generation === runtime.cacheGeneration && getPage() === '训练资源') renderCachePanel();
    } catch (error) {
      if (generation === runtime.cacheGeneration) notify(error.message || '读取本机资源缓存失败');
    }
  }

  function enhanceResourcePage() {
    const cards = [...document.querySelectorAll('.resource-actions .quick-card')];
    const ultralyticsCard = cards.find(card => card.querySelector('.quick-title')?.textContent.includes('Ultralytics'));
    const modelsCard = cards.find(card => card.querySelector('.quick-title')?.textContent.includes('模型目录'));
    if (ultralyticsCard) {
      const row = ultralyticsCard.querySelector('.row');
      if (row) row.innerHTML = '<button class="btn primary small" onclick="detectUltra()">检测指定目录</button><button class="btn soft small" onclick="quickUltraDetect()">一键检测</button>';
      if (!ultralyticsCard.querySelector('.rd-card-note')) ultralyticsCard.insertAdjacentHTML('beforeend', '<div class="item-sub rd-card-note">环境检测与模型文件相互独立；没有 yolo11n.pt 不影响环境可用性。</div>');
    }
    if (modelsCard) {
      const oldButton = modelsCard.querySelector('button');
      oldButton?.remove();
      if (!modelsCard.querySelector('.rd-model-actions')) modelsCard.insertAdjacentHTML('beforeend', '<div class="row rd-model-actions"><button class="btn small" onclick="scanModels()">扫描指定目录</button><button class="btn soft small" onclick="scanAllModels()">全机扫描模型</button></div>');
    }
    const layout = document.querySelector('.resource-layout');
    if (layout && !document.getElementById('resourceDiscoveryCache')) layout.insertAdjacentHTML('beforeend', '<section class="panel"><div class="panel-body" id="resourceDiscoveryCache"><div class="loading">正在读取本机资源缓存…</div></div></section>');
    renderCachePanel();
  }

  function progressBody(task, kind) {
    const metrics = task.metrics || task;
    const environment = kind === 'environment';
    const taskStatus = status(task.status);
    const error = task.error?.message || task.error || '';
    return `<div class="rd-task" id="resourceDiscoveryTask" data-task-id="${escapeHtml(task.id || task.task_id || '')}">
      <div class="rd-task-state"><span class="pill ${SUCCESS_TASK_STATUSES.has(taskStatus) ? 'ok' : taskStatus === 'FAILED' ? 'err' : 'run'}">${escapeHtml(taskStatus || 'QUEUED')}</span><b>${escapeHtml(task.stage || '等待 Worker 领取')}</b></div>
      ${ACTIVE_TASK_STATUSES.has(taskStatus) ? '<div class="rd-indeterminate"><i></i></div>' : ''}
      <div class="rd-task-counts"><div><span>已扫描目录</span><b>${Number(metrics.scanned_dirs) || 0}</b></div>${environment ? `<div><span>Python 候选</span><b>${Number(metrics.python_candidates) || 0}</b></div><div><span>已验证环境</span><b>${Number(metrics.validated_environments) || 0}</b></div>` : `<div><span>发现模型</span><b>${Number(metrics.models_found) || 0}</b></div>`}<div><span>权限失败</span><b>${Number(metrics.permission_errors) || 0}</b></div></div>
      <div class="rd-current"><span>当前路径</span><code>${escapeHtml(task.current_item || metrics.current_item || '等待扫描')}</code></div>
      ${error ? `<div class="error-box422"><b>检测失败</b><span>${escapeHtml(typeof error === 'string' ? error : JSON.stringify(error))}</span></div>` : ''}
      <div class="row end"><button class="btn" onclick="closeModal()">关闭</button></div>
    </div>`;
  }

  function watchModalClose(taskId, controller) {
    const observer = new MutationObserver(() => {
      const current = document.getElementById('resourceDiscoveryTask');
      if (!current || current.dataset.taskId !== String(taskId)) controller.abort();
    });
    observer.observe(document.body, {childList: true, subtree: true});
    controller.signal.addEventListener('abort', () => observer.disconnect(), {once: true});
  }

  async function pollTask(initial, kind) {
    let task = initial;
    const taskId = task.id || task.task_id;
    if (!taskId) throw new Error('后台任务未返回 task_id');
    showModal(kind === 'environment' ? '检测本机 Ultralytics 环境' : '扫描本机模型', progressBody(task, kind), true);
    const root = document.getElementById('resourceDiscoveryTask');
    const controller = new AbortController();
    runtime.pollControllers.add(controller);
    if (root) watchModalClose(taskId, controller);
    try {
      while (!controller.signal.aborted && ACTIVE_TASK_STATUSES.has(status(task.status))) {
        await abortableDelay(1100, controller.signal);
        task = await request(`/api/resource-discovery/tasks/${encodeURIComponent(taskId)}`, {signal: controller.signal});
        const live = document.getElementById('resourceDiscoveryTask');
        if (!live || live.dataset.taskId !== String(taskId)) {
          controller.abort();
          break;
        }
        live.outerHTML = progressBody(task, kind);
      }
      if (!controller.signal.aborted) {
        if (SUCCESS_TASK_STATUSES.has(status(task.status))) {
          await refreshCache(true);
          notify(kind === 'environment' ? '环境检测完成，请确认要使用的环境' : '模型扫描完成');
        } else if (status(task.status) === 'FAILED') {
          notify(task.error?.message || task.error || '资源检测失败');
        }
      }
      return task;
    } catch (error) {
      if (error?.name !== 'AbortError') notify(error.message || '读取检测进度失败');
      return null;
    } finally {
      runtime.pollControllers.delete(controller);
      controller.abort();
    }
  }

  async function createTask(endpoint, payload, kind) {
    try {
      const task = await request(endpoint, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
      return pollTask(task, kind);
    } catch (error) {
      notify(error.message || '创建资源检测任务失败');
      return null;
    }
  }

  runtime.detectEnvironment = ({scope = 'auto', roots = []} = {}) => createTask('/api/ultralytics_env/detect', {scope, roots}, 'environment');
  runtime.scanModels = ({scope = 'directory', roots = []} = {}) => createTask('/api/local_models/scan', {scope, roots}, 'models');
  runtime.refreshCache = refreshCache;

  window.quickUltraDetect = () => runtime.detectEnvironment({scope: 'auto'});
  window.deepDetectResourceEnvironment = () => runtime.detectEnvironment({scope: 'full'});
  window.detectUltra = () => {
    const root = document.getElementById('uroot')?.value.trim() || '';
    return runtime.detectEnvironment(root ? {scope: 'fast', roots: [root]} : {scope: 'auto'});
  };
  window.scanModels = () => {
    const root = document.getElementById('scanRoot')?.value.trim() || '';
    if (!root) return notify('请先填写要扫描的模型目录');
    return runtime.scanModels({scope: 'directory', roots: [root]});
  };
  window.scanAllModels = () => runtime.scanModels({scope: 'full'});
  window.refreshResourceDiscoveryCache = () => refreshCache(true);
  window.selectResourceEnvironment = async index => {
    const candidate = runtime.environments[Number(index)];
    if (!candidate || status(candidate.status) !== 'AVAILABLE') return notify('该环境不可用，无法启用');
    try {
      await request('/api/ultralytics_env/select', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({python_path: candidate.python_path || candidate.python_executable, root: candidate.root || '', yolo_path: candidate.yolo_path || ''})});
      notify('已启用所选 Ultralytics 环境');
      await refreshApplication();
      await refreshCache(true);
    } catch (error) {
      notify(error.message || '启用环境失败');
    }
  };
  window.resourceModelsPage = async direction => {
    if (Number(direction) > 0 && runtime.modelNextCursor) {
      runtime.modelCursorStack.push(runtime.modelCursor);
      runtime.modelCursor = runtime.modelNextCursor;
    } else if (Number(direction) < 0 && runtime.modelCursorStack.length) {
      runtime.modelCursor = runtime.modelCursorStack.pop() || null;
    } else return;
    try {
      await loadModelCache(runtime.modelCursor);
      renderCachePanel();
    } catch (error) {
      notify(error.message || '读取模型缓存失败');
    }
  };

  window.renderResources = function resourceDiscoveryRenderResources() {
    previousRenderResources?.();
    enhanceResourcePage();
    refreshCache(true);
  };
  runtime.render = window.renderResources;
  window.ResourceDiscoveryRuntime = runtime;
  if (getPage() === '训练资源') window.renderResources();
  return runtime;
}

import {isTaskActive, taskProgress} from './task-poller.js?v=422001';

export function storageImportProgressText(task = {}) {
  const status = String(task.status || '').toUpperCase();
  const stage = String(task.phase || task.stage || status || 'SCANNING');
  const current = String(task.current_item || '').trim();
  const {percent} = taskProgress(task);
  const queuePosition = Number(task.resource_queue_position || 0);
  const priority = Number(task.priority || 0);
  const worker = String(task.worker_id || '').trim();
  const waitReason = String(task.resource_wait_reason || '').trim();
  if (status === 'WAITING_RESOURCE') {
    return ['等待资源', queuePosition > 0 ? `队列第 ${queuePosition} 位` : '', waitReason].filter(Boolean).join(' · ');
  }
  if (status === 'QUEUED') {
    return ['排队中', queuePosition > 0 ? `队列第 ${queuePosition} 位` : '', priority > 0 ? `优先级 ${priority}` : ''].filter(Boolean).join(' · ');
  }
  if (stage === 'FINALIZING') return percent > 0 ? `正在整理扫描结果 · ${percent.toFixed(0)}%` : '正在整理扫描结果';
  const parts = [stage];
  if (percent > 0) parts.push(`${percent.toFixed(0)}%`);
  if (current) parts.push(current);
  if (worker) parts.push(`执行节点 ${worker}`);
  if (parts.length === 1) parts.push('正在扫描对象');
  return parts.join(' · ');
}

async function responseJson(response) {
  if (response.ok) return response.json();
  const text = await response.text();
  let body = {};
  try { body = JSON.parse(text); } catch (_error) { body = {detail: text}; }
  throw new Error(body.message || body.detail || `HTTP ${response.status}`);
}

export function installStorageImportProgressRuntime() {
  if (typeof window === 'undefined' || typeof document === 'undefined') return false;
  if (window.__storageImportProgressRuntimeInstalled) return true;
  if (typeof window.startStorageImport61 !== 'function') return false;

  window.__storageImportProgressRuntimeInstalled = true;

  window.startStorageImport61 = async function truthfulStorageImportScan() {
    const status = document.getElementById('si61Status');
    const source = document.getElementById('si61Source')?.value || '';
    if (!source) {
      window.toast?.('请选择存储源');
      return;
    }
    const projectId = String(state?.project?.id || '');
    if (!projectId) {
      window.toast?.('当前项目不可用');
      return;
    }

    try {
      const body = {
        storage_source_id: source,
        prefix: document.getElementById('si61Prefix')?.value || '',
        recursive: document.getElementById('si61Recursive')?.checked !== false,
      };
      const task = await responseJson(await fetch(
        `/api/v61/projects/${encodeURIComponent(projectId)}/storage-imports/scan`,
        {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(body),
        },
      ));
      if (status) status.textContent = '扫描任务已进入 Storage Worker 队列';

      let current = task;
      while (isTaskActive(current.status)) {
        await new Promise(resolve => setTimeout(resolve, 1200));
        // Closing the dialog only stops browser polling; the durable worker task keeps running.
        if (status && !status.isConnected) return;
        current = await responseJson(await fetch(
          `/api/v62/projects/${encodeURIComponent(projectId)}/tasks/${encodeURIComponent(task.task_id)}`,
        ));
        if (status) status.textContent = storageImportProgressText(current);
      }

      if (String(current.status || '').toUpperCase() !== 'SUCCEEDED') {
        throw new Error(current.error || `扫描未成功：${current.status || 'UNKNOWN'}`);
      }
      const completed = await responseJson(await fetch(
        `/api/v61/projects/${encodeURIComponent(projectId)}/storage-imports/${encodeURIComponent(task.task_id)}`,
      ));
      const result = completed.result || {};
      const scanned = Number(result.scanned_files ?? result.scanned ?? 0);
      const importable = Number(result.importable_images ?? result.importable ?? 0);
      const duplicates = Number(result.duplicates ?? 0);
      const failed = Number(result.failed ?? 0);
      if (status) {
        status.innerHTML = `扫描完成：发现 <b>${scanned}</b> 个对象，可导入 <b>${importable}</b> 张，重复 <b>${duplicates}</b> 张，失败 <b>${failed}</b> 张。 <button class="btn mini primary" onclick="confirmStorageImport61('${String(task.task_id).replace(/'/g, '')}')">确认建立索引</button>`;
      }
    } catch (error) {
      if (status) {
        const message = String(error?.message || error || '扫描失败')
          .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        status.innerHTML = `<span class="err">${message}</span>`;
      }
    }
  };
  return true;
}

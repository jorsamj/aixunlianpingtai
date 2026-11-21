import {computed,onBeforeUnmount,reactive} from 'vue';
import {
  createMaterialDeletion,estimateMaterialDeletion,getMaterialBatch,
  getMaterialBatchResults,
} from '../api/material-batches';
import type {MaterialBatchEstimate,MaterialBatchTask} from '../api/material-batches';

const TERMINAL = new Set([
  'SUCCEEDED', 'PARTIAL_SUCCESS', 'FAILED', 'CANCELLED',
  'BLOCKED_BY_ENVIRONMENT', 'BLOCKED_BY_HARDWARE',
]);
const ACTIVE = new Set(['QUEUED', 'WAITING_RESOURCE', 'RUNNING', 'CANCEL_REQUESTED']);
const STATUS_LABEL: Record<string, string> = {
  QUEUED: '排队中', WAITING_RESOURCE: '等待资源', RUNNING: '处理中',
  CANCEL_REQUESTED: '正在取消', SUCCEEDED: '已完成', PARTIAL_SUCCESS: '部分成功',
  FAILED: '失败', CANCELLED: '已取消', BLOCKED_BY_ENVIRONMENT: '环境阻断',
  BLOCKED_BY_HARDWARE: '硬件阻断',
};
type DeleteMode = 'single' | 'selected';
interface RecoveryRecord {
  project_id: string; plan_id: string; operation: 'DELETE_INDEX';
  mode: DeleteMode; image_id?: string; image_count: number;
}
export interface DeleteSettlement {
  deletedIds: string[]; failedIds: string[]; terminal: string; unknown: boolean;
}
function message(cause: unknown) {
  return cause instanceof Error ? cause.message : '操作失败';
}

export function useMaterialDelete(options: {
  enabled: () => boolean;
  projectId: () => string;
  actorKey: () => string;
  onSettled: (result: DeleteSettlement) => Promise<void> | void;
}) {
  const state = reactive({
    dialog: false, busy: false, estimate: null as MaterialBatchEstimate | null,
    task: null as MaterialBatchTask | null, targetId: '', targetIds: [] as string[],
    mode: 'single' as DeleteMode, error: '', notice: '', unknown: false,
    pendingPlanId: '', pendingImageId: '', pendingCount: 0,
  });
  let poll: number | undefined;

  const storageKey = () => 'ai-material-delete:v1:' + JSON.stringify([
    options.actorKey(), options.projectId(),
  ]);
  function readRecord(): RecoveryRecord | null {
    try {
      const value = JSON.parse(localStorage.getItem(storageKey()) || 'null');
      if (!value || value.operation !== 'DELETE_INDEX'
          || typeof value.plan_id !== 'string' || value.project_id !== options.projectId())
        return null;
      const mode: DeleteMode = value.mode === 'selected' ? 'selected' : 'single';
      if (mode === 'single' && typeof value.image_id !== 'string') return null;
      return {
        project_id: value.project_id, plan_id: value.plan_id, operation: 'DELETE_INDEX',
        mode, image_id: typeof value.image_id === 'string' ? value.image_id : undefined,
        image_count: Math.max(1, Number(value.image_count) || 1),
      };
    } catch { return null; }
  }
  function syncPending() {
    const record = readRecord();
    state.pendingPlanId = record?.plan_id || '';
    state.pendingImageId = record?.image_id || '';
    state.pendingCount = record?.image_count || 0;
  }
  function writeRecord(planId: string, mode: DeleteMode, count: number, imageId?: string): boolean {
    const current = readRecord();
    if (current && current.plan_id !== planId) return false;
    try {
      localStorage.setItem(storageKey(), JSON.stringify({
        project_id: options.projectId(), plan_id: planId, operation: 'DELETE_INDEX',
        mode, image_id: mode === 'single' ? imageId : undefined,
        image_count: Math.max(1, count),
      }));
      syncPending();
      return true;
    } catch { return false; }
  }
  function clearRecord() {
    try { localStorage.removeItem(storageKey()); } catch { /* storage unavailable */ }
    syncPending();
  }
  function stopPoll() {
    if (poll !== undefined) { window.clearInterval(poll); poll = undefined; }
  }
  function startPoll() {
    if (poll !== undefined) return;
    poll = window.setInterval(() => { void refresh(); }, 2000);
  }
  syncPending();

  const statusLabel = computed(() => state.task
    ? STATUS_LABEL[state.task.status] || state.task.status : '');
  const terminal = computed(() => !!state.task && TERMINAL.has(state.task.status));
  const pending = computed(() => !!state.pendingPlanId || state.unknown
    || (!!state.task && !terminal.value));

  async function refresh() {
    if (!options.enabled()) return;
    const project = options.projectId();
    const record = readRecord();
    const taskId = state.task?.task_id || record?.plan_id;
    if (!project || !taskId) return;
    try {
      const task = await getMaterialBatch(project, taskId, new AbortController().signal);
      if (task.project_id !== project || task.operation !== 'DELETE_INDEX'
          || task.task_id !== taskId) {
        stopPoll(); state.error = '删除任务身份不一致，已停止刷新'; return;
      }
      state.task = task; state.unknown = false;
      if (TERMINAL.has(task.status)) { stopPoll(); await finish(task); }
    } catch (cause) {
      const status = (cause as {httpStatus?: number}).httpStatus;
      if (status === 404) { state.unknown = true; return; }
      if (!state.task) state.error = message(cause);
    }
  }

  async function readResults(task: MaterialBatchTask) {
    const succeeded = new Set<string>(), failed = new Set<string>();
    let seen = 0, cursor: string | null = null, pages = 0;
    do {
      const page = await getMaterialBatchResults(
        options.projectId(), task.task_id, new AbortController().signal, cursor,
      );
      for (const row of page.items || []) {
        seen += 1;
        if (row.item_state === 'succeeded') succeeded.add(row.image_id);
        else failed.add(row.image_id);
      }
      for (const id of page.succeeded_image_ids || []) succeeded.add(id);
      cursor = page.next_cursor || null;
      pages += 1;
      if (pages > 500) break;
    } while (cursor);
    return {succeeded, failed, seen, truncated: pages > 500};
  }

  async function finish(task: MaterialBatchTask) {
    const record = readRecord();
    const mode: DeleteMode = record?.mode || state.mode;
    const imageId = record?.image_id || state.targetId;
    const required = Math.max(1, Number(record?.image_count) || state.estimate?.count
      || Number(task.total) || 1);
    let results;
    try {
      results = await readResults(task);
    } catch {
      state.unknown = true;
      state.notice = '任务已到终态，但逐项结果暂不可读；原删除身份已保留。';
      return;
    }
    const deletedIds = [...results.succeeded];
    const failedIds = [...results.failed];
    if (results.truncated || results.seen < required) {
      state.unknown = true;
      state.notice = '逐项结果尚未完整覆盖本次范围，删除结果未证明；原删除身份已保留。';
      return;
    }
    if (mode === 'single' && !results.succeeded.has(imageId) && !results.failed.has(imageId)) {
      state.unknown = true;
      state.notice = '逐项结果未包含该素材，删除结果尚未证明；原删除身份已保留。';
      return;
    }
    clearRecord();
    state.unknown = false;
    const succeededCount = deletedIds.length;
    const failedCount = failedIds.length;
    if (task.status === 'SUCCEEDED' && failedCount === 0) {
      state.notice = mode === 'single'
        ? '素材删除成功（原图字节保留）。'
        : `已删除 ${succeededCount} 张素材（原图字节保留）。`;
      state.dialog = false;
      await options.onSettled({deletedIds, failedIds, terminal: task.status, unknown: false});
      return;
    }
    state.notice = task.status === 'PARTIAL_SUCCESS'
      ? `部分成功：已删除 ${succeededCount} 张，失败 ${failedCount} 张；未确认的不会当作已删除。`
      : `任务终态：${STATUS_LABEL[task.status] || task.status}；已证明删除 ${succeededCount} 张、失败 ${failedCount} 张。`;
    await options.onSettled({deletedIds, failedIds, terminal: task.status, unknown: false});
  }

  async function verifyResults() {
    if (!state.task) return;
    state.busy = true; state.error = '';
    try { await finish(state.task); }
    catch (cause) { state.error = message(cause); }
    finally { state.busy = false; }
  }

  function openTask() {
    state.dialog = true;
    if (state.pendingImageId) state.targetId = state.pendingImageId;
  }

  async function prepareMany(ids: string[], mode: DeleteMode = 'selected') {
    if (!options.enabled() || state.busy) return;
    const unique = [...new Set(ids.filter(Boolean))];
    if (!unique.length) return;
    syncPending();
    if (state.pendingPlanId) {
      state.targetId = state.pendingImageId || (mode === 'single' ? unique[0] : '');
      state.notice = '存在未完成的删除任务，正在核验原任务；请先处理该任务。';
      state.dialog = true;
      state.unknown = true;
      await refresh();
      return;
    }
    if (state.unknown || (state.task && ACTIVE.has(state.task.status))) {
      state.dialog = true;
      return;
    }
    state.busy = true; state.error = ''; state.notice = ''; state.task = null;
    state.unknown = false; state.mode = mode;
    state.targetIds = unique; state.targetId = unique[0];
    try {
      const estimate = await estimateMaterialDeletion(
        options.projectId(), unique, new AbortController().signal,
      );
      if (!estimate.supported || !estimate.deletion_preview || estimate.count < 1)
        throw new Error(estimate.message || '当前素材暂不支持删除');
      if (mode === 'single' && estimate.count !== 1)
        throw new Error('单张删除范围与预检结果不一致');
      state.estimate = estimate;
      state.dialog = true;
    } catch (cause) {
      state.error = message(cause);
    } finally { state.busy = false; }
  }
  function prepare(imageId: string) { return prepareMany([imageId], 'single'); }

  async function confirm() {
    const estimate = state.estimate;
    if (!estimate?.deletion_preview || state.busy || state.task || state.unknown
        || state.pendingPlanId) return;
    const preview = estimate.deletion_preview;
    state.busy = true; state.error = ''; state.notice = '';
    if (!writeRecord(preview.plan_id, state.mode, estimate.count,
      state.mode === 'single' ? state.targetId : undefined)) {
      state.busy = false;
      state.error = '浏览器无法保存删除计划身份，已停止提交；请允许站点存储后重试。';
      return;
    }
    try {
      const task = await createMaterialDeletion(
        options.projectId(), estimate, new AbortController().signal,
      );
      if (task.project_id !== options.projectId() || task.operation !== 'DELETE_INDEX'
          || task.task_id !== preview.plan_id) {
        state.unknown = true;
        state.notice = '创建回执身份与删除计划不一致，已停止采信；原计划身份已保留。';
        startPoll();
        return;
      }
      state.task = task; state.unknown = false; startPoll();
    } catch (cause) {
      const status = (cause as {httpStatus?: number}).httpStatus;
      if (status !== undefined && status < 500) {
        state.error = message(cause); clearRecord(); return;
      }
      state.unknown = true;
      state.notice = '创建结果未确认；已保留原计划身份，只查询、不重复提交。';
      try {
        const task = await getMaterialBatch(
          options.projectId(), preview.plan_id, new AbortController().signal,
        );
        if (task.project_id === options.projectId() && task.operation === 'DELETE_INDEX'
            && task.task_id === preview.plan_id) {
          state.task = task; state.unknown = false;
        }
      } catch { /* keep unknown; polling only GETs the original plan */ }
      startPoll();
    } finally { state.busy = false; }
  }

  async function recover() {
    if (!options.enabled()) return;
    const record = readRecord();
    if (!record) { syncPending(); return; }
    state.mode = record.mode;
    state.pendingCount = record.image_count;
    state.targetId = record.image_id || '';
    state.unknown = true;
    state.notice = '正在核验上次未完成的删除任务…';
    await refresh();
    if (!state.task && !state.error) {
      state.notice = '原删除任务暂不可读；保持待确认，不会重复提交。';
    }
    startPoll();
  }

  function close() { if (!state.busy) state.dialog = false; }
  onBeforeUnmount(stopPoll);
  return {
    state, statusLabel, terminal, pending, prepare, prepareMany, confirm, recover,
    verifyResults, openTask, close, refresh,
  };
}

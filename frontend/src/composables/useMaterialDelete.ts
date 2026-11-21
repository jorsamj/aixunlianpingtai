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
const STATUS_LABEL: Record<string, string> = {
  QUEUED: '排队中', WAITING_RESOURCE: '等待资源', RUNNING: '处理中',
  CANCEL_REQUESTED: '正在取消', SUCCEEDED: '已完成', PARTIAL_SUCCESS: '部分成功',
  FAILED: '失败', CANCELLED: '已取消', BLOCKED_BY_ENVIRONMENT: '环境阻断',
  BLOCKED_BY_HARDWARE: '硬件阻断',
};
interface RecoveryRecord {
  project_id: string; image_id: string; plan_id: string; operation: 'DELETE_INDEX';
}

function message(cause: unknown) {
  return cause instanceof Error ? cause.message : '操作失败';
}

export function useMaterialDelete(options: {
  enabled: () => boolean;
  projectId: () => string;
  actorKey: () => string;
  onSettled: () => Promise<void> | void;
}) {
  const state = reactive({
    dialog: false, busy: false, estimate: null as MaterialBatchEstimate | null,
    task: null as MaterialBatchTask | null, targetId: '', error: '', notice: '',
    unknown: false,
  });
  let poll: number | undefined;

  const storageKey = () => 'ai-material-delete:v1:' + JSON.stringify([
    options.actorKey(), options.projectId(),
  ]);
  function readRecord(): RecoveryRecord | null {
    try {
      const value = JSON.parse(localStorage.getItem(storageKey()) || 'null');
      if (!value || value.operation !== 'DELETE_INDEX'
          || typeof value.plan_id !== 'string' || typeof value.image_id !== 'string'
          || value.project_id !== options.projectId()) return null;
      return value;
    } catch { return null; }
  }
  function writeRecord(planId: string, imageId: string) {
    localStorage.setItem(storageKey(), JSON.stringify({
      project_id: options.projectId(), image_id: imageId,
      plan_id: planId, operation: 'DELETE_INDEX',
    }));
  }
  function clearRecord() {
    try { localStorage.removeItem(storageKey()); } catch { /* storage unavailable */ }
  }
  function stopPoll() {
    if (poll !== undefined) { window.clearInterval(poll); poll = undefined; }
  }
  function startPoll() {
    if (poll !== undefined) return;
    poll = window.setInterval(() => { void refresh(); }, 2000);
  }

  const statusLabel = computed(() => state.task
    ? STATUS_LABEL[state.task.status] || state.task.status : '');
  const terminal = computed(() => !!state.task && TERMINAL.has(state.task.status));

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

  async function finish(task: MaterialBatchTask) {
    const record = readRecord();
    const imageId = record?.image_id || state.targetId;
    let deleted = false;
    try {
      const results = await getMaterialBatchResults(
        options.projectId(), task.task_id, new AbortController().signal,
      );
      const item = results.items?.find(row => row.image_id === imageId);
      deleted = item
        ? item.item_state === 'succeeded'
        : (results.succeeded_image_ids || []).includes(imageId);
    } catch {
      state.unknown = true;
      state.notice = '任务已到终态，但逐项结果暂不可读；请稍后刷新核实。';
      clearRecord();
      return;
    }
    clearRecord();
    if (task.status === 'SUCCEEDED' && deleted) {
      state.notice = '素材删除成功（原图字节保留）。';
      state.dialog = false;
      await options.onSettled();
      return;
    }
    state.notice = task.status === 'PARTIAL_SUCCESS'
      ? '素材部分处理；请查看逐项结果，未成功的素材不会被当作已删除。'
      : `任务终态：${STATUS_LABEL[task.status] || task.status}${deleted ? '，本素材已删除' : '，本素材未确认删除'}。`;
    await options.onSettled();
  }

  async function prepare(imageId: string) {
    if (!options.enabled() || state.busy) return;
    state.busy = true; state.error = ''; state.notice = ''; state.task = null;
    state.unknown = false; state.targetId = imageId;
    try {
      const estimate = await estimateMaterialDeletion(
        options.projectId(), imageId, new AbortController().signal,
      );
      if (!estimate.supported || !estimate.deletion_preview || estimate.count !== 1)
        throw new Error(estimate.message || '当前素材暂不支持删除');
      state.estimate = estimate;
      state.dialog = true;
    } catch (cause) {
      state.error = message(cause);
    } finally { state.busy = false; }
  }

  async function confirm() {
    const estimate = state.estimate;
    if (!estimate?.deletion_preview || state.busy) return;
    const preview = estimate.deletion_preview;
    state.busy = true; state.error = ''; state.notice = '';
    writeRecord(preview.plan_id, state.targetId);
    try {
      const task = await createMaterialDeletion(
        options.projectId(), estimate, new AbortController().signal,
      );
      if (task.project_id !== options.projectId() || task.operation !== 'DELETE_INDEX')
        throw new Error('删除任务身份不一致');
      state.task = task; state.unknown = false; startPoll();
    } catch (cause) {
      const status = (cause as {httpStatus?: number}).httpStatus;
      if (status !== undefined && status < 500) {
        // The server definitively rejected this plan; no task was accepted.
        state.error = message(cause); clearRecord(); return;
      }
      state.unknown = true;
      state.notice = '创建结果未确认；已保留原计划身份，只查询、不重复提交。';
      try {
        const task = await getMaterialBatch(
          options.projectId(), preview.plan_id, new AbortController().signal,
        );
        if (task.project_id === options.projectId() && task.operation === 'DELETE_INDEX') {
          state.task = task; state.unknown = false;
        }
      } catch { /* keep unknown; polling only GETs the original plan */ }
      startPoll();
    } finally { state.busy = false; }
  }

  async function recover() {
    if (!options.enabled()) return;
    const record = readRecord();
    if (!record) return;
    state.targetId = record.image_id;
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
  return {state, statusLabel, terminal, prepare, confirm, recover, close, refresh};
}

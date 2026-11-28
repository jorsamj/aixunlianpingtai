import {computed,onBeforeUnmount,reactive} from 'vue';
import {
  createMaterialDeletion,estimateMaterialDeletion,getMaterialBatch,
  getMaterialBatchResults,
} from '../api/material-batches';
import type {MaterialBatchEstimate,MaterialBatchSelection,MaterialBatchTask} from '../api/material-batches';

const TERMINAL = new Set([
  'SUCCEEDED', 'PARTIAL_SUCCESS', 'FAILED', 'CANCELLED',
  'BLOCKED_BY_ENVIRONMENT', 'BLOCKED_BY_HARDWARE',
]);
const ACTIVE = new Set(['QUEUED', 'WAITING_RESOURCE', 'RUNNING', 'CANCEL_REQUESTED']);
const ITEM_STATES = new Set(['pending', 'running', 'succeeded', 'failed']);
const STATUS_LABEL: Record<string, string> = {
  QUEUED: '排队中', WAITING_RESOURCE: '等待资源', RUNNING: '处理中',
  CANCEL_REQUESTED: '正在取消', SUCCEEDED: '已完成', PARTIAL_SUCCESS: '部分成功',
  FAILED: '失败', CANCELLED: '已取消', BLOCKED_BY_ENVIRONMENT: '环境阻断',
  BLOCKED_BY_HARDWARE: '硬件阻断',
};
type DeleteMode = 'single' | 'selected' | 'filtered';
interface RecoveryRecord {
  project_id: string; plan_id: string; operation: 'DELETE_INDEX';
  mode: DeleteMode; image_id?: string; image_count: number; id_digest?: string;
}
export interface DeleteSettlement {
  deletedIds: string[]; failedIds: string[]; terminal: string; unknown: boolean;
}
interface ResultCounts {
  succeeded: number; failed: number; pending: number; running: number; conflict: number;
  seen: number; required: number;
}
interface ResultScan {
  succeeded: Set<string>; failed: Set<string>; pending: Set<string>; running: Set<string>;
  conflicts: Set<string>; seen: number; truncated: boolean;
}
const EMPTY_COUNTS: ResultCounts = {
  succeeded: 0, failed: 0, pending: 0, running: 0, conflict: 0, seen: 0, required: 0,
};
function message(cause: unknown) {
  return cause instanceof Error ? cause.message : '操作失败';
}
function countsText(counts: ResultCounts) {
  return `成功 ${counts.succeeded} · 失败 ${counts.failed} · 未处理 ${counts.pending}`
    + ` · 处理中 ${counts.running}`
    + (counts.conflict ? ` · 证据冲突 ${counts.conflict}` : '');
}
// Cryptographic scope proof for large selections without persisting 100k ids.
async function digestIds(ids: Iterable<string>) {
  const sorted = [...new Set(ids)].sort();
  const subtle = globalThis.crypto?.subtle;
  if (!subtle) throw new Error('当前浏览器不支持范围摘要，无法证明删除范围');
  const bytes = new TextEncoder().encode(sorted.join('\n'));
  const hash = await subtle.digest('SHA-256', bytes);
  const hex = [...new Uint8Array(hash)].map(value => value.toString(16).padStart(2, '0')).join('');
  return `sha256:${hex}:${sorted.length}`;
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
    summary: {...EMPTY_COUNTS},
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
      const rawMode = value.mode;
      if (rawMode !== 'single' && rawMode !== 'selected' && rawMode !== 'filtered')
        return null;
      const mode: DeleteMode = rawMode;
      if (mode === 'single' && typeof value.image_id !== 'string') return null;
      if (mode === 'filtered'
          && (typeof value.id_digest !== 'string' || !value.id_digest.startsWith('sha256:')))
        return null;
      return {
        project_id: value.project_id, plan_id: value.plan_id, operation: 'DELETE_INDEX',
        mode, image_id: typeof value.image_id === 'string' ? value.image_id : undefined,
        image_count: Math.max(1, Number(value.image_count) || 1),
        id_digest: typeof value.id_digest === 'string' ? value.id_digest : undefined,
      };
    } catch { return null; }
  }
  function syncPending() {
    const record = readRecord();
    state.pendingPlanId = record?.plan_id || '';
    state.pendingImageId = record?.image_id || '';
    state.pendingCount = record?.image_count || 0;
  }
  function writeRecord(
    planId: string, mode: DeleteMode, count: number, imageId?: string, idDigest?: string,
  ): boolean {
    const current = readRecord();
    if (current && current.plan_id !== planId) return false;
    try {
      localStorage.setItem(storageKey(), JSON.stringify({
        project_id: options.projectId(), plan_id: planId, operation: 'DELETE_INDEX',
        mode, image_id: mode === 'single' ? imageId : undefined,
        image_count: Math.max(1, Number(count) || 1),
        id_digest: idDigest || undefined,
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

  async function readResults(task: MaterialBatchTask, required: number): Promise<ResultScan> {
    const rows = new Map<string, string>();
    const conflicts = new Set<string>();
    const visited = new Set<string>(['']);
    let cursor: string | null = null, pages = 0, truncated = false;
    const limit = required > 5000 ? 500 : 100;
    const maxPages = Math.max(4, Math.min(2000, Math.ceil(required / limit) + 3));
    do {
      const page = await getMaterialBatchResults(
        options.projectId(), task.task_id, new AbortController().signal, cursor, limit,
      );
      pages += 1;
      for (const row of page.items || []) {
        const id = typeof row?.image_id === 'string' ? row.image_id : '';
        if (!id) { truncated = true; continue; }
        const stateValue = typeof row.item_state === 'string' ? row.item_state : '';
        if (!ITEM_STATES.has(stateValue)) { conflicts.add(id); continue; }
        const prior = rows.get(id);
        if (prior === undefined) rows.set(id, stateValue);
        else if (prior !== stateValue) conflicts.add(id);
      }
      for (const id of page.succeeded_image_ids || []) {
        if (typeof id !== 'string' || !id) { truncated = true; continue; }
        const prior = rows.get(id);
        if (prior === undefined) rows.set(id, 'succeeded');
        else if (prior !== 'succeeded') conflicts.add(id);
      }
      const next = typeof page.next_cursor === 'string' && page.next_cursor
        ? page.next_cursor : null;
      if (!next) { cursor = null; break; }
      if (next === cursor || visited.has(next) || (cursor !== null && next <= cursor)) {
        truncated = true; break;
      }
      visited.add(next);
      cursor = next;
      if (pages >= maxPages) { truncated = true; break; }
    } while (cursor !== null);
    const succeeded = new Set<string>(), failed = new Set<string>();
    const pending = new Set<string>(), running = new Set<string>();
    for (const [id, value] of rows) {
      if (conflicts.has(id)) continue;
      if (value === 'succeeded') succeeded.add(id);
      else if (value === 'failed') failed.add(id);
      else if (value === 'pending') pending.add(id);
      else if (value === 'running') running.add(id);
    }
    return {succeeded, failed, pending, running, conflicts, seen: rows.size, truncated};
  }

  async function finish(task: MaterialBatchTask) {
    const record = readRecord();
    const mode: DeleteMode = record?.mode || state.mode;
    const imageId = record?.image_id || state.targetId;
    const required = Math.max(1, Number(record?.image_count)
      || state.estimate?.count || Number(task.total) || 1);
    let results: ResultScan;
    try {
      results = await readResults(task, required);
    } catch {
      state.unknown = true;
      state.notice = '任务已到终态，但逐项结果暂不可读；原删除身份已保留。';
      return;
    }
    const counts: ResultCounts = {
      succeeded: results.succeeded.size, failed: results.failed.size,
      pending: results.pending.size, running: results.running.size,
      conflict: results.conflicts.size, seen: results.seen, required,
    };
    state.summary = counts;
    const deletedIds = [...results.succeeded];
    const failedIds = [...results.failed];
    const resultIds = [...results.succeeded, ...results.failed, ...results.pending,
      ...results.running, ...results.conflicts];
    if (results.seen > required) {
      state.unknown = true;
      state.notice = '逐项结果包含预检冻结范围之外的素材，身份异常；未执行本地清理，原删除身份已保留。';
      return;
    }
    if (results.truncated || results.seen !== required) {
      state.unknown = true;
      state.notice = `逐项结果尚未完整覆盖本次范围（已读 ${results.seen} / 应有 ${required}），`
        + '删除结果未证明；原删除身份已保留。';
      return;
    }
    if (record?.id_digest?.startsWith('sha256:')) {
      let proven = '';
      try { proven = await digestIds(resultIds); }
      catch {
        state.unknown = true;
        state.notice = '无法计算删除范围摘要，删除结果未证明；原删除身份已保留。';
        return;
      }
      if (proven !== record.id_digest) {
        state.unknown = true;
        state.notice = '逐项结果与预检冻结范围不一致，身份异常；未执行本地清理，原删除身份已保留。';
        return;
      }
    } else if (Number(record?.image_count) > 500) {
      // A pre-digest 501+ record may contain only a truncated image_ids list.
      // It cannot prove the frozen set and must be re-prechecked.
      state.unknown = true;
      state.notice = '旧版删除恢复记录缺少完整范围摘要，无法证明本次范围；请重新预检后再提交，原计划身份已保留。';
      return;
    }
    if (results.conflicts.size) {
      state.unknown = true;
      state.notice = `逐项结果存在冲突或未知状态（${countsText(counts)}）；`
        + '删除结果未证明，原删除身份已保留。';
      return;
    }
    if (results.pending.size || results.running.size) {
      state.unknown = true;
      state.notice = `逐项结果仍有未处理/处理中素材（${countsText(counts)}），不能当作已删除或失败；`
        + '已证明成功的素材会从选择中移除，原删除身份保留待核验。';
      if (deletedIds.length)
        await options.onSettled({deletedIds, failedIds, terminal: task.status, unknown: true});
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
      ? `部分成功：已删除 ${succeededCount} 张，失败 ${failedCount} 张；`
        + '只有成功项从选择中移除，失败项保持可见。'
      : `任务终态：${STATUS_LABEL[task.status] || task.status}；`
        + `已证明删除 ${succeededCount} 张、失败 ${failedCount} 张。`;
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
    state.unknown = false; state.mode = mode; state.summary = {...EMPTY_COUNTS};
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

  function canonicalSelection(value: MaterialBatchSelection) {
    const normalize = (item: unknown): unknown => {
      if (Array.isArray(item)) return item.map(normalize).sort();
      if (item && typeof item === 'object') return Object.fromEntries(
        Object.entries(item as Record<string, unknown>)
          .filter(([, entry]) => entry !== '' && entry !== null && entry !== undefined)
          .sort(([left], [right]) => left.localeCompare(right))
          .map(([key, entry]) => [key, normalize(entry)]),
      );
      return item;
    };
    return JSON.stringify({
      scope: value.scope,
      filters: normalize(value.filters || {}),
      excluded: normalize(value.excluded_image_ids || []),
    });
  }

  async function prepareFiltered(selection: MaterialBatchSelection) {
    if (!options.enabled() || state.busy) return;
    if (selection.scope !== 'FILTERED') {
      state.error = '全选删除必须使用服务端筛选范围';
      return;
    }
    if ((selection.excluded_image_ids?.length || 0) > 500) {
      state.error = '本次排除超过 500 张，请缩小排除范围后重新预检';
      return;
    }
    syncPending();
    if (state.pendingPlanId) {
      state.notice = '存在未完成的删除任务，正在核验原任务；请先处理该任务。';
      state.dialog = true; state.unknown = true;
      await refresh();
      return;
    }
    if (state.unknown || (state.task && ACTIVE.has(state.task.status))) {
      state.dialog = true;
      return;
    }
    state.busy = true; state.error = ''; state.notice = ''; state.task = null;
    state.unknown = false; state.mode = 'filtered'; state.summary = {...EMPTY_COUNTS};
    state.targetIds = []; state.targetId = '';
    try {
      const estimate = await estimateMaterialDeletion(
        options.projectId(), selection, new AbortController().signal,
      );
      if (!estimate.supported || !estimate.deletion_preview || estimate.count < 1)
        throw new Error(estimate.message || '当前筛选范围暂不支持删除');
      if (estimate.selection_spec?.scope !== 'FILTERED'
          || !estimate.deletion_preview.selection_digest)
        throw new Error('全选删除预检身份不完整，请重新预检');
      if (canonicalSelection(selection) !== canonicalSelection(estimate.selection_spec))
        throw new Error('预检返回的筛选或排除范围与本次请求不一致，请重新预检');
      const previewCount = Number(estimate.deletion_preview.delete_count
        ?? estimate.deletion_preview.selected_count ?? -1);
      const digestCount = Number(estimate.deletion_preview.selection_digest.split(':').at(-1));
      if (previewCount !== estimate.count || digestCount !== estimate.count)
        throw new Error('预检数量与冻结集合摘要不一致，请重新预检');
      state.estimate = estimate;
      state.dialog = true;
    } catch (cause) {
      state.error = message(cause);
    } finally { state.busy = false; }
  }

  async function confirm() {
    const estimate = state.estimate;
    if (!estimate?.deletion_preview || state.busy || state.task || state.unknown
        || state.pendingPlanId) return;
    const preview = estimate.deletion_preview;
    const filtered = estimate.selection_spec?.scope === 'FILTERED';
    const scopeIds = estimate.selection_spec?.scope === 'SELECTED'
      ? [...new Set(estimate.selection_spec.image_ids || [])] : [];
    const targets = [...new Set(state.targetIds)];
    let idDigest = '';
    if (filtered) {
      if (state.mode !== 'filtered' || estimate.count < 1
          || !preview.selection_digest
          || !preview.selection_digest.startsWith('sha256:')) {
        state.error = '全选删除的冻结范围身份不完整，已停止提交；请重新预检。';
        return;
      }
      idDigest = preview.selection_digest;
    } else {
      const frozen = new Set(scopeIds);
      if (!scopeIds.length || estimate.count !== targets.length
          || frozen.size !== targets.length || targets.some(id => !frozen.has(id))) {
        state.error = '预检返回的选择范围与当前选择不一致，已停止提交；请重新预检。';
        return;
      }
      try { idDigest = await digestIds(scopeIds); }
      catch (cause) {
        state.busy = false;
        state.error = message(cause);
        return;
      }
    }
    state.busy = true; state.error = ''; state.notice = '';
    if (!writeRecord(preview.plan_id, state.mode, estimate.count,
      state.mode === 'single' ? state.targetId : undefined, idDigest)) {
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
    state, statusLabel, terminal, pending, prepare, prepareMany, prepareFiltered, confirm, recover,
    verifyResults, openTask, close, refresh,
  };
}

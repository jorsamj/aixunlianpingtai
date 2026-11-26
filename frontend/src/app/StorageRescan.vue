<script setup lang="ts">
import {computed, onMounted, onUnmounted, reactive, ref} from 'vue';
import {request} from './http';
import {useWorkspace} from './main';
import {storageError, storageResponseUnknown, type StorageSource} from './storage-management';

const {projectId, source, legacy} = defineProps<{projectId: string; source: StorageSource; legacy: string}>();
const emit = defineEmits<{close: []}>();
const scope = new AbortController();
const root = `/api/v61/projects/${encodeURIComponent(projectId)}`;
const creation = `${root}/storage-sources/${encodeURIComponent(source.id)}/rescans`;
const legacyKey = `mc_storage_rescan_${projectId}_${source.id}`;
const pendingKey = 'storage-rescan-create:' + JSON.stringify([useWorkspace().actorKey, projectId, source.id]);
const taskId = ref('');
const createUnknown = ref(false);
try {
  taskId.value = localStorage.getItem(legacyKey) || '';
  createUnknown.value = sessionStorage.getItem(pendingKey) === 'pending';
} catch {
  createUnknown.value = true;
}
const readError = ref('');
const error = ref('');
const busy = ref(false);
const reading = ref(false);
const writeUnknown = ref(false);
type ScanFormat = 'images' | 'yolo' | 'coco' | 'voc';
type Mode = 'local' | 'agent';
interface ScanTask {
  task_id: string; project_id: string; status: string; stage?: string; accepted?: boolean | null;
  execution_mode: Mode; import_format: ScanFormat; worker_id?: string; error?: unknown;
  counts?: Record<string, number>; examples?: Record<string, string[]>;
  annotation_counts?: Record<string, number>; annotation_examples?: Record<string, string[]>;
  applied?: number; annotation_applied?: number;
}
interface Preflight {
  local_available: boolean; agent_available: boolean;
  local_supported_formats: ScanFormat[]; agent_supported_formats: ScanFormat[];
  eligible_nodes: {node_id: string; display_name?: string}[];
}
const task = ref<ScanTask>();
const preflight = ref<Preflight>();
const preflightLoading = ref(false);
const preflightError = ref('');
const form = reactive<{mode: Mode; format: ScanFormat; yaml: string}>({mode: 'local', format: 'images', yaml: ''});
const policy = reactive({newImages: true, missing: true, changed: true});
const terminal = new Set(['SUCCEEDED', 'PARTIAL_SUCCESS', 'FAILED', 'CANCELLED', 'BLOCKED_BY_ENVIRONMENT', 'BLOCKED_BY_HARDWARE']);
const completion = computed(() => !!task.value && terminal.has(task.value.status));
// Only a task that actually applied images or annotations has collected results;
// a failed or cancelled task must not be presented as an import result.
const collected = computed(() => {
  const current = task.value;
  if (!current || !['SUCCEEDED', 'PARTIAL_SUCCESS'].includes(String(current.status))) return false;
  const applied = Number(current.applied ?? 0);
  const annotations = Number(current.annotation_applied ?? 0);
  return (Number.isFinite(applied) && applied > 0) || (Number.isFinite(annotations) && annotations > 0);
});
const waiting = computed(() => task.value?.status === 'AWAITING_CONFIRMATION' && task.value.accepted !== true);
const formats = computed(() => (form.mode === 'agent' ? preflight.value?.agent_supported_formats : preflight.value?.local_supported_formats) || []);
const canStart = computed(() => !!preflight.value && (form.mode === 'agent' ? preflight.value.agent_available : preflight.value.local_available)
  && formats.value.includes(form.format) && !createUnknown.value && (!taskId.value || completion.value));
const canCancel = computed(() => !!task.value && !completion.value && task.value.status !== 'CANCEL_REQUESTED');
const formatLabels: Record<ScanFormat, string> = {images: '仅图片', yolo: '图片 + YOLO 标注', coco: '图片 + COCO 标注', voc: '图片 + Pascal VOC 标注'};
const statusLabels: Record<string, string> = {
  QUEUED: '排队中', WAITING_RESOURCE: '等待执行资源', RUNNING: '执行中', AWAITING_CONFIRMATION: '待确认',
  SUCCEEDED: '已完成', PARTIAL_SUCCESS: '部分完成', FAILED: '失败', CANCELLED: '已取消',
  CANCEL_REQUESTED: '正在取消', BLOCKED_BY_ENVIRONMENT: '环境阻塞', BLOCKED_BY_HARDWARE: '硬件阻塞',
};
const countLabels: Record<string, string> = {
  NEW: '新增图片', MISSING: '缺失图片', CHANGED: '变化图片', UNCHANGED: '未变图片', INVALID: '异常图片', SKIPPED: '跳过',
  ANNOTATION_NEW: '新增标注', ANNOTATION_CHANGED: '标注变化', ANNOTATION_REMOVED: '标注缺失',
  ANNOTATION_UNCHANGED: '标注未变', ANNOTATION_CONFLICT: '标注冲突', ANNOTATION_INVALID: '标注异常',
};
const counts = computed(() => Object.entries({...task.value?.counts, ...task.value?.annotation_counts}));
const examples = computed(() => Object.entries({...task.value?.examples, ...task.value?.annotation_examples}).filter(([, items]) => items.length));
const endpoint = () => `${root}/storage-rescans/${encodeURIComponent(taskId.value)}`;
let timer: number | undefined;

function ensureTask(result: ScanTask, expected?: string) {
  if (!/^[a-f0-9]{12}$/.test(result?.task_id) || result.project_id !== projectId || (expected && result.task_id !== expected)) {
    throw new Error('Unverified scan task identity');
  }
  return result;
}
function schedule() {
  window.clearTimeout(timer);
  if (!scope.signal.aborted && !document.hidden && !busy.value && task.value && !completion.value && !waiting.value) {
    timer = window.setTimeout(() => void readTask(), 2400);
  }
}
async function readTask() {
  if (!taskId.value || reading.value) return;
  const expected = taskId.value;
  reading.value = true;
  readError.value = '';
  try {
    const result = ensureTask(await request<ScanTask>(endpoint(), {signal: scope.signal}), expected);
    if (!scope.signal.aborted && taskId.value === expected) task.value = result;
  } catch (cause) {
    if (!scope.signal.aborted) readError.value = storageError(cause, '读取扫描任务失败');
  } finally {
    reading.value = false;
    if (!readError.value) schedule();
  }
}
function syncFormat() {
  if (!formats.value.includes(form.format)) form.format = 'images';
}
async function readPreflight() {
  if (preflightLoading.value) return;
  preflightLoading.value = true;
  preflightError.value = '';
  try {
    preflight.value = await request<Preflight>(creation + '/preflight', {signal: scope.signal});
    if (form.mode === 'agent' && !preflight.value.agent_available) form.mode = 'local';
    syncFormat();
  } catch (cause) {
    preflight.value = undefined;
    if (!scope.signal.aborted) preflightError.value = storageError(cause, '读取可用扫描资源失败');
  } finally {
    preflightLoading.value = false;
  }
}
async function start() {
  if (!canStart.value || busy.value || reading.value) return;
  busy.value = true;
  error.value = '';
  let sent = false;
  try {
    sessionStorage.setItem(pendingKey, 'pending');
    sent = true;
    const body = {execution_mode: form.mode, import_format: form.format, dataset_yaml: form.format === 'yolo' ? form.yaml.trim() : ''};
    const result = ensureTask(await request<ScanTask>(creation, {method: 'POST', body: JSON.stringify(body)}));
    taskId.value = result.task_id;
    task.value = result;
    localStorage.setItem(legacyKey, result.task_id);
    sessionStorage.removeItem(pendingKey);
    Object.assign(policy, {newImages: true, missing: true, changed: true});
    writeUnknown.value = false;
  } catch (cause) {
    createUnknown.value = !sent || storageResponseUnknown(cause);
    if (sent && !createUnknown.value) sessionStorage.removeItem(pendingKey);
    error.value = createUnknown.value
      ? '任务提交结果无法核实。原扫描接口无按请求恢复入口，当前标签页已暂停重复提交。'
      : storageError(cause, '创建扫描任务失败');
  } finally {
    busy.value = false;
    schedule();
  }
}
async function changeTask(action: 'confirm' | 'cancel') {
  if (busy.value || reading.value || readError.value || writeUnknown.value) return;
  if (action === 'confirm' && (!waiting.value || task.value?.import_format !== 'images')) return;
  if (action === 'cancel' && !canCancel.value) return;
  busy.value = true;
  error.value = '';
  window.clearTimeout(timer);
  const body = action === 'confirm' ? JSON.stringify({
    new: policy.newImages ? 'import' : 'ignore',
    missing: policy.missing ? 'mark_unavailable' : 'ignore',
    changed: policy.changed ? 'update' : 'ignore',
  }) : undefined;
  try {
    task.value = ensureTask(await request<ScanTask>(endpoint() + '/' + action, {method: 'POST', body}), taskId.value);
  } catch (cause) {
    writeUnknown.value = storageResponseUnknown(cause);
    error.value = writeUnknown.value ? '操作结果未知。请读取原任务状态核对。' : storageError(cause, '扫描任务操作失败');
  } finally {
    busy.value = false;
    if (!scope.signal.aborted) await readTask();
  }
}
function onVisibility() {
  if (document.hidden) window.clearTimeout(timer);
  else if (!busy.value) schedule();
}
onMounted(() => {
  void readPreflight();
  void readTask();
  document.addEventListener('visibilitychange', onVisibility);
});
onUnmounted(() => {
  scope.abort();
  window.clearTimeout(timer);
  document.removeEventListener('visibilitychange', onVisibility);
});
</script>

<template>
  <el-dialog :model-value="true" :title="`存储源重新扫描 / 恢复 · ${source.name}`" width="min(760px, 94vw)"
    :close-on-click-modal="!busy" :close-on-press-escape="!busy" :show-close="!busy" @close="emit('close')">
    <el-alert v-if="error || createUnknown" :title="error || '本标签页有提交结果未知的扫描，已暂停重复提交。'" type="warning" :closable="false"/>
    <el-alert v-if="preflightError" :title="preflightError" type="error" :closable="false"/>
    <el-alert v-if="readError" :title="readError" type="error" :closable="false"/>
    <form class="algorithm-form" @submit.prevent="start">
      <label>执行位置<el-select v-model="form.mode" aria-label="执行位置" :disabled="busy || !preflight || (!!taskId && !completion)" @change="syncFormat">
        <el-option label="中央 Worker" value="local"/>
        <el-option label="远程 Agent" value="agent" :disabled="!preflight?.agent_available"/>
      </el-select></label>
      <label>扫描内容<el-select v-model="form.format" aria-label="扫描内容" :disabled="busy || !preflight || (!!taskId && !completion)">
        <el-option v-for="format in formats" :key="format" :label="formatLabels[format]" :value="format"/>
      </el-select></label>
      <label v-if="form.format === 'yolo'">YOLO data.yaml
        <el-input v-model="form.yaml" aria-label="YOLO data.yaml" placeholder="可留空自动发现" :disabled="busy || (!!taskId && !completion)"/>
      </label>
      <p v-if="preflight">远程 Agent {{ preflight.agent_available ? '可用' : '不可用' }}
        <template v-if="preflight.eligible_nodes?.length"> · {{ preflight.eligible_nodes.map(node => node.display_name || node.node_id).join('、') }}</template>
      </p>
      <p><el-button native-type="submit" type="primary" :disabled="!canStart || busy || reading">开始新的扫描</el-button>
        <el-button :loading="preflightLoading" :disabled="busy" @click="readPreflight">刷新执行资源</el-button></p>
    </form>
    <section v-if="task" aria-label="扫描结果">
      <h3>{{ statusLabels[task.status] || task.status }} · {{ formatLabels[task.import_format] || task.import_format }}</h3>
      <p>任务 {{ task.task_id }} · {{ task.execution_mode === 'agent' ? '远程 Agent' : '中央 Worker' }}
        <template v-if="task.worker_id"> · Worker {{ task.worker_id }}</template></p>
      <p v-if="counts.length">{{ counts.map(([key, count]) => `${countLabels[key] || key} ${count}`).join(' · ') }}</p>
      <p v-if="completion">已应用图片项 {{ task.applied ?? '—' }} · 已应用标注项 {{ task.annotation_applied ?? '—' }}</p>
      <el-alert v-if="task.error" title="任务报告错误。请在原存储配置核对任务。" type="error" :closable="false"/>
      <details v-for="[key, items] in examples" :key="key">
        <summary>{{ countLabels[key] || key }}示例</summary>
        <ul><li v-for="(item, index) in items" :key="index">{{ item }}</li></ul>
      </details>
      <template v-if="waiting && task.import_format === 'images'">
        <h3>图片同步策略</h3>
        <div><el-checkbox v-model="policy.newImages" :disabled="busy">建立新增图片索引</el-checkbox></div>
        <div><el-checkbox v-model="policy.missing" :disabled="busy">缺失图片标记不可用</el-checkbox></div>
        <div><el-checkbox v-model="policy.changed" :disabled="busy">更新图片内容变化</el-checkbox></div>
        <el-button type="primary" :disabled="busy || reading || !!readError || writeUnknown" @click="changeTask('confirm')">确认应用</el-button>
      </template>
      <el-alert v-else-if="waiting" title="使用原存储配置完成标注质量报告、类别映射及同步确认。" :closable="false"/>
      <p v-if="collected" class="rescan-link"><router-link :to="{name:'materials',params:{projectId}}">返回素材库查看归集结果</router-link></p>
    </section>
    <p v-else-if="!taskId">尚未创建扫描任务。</p>
    <template #footer>
      <el-button v-if="taskId" :loading="reading" :disabled="busy" @click="readTask">刷新任务</el-button>
      <el-button v-if="canCancel" :disabled="busy || reading || !!readError || writeUnknown" @click="changeTask('cancel')">取消任务</el-button>
      <el-button v-if="!busy" tag="a" :href="legacy">原存储配置</el-button>
      <el-button :disabled="busy" @click="emit('close')">关闭</el-button>
    </template>
  </el-dialog>
</template>

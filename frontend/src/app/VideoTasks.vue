<script setup lang="ts">
import {computed, onMounted, onUnmounted, reactive, ref} from 'vue';
import {isActiveVideoTask, videoTaskFormValues} from '../../../static/modules/video-tasks.js';
import {videoTasks, type VideoTask} from '../api/video-tasks';
import {useWorkspace} from './main';

const {projectId} = defineProps<{projectId: string}>();
const api = videoTasks(projectId);
const scope = new AbortController();
const rows = ref<VideoTask[]>([]);
const cursors = ref(['']);
const next = ref('');
const loading = ref(false);
const error = ref('');
const detail = ref<VideoTask>();
const showDetail = ref(false);
const showCreate = ref(false);
const busy = ref(false);
const uncertain = ref(false);
const createKey = 'video-create:' + JSON.stringify([useWorkspace().actorKey, projectId]);
try { uncertain.value = sessionStorage.getItem(createKey) === 'pending'; }
catch { uncertain.value = true; }
const createError = ref('');
const stopping = ref('');
const file = ref<File>();
const duration = ref(0);
const metadataUrl = ref('');
const splits = {unassigned: '未处理', train: '训练集', val: '验证集', test: '试验集'};
const initialForm = () => ({mode: 'interval_seconds', split: 'unassigned', intervalSeconds: 1, extractFps: 1, fixedCount: 50, maxFrames: 0});
const form = reactive(initialForm());
let timer: number | undefined;
let pendingRefresh: Promise<void> | undefined;

function splitLabel(key: string) {
  return splits[key as keyof typeof splits] || key;
}
function formatDate(value?: string) {
  return value?.replace('T', ' ').slice(0, 19) || '—';
}
function clearMetadata() {
  if (metadataUrl.value) URL.revokeObjectURL(metadataUrl.value);
  metadataUrl.value = '';
  duration.value = 0;
}
function chooseVideo(event: Event) {
  clearMetadata();
  file.value = (event.target as HTMLInputElement).files?.[0];
  if (file.value) metadataUrl.value = URL.createObjectURL(file.value);
}
function captureDuration(event: Event) {
  const value = (event.target as HTMLVideoElement).duration;
  duration.value = Number.isFinite(value) ? value : 0;
}
const estimate = computed(() => {
  const count = form.mode === 'fixed_count' ? form.fixedCount
    : form.mode === 'fps' ? duration.value * form.extractFps
    : duration.value / Math.max(0.05, form.intervalSeconds);
  return Math.ceil(form.maxFrames > 0 ? Math.min(form.maxFrames, count) : count);
});

function scheduleRefresh() {
  window.clearTimeout(timer);
  if (!scope.signal.aborted && !document.hidden && rows.value.some(isActiveVideoTask)) {
    timer = window.setTimeout(() => void refresh(), error.value ? 5000 : 2000);
  }
}
function refresh(page = cursors.value) {
  if (scope.signal.aborted) return;
  return pendingRefresh ??= readPage(page).finally(() => {pendingRefresh = undefined});
}
async function readPage(page: string[]) {
  loading.value = true;
  window.clearTimeout(timer);
  try {
    const result = await api.list(page.at(-1) || '', scope.signal);
    rows.value = result.items;
    next.value = result.next;
    cursors.value = page;
    if (detail.value && showDetail.value) {
      detail.value = rows.value.find(row => row.id === detail.value?.id) || detail.value;
    }
    error.value = '';
  } catch (cause) {
    if (!scope.signal.aborted) error.value = (cause as Error).message;
  } finally {
    loading.value = false;
    scheduleRefresh();
  }
}
function visibilityChange() {
  if (document.hidden) window.clearTimeout(timer);
  else if (rows.value.some(isActiveVideoTask)) void refresh();
}
onMounted(() => {
  document.addEventListener('visibilitychange', visibilityChange);
  void refresh();
});
onUnmounted(() => {
  scope.abort();
  window.clearTimeout(timer);
  document.removeEventListener('visibilitychange', visibilityChange);
  clearMetadata();
});

function openCreate() {
  file.value = undefined;
  createError.value = '';
  Object.assign(form, initialForm());
  showCreate.value = true;
}
async function create() {
  if (busy.value || uncertain.value) return;
  if (!file.value) {
    createError.value = '请选择视频';
    return;
  }
  let values: ReturnType<typeof videoTaskFormValues>;
  try { values = videoTaskFormValues(form.mode, form); }
  catch (cause) { createError.value = (cause as Error).message; return; }
  busy.value = true;
  createError.value = '';
  let sent = false;
  try {
    sessionStorage.setItem(createKey, 'pending');
    sent = true;
    await api.create(file.value, form.split, values);
    sessionStorage.removeItem(createKey);
    showCreate.value = false;
  } catch (cause) {
    const failure = cause as Error & {httpStatus?: number; outcome?: string};
    uncertain.value = sent && !(failure.httpStatus && failure.httpStatus >= 400 && failure.httpStatus < 500);
    if (sent && !uncertain.value) sessionStorage.removeItem(createKey);
    createError.value = uncertain.value
      ? '创建结果未知，请先查看任务记录，确认是否已经受理。'
      : failure.message;
  } finally {
    busy.value = false;
    if (!createError.value || uncertain.value) {
      await pendingRefresh;
      await refresh(['']);
    }
  }
}
function confirmTaskList() {
  try { sessionStorage.removeItem(createKey); uncertain.value = false; }
  catch { error.value = '浏览器无法保存核对状态。'; }
}
async function openDetail(task: VideoTask) {
  detail.value = task;
  showDetail.value = true;
  try {
    const current = await api.detail(task.id, scope.signal);
    if (detail.value?.id === task.id) detail.value = current;
  } catch (cause) {
    if (!scope.signal.aborted) error.value = (cause as Error).message;
  }
}
async function stop(task: VideoTask) {
  if (stopping.value) return;
  stopping.value = task.id;
  let message = '';
  try {
    await api.stop(task.id);
  } catch (cause) {
    message = (cause as Error).message;
  } finally {
    await pendingRefresh;
    await refresh();
    if (message && !scope.signal.aborted) error.value = message;
    stopping.value = '';
  }
}
</script>

<template>
  <section aria-label="切帧任务记录">
    <div class="page-toolbar">
      <div><el-button @click="refresh()">刷新任务</el-button>
        <router-link :to="{name:'materials', params:{projectId}}">查看素材库</router-link>
      </div>
      <el-button type="primary" :disabled="uncertain" @click="openCreate">＋ 创建切帧任务</el-button>
    </div>
    <el-alert v-if="error" :title="error" type="error" :closable="false"/>
    <el-alert v-if="uncertain" title="上次创建结果未知，请核对最新任务记录。" type="warning" :closable="false">
      <el-button text :disabled="loading" @click="confirmTaskList">已核对，允许再次创建</el-button>
    </el-alert>
    <el-table :data="rows" row-key="id" :empty-text="loading ? '正在读取切帧任务…' : '暂无切帧任务'">
      <el-table-column label="视频" min-width="160"><template #default="{row}">{{ row.video_name || '—' }}<small>{{ row.id }}</small></template></el-table-column>
      <el-table-column label="切帧方式" min-width="130"><template #default="{row}">{{ row.samplingText }}<small>最多 {{ row.max_frames || '不限' }} 张</small></template></el-table-column>
      <el-table-column label="素材归属" min-width="92"><template #default="{row}">{{ splitLabel(row.split) }}</template></el-table-column>
      <el-table-column label="状态" min-width="126"><template #default="{row}">{{ row.statusText }}<small>{{ row.runtimeText }}</small></template></el-table-column>
      <el-table-column label="进度" min-width="135"><template #default="{row}"><el-progress :percentage="row.progress"/><small>{{ row.extractedFrames }} 张</small></template></el-table-column>
      <el-table-column label="当前帧" min-width="85"><template #default="{row}">{{ row.current_item || '—' }}</template></el-table-column>
      <el-table-column label="创建/完成" min-width="164"><template #default="{row}">{{ formatDate(row.created_at) }}<small>{{ formatDate(row.finished_at) }}</small></template></el-table-column>
      <el-table-column label="操作" min-width="133"><template #default="{row}">
        <el-button text @click="openDetail(row)">详情</el-button>
        <el-button v-if="isActiveVideoTask(row)" text :disabled="row.status === 'CANCEL_REQUESTED'" :loading="stopping === row.id" @click="stop(row)">停止</el-button>
        <small v-if="row.error" class="task-error">{{ row.error }}</small>
      </template></el-table-column>
    </el-table>
    <div v-if="cursors.length > 1 || next" class="pagination">
      <el-button :disabled="loading || cursors.length === 1" @click="refresh(cursors.slice(0, -1))">上一页</el-button>
      <span>第 {{ cursors.length }} 页</span>
      <el-button :disabled="loading || !next" @click="refresh([...cursors, next])">下一页</el-button>
    </div>
    <el-dialog v-model="showCreate" title="创建切帧任务" width="min(620px, 94vw)" destroy-on-close
      :show-close="!busy" :close-on-click-modal="!busy" :close-on-press-escape="!busy" @closed="clearMetadata">
      <form id="video-task-form" class="video-form" @submit.prevent="create">
        <label class="wide">上传视频文件<input required type="file" accept="video/*" :disabled="busy" @change="chooseVideo"></label>
        <video v-if="metadataUrl" :key="metadataUrl" hidden preload="metadata" :src="metadataUrl" @loadedmetadata="captureDuration"/>
        <label>切帧方式<select v-model="form.mode" :disabled="busy"><option value="interval_seconds">按时间间隔</option><option value="fps">按每秒帧数</option><option value="fixed_count">按固定帧数</option></select></label>
        <label>素材归属<select v-model="form.split" :disabled="busy"><option v-for="(label, key) in splits" :key="key" :value="key">{{ label }}</option></select></label>
        <label v-if="form.mode === 'interval_seconds'">切帧间隔（秒）<input v-model.number="form.intervalSeconds" type="number" required min="0.05" step="any" :disabled="busy"></label>
        <label v-else-if="form.mode === 'fps'">每秒抽取帧数<input v-model.number="form.extractFps" type="number" required min="0.1" step="any" :disabled="busy"></label>
        <label v-else>固定抽取帧数<input v-model.number="form.fixedCount" type="number" required min="1" step="1" :disabled="busy"></label>
        <label>最大切帧数量（可选）<input v-model.number="form.maxFrames" type="number" min="0" step="1" :disabled="busy"></label>
        <span class="wide">{{ duration ? `视频约 ${duration.toFixed(1)} 秒 · 预计生成 ${estimate} 张` : file ? '正在读取视频时长，部分格式无法预估' : '选择视频后计算预计帧数' }}</span>
        <el-alert v-if="createError" class="wide" :title="createError" type="error" :closable="false"/>
      </form>
      <template #footer><el-button :disabled="busy" @click="showCreate = false">取消</el-button><el-button type="primary" native-type="submit" form="video-task-form" :disabled="uncertain" :loading="busy">创建任务</el-button></template>
    </el-dialog>
    <el-dialog v-model="showDetail" title="切帧任务详情" width="min(620px, 94vw)">
      <dl v-if="detail" class="readonly-facts">
        <dt>视频</dt><dd>{{ detail.video_name }}</dd>
        <dt>状态</dt><dd>{{ detail.statusText }}</dd>
        <dt>素材归属</dt><dd>{{ splitLabel(detail.split) }}</dd>
        <dt>已生成</dt><dd>{{ detail.extractedFrames }} 张</dd>
        <dt>进度</dt><dd>{{ detail.progress }}%</dd>
        <dt>输出目录</dt><dd>{{ detail.result?.output_ref || '—' }}</dd>
      </dl>
      <el-alert v-if="detail?.error" :title="detail.error" type="error" :closable="false"/>
      <template #footer><el-button tag="a" :href="$router.resolve({name:'materials', params:{projectId}}).href">查看素材库</el-button></template>
    </el-dialog>
  </section>
</template>

<style scoped>
.page-toolbar a {margin-inline: 12px; font-size: 14px;}
.el-table small {display: block; color: #666; overflow-wrap: anywhere;}
.el-table .task-error {color: var(--el-color-danger);}
.video-form {display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px;}
.video-form label {display: grid; gap: 8px;}
.video-form input,.video-form select {min-width: 0; border: 1px solid #ccc; border-radius: 6px; padding: 8px; font: inherit;}
.wide {grid-column: 1/-1;}
@media(max-width:600px) {.video-form {grid-template-columns: 1fr;}}
</style>

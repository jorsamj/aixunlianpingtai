<script setup lang="ts">
import {computed, onMounted, onUnmounted, reactive, ref} from 'vue';
import {ElMessageBox} from 'element-plus';
import {buildStorageSourcePayload, STORAGE_TYPE_LABELS} from '../../../static/modules/storage.js';
import {request} from './http';
import {legacyUrl} from './navigation';
import StorageRescan from './StorageRescan.vue';
import {storageAddress, storageError, storageResponseUnknown, storageSourcesUrl, storageSourceUrl, type StorageSource} from './storage-management';

const {projectId} = defineProps<{projectId: string}>();
const legacy = legacyUrl(projectId, '存储配置');
const legacyMaterials = legacyUrl(projectId, '数据集', '', '', 'material-integrity');
const project = encodeURIComponent(projectId);
const scope = new AbortController();
const sources = ref<StorageSource[]>([]);
const loading = ref(false);
const busy = ref(false);
const error = ref('');
const notice = ref('');
const editOpen = ref(false);
const editing = ref<StorageSource>();
const scanSource = ref<StorageSource>();
const reviewSource = ref<StorageSource>();
const refsCount = ref<number>();
const refsError = ref('');
const diagnostics = ref<string>();
interface LifecycleSummary {
  ok: boolean;
  project_id: string;
  sampled_at?: string;
  metrics?: Record<string, {value?: number | null; scope?: string}>;
}
interface ArtifactStorageSummary {
  ok?: boolean;
  config?: {storage_source_id?: string; root_prefix?: string; auto_upload_enabled?: boolean};
  artifact_storage?: {endpoint?: string; bucket?: string; public_base_url?: string; credential_configured?: boolean};
}
const sampled = ref<LifecycleSummary>();
const artifacts = ref<ArtifactStorageSummary>();
const artifactsError = ref('');
const lifecycleLabels = {
  original_index_logical_bytes: '原素材索引逻辑量',
  gt_index_logical_bytes: 'GT 索引逻辑量',
  thumbnail_cache_logical_bytes: '缩略图缓存逻辑量',
  shared_cache_logical_bytes: '共享素材缓存逻辑量',
  worker_workspace_logical_bytes: 'Worker 临时空间逻辑量',
  reclaimable_logical_bytes: '可回收逻辑量',
  cleanup_pending_tasks: '待清理任务',
  cleanup_failed_tasks: '清理失败任务',
};
function humanBytes(value:number){
  if(!Number.isFinite(value)||value<0)return '未获取';
  const units=['B','KB','MB','GB','TB'];let index=0;let size=value;
  while(size>=1024&&index<4){size/=1024;index++}
  return `${size.toFixed(index?1:0)} ${units[index]}`;
}
const sourceSummary = computed(()=>{
  const list = sources.value;
  return {
    total: list.length,
    enabled: list.filter(row=>row.enabled).length,
    secrets: list.filter(row=>row.secret_configured).length,
    unchecked: list.filter(row=>!row.health_status||row.health_status==='UNKNOWN').length,
  };
});
const healthTone=(status?:string)=>status==='OK'||status==='HEALTHY'?'success':status==='UNKNOWN'||!status?'info':'danger';
const lifecycle = computed(() => Object.entries(lifecycleLabels).map(([key, label]) => {
  const metric = sampled.value?.metrics?.[key];
  const tasks = key.endsWith('_tasks');
  return {key, label, tasks, scope: metric?.scope || '—',
    value: typeof metric?.value === 'number'
      ? `${metric.value.toLocaleString()} ${tasks ? '项' : 'B'}${tasks ? '' : ' · ' + humanBytes(metric.value)}`
      : '未获取'};
}));
const usageLoading = ref(false);
const usageError = ref('');const freshForm = () => ({
  name: '', type: 'local', enabled: true, root: '', endpoint: '', bucket: '', region: '',
  public_base_url: '', prefix: '', base_url: '', namespace: '', use_ssl: true,
  protect_existing_objects: true, access_key_id: '', access_key_secret: '', secret_access_key: '', token: '',
});
const form = reactive(freshForm());
const configFields = computed<{key: 'root'|'endpoint'|'bucket'|'region'|'public_base_url'|'prefix'|'base_url'|'namespace'; label: string}[]>(() => {
  if (form.type === 'oss') return [
    {key: 'endpoint', label: 'Endpoint'}, {key: 'bucket', label: 'Bucket'},
    {key: 'public_base_url', label: '外网地址'}, {key: 'prefix', label: '素材目录'},
  ];
  if (form.type === 's3') return [
    {key: 'endpoint', label: 'Endpoint'}, {key: 'region', label: 'Region'},
    {key: 'bucket', label: 'Bucket'}, {key: 'prefix', label: 'Prefix'},
  ];
  if (form.type === 'remote') return [
    {key: 'base_url', label: '服务器地址'}, {key: 'namespace', label: '命名空间'}, {key: 'root', label: '根目录'},
  ];
  return [{key: 'root', label: '根目录'}];
});

function clearCredentials() {
  form.access_key_id = '';
  form.access_key_secret = '';
  form.secret_access_key = '';
  form.token = '';
}
function openEditor(source?: StorageSource) {
  editing.value = source;
  Object.assign(form, freshForm());
  if (source) Object.assign(form, {name: source.name, type: source.type, enabled: source.enabled});
  error.value = '';
  notice.value = '';
  editOpen.value = true;
}
function closeEditor() {
  clearCredentials();
  editing.value = undefined;
}
async function load() {
  if (loading.value) return;
  loading.value = true;
  try {
    const result = await request<{items: StorageSource[]}>(storageSourcesUrl, {signal: scope.signal});
    if (!Array.isArray(result.items)) throw new Error('Invalid storage source response');
    sources.value = result.items;
  } catch (cause) {
    if (!scope.signal.aborted) error.value = storageError(cause, '读取存储来源失败');
  } finally {
    loading.value = false;
  }
}
async function mutate(url: string, options: RequestInit, label: string, valid: (result: unknown) => boolean) {
  if (busy.value || loading.value) return false;
  busy.value = true;
  error.value = '';
  notice.value = '';
  try {
    const result = await request(url, options);
    if (!valid(result)) throw new Error('Unverified storage mutation');
    notice.value = `${label}已完成。`;
    return true;
  } catch (cause) {
    if (!scope.signal.aborted) error.value = storageResponseUnknown(cause)
      ? `${label}结果未知。请核对当前列表及连接状态后再操作。`
      : storageError(cause, `${label}失败`);
    return false;
  } finally {
    if (!scope.signal.aborted) await load();
    busy.value = false;
  }
}
async function save() {
  if (busy.value || loading.value) return;
  const source = editing.value;
  let payload: ReturnType<typeof buildStorageSourcePayload>;
  try {
    payload = buildStorageSourcePayload(form);
  } catch {
    error.value = 'AccessKey 和 Secret 必须同时填写。';
    return;
  }
  if (!payload.name) {
    error.value = '请输入存储源名称。';
    return;
  }
  // Omit config on PATCH so existing storage identity and all config fields stay intact.
  const body = source
    ? {name: payload.name, ...(payload.enabled !== source.enabled ? {enabled: payload.enabled} : {}), credentials: payload.credentials}
    : payload;
  const saved = await mutate(source ? storageSourceUrl(source.id) : storageSourcesUrl,
    {method: source ? 'PATCH' : 'POST', body: JSON.stringify(body)}, '保存配置', result => {
      const row = result as Partial<StorageSource>;
      return !!row?.id && (!source || row.id === source.id) && row.name === payload.name;
    });
  clearCredentials();
  if (saved) editOpen.value = false;
}
async function testConnection(source: StorageSource) {
  try {
    await ElMessageBox.confirm('此操作会在存储源写入、读取并删除测试对象。', `测试连接 · ${source.name}`);
  } catch {
    return;
  }
  if (scope.signal.aborted) return;
  await mutate(storageSourceUrl(source.id) + '/test', {method: 'POST'}, '连接与读写删除测试', result => {
    const row = result as {ok?: boolean; source?: StorageSource};
    return row?.ok === true && row.source?.id === source.id;
  });
}
function setDefault(source: StorageSource) {
  void mutate(storageSourceUrl(source.id) + '/default', {method: 'POST'}, '设置默认存储',
    result => (result as StorageSource)?.id === source.id && (result as StorageSource)?.is_default === true);
}
function toggle(source: StorageSource) {
  const enabled = !source.enabled;
  void mutate(storageSourceUrl(source.id), {method: 'PATCH', body: JSON.stringify({enabled})},
    enabled ? '启用存储源' : '停用存储源',
    result => (result as StorageSource)?.id === source.id && (result as StorageSource)?.enabled === enabled);
}
async function readReferences(source: StorageSource) {
  reviewSource.value = source;
  refsCount.value = undefined;
  refsError.value = '';
  const query = new URLSearchParams({storage_source_id: source.id, page: '1', page_size: '1', reader_view: 'true'});
  try {
    const data = await request<{total: number; project_id?: string}>(`/api/v61/projects/${project}/materials?${query}`, {signal: scope.signal});
    if (data.project_id !== projectId || !Number.isInteger(data.total)) throw new Error('Invalid material reference response');
    if (reviewSource.value?.id === source.id) refsCount.value = data.total;
  } catch (cause) {
    if (reviewSource.value?.id === source.id && !scope.signal.aborted) refsError.value = storageError(cause, '读取项目素材引用失败');
  }
}
async function readUsage() {
  if (usageLoading.value) return;
  usageLoading.value = true;
  usageError.value = '';
  try {
    const data = await request<LifecycleSummary>(`/api/v62/projects/${project}/storage/lifecycle-summary`, {signal: scope.signal});
    if (data.ok !== true || data.project_id !== projectId) throw new Error('Invalid lifecycle response');
    sampled.value = data;
  } catch (cause) {
    if (!scope.signal.aborted) usageError.value = storageError(cause, '读取存储占用失败');
  } finally {
    usageLoading.value = false;
  }
}
async function readArtifactStorage() {
  artifactsError.value = '';
  try {
    const data = await request<ArtifactStorageSummary>('/api/v64/model-artifacts/config', {signal: scope.signal});
    if (data.ok !== true || !data.config) throw new Error('Invalid artifact storage configuration');
    artifacts.value = data;
  } catch (cause) {
    if (!scope.signal.aborted) artifactsError.value = storageError(cause, '读取算法产物归档配置失败');
  }
}
async function readDiagnostics() {
  try {
    const data = await request<{task?: {status?: string; result?: {scanned_images?: number; affected_images?: number; scan_failures?: number}}}>(`/api/v62/projects/${project}/material-integrity/audits/latest`, {signal: scope.signal});
    const task = data.task;
    diagnostics.value = task
      ? [task.status, task.result ? `已核验 ${task.result.scanned_images ?? '—'} 张，受影响 ${task.result.affected_images ?? '—'} 张，无法核验 ${task.result.scan_failures ?? '—'} 张` : ''].filter(Boolean).join(' · ')
      : '尚无素材完整性审计记录。';
  } catch (cause) {
    if (!scope.signal.aborted) diagnostics.value = storageError(cause, '读取素材完整性审计失败');
  }
}
onMounted(() => { void load(); void readUsage(); void readArtifactStorage(); });
onUnmounted(() => { scope.abort(); clearCredentials(); });
</script>

<template>
  <section aria-label="存储管理">
    <section class="version-panel" v-loading="loading" aria-label="素材存储">
      <header>
        <div><h2>素材存储</h2><h3>本地存储、阿里云 OSS、S3 兼容对象存储与其他服务器</h3></div>
        <div>
          <el-button :disabled="busy || loading" @click="load">刷新</el-button>
          <el-button tag="a" :href="legacy">从存储导入素材（原入口）</el-button>
          <el-button type="primary" :disabled="busy || loading" @click="openEditor()">新增存储源</el-button>
        </div>
      </header>
      <el-alert v-if="error && !editOpen" :title="error" type="error" :closable="false"/>
      <el-alert v-if="notice" :title="notice" type="success" :closable="false"/>
      <dl v-if="sources.length" class="storage-summary" aria-label="存储源概览">
        <div><dt>存储源</dt><dd>{{ sourceSummary.total }}</dd></div>
        <div><dt>已启用</dt><dd>{{ sourceSummary.enabled }}</dd></div>
        <div><dt>已配置密钥</dt><dd>{{ sourceSummary.secrets }}</dd></div>
        <div><dt>健康未检测</dt><dd :class="{warn:sourceSummary.unchecked>0}">{{ sourceSummary.unchecked }}</dd></div>
      </dl>
      <el-table :data="sources" row-key="id" empty-text="暂无存储源">
        <el-table-column label="名称 / 类型" min-width="180">
          <template #default="{row}">
            <b>{{ row.name }}</b><small>{{ STORAGE_TYPE_LABELS[row.type] || row.type }}{{ row.is_default ? ' · 默认存储' : '' }}</small>
          </template>
        </el-table-column>
        <el-table-column label="地址 / Bucket" min-width="240">
          <template #default="{row}">
            <span>{{ storageAddress(row.config.endpoint || row.config.base_url || row.config.root) }}</span>
            <small>{{ storageAddress(row.config.bucket || row.config.namespace || row.config.prefix) }}</small>
            <small v-if="row.type === 'oss' || row.type === 's3'">{{ row.config.protect_existing_objects === false ? '允许原地覆盖' : '禁止平台原地覆盖对象' }}</small>
          </template>
        </el-table-column>
        <el-table-column label="状态" min-width="150">
          <template #default="{row}">
            <el-tag :type="row.enabled ? 'success' : 'info'" effect="plain" size="small">{{ row.enabled ? '已启用' : '已停用' }}</el-tag>
            <el-tag :type="healthTone(row.health_status)" effect="plain" size="small">{{ row.health_status === 'UNKNOWN' || !row.health_status ? '未检测' : row.health_status }}</el-tag>
            <small>{{ row.last_checked_at || '—' }} · {{ row.secret_configured ? '已配置密钥' : '未配置密钥' }}</small>
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="290">
          <template #default="{row}">
            <el-button link :disabled="busy || loading" @click="openEditor(row)">编辑</el-button>
            <el-button link :disabled="busy || loading" @click="testConnection(row)">测试连接</el-button>
            <el-button v-if="row.enabled && !row.is_default" link :disabled="busy || loading" @click="setDefault(row)">设为默认</el-button>
            <el-button v-if="row.id !== 'default_local'" link :disabled="busy || loading" @click="toggle(row)">{{ row.enabled ? '停用' : '启用' }}</el-button>
            <el-button link @click="readReferences(row)">引用</el-button>
            <el-button v-if="row.enabled" link @click="scanSource = row">重新扫描 / 恢复</el-button>
          </template>
        </el-table-column>
      </el-table>
      <p><el-button tag="a" :href="legacy">原存储配置（删除、地址变更）</el-button></p>
      <el-alert v-if="reviewSource" :title="`${reviewSource.name} · 当前项目素材索引引用 ${refsCount ?? '未获取'} 条`"
        :description="refsError || '全局引用和删除资格由原服务在执行时核查。'" :closable="false"/>
    </section>
    <section class="version-panel" aria-label="算法产物归档">
      <header><div><h2>算法产物归档</h2><h3>训练模型及转换结果</h3></div>
        <div><el-button @click="readArtifactStorage">刷新归档配置</el-button>
          <el-button tag="a" :href="legacy">原归档配置与连接测试</el-button></div>
      </header>
      <el-alert v-if="artifactsError" :title="artifactsError" type="error" :closable="false"/>
      <dl v-if="artifacts?.config" class="readonly-facts">
        <dt>存储源</dt><dd>{{ artifacts.config.storage_source_id || '—' }}</dd>
        <dt>归档根目录</dt><dd>{{ storageAddress(artifacts.config.root_prefix) }}</dd>
        <dt>Endpoint / Bucket</dt><dd>{{ storageAddress(artifacts.artifact_storage?.endpoint) }} / {{ storageAddress(artifacts.artifact_storage?.bucket) }}</dd>
        <dt>自动归档</dt><dd>{{ artifacts.config.auto_upload_enabled === false ? '已停用' : '已启用' }}</dd>
        <dt>凭据</dt><dd>{{ artifacts.artifact_storage?.credential_configured ? '已配置' : '未显示配置记录' }}</dd>
      </dl>
    </section>
    <section class="version-panel" v-loading="usageLoading" aria-label="存储生命周期占用">
      <header><div><h2>存储生命周期占用</h2><h3>各项为对应范围的逻辑量，分别读取。</h3></div>
        <el-button :loading="usageLoading" @click="readUsage">刷新占用信息</el-button>
      </header>
      <el-alert v-if="usageError" :title="usageError" type="error" :closable="false"/>
      <p class="storage-note">逻辑量来自服务端采样，不等于物理文件大小；“可回收逻辑量”不代表已确认释放，物理释放需由原服务执行并回执。</p>
      <h3>逻辑占用</h3>
      <el-table :data="lifecycle.filter(row=>!row.tasks)" row-key="key">
        <el-table-column prop="label" label="项目" min-width="170"/>
        <el-table-column prop="value" label="逻辑量" min-width="200"/>
        <el-table-column prop="scope" label="采样范围" min-width="245"/>
      </el-table>
      <h3>清理任务</h3>
      <el-table :data="lifecycle.filter(row=>row.tasks)" row-key="key" empty-text="暂无清理任务统计">
        <el-table-column prop="label" label="项目" min-width="170"/>
        <el-table-column prop="value" label="任务数" min-width="120"/>
        <el-table-column prop="scope" label="采样范围" min-width="245"/>
      </el-table>
      <small>采样时间 {{ sampled?.sampled_at || '未获取' }}</small>
    </section>
    <section class="version-panel" aria-label="素材完整性诊断">
      <header><div><h2>素材完整性诊断</h2><h3>读取当前项目的最近审计</h3></div>
        <div><el-button @click="readDiagnostics">读取最近审计</el-button>
          <el-button tag="a" :href="legacyMaterials">原素材库 · 重复与异常素材</el-button></div>
      </header>
      <p v-if="diagnostics" role="status">{{ diagnostics }}</p>
    </section>
    <el-dialog v-model="editOpen" :title="editing ? '编辑存储源' : '新增存储源'" width="min(680px, 94vw)"
      :close-on-click-modal="!busy" :close-on-press-escape="!busy" :show-close="!busy" @closed="closeEditor">
      <form class="algorithm-form" @submit.prevent="save">
        <label>名称<el-input v-model="form.name" aria-label="名称" :disabled="busy"/></label>
        <label>类型<el-select v-model="form.type" aria-label="类型" :disabled="!!editing || busy" @change="clearCredentials">
          <el-option v-for="(label, type) in STORAGE_TYPE_LABELS" :key="type" :label="label" :value="type"/>
        </el-select></label>
        <template v-if="!editing">
          <label v-for="field in configFields" :key="field.key">{{ field.label }}
            <el-input v-model="form[field.key]" :aria-label="field.label" :disabled="busy"/>
          </label>
          <el-checkbox v-if="form.type === 's3'" v-model="form.use_ssl" :disabled="busy">使用 SSL</el-checkbox>
          <el-checkbox v-if="form.type === 'oss' || form.type === 's3'" v-model="form.protect_existing_objects" :disabled="busy">禁止平台写入覆盖已有对象</el-checkbox>
        </template>
        <template v-if="form.type === 'oss' || form.type === 's3'">
          <label>AccessKey ID<el-input v-model="form.access_key_id" type="password" autocomplete="new-password" aria-label="AccessKey ID" :disabled="busy"/></label>
          <label>AccessKey Secret
            <el-input v-if="form.type === 'oss'" v-model="form.access_key_secret" type="password" autocomplete="new-password" aria-label="AccessKey Secret" :disabled="busy"/>
            <el-input v-else v-model="form.secret_access_key" type="password" autocomplete="new-password" aria-label="AccessKey Secret" :disabled="busy"/>
          </label>
        </template>
        <label v-if="form.type === 'remote'">API Token<el-input v-model="form.token" type="password" autocomplete="new-password" aria-label="API Token" :disabled="busy"/></label>
        <small v-if="editing?.secret_configured">留空表示继续使用原凭据。</small>
        <el-checkbox v-model="form.enabled" :disabled="editing?.id === 'default_local' || busy">启用该存储源</el-checkbox>
        <el-alert v-if="error" :title="error" type="error" :closable="false"/>
        <p><el-button :disabled="busy" @click="editOpen = false">取消</el-button>
          <el-button native-type="submit" type="primary" :loading="busy" :disabled="loading">保存</el-button></p>
      </form>
    </el-dialog>
    <StorageRescan v-if="scanSource" :key="scanSource.id" :source="scanSource" :project-id="projectId" :legacy="legacy" @close="scanSource = undefined"/>
  </section>
</template>

<style scoped>
.el-table small {
  display: block;
  color: #666;
  overflow-wrap: anywhere;
}
.version-panel header {
  flex-wrap: wrap;
  gap: 12px;
}
.version-panel header > div:last-child {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.version-panel header .el-button + .el-button {
  margin-left: 0;
}
.storage-summary {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 8px;
  margin: 12px 0;
}
.storage-summary > div {
  padding: 10px 12px;
  background: var(--workspace-surface, #fff);
  border: 1px solid var(--workspace-line, #e4e4e7);
  border-radius: 8px;
}
.storage-summary dt {
  font-size: 12px;
  color: var(--workspace-subtle, #686872);
}
.storage-summary dd {
  margin: 4px 0 0;
  font-size: 20px;
  font-weight: 650;
  font-variant-numeric: tabular-nums;
}
.storage-summary dd.warn {
  color: var(--el-color-warning);
}
.storage-note {
  margin: 0 0 12px;
  font-size: 12px;
  color: var(--workspace-muted, #52525b);
}
.version-panel h3 {
  margin: 16px 0 6px;
  font-size: 13px;
  color: var(--workspace-muted, #52525b);
  font-weight: 600;
}
</style>

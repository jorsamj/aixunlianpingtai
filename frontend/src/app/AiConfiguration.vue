<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import AiModelDiagnostics from './AiModelDiagnostics.vue';
import AiPromptSettings from './AiPromptSettings.vue';
import { legacyUrl } from './navigation';
import { readModels, readPrompts, saveModel, setModelAvailability, type ModelConfig, type ModelSettings, type PromptConfig } from '../api/ai-configuration';

const route = useRoute();
const legacy = computed(() => legacyUrl(String(route.params.projectId || ''), '模型配置'));
const models = ref<ModelConfig[]>([]);
const prompts = ref<PromptConfig[]>([]);
const loadingModels = ref(true);
const loadingPrompts = ref(true);
const modelLoadError = ref('');
const promptLoadError = ref('');
const modelError = ref('');
const modelNotice = ref('');
const modelWriteUnconfirmed = ref(false);
const saving = ref(false);
const editOpen = ref(false);
const diagnosticId = ref('');
const diagnosticOpen = ref(false);
const diagnosticModel = computed(() => models.value.find(model => model.id === diagnosticId.value));
const editId = ref('');
const hasKey = ref(false);
const credential = ref<'keep' | 'update'>('keep');
const keyInput = ref('');
const queryRows = ref<{ key: number; code: string; query: string }[]>([]);
const controller = new AbortController();
let nextQuery = 0;

const providers = [
  { value: 'volcengine_ark', label: '通用 · 火山方舟', url: 'https://ark.cn-beijing.volces.com/api/v3', help: '填写已开通的模型 ID 或 Endpoint ID。' },
  { value: 'aliyun_qwen', label: '通用 · 阿里云千问', url: '', help: '填写所在地域的服务地址与模型 ID。' },
  { value: 'local_openai', label: '通用 · OpenAI 兼容', url: 'http://127.0.0.1:8000/v1', help: '支持 Chat Completions 或 Responses 兼容服务。' },
  { value: 'ollama', label: '通用 · Ollama', url: 'http://127.0.0.1:11434', help: '使用 Ollama 原生协议，服务需已加载视觉模型。' },
  { value: 'wevisone_vl', label: 'WeVisOne · 专用视觉', url: 'http://127.0.0.1:18000', help: '原生检测使用各目标标签定位描述，不接收通用聊天提示词和参考图。支持实例分割与抠图预览。' },
];
const promptsExample = '你是视觉目标检测标注助手。只标注标签库中的目标：{{labels_json}}。图片尺寸 {{image_width}}x{{image_height}}。{{business_instruction}} 只返回 JSON：{{output_schema}}';
const personExample = '仅标注图片中真实存在的人，包括站立、蹲下、坐卧、部分遮挡和背光下仍可辨认的人体。服装颜色不改变 person 的定义。不要将门框、墙体、阴影、挂着的衣服、背景纹理单独标注为人。框应尽量包围真实可见人体；没有可确认的目标则返回空列表。仅输出平台要求的结构化结果。';
const dormitoryExamples = {
  person: 'A real human standing or walking upright on the floor, outside any bed. Not a person lying in bed. Not a fire extinguisher or other upright object.',
  tangzhe: 'A real human lying or reclining on a bed or mattress, covered by a blanket or uncovered. Blue bedsheets may be present but are not proof of a human. Not an empty bed or pillow.',
};

function providerOf(item: ModelConfig) {
  return item.provider_adapter || item.provider_type || 'local_openai';
}
function providerLabel(item: ModelConfig) {
  const adapter = providerOf(item);
  return providers.find(provider => provider.value === adapter)?.label ?? adapter;
}
function testLabel(item: ModelConfig) {
  if (item.enabled === false) return '已停用';
  if (item.last_test?.code === 'MODEL_NOT_LOADED') return '上次模型未加载';
  if (item.last_test?.status === 'failed') return '上次测试失败';
  return item.last_test?.status === 'protocol_passed' ? '上次协议通过' : '尚未测试';
}
function settings(item?: ModelConfig): ModelSettings {
  const kind = item ? providerOf(item) : 'local_openai';
  const baseUrl = item ? item.base_url || item.detect_url || '' : 'http://127.0.0.1:8000/v1';
  return {
    name: item?.name ?? '', model_name: item?.model_name ?? '', provider_adapter: item?.provider_adapter ?? kind,
    provider_type: item?.provider_type ?? kind, model_kind: item?.model_kind ?? 'vlm',
    base_url: baseUrl, detect_url: item?.detect_url ?? baseUrl, health_url: item?.health_url ?? '',
    api_protocol: item?.api_protocol ?? 'auto', structured_output: item?.structured_output ?? 'auto',
    coordinate_space: item ? item.coordinate_space || 'legacy_auto' : 'pixel',
    coordinate_order: item?.coordinate_order ?? 'xyxy', coordinate_origin: item?.coordinate_origin ?? 'top_left',
    coordinate_image_space: item?.coordinate_image_space ?? 'original_input', output_protocol: item?.output_protocol ?? 'json_boxes',
    coordinate_contract_version: item?.coordinate_contract_version ?? 1, enabled: item?.enabled !== false,
    default_for_annotation: item?.default_for_annotation ?? false, default_for_training_ai: item?.default_for_training_ai ?? false,
    annotation_prompt_template: item?.annotation_prompt_template ?? promptsExample,
    training_intervention_prompt: item?.training_intervention_prompt ?? '',
    request_mode: item?.request_mode ?? 'openai_vision', image_field: item?.image_field ?? 'image',
    prompt_field: item?.prompt_field ?? 'prompt', threshold_field: item?.threshold_field ?? 'threshold',
    headers_json: item?.headers_json, remark: item?.remark ?? '',
  };
}
const draft = ref(settings());
const adapter = ref('local_openai');
const dedicated = computed(() => adapter.value === 'wevisone_vl');
const openAi = computed(() => !dedicated.value && adapter.value !== 'ollama');
const provider = computed(() => providers.find(item => item.value === adapter.value));
function selectProvider(value: string) {
  const selected = providers.find(item => item.value === value);
  if (!selected) return;
  if (!draft.value.base_url || providers.some(item => item.url && item.url === draft.value.base_url)) {
    draft.value.base_url = selected.url || draft.value.base_url;
    draft.value.detect_url = draft.value.base_url;
  }
  draft.value.provider_adapter = value;
  draft.value.provider_type = value;
  if (value === 'ollama') {
    credential.value = 'keep';
    keyInput.value = '';
  }
}
function addQuery(code = '', query = '') {
  if (queryRows.value.length < 100) queryRows.value.push({ key: nextQuery++, code, query });
}
function editModel(item?: ModelConfig) {
  editId.value = item?.id ?? '';
  draft.value = settings(item);
  adapter.value = item ? providerOf(item) : 'local_openai';
  queryRows.value = [];
  for (const [code, query] of Object.entries(item?.wevisone_label_queries ?? {})) addQuery(code, query);
  hasKey.value = item?.has_api_key ?? false;
  credential.value = 'keep';
  keyInput.value = '';
  modelError.value = modelNotice.value = '';
  editOpen.value = true;
}
function setCredential(value: string | number | boolean | undefined) {
  if (value !== 'update') keyInput.value = '';
}
function useDormitoryExample() {
  queryRows.value = [];
  for (const [code, query] of Object.entries(dormitoryExamples)) addQuery(code, query);
}
function showDiagnostics(item: ModelConfig) {
  diagnosticId.value = item.id;
  diagnosticOpen.value = true;
}
async function reloadModels() {
  loadingModels.value = true;
  modelLoadError.value = '';
  try {
    models.value = (await readModels(controller.signal)).items;
    modelWriteUnconfirmed.value = false;
  } catch {
    if (!controller.signal.aborted) modelLoadError.value = '模型配置读取失败，请重试。';
  } finally {
    loadingModels.value = false;
  }
}
async function reloadPrompts() {
  loadingPrompts.value = true;
  promptLoadError.value = '';
  try {
    prompts.value = (await readPrompts(controller.signal)).items;
  } catch {
    if (!controller.signal.aborted) promptLoadError.value = '提示词模板读取失败，请重试。';
  } finally {
    loadingPrompts.value = false;
  }
}
async function save() {
  if (saving.value || modelWriteUnconfirmed.value) return;
  const body = { ...draft.value, name: draft.value.name.trim(), model_name: draft.value.model_name.trim(), base_url: draft.value.base_url.trim() };
  if (!body.name || !body.model_name || !body.base_url || body.coordinate_space === 'legacy_auto') {
    modelError.value = '请填写配置名称、模型 ID、服务地址，并明确坐标范围。';
    return;
  }
  if (!body.enabled && body.default_for_annotation) {
    modelError.value = '停用的模型不能设为默认自动标注模型。';
    return;
  }
  if (credential.value === 'update' && !keyInput.value.trim()) {
    modelError.value = '请填写新 API Key，或选择保留原值。';
    return;
  }
  if (dedicated.value) {
    const rows = queryRows.value.map(({ code, query }) => [code.trim(), query.trim()] as const).filter(([code, query]) => code || query);
    if (rows.some(([code, query]) => !code || !query || /\s/.test(code) || code.length > 80 || query.length > 300 || /[\r\n]|<\|[^>]*\|>|<\/?(?:c|ref|box)>/i.test(query))
        || new Set(rows.map(([code]) => code)).size !== rows.length
        || new Set(rows.map(([, query]) => query)).size !== rows.length
        || rows.some(([code]) => rows.some(([other, query]) => other !== code && query === code))) {
      modelError.value = '请为每行填写独立标签编码和不超过 300 字符的唯一检测描述。';
      return;
    }
    body.wevisone_label_queries = Object.fromEntries(rows);
  }
  const stored = models.value.find(item => item.id === editId.value);
  if (!stored?.detect_url || !stored.base_url || stored.detect_url === stored.base_url || providerOf(stored) !== adapter.value) {
    body.detect_url = body.base_url;
  }
  saving.value = true;
  modelError.value = '';
  try {
    const saved = await saveModel(editId.value, {
      ...body, ...(credential.value === 'update' ? { api_key: keyInput.value.trim() } : {}),
    }, controller.signal);
    if (!saved.id) throw new Error('missing model id');
    modelNotice.value = saved.protocol_warning || '视觉模型配置已保存。';
    keyInput.value = '';
    editOpen.value = false;
    await reloadModels();
  } catch (error) {
    if (!controller.signal.aborted) {
      const httpStatus = (error as { httpStatus?: number }).httpStatus;
      if (httpStatus && httpStatus < 500) {
        modelError.value = '配置保存被拒绝。请检查服务地址、坐标和模型参数。';
      } else {
        modelWriteUnconfirmed.value = true;
        modelError.value = '保存结果未确认。请关闭编辑窗口并刷新列表，核对模型配置和 API Key 状态。';
      }
    }
  } finally {
    saving.value = false;
  }
}
async function toggleModel(item: ModelConfig) {
  if (saving.value || modelWriteUnconfirmed.value) return;
  saving.value = true;
  modelError.value = modelNotice.value = '';
  try {
    const saved = await setModelAvailability(item.id, item.enabled === false, controller.signal);
    modelNotice.value = saved.enabled ? '模型已启用。' : '模型已停用。';
    await reloadModels();
  } catch {
    if (!controller.signal.aborted) modelError.value = '启停结果未确认。请刷新列表核对模型状态。';
  } finally {
    saving.value = false;
  }
}
onMounted(() => { void reloadModels(); void reloadPrompts(); });
onBeforeUnmount(() => controller.abort());
</script>

<template>
  <div class="ai-configuration">
    <section class="panel settings-panel">
      <header class="section-head">
        <h2>视觉模型管理</h2>
        <div class="actions">
          <el-button tag="a" :href="legacy">打开原模型配置</el-button>
          <el-button :disabled="loadingModels" @click="reloadModels">刷新</el-button>
          <el-button type="primary" :disabled="loadingModels || saving || modelWriteUnconfirmed || !!modelLoadError" @click="editModel()">新增视觉模型</el-button>
        </div>
      </header>
      <p class="reference-note">通用模型的参考素材 ID 仅随任务保存。当前推理接口只接收待标注的单张图片。</p>
      <p v-if="modelLoadError" role="alert">{{ modelLoadError }}</p>
      <p v-if="!editOpen && modelError" role="alert">{{ modelError }}</p>
      <p v-if="modelNotice" role="status">{{ modelNotice }}</p>
      <el-table v-loading="loadingModels" :data="models" empty-text="暂无视觉模型">
        <el-table-column label="模型配置" min-width="172">
          <template #default="{ row }">
            <strong>{{ row.name }}</strong>
            <small>{{ row.model_name || '未填写模型 ID' }}</small>
            <small v-if="row.default_for_annotation">默认标注</small>
          </template>
        </el-table-column>
        <el-table-column label="适配方式" min-width="157">
          <template #default="{ row }">
            {{ providerLabel(row) }}
            <small v-if="providerOf(row) === 'wevisone_vl'">检测 · 分割 · 抠图</small>
            <small v-else-if="row.resolved_api_protocol">{{ row.resolved_api_protocol }}</small>
          </template>
        </el-table-column>
        <el-table-column label="验证状态" min-width="145">
          <template #default="{ row }">
            {{ testLabel(row) }}
            <small>{{ row.coordinate_validation?.status === 'verified' ? '坐标已人工确认' : '坐标未确认' }}</small>
          </template>
        </el-table-column>
        <el-table-column label="服务地址 / 最近测试" min-width="184">
          <template #default="{ row }">
            <span class="service-url">{{ row.base_url || row.detect_url || '—' }}</span>
            <small>{{ row.last_test?.checked_at?.slice(0, 19).replace('T', ' ') || '尚无测试记录' }}</small>
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="224">
          <template #default="{ row }">
            <div class="actions">
              <el-button size="small" :disabled="saving || loadingModels" @click="showDiagnostics(row)">测试与诊断</el-button>
              <el-button size="small" :disabled="saving || loadingModels || modelWriteUnconfirmed" @click="editModel(row)">配置</el-button>
              <el-button size="small" :disabled="saving || loadingModels || modelWriteUnconfirmed" @click="toggleModel(row)">{{ row.enabled === false ? '启用' : '停用' }}</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <p v-if="models.length">模型删除沿用原模型配置入口。</p>
    </section>
    <AiPromptSettings :models="models" :prompts="prompts" :loading="loadingPrompts" :load-error="promptLoadError" @refresh="reloadPrompts" @retry="reloadPrompts" />

    <el-dialog v-model="editOpen" :title="editId ? '编辑视觉模型配置' : '新增视觉模型配置'" width="min(800px, 95vw)" :close-on-click-modal="false" :close-on-press-escape="!saving" :show-close="!saving" destroy-on-close @closed="keyInput = ''">
      <el-form label-position="top" class="settings-form" :disabled="saving" @submit.prevent="save">
        <el-form-item label="配置名称" required><el-input v-model="draft.name" /></el-form-item>
        <el-form-item label="模型提供商" required>
          <el-select v-model="adapter" @change="selectProvider">
            <el-option v-if="!provider" :label="adapter" :value="adapter" />
            <el-option v-for="item in providers" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <p v-if="provider" class="full provider-help">{{ provider.help }}</p>
        <el-form-item :label="dedicated ? '模型 ID' : '模型名称 / Endpoint ID'" required><el-input v-model="draft.model_name" /></el-form-item>
        <el-form-item :label="dedicated ? '服务地址' : 'Base URL'" required><el-input v-model="draft.base_url" /></el-form-item>
        <el-form-item v-if="adapter !== 'ollama'" label="API Key" class="full">
          <el-radio-group v-model="credential" @change="setCredential">
            <el-radio value="keep">{{ hasKey ? '保留原值' : '不设置' }}</el-radio>
            <el-radio value="update">{{ hasKey ? '更新' : '设置' }}</el-radio>
            <el-radio v-if="hasKey" value="clear" disabled>清除</el-radio>
          </el-radio-group>
          <el-input v-if="credential === 'update'" v-model="keyInput" type="password" autocomplete="new-password" aria-label="新 API Key" />
          <small v-else-if="hasKey">清除凭据需核对引用。现有接口支持保留或更新。</small>
        </el-form-item>
        <el-form-item class="full">
          <el-checkbox v-model="draft.enabled">启用此模型配置</el-checkbox>
          <el-checkbox v-model="draft.default_for_annotation">设为默认自动标注模型</el-checkbox>
        </el-form-item>
        <el-form-item v-if="!dedicated" label="自动标注提示词" class="full">
          <el-input v-model="draft.annotation_prompt_template" type="textarea" :rows="5" />
          <el-button @click="draft.annotation_prompt_template = personExample">填入人员识别示例</el-button>
          <small>允许变量 labels_json、image_width、image_height、business_instruction、output_schema</small>
        </el-form-item>
        <section v-else class="full query-section" aria-label="WeVisOne 标签定位描述">
          <header class="section-head"><h3>标签定位描述</h3><el-button :disabled="saving" @click="useDormitoryExample">填入宿舍示例</el-button></header>
          <div v-for="(row, index) in queryRows" :key="row.key" class="query-row">
            <el-input v-model="row.code" aria-label="正式标签编码" placeholder="例如 person" maxlength="80" />
            <el-input v-model="row.query" aria-label="原生检测描述" placeholder="姿态、位置与排除对象" maxlength="300" />
            <el-button :disabled="saving" @click="queryRows.splice(index, 1)">移除</el-button>
          </div>
          <el-button :disabled="saving || queryRows.length >= 100" @click="addQuery()">添加描述</el-button>
          <small>未配置描述的标签沿用原标签名称。</small>
        </section>
        <details class="full advanced">
          <summary>高级设置</summary>
          <div class="settings-form">
            <el-form-item label="输出协议"><span>JSON boxes / x1 y1 x2 y2</span></el-form-item>
            <el-form-item label="坐标范围">
              <el-select v-model="draft.coordinate_space">
                <el-option v-if="draft.coordinate_space === 'legacy_auto'" value="legacy_auto" label="历史兼容（请选择明确范围）" />
                <el-option value="pixel" label="原始像素" />
                <el-option value="normalized_01" label="0～1" />
                <el-option value="normalized_1000" label="0～1000" />
              </el-select>
            </el-form-item>
            <el-form-item label="字段值顺序">
              <el-select v-model="draft.coordinate_order">
                <el-option value="xyxy" label="XYXY" />
                <el-option value="yxyx" label="YXYX" />
              </el-select>
            </el-form-item>
            <el-form-item label="坐标原点">
              <el-select v-model="draft.coordinate_origin">
                <el-option value="top_left" label="左上" />
                <el-option value="bottom_left" label="左下" />
              </el-select>
            </el-form-item>
            <el-form-item label="坐标图像空间">
              <el-select v-model="draft.coordinate_image_space">
                <el-option value="original_input" label="完整输入原图" />
                <el-option value="processed_image" label="服务处理图（需适配器几何证据）" />
              </el-select>
            </el-form-item>
            <el-form-item label="API 协议">
              <el-select v-model="draft.api_protocol" :disabled="!openAi">
                <el-option value="auto" label="自动识别（历史默认 Chat）" />
                <el-option value="chat_completions" label="Chat Completions API" />
                <el-option value="responses" label="Responses API" />
              </el-select>
            </el-form-item>
            <el-form-item label="结构化输出能力">
              <el-select v-model="draft.structured_output" :disabled="!openAi">
                <el-option value="auto" label="自动" />
                <el-option value="json_schema" label="JSON Schema" />
                <el-option value="json_object" label="JSON Object" />
                <el-option value="prompt" label="提示词约束与平台校验" />
              </el-select>
            </el-form-item>
            <el-form-item v-if="!dedicated" label="健康检查地址"><el-input v-model="draft.health_url" /></el-form-item>
            <el-form-item label="备注"><el-input v-model="draft.remark" /></el-form-item>
          </div>
        </details>
      </el-form>
      <p v-if="modelError" role="alert">{{ modelError }}</p>
      <template #footer>
        <el-button :disabled="saving" @click="editOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" :disabled="modelWriteUnconfirmed" @click="save">保存配置</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="diagnosticOpen" :title="`模型测试与诊断 · ${diagnosticModel?.name || ''}`" width="min(760px, 95vw)" destroy-on-close>
      <AiModelDiagnostics v-if="diagnosticOpen && diagnosticModel" :key="diagnosticId" :model="diagnosticModel" @refresh="reloadModels" />
    </el-dialog>
  </div>
</template>

<style scoped>
.ai-configuration { display: grid; gap: 18px; }
.settings-panel { padding: 18px; min-width: 0; }
.section-head, .actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.section-head { justify-content: space-between; margin-bottom: 12px; }
.section-head h2, .section-head h3 { margin: 0; font-size: 18px; }
.actions :deep(.el-button + .el-button) { margin-left: 0; }
.settings-panel small { display: block; color: #666; }
.reference-note { color: #555; margin: 0 0 12px; }
.service-url { overflow-wrap: anywhere; }
.settings-form { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(250px, 100%), 1fr)); gap: 0 16px; }
.full { grid-column: 1 / -1; }
.provider-help { margin: 0 0 12px; }
.query-section { margin-bottom: 17px; }
.query-section small { display: block; margin-top: 7px; }
.query-row { display: grid; grid-template-columns: minmax(100px, 1fr) minmax(140px, 3fr) auto; gap: 8px; margin-bottom: 8px; }
.advanced summary { cursor: pointer; margin-bottom: 12px; }
@media (max-width: 540px) { .query-row { grid-template-columns: 1fr; } }
</style>

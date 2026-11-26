<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue';
import { confirmCoordinates, inspectCapacity, testModel, verifyCoordinates, type DiagnosticResult, type ModelConfig } from '../api/ai-configuration';

const props = defineProps<{ model: ModelConfig }>();
const emit = defineEmits<{ refresh: [] }>();
const busy = ref(false);
const error = ref('');
const capacity = ref('');
const connection = ref<DiagnosticResult>();
const sample = ref<DiagnosticResult>();
const file = ref<File>();
const labelsText = ref('');
const operation = ref('detect');
const confirmed = ref(false);
const controller = new AbortController();
const dedicated = computed(() => (props.model.provider_adapter || props.model.provider_type) === 'wevisone_vl');
const boxes = computed(() => sample.value?.parsed_boxes ?? []);
const instances = computed(() => sample.value?.instances ?? (sample.value?.images ? [{ images: sample.value.images, label: '' }] : []));
const evidence = computed(() => sample.value?.coordinate_validation);
const capacityNames: Record<string, string> = {
  unknown: '容量未知', legacy: '历史串行', operator_attested: '运维证据已核对',
  expired: '容量证据已过期', configuration_changed: '配置变化需重新核验', insufficient_evidence: '容量证据不足',
};
function capacityText(policy?: { concurrency: number; evidence_status: string }) {
  return `有效并发 ${policy?.concurrency ?? 1} · ${capacityNames[policy?.evidence_status ?? 'unknown'] ?? capacityNames.unknown}`;
}
function imageUrl(value?: string) {
  return value && /^data:image\/(?:jpeg|png|webp);base64,/i.test(value) ? value : undefined;
}
function chooseFile(event: Event) {
  file.value = (event.target as HTMLInputElement).files?.[0];
}
async function run(action: () => Promise<void>, fallback: string) {
  if (busy.value) return;
  busy.value = true;
  error.value = '';
  try {
    await action();
  } catch (failure) {
    if (controller.signal.aborted) return;
    const code = (failure as { code?: unknown })?.code;
    error.value = code === 'MODEL_NOT_LOADED' ? '模型未加载，请检查服务和已配置的模型 ID。' : fallback;
  } finally {
    busy.value = false;
  }
}
function connectionTest() {
  connection.value = undefined;
  return run(async () => {
    try {
      connection.value = await testModel(props.model.id, controller.signal);
    } finally {
      if (!controller.signal.aborted) emit('refresh');
    }
  }, '连接或标注协议测试未通过。请检查服务地址、模型 ID、API Key 和输出协议。');
}
function capacityTest() {
  return run(async () => {
    const result = await inspectCapacity(props.model.id, controller.signal);
    capacity.value = `${capacityText(result.policy)}。 ${result.message}`;
  }, '容量证据读取失败，请重试。');
}
function readSample(image: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',')[1] ?? '');
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(image);
  });
}
function sampleTest() {
  const image = file.value;
  const labels = [...new Set(labelsText.value.split(/[,，]/).map(label => label.trim()).filter(Boolean))];
  if (!image || image.size > 10000000 || !labels.length || labels.length > 100) {
    error.value = '请选择 10 MB 以内的真实样本图片并填写 1 至 100 个目标标签。';
    return;
  }
  sample.value = undefined;
  confirmed.value = false;
  return run(async () => {
    try {
      sample.value = await verifyCoordinates(props.model.id, {
        image_base64: await readSample(image), labels, operation: operation.value,
      }, controller.signal);
    } finally {
      if (!controller.signal.aborted && operation.value === 'detect') emit('refresh');
    }
  }, '样本验证失败。请检查样本图片、已保存的模型及坐标配置，并重新验证。');
}
function confirmSample() {
  const current = evidence.value;
  if (!current?.receipt || !current.config_revision || !current.sample_sha256 || !boxes.value.length) return;
  const { receipt, config_revision, sample_sha256 } = current;
  return run(async () => {
    await confirmCoordinates(props.model.id, receipt, config_revision, sample_sha256, controller.signal);
    confirmed.value = true;
    emit('refresh');
  }, '确认结果未取得。请刷新模型状态，必要时重新验证真实样本。');
}
onBeforeUnmount(() => controller.abort());
</script>

<template>
  <div class="model-diagnostics" :aria-busy="busy">
    <section>
      <h3>连接与标注协议</h3>
      <p v-if="model.enabled === false">模型已停用，启用后可测试连接与样本。</p>
      <el-button :disabled="busy || model.enabled === false" @click="connectionTest">测试连接和解析</el-button>
      <p v-if="connection" role="status">
        协议测试通过 · {{ connection.latency_ms ?? 0 }} ms ·
        {{ connection.model_loaded === false ? '模型未加载' : connection.model_loaded ? '模型已加载' : '模型加载状态未提供' }}。
        {{ connection.parsed_boxes?.length ? `返回 ${connection.parsed_boxes.length} 个候选框。` : '白底样本未检测到目标。' }}
        实际框位置需另用真实样本核验。
      </p>
      <details v-if="connection?.raw_preview">
        <summary>查看脱敏响应预览</summary>
        <pre>{{ connection.raw_preview }}</pre>
      </details>
    </section>
    <section>
      <h3>推理容量</h3>
      <p role="status">{{ capacity || capacityText(model.inference_capacity) }}</p>
      <el-button :disabled="busy" @click="capacityTest">检查已保存容量证据</el-button>
    </section>
    <fieldset :disabled="busy || model.enabled === false">
      <legend>真实样本诊断</legend>
      <p>{{ model.coordinate_validation?.reason || '保存并明确坐标配置后，用真实样本核验。' }}</p>
      <label>真实样本图片（最大 10 MB）<input type="file" accept="image/*" @change="chooseFile"></label>
      <label>目标标签（逗号分隔）<input v-model="labelsText" placeholder="例如 person"></label>
      <label v-if="dedicated">本次验证能力
        <select v-model="operation">
          <option value="detect">检测画框</option>
          <option value="segment">实例分割预览</option>
          <option value="matting">透明抠图预览</option>
        </select>
      </label>
      <p>预览只展示候选结果，无正式 GT 写入。</p>
      <el-button :disabled="busy || model.enabled === false" @click="sampleTest">验证真实样本</el-button>
    </fieldset>
    <p v-if="busy" role="status">正在处理诊断请求…</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <section v-if="sample">
      <template v-if="evidence && sample.image_width && sample.image_height && imageUrl(sample.input_image_url)">
        <p>{{ confirmed ? '已人工确认当前配置与样本的框位置。' : evidence.reason }}</p>
        <p>{{ sample.geometry }}</p>
        <div class="sample-stage">
          <img :src="imageUrl(sample.input_image_url)" alt="EXIF 校正后的真实样本">
          <div
            v-for="(box, index) in boxes" :key="index" class="sample-box"
            :title="box.label"
            :style="{ left: (100 * box.x1 / sample.image_width) + '%', top: (100 * box.y1 / sample.image_height) + '%',
                      width: (100 * (box.x2 - box.x1) / sample.image_width) + '%', height: (100 * (box.y2 - box.y1) / sample.image_height) + '%' }"
          />
        </div>
        <ul v-if="boxes.length">
          <li v-for="(box, index) in boxes" :key="index">
            {{ box.label }} · {{ box.x1 }}, {{ box.y1 }} → {{ box.x2 }}, {{ box.y2 }}
            · {{ box.confidence == null ? '置信度未提供' : Math.round(100 * box.confidence) + '%' }}
          </li>
        </ul>
        <p v-else>本图未检测到目标，需另选含目标的样本才能确认位置。</p>
        <details v-if="sample.raw_preview">
          <summary>查看脱敏响应与最终框</summary>
          <pre>{{ sample.raw_preview }}</pre>
          <pre>{{ JSON.stringify(boxes, null, 2) }}</pre>
        </details>
        <el-button v-if="boxes.length && evidence.receipt" :disabled="busy || confirmed" @click="confirmSample">
          {{ confirmed ? '已确认当前样本' : '框位置正确，确认此配置' }}
        </el-button>
      </template>
      <template v-else>
        <p>共 {{ instances.length }} 个预览实例 · {{ sample.latency_ms ?? 0 }} ms</p>
        <section v-for="(instance, index) in instances" :key="index">
          <h4>目标 {{ index + 1 }} · {{ instance.label || '未提供类别' }}</h4>
          <div class="instance-images">
            <template v-for="(url, name) in instance.images" :key="name">
              <figure v-if="imageUrl(url)">
                <img :src="imageUrl(url)" :alt="String(name)">
                <figcaption>{{ name }}</figcaption>
              </figure>
            </template>
          </div>
        </section>
      </template>
    </section>
  </div>
</template>

<style scoped>
.model-diagnostics { display: grid; gap: 16px; }
.model-diagnostics h3, .model-diagnostics p { margin: 0 0 9px; overflow-wrap: anywhere; }
.model-diagnostics fieldset { display: grid; gap: 10px; border: 1px solid #d4d4d4; border-radius: 6px; }
.model-diagnostics fieldset label { display: grid; gap: 4px; }
.model-diagnostics fieldset input, .model-diagnostics fieldset select { padding: 6px; max-width: 100%; }
.model-diagnostics fieldset .el-button { justify-self: start; }
.sample-stage { position: relative; width: fit-content; max-width: 100%; line-height: 0; }
.sample-stage img, .instance-images img { max-width: 100%; height: auto; }
.sample-box { position: absolute; box-sizing: border-box; border: 2px solid #22c55e; }
.model-diagnostics pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 220px; overflow: auto; }
.instance-images { display: flex; gap: 12px; flex-wrap: wrap; }
.instance-images figure { max-width: 200px; margin: 0; }
</style>

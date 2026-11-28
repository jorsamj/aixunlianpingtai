<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue';
import { renderAiPrompt } from '../api/ai-annotation-create';
import { deletePrompt, savePrompt, type ModelConfig, type PromptConfig, type PromptSettings } from '../api/ai-configuration';

const props = defineProps<{ models: ModelConfig[]; prompts: PromptConfig[]; loading: boolean; loadError: string }>();
const emit = defineEmits<{ refresh: []; retry: [] }>();
const open = ref(false);
const id = ref('');
const busy = ref(false);
const error = ref('');
const status = ref('');
const preview = ref('');
const labelsText = ref('');
const draft = ref<PromptSettings>(defaults());
const controller = new AbortController();

function defaults(): PromptSettings {
  return {
    name: '', model_config_id: '', framework: 'common', task_type: '目标检测',
    labels: ['fire'], threshold: 0.5, save_format: 'internal', output_schema: 'bbox_json',
    prompt: '请检测图片中的目标，返回JSON：{"objects":[{"label":"fire","confidence":0.9,"bbox":[x1,y1,x2,y2]}]}。只返回JSON，不要解释。',
    remark: '', overwrite: false,
  };
}
function edit(item?: PromptConfig) {
  const initial = defaults();
  id.value = item?.id ?? '';
  draft.value = {
    name: item?.name ?? initial.name, model_config_id: item?.model_config_id ?? initial.model_config_id,
    framework: item?.framework ?? initial.framework, task_type: item?.task_type ?? initial.task_type,
    labels: item?.labels ?? initial.labels, threshold: item?.threshold ?? initial.threshold,
    save_format: item?.save_format ?? initial.save_format, output_schema: item?.output_schema ?? initial.output_schema,
    prompt: item?.prompt ?? initial.prompt, remark: item?.remark ?? initial.remark,
    overwrite: item?.overwrite ?? initial.overwrite,
  };
  labelsText.value = draft.value.labels.join(',');
  error.value = '';
  preview.value = '';
  open.value = true;
}
function labels() {
  return labelsText.value.split(/[,，\n]/).map(value => value.trim()).filter(Boolean);
}
async function run(action: () => Promise<void>) {
  if (busy.value) return;
  busy.value = true;
  error.value = '';
  status.value = '';
  try {
    await action();
  } catch (failure) {
    if (!controller.signal.aborted) error.value = failure instanceof Error ? failure.message : '操作失败，请重试。';
  } finally {
    busy.value = false;
  }
}
function save() {
  if (!draft.value.name.trim() || !draft.value.prompt.trim() || !Number.isFinite(draft.value.threshold) || draft.value.threshold < 0 || draft.value.threshold > 1) {
    error.value = '请填写模板名称、提示词和 0 至 1 之间的置信度阈值。';
    return;
  }
  return run(async () => {
    const saved = await savePrompt(id.value, { ...draft.value, labels: labels() }, controller.signal);
    if (!saved.id) throw new Error('未取得模板保存结果，请刷新列表确认。');
    open.value = false;
    status.value = '已保存模型标注模板。';
    emit('refresh');
  });
}
function remove(item: PromptConfig) {
  if (!window.confirm(`确认删除模板“${item.name}”？`)) return;
  return run(async () => {
    const result = await deletePrompt(item.id, controller.signal);
    if (!result.ok) throw new Error('未取得删除结果，请刷新列表确认。');
    status.value = '已删除模板。';
    emit('refresh');
  });
}
function renderPreview() {
  preview.value = '';
  return run(async () => {
    const result = await renderAiPrompt({
      prompt: draft.value.prompt, labels: labels().map(code => ({ code, display_name_zh: code })),
      image_width: 640, image_height: 480, business_instruction: '',
    }, controller.signal);
    preview.value = result.rendered_prompt;
  });
}
onBeforeUnmount(() => controller.abort());
</script>

<template>
  <section class="panel ai-prompt">
    <header class="section-head">
      <h2>通用提示词模板</h2>
      <el-button :disabled="loading || busy" @click="edit()">新增模板</el-button>
    </header>
    <p v-if="loadError" role="alert">{{ loadError }} <el-button @click="emit('retry')">重试</el-button></p>
    <p v-if="!open && error" role="alert">{{ error }}</p>
    <p v-if="status" role="status">{{ status }}</p>
    <el-table v-loading="loading" :data="prompts" empty-text="暂无提示词模板">
      <el-table-column prop="name" label="名称" min-width="165" />
      <el-table-column prop="framework" label="框架" min-width="110" />
      <el-table-column label="标签" min-width="130">
        <template #default="{ row }">{{ row.labels?.join('、') || '—' }}</template>
      </el-table-column>
      <el-table-column prop="save_format" label="保存格式" min-width="105" />
      <el-table-column label="关联模型" min-width="150">
        <template #default="{ row }">{{ row.model_config_id ? models.find(model => model.id === row.model_config_id)?.name || row.model_config_id : '不指定' }}</template>
      </el-table-column>
      <el-table-column label="操作" width="170">
        <template #default="{ row }">
          <el-button size="small" :disabled="busy" @click="edit(row)">编辑</el-button>
          <el-button size="small" :disabled="busy" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-dialog v-model="open" :title="id ? '编辑模型标注模板' : '新增模型标注模板'" width="min(700px, 95vw)" :close-on-click-modal="false" :close-on-press-escape="!busy" :show-close="!busy" destroy-on-close>
      <el-form label-position="top" class="prompt-form" :disabled="busy" @submit.prevent="save">
        <el-form-item label="模板名称" required><el-input v-model="draft.name" /></el-form-item>
        <el-form-item label="关联模型">
          <el-select v-model="draft.model_config_id">
            <el-option label="不指定" value="" />
            <el-option v-if="draft.model_config_id && !props.models.some(model => model.id === draft.model_config_id)" :label="draft.model_config_id" :value="draft.model_config_id" />
            <el-option v-for="model in models" :key="model.id" :label="model.name || model.id" :value="model.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="训练框架">
          <el-select v-model="draft.framework">
            <el-option label="通用" value="common" />
            <el-option label="Ultralytics / YOLO" value="ultralytics" />
            <el-option label="飞桨 / PaddleDetection" value="paddle" />
          </el-select>
        </el-form-item>
        <el-form-item label="保存格式">
          <el-select v-model="draft.save_format">
            <el-option label="仅保存平台标注" value="internal" />
            <el-option label="YOLO 训练格式" value="yolo" />
            <el-option label="Paddle / COCO 训练格式" value="paddle" />
          </el-select>
        </el-form-item>
        <el-form-item label="目标标签（逗号分隔）"><el-input v-model="labelsText" /></el-form-item>
        <el-form-item label="置信度阈值"><el-input-number v-model="draft.threshold" :min="0" :max="1" :step="0.05" /></el-form-item>
        <el-form-item label="提示词" class="full" required><el-input v-model="draft.prompt" type="textarea" :rows="7" /></el-form-item>
        <el-form-item label="备注" class="full"><el-input v-model="draft.remark" /></el-form-item>
      </el-form>
      <p v-if="error" role="alert">{{ error }}</p>
      <section v-if="preview" aria-label="提示词渲染预览">
        <h3>渲染预览 · 640 × 480</h3>
        <pre>{{ preview }}</pre>
      </section>
      <template #footer>
        <el-button :disabled="busy" @click="open = false">取消</el-button>
        <el-button :disabled="busy" @click="renderPreview">预览提示词</el-button>
        <el-button type="primary" :loading="busy" @click="save">保存模板</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.ai-prompt { padding: 18px; }
.section-head { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.section-head h2 { margin: 0; font-size: 18px; }
.prompt-form { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(240px, 100%), 1fr)); gap: 0 16px; }
.full { grid-column: 1 / -1; }
.ai-prompt pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 260px; overflow: auto; }
</style>

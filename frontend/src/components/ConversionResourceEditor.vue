<script setup lang="ts">
import {reactive} from 'vue';
import type {ResourceConfiguration} from '../api/conversion-environment';
import type {DeployResource} from '../types/conversion-job';

const props=defineProps<{resource:DeployResource|null;kinds:Record<string,string>;busy:boolean;error:string}>();
const emit=defineEmits<{close:[];save:[configuration:ResourceConfiguration]}>();
const row=props.resource;
const form=reactive<ResourceConfiguration>({
  name:row?.name||'',kind:row?.kind||'sophon',
  mode:row?.mode==='agent'||row?.mode==='remote'?row.mode:'local',
  base_url:row?.base_url||'',api_key:'',python_path:row?.python_path||'',
  ultralytics_python:row?.ultralytics_python||'',paddledet_dir:row?.paddledet_dir||'',
  paddle2onnx_path:row?.paddle2onnx_path||'',tool_root:row?.tool_root||'',
  trtexec_path:row?.trtexec_path||'',atc_path:row?.atc_path||'',
  env_script:row?.env_script||'',remark:row?.remark||'',
});

function submit(){
  if(props.busy||!form.name.trim())return;
  emit('save',{...form});
  form.api_key='';
}
</script>

<template>
 <el-dialog :model-value="true" :title="resource?'编辑部署资源':'新增部署资源'"
  width="min(620px, 95vw)" :close-on-click-modal="false" :close-on-press-escape="!busy" :show-close="!busy" @close="emit('close')">
  <form class="resource-form" @submit.prevent="submit">
   <el-alert v-if="error" :title="error" type="error" :closable="false"/>
   <label>资源名称<el-input v-model="form.name" aria-label="资源名称" :disabled="busy" required/></label>
   <label>运行位置<el-select v-model="form.mode" aria-label="运行位置" :disabled="busy">
    <el-option label="本机" value="local"/><el-option label="远程转换服务器" value="remote"/><el-option label="服务节点 Agent" value="agent"/>
   </el-select></label>
   <label>资源类型<el-select v-model="form.kind" aria-label="资源类型" :disabled="busy">
    <el-option v-if="!(form.kind in kinds)" :label="form.kind" :value="form.kind"/>
    <el-option v-for="(label,kind) in kinds" :key="kind" :label="label" :value="kind"/>
   </el-select></label>
   <template v-if="form.mode==='remote'">
    <label>服务地址<el-input v-model="form.base_url" aria-label="服务地址" :disabled="busy"/></label>
    <label>API Key<el-input v-model="form.api_key" aria-label="API Key" type="password" autocomplete="new-password" :disabled="busy"
     :placeholder="resource?.has_api_key?'已配置，留空继续使用原密钥':'请输入 API Key'"/></label>
   </template>
   <template v-if="form.mode==='local'">
    <label>工具目录<el-input v-model="form.tool_root" aria-label="工具目录" :disabled="busy"/></label>
    <label>Python 路径<el-input v-model="form.python_path" aria-label="Python 路径" :disabled="busy" placeholder="留空使用平台 Python"/></label>
    <label v-if="form.kind==='ultralytics'">Ultralytics Python 路径<el-input v-model="form.ultralytics_python" aria-label="Ultralytics Python 路径" :disabled="busy"/></label>
    <template v-if="form.kind==='paddle'">
     <label>PaddleDetection 目录<el-input v-model="form.paddledet_dir" aria-label="PaddleDetection 目录" :disabled="busy"/></label>
     <label>paddle2onnx<el-input v-model="form.paddle2onnx_path" aria-label="paddle2onnx" :disabled="busy"/></label>
    </template>
    <label v-if="form.kind==='tensorrt'">trtexec 路径<el-input v-model="form.trtexec_path" aria-label="trtexec 路径" :disabled="busy"/></label>
    <template v-if="form.kind==='ascend'">
     <label>ATC 路径<el-input v-model="form.atc_path" aria-label="ATC 路径" :disabled="busy"/></label>
     <label>CANN 环境脚本<el-input v-model="form.env_script" aria-label="CANN 环境脚本" :disabled="busy" placeholder="/usr/local/Ascend/ascend-toolkit/set_env.sh"/></label>
    </template>
   </template>
   <label>备注<el-input v-model="form.remark" aria-label="备注" :disabled="busy"/></label>
   <footer><el-button :disabled="busy" @click="emit('close')">取消</el-button>
    <el-button type="primary" native-type="submit" :loading="busy" :disabled="!form.name.trim()">保存并返回</el-button></footer>
  </form>
 </el-dialog>
</template>

<style scoped>
.resource-form{display:grid;gap:12px}.resource-form label{display:grid;gap:5px}.resource-form footer{display:flex;justify-content:flex-end}
</style>

<script setup lang="ts">
import {computed,onBeforeUnmount,reactive,shallowRef} from 'vue';
import {readLabels,writeLabel,type ProjectLabel,type LabelFields} from '../api/label-management';
import {browseError} from '../api/model-browse';
const props=defineProps<{projectId:string;label:ProjectLabel|null}>();
const emit=defineEmits<{saved:[];close:[];pending:[value:boolean]}>();
const controller=new AbortController();
onBeforeUnmount(()=>controller.abort());
const form=reactive({code:props.label?.code||'',display_name:props.label?.display_name||'',color:props.label?.color||'',hotkey:props.label?.hotkey||'',aliases:(props.label?.aliases||[]).join('\n')});
const busy=shallowRef(false),unknown=shallowRef(false),error=shallowRef('');
let submitted:LabelFields|null=null;
const valid=computed(()=>/^[A-Za-z][A-Za-z0-9_-]*$/.test(form.code));
function setUnknown(value:boolean){unknown.value=value;emit('pending',value)}
async function verify(){
  if(!submitted)return;
  const result=await readLabels(props.projectId,controller.signal);
  const row=result.items.find(row=>props.label?row.class_id===props.label.class_id:row.code===submitted?.code);
  const expected=submitted;
  if(!row||row.code!==expected.code||(row.display_name||row.code)!==(expected.display_name||expected.code)||(!!expected.color&&row.color!==expected.color)||
    (props.label&&(row.hotkey||'')!==expected.hotkey)||JSON.stringify([...(row.aliases||[])].sort())!==JSON.stringify([...expected.aliases].sort()))throw new Error('当前标签与提交内容不同，请核对后再操作。');
  setUnknown(false);emit('saved');
}
async function check(){busy.value=true;error.value='';try{await verify()}catch(cause){if(!controller.signal.aborted)error.value=browseError(cause)}finally{busy.value=false}}
async function save(){
  if(busy.value||unknown.value||!valid.value)return;
  submitted={code:form.code,display_name:form.display_name,color:form.color,hotkey:form.hotkey,aliases:[...new Set(form.aliases.split(/\n/).map(value=>value.trim()).filter(Boolean))]};
  busy.value=true;error.value='';
  try{
    setUnknown(true);
    try{await writeLabel(props.projectId,props.label?.class_id??null,submitted)}catch(cause){
      const status=(cause as {httpStatus?:number}).httpStatus;
      if(status&&[400,401,403,404,409,422].includes(status))setUnknown(false);
      throw cause;
    }
    await verify();
  }catch(cause){if(!controller.signal.aborted)error.value=browseError(cause)}finally{busy.value=false}
}
</script>
<template><form class="label-form" @submit.prevent="save">
 <el-alert v-if="error" :title="error" type="error" :closable="false"/>
 <el-alert v-if="unknown" title="保存结果待核对，请勿重复提交。" type="warning" :closable="false"/>
 <fieldset :disabled="busy||unknown"><label>标签编码<el-input v-model="form.code" aria-label="标签编码" :disabled="busy||unknown"/><small>以英文字母开头，可包含数字、_ 和 -。</small></label>
 <label>显示名称<el-input v-model="form.display_name" aria-label="标签显示名称" :disabled="busy||unknown"/></label>
 <div class="label-form-row"><label>标注颜色<el-color-picker v-model="form.color" aria-label="标注颜色" :disabled="busy||unknown"/><small v-if="!label">不设置时使用自动配色。</small></label><label v-if="label">快捷键<el-input v-model="form.hotkey" aria-label="标签快捷键" :disabled="busy||unknown"/></label></div>
 <label>别名<el-input v-model="form.aliases" type="textarea" :rows="3" aria-label="标签别名" placeholder="每行一个别名" :disabled="busy||unknown"/></label></fieldset>
 <footer><el-button :disabled="busy||unknown" @click="emit('close')">取消</el-button><el-button v-if="unknown" type="primary" :loading="busy" @click="check">核对保存结果</el-button><el-button v-else type="primary" native-type="submit" :loading="busy" :disabled="!valid">保存</el-button></footer>
</form></template>
<style scoped>
.label-form{display:grid;gap:18px}.label-form fieldset{border:0;padding:0;margin:0;display:grid;gap:18px;min-width:0}.label-form label{display:grid;gap:7px;font-size:13px}.label-form small{color:#737373}.label-form-row{display:grid;grid-template-columns:1fr 1fr;gap:18px}.label-form input[type=color]{height:32px;width:72px;padding:2px;border:1px solid #ddd;border-radius:4px;background:#fff}.label-form footer{display:flex;justify-content:flex-end;gap:8px}
</style>

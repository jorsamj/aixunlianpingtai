<script setup lang="ts">
import {onMounted,reactive,ref} from 'vue';
import type {BrowseContext} from '../types/model-browse';
import {algorithmManagementApi,type AlgorithmForm,type AlgorithmBasic} from '../api/algorithm-management';
import ReadOnlyFacts from './ReadOnlyFacts.vue';
import {browseError} from '../api/model-browse';
import {useReadScope} from '../composables/useReadScope';
const props=defineProps<{context:BrowseContext;algorithmId:string}>(),emit=defineEmits<{saved:[id:string];close:[]}>();
const api=algorithmManagementApi(props.context),reads=useReadScope(props.context),saving=ref(false),editable=ref(!props.algorithmId),error=ref('');
const form=reactive<AlgorithmForm>({name:'',remark:'',industry:'',algorithm_type:''});
const basic=ref<AlgorithmBasic|null>(null);
onMounted(()=>{if(props.algorithmId)void reads.run('basic',signal=>api.basic(props.algorithmId,signal),row=>{basic.value=row;Object.assign(form,{name:row.name,remark:row.remark||'',industry:row.industry||'',algorithm_type:row.algorithm_type||''});editable.value=row.editable})});
async function save(){if(!editable.value||saving.value||props.context.algorithmPending?.value)return;error.value='';form.name=form.name.trim();form.industry=form.industry.trim();form.algorithm_type=form.algorithm_type.trim();if(!form.name){error.value='请填写算法名称';return}saving.value=true;props.context.algorithmPending?.save({algorithmId:props.algorithmId,body:{...form}});
 try{const saved=await api.save(props.algorithmId,{...form},props.context.signal);props.context.algorithmPending?.save(null);if(!props.context.signal.aborted)emit('saved',saved.id)}catch(cause){if(props.context.signal.aborted)return;if((cause as {writeRejected?:boolean}).writeRejected)props.context.algorithmPending?.save(null);error.value=browseError(cause)}finally{saving.value=false}}
</script>
<template><div class="algorithm-editor"><el-alert v-if="error||reads.errors.basic" :title="error||reads.errors.basic" type="error" :closable="false"/><el-skeleton v-if="reads.busy.basic" :rows="5" animated/><form v-else @submit.prevent="save"><ReadOnlyFacts v-if="basic" :fields="[['算法 ID',basic.id],['来源',basic.source_type],['当前版本 ID',basic.current_version_id]]"/><label>算法名称<el-input v-model="form.name" aria-label="算法名称" :disabled="!editable||saving" maxlength="160"/></label><label>行业 / 分类<el-input v-model="form.industry" aria-label="行业分类" :disabled="!editable||saving" maxlength="160"/></label><label>算法类型<el-input v-model="form.algorithm_type" aria-label="算法类型标识" placeholder="沿用原算法类型标识，例如 custom_python" :disabled="!editable||saving" maxlength="160"/></label><label>备注<el-input v-model="form.remark" type="textarea" aria-label="算法备注" :disabled="!editable||saving" maxlength="4000"/></label><p v-if="algorithmId&&!editable" class="evidence-note">此记录为外部只读、超出本页读取边界或尚未读取成功，请使用原管理入口。</p><div class="preview-actions"><el-button :disabled="saving" @click="emit('close')">关闭</el-button><el-button native-type="submit" type="primary" :loading="saving" :disabled="!editable||!!context.algorithmPending?.value">保存并核验</el-button></div></form></div></template>

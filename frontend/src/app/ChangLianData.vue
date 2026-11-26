<script setup lang="ts">
import {computed,ref,shallowRef,watch} from 'vue';
import {ElMessage} from 'element-plus';
import {providerItems,providerDetail,productIdentity,versionIdentity,weightIdentity,weightRemoteLink,remoteField,tagsView} from '../../../static/modules/changlian-data-browser.js';
import {changLianProvider as provider,isProviderId,readWeightDetail,weightDetailGroups,type WeightSelection} from '../api/changlian-weight-details';
import {useReadScope} from '../composables/useReadScope';
import {request} from './http';
import {legacyUrl} from './navigation';

const {projectId}=defineProps<{projectId:string}>();
type Row=Record<string,unknown>;
const reads=useReadScope(new AbortController());
const products=ref<{row:Row;enabled:boolean}[]>([]),versions=ref<Row[]>([]),weights=ref<Row[]>([]);
const product=ref(''),version=ref(''),query=ref(''),time=ref(''),sourceStatus=ref('');
const show=ref(false),showEvidence=ref(false);
const selected=shallowRef<WeightSelection>();
const detail=shallowRef<Awaited<ReturnType<typeof readWeightDetail>>>();
const detailTags=computed(()=>detail.value && tagsView(detail.value.tags));
const rawEvidence=computed(()=>detail.value ? JSON.stringify(detail.value.evidence,null,2) : '');
const productName=(row:Row)=>String(row.productName||row.name||productIdentity(row));
const versionName=(row:Row)=>String(row.versionName||row.name||versionIdentity(row));
const selectionLabel=computed(()=>{
  const current=selected.value;
  if(!current)return '';
  const productRow=products.value.find(item=>productIdentity(item.row)===current.productId)?.row;
  const versionRow=versions.value.find(row=>versionIdentity(row)===current.versionId);
  return `${productRow ? productName(productRow) : current.productId} / ${versionRow ? versionName(versionRow) : current.versionId}`;
});
const filtered=computed(()=>products.value.filter(item=>
  (!sourceStatus.value||String(item.enabled)===sourceStatus.value)&&
  (!query.value||[productName(item.row),productIdentity(item.row)].some(value=>value.toLowerCase().includes(query.value.trim().toLowerCase())))));
function clearVersion(){
  reads.cancel('weights');closeDetail();
  version.value='';weights.value=[];show.value=false;
}
function clearProduct(){
  reads.cancel('versions');clearVersion();product.value='';versions.value=[];
}
function refresh(){
  if(reads.busy.products)return;
  return reads.run('products',async signal=>{
    const results=await Promise.all([1,0].map(status=>request(provider+'/products?status='+status,{signal})));
    const seen=new Set<string>();
    return results.flatMap((value,index)=>providerItems(providerDetail(value)).flatMap(row=>{
      const id=productIdentity(row);
      if(!isProviderId(id)||seen.has(id))return [];
      seen.add(id);return [{row,enabled:index===0}];
    }));
  },value=>{clearProduct();products.value=value;time.value=new Date().toLocaleString()});
}
function chooseProduct(row:Row){
  clearProduct();
  const id=productIdentity(row);
  if(!isProviderId(id))return;
  product.value=id;
  return reads.run('versions',signal=>request(provider+'/versions/by-product/'+encodeURIComponent(id),{signal}),value=>{
    if(product.value===id)versions.value=providerItems(providerDetail(value));
  });
}
function chooseVersion(row:Row){
  clearVersion();
  const id=versionIdentity(row);
  if(!isProviderId(id))return;
  version.value=id;
  return reads.run('weights',signal=>request(provider+'/weights/by-version/'+encodeURIComponent(id),{signal}),value=>{
    if(version.value===id)weights.value=providerItems(providerDetail(value));
  });
}
function openWeight(row:Row){
  const weightId=weightIdentity(row),productId=product.value,versionId=version.value;
  if(![weightId,productId,versionId].every(isProviderId))return;
  selected.value={weightId,productId,versionId,listWeight:row};
  show.value=true;
  return loadDetail();
}
function loadDetail(){
  const current=selected.value;
  if(!current)return;
  detail.value=undefined;showEvidence.value=false;
  return reads.run('detail',signal=>readWeightDetail(current,signal),value=>{detail.value=value});
}
function closeDetail(){
  reads.cancel('detail');selected.value=undefined;detail.value=undefined;showEvidence.value=false;
}
function canCopyField(key:string,value:unknown){
  return ['weightId','filePath','fileSha256'].includes(key)&&
    (typeof value==='string'||typeof value==='number')&&String(value)!=='';
}
async function copy(value:unknown){
  try{
    await navigator.clipboard.writeText(String(value));
    ElMessage.success('已复制');
  }catch{
    ElMessage.error('复制失败，请检查浏览器剪贴板权限。');
  }
}
watch(()=>projectId,()=>{
  reads.cancel('products');
  clearProduct();
  products.value=[];time.value='';query.value='';sourceStatus.value='';
});
</script>

<template>
  <section class="cloud-browser">
    <header>
      <div><h2>畅联云数据</h2><small>{{time?'最近读取 '+time:'尚未读取畅联云'}}</small></div>
      <div class="tools">
        <router-link :to="{name:'platform-integration',params:{projectId}}">同步配置</router-link>
        <a :href="legacyUrl(projectId,'畅联云数据')">原数据查看</a>
        <el-button type="primary" :loading="reads.busy.products" @click="refresh">读取畅联云</el-button>
      </div>
    </header>
    <el-alert v-if="reads.errors.products" :title="reads.errors.products" type="error" :closable="false"/>
    <div v-if="time" class="browser-grid">
      <section>
        <h3>算法产品</h3>
        <div class="tools">
          <el-input v-model="query" placeholder="名称或产品 ID" aria-label="搜索算法产品" clearable/>
          <el-select v-model="sourceStatus" aria-label="产品状态">
            <el-option label="全部状态" value=""/><el-option label="启用" value="true"/><el-option label="停用" value="false"/>
          </el-select>
        </div>
        <el-table :data="filtered" max-height="480" empty-text="暂无符合条件的产品">
          <el-table-column label="名称 / ID" min-width="174"><template #default="{row}">
            <el-button link :type="product===productIdentity(row.row)?'primary':''" @click="chooseProduct(row.row)">{{productName(row.row)}}</el-button>
            <small>{{productIdentity(row.row)}}</small>
          </template></el-table-column>
          <el-table-column label="状态" width="70"><template #default="{row}">{{row.enabled?'启用':'停用'}}</template></el-table-column>
        </el-table>
      </section>
      <section>
        <h3>算法版本</h3>
        <el-alert v-if="reads.errors.versions" :title="reads.errors.versions" type="error" :closable="false"/>
        <el-table :data="versions" v-loading="reads.busy.versions" max-height="480" :empty-text="product?'暂无版本':'请先选择算法产品'">
          <el-table-column label="版本 / ID"><template #default="{row}">
            <el-button link :type="version===versionIdentity(row)?'primary':''" @click="chooseVersion(row)">{{versionName(row)}}</el-button>
            <small>{{versionIdentity(row)}}</small>
          </template></el-table-column>
        </el-table>
      </section>
      <section>
        <h3>权重与转换结果</h3>
        <el-alert v-if="reads.errors.weights" :title="reads.errors.weights" type="error" :closable="false"/>
        <el-table :data="weights" v-loading="reads.busy.weights" max-height="480" :empty-text="version?'暂无权重':'请先选择算法版本'">
          <el-table-column label="文件 / ID"><template #default="{row}">
            <el-button link @click="openWeight(row)">{{row.fileName||weightIdentity(row)}}</el-button><small>{{row.chipCode||weightIdentity(row)}}</small>
          </template></el-table-column>
        </el-table>
      </section>
    </div>
    <el-dialog v-model="show" title="权重文件详情" width="min(840px, 94vw)" @close="closeDetail">
      <p v-if="selectionLabel" class="weight-context">列表位置 · {{selectionLabel}} · Weight ID {{selected?.weightId}}</p>
      <div v-if="reads.errors.detail" class="detail-section">
        <el-alert :title="reads.errors.detail" type="error" :closable="false"/>
        <el-button @click="loadDetail">重新加载</el-button>
      </div>
      <el-skeleton v-else-if="reads.busy.detail" :rows="4" animated/>
      <p v-else-if="detail===null">远端没有返回详情。</p>
      <template v-else-if="detail">
        <div class="detail-sections">
          <el-alert v-if="detail.differences.length" title="列表信息已变化，请手动刷新列表。" type="warning" :closable="false">
            <ul><li v-for="difference in detail.differences" :key="difference">{{difference}}</li></ul>
          </el-alert>
          <section v-if="detailTags" class="detail-section">
            <header><h3>标签信息</h3><small>{{detail.source}}</small></header>
            <p :data-tags-state="detailTags.state">{{detailTags.label}}<template v-if="Array.isArray(detail.tags.tags)"> · {{detailTags.items.length}} 项</template></p>
            <div v-if="detailTags.items.length" class="tools">
              <el-tag v-for="(tag,index) in detailTags.items" :key="index" type="info">{{tag===''?'空字符串':tag}}</el-tag>
            </div>
            <el-alert v-if="detail.tagsError" :title="'标签查询失败：'+detail.tagsError" type="error" :closable="false"/>
            <el-button v-if="detail.tagsError" @click="loadDetail">重新加载</el-button>
          </section>
          <section v-for="group in weightDetailGroups" :key="group.name" class="detail-section">
            <h3>{{group.name}}</h3>
            <p v-if="group.name==='模型基本信息'">输入尺寸 · {{remoteField(detail.data,'imageWidth')}} × {{remoteField(detail.data,'imageHeight')}}</p>
            <dl class="detail">
              <div v-for="[key,label] in group.fields" :key="key">
                <dt>{{label}}</dt>
                <dd>
                  {{remoteField(detail.data,key)}}
                  <el-button v-if="canCopyField(key,detail.data[key])" link :aria-label="'复制'+label" @click="copy(detail.data[key])">复制</el-button>
                </dd>
              </div>
            </dl>
          </section>
          <a v-if="weightRemoteLink(detail.data)" :href="weightRemoteLink(detail.data)" target="_blank" rel="noopener noreferrer">打开文件下载地址</a>
          <details @toggle="showEvidence=($event.currentTarget as HTMLDetailsElement).open">
            <summary>完整原始数据</summary>
            <template v-if="showEvidence">
              <el-button @click="copy(rawEvidence)">复制原始数据</el-button>
              <pre class="raw-evidence">{{rawEvidence}}</pre>
            </template>
          </details>
        </div>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.cloud-browser{display:grid;gap:14px;min-width:0}
.cloud-browser header,.tools{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.cloud-browser header{justify-content:space-between}
.cloud-browser h2,.cloud-browser h3{margin:0 0 8px}
.browser-grid{display:grid;grid-template-columns:minmax(250px,1fr) minmax(160px,.8fr) minmax(225px,1fr);gap:14px}
.browser-grid>section{min-width:0}
.tools .el-input{width:160px}
.tools .el-select{width:110px}
.browser-grid small{display:block}
.detail{display:grid;grid-template-columns:repeat(auto-fit,minmax(185px,1fr));gap:12px}
.detail dd{margin:4px 0 0;overflow-wrap:anywhere}
.weight-context,.detail-section,.detail-sections{overflow-wrap:anywhere}
.detail-sections,.detail-section{display:grid;gap:8px}
.detail-section>h3,.detail-section>p,.detail-section>dl{margin:0}
.detail-section{border-bottom:1px solid var(--el-border-color);padding-block:8px}
.detail-section>.el-button{justify-self:start}
.raw-evidence{max-height:22rem;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere}
@media(max-width:1050px){.browser-grid{grid-template-columns:1fr}}
</style>

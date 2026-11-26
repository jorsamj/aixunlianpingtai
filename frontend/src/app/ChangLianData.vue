<script setup lang="ts">
import {computed,ref} from 'vue';
import {providerItems,providerDetail,productIdentity,versionIdentity,weightIdentity,weightRemoteLink,remoteField,tagsView} from '../../../static/modules/changlian-data-browser.js';
import {useReadScope} from '../composables/useReadScope';
import {request} from './http';
import {legacyUrl} from './navigation';

const {projectId}=defineProps<{projectId:string}>();
type Row=Record<string,unknown>;
const provider='/api/v63/external-algorithm-platform/provider';
const reads=useReadScope(new AbortController());
const products=ref<{row:Row;enabled:boolean}[]>([]),versions=ref<Row[]>([]),weights=ref<Row[]>([]);
const product=ref(''),version=ref(''),query=ref(''),time=ref(''),sourceStatus=ref('');
const show=ref(false),weight=ref(''),detail=ref<Row|null>();
const detailFields=[
  ['weightId','权重文件 ID'],['productId','产品 ID'],['algoVersionId','版本 ID'],['fileName','文件名称'],['fileSize','文件大小'],
  ['fileSha256','SHA256'],['computePlatformName','算力环境'],['chipCode','芯片'],['filePath','文件地址'],
  ['imageWidth','输入宽度'],['imageHeight','输入高度'],['updateTime','更新时间'],['remark','备注'],
];
const productName=(row:Row)=>String(row.productName||row.name||productIdentity(row));
const versionName=(row:Row)=>String(row.versionName||row.name||versionIdentity(row));
const filtered=computed(()=>products.value.filter(item=>
  (!sourceStatus.value||String(item.enabled)===sourceStatus.value)&&
  (!query.value||[productName(item.row),productIdentity(item.row)].some(value=>value.toLowerCase().includes(query.value.trim().toLowerCase())))));
const safeId=(id:string)=>/^[1-9][0-9]{0,18}$/.test(id)&&BigInt(id)<=9223372036854775807n;
function clearVersion(){
  reads.cancel('weights');reads.cancel('detail');
  version.value='';weights.value=[];weight.value='';detail.value=undefined;show.value=false;
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
      if(!safeId(id)||seen.has(id))return [];
      seen.add(id);return [{row,enabled:index===0}];
    }));
  },value=>{clearProduct();products.value=value;time.value=new Date().toLocaleString()});
}
function chooseProduct(row:Row){
  clearProduct();
  const id=productIdentity(row);
  if(!safeId(id))return;
  product.value=id;
  return reads.run('versions',signal=>request(provider+'/versions/by-product/'+encodeURIComponent(id),{signal}),value=>{
    if(product.value===id)versions.value=providerItems(providerDetail(value));
  });
}
function chooseVersion(row:Row){
  clearVersion();
  const id=versionIdentity(row);
  if(!safeId(id))return;
  version.value=id;
  return reads.run('weights',signal=>request(provider+'/weights/by-version/'+encodeURIComponent(id),{signal}),value=>{
    if(version.value===id)weights.value=providerItems(providerDetail(value));
  });
}
function openWeight(row:Row){
  const id=weightIdentity(row),productId=product.value,versionId=version.value;
  if(!safeId(id))return;
  show.value=true;weight.value=id;detail.value=undefined;
  return reads.run('detail',signal=>request(provider+'/weights/'+encodeURIComponent(id)+'?withTags=true',{signal}),value=>{
    const found=providerDetail(value).data;
    if(weight.value!==id||product.value!==productId||version.value!==versionId)return;
    if(found===null){detail.value=null;return}
    if(!found||typeof found!=='object'||Array.isArray(found)||
      weightIdentity(found)!==id||
      (found.productId!==undefined&&String(found.productId)!==productId)||
      (found.algoVersionId!==undefined&&String(found.algoVersionId)!==versionId))
      throw new Error('权重详情与所选产品、版本或文件身份不一致');
    detail.value=found;
  });
}
function closeDetail(){reads.cancel('detail');weight.value='';detail.value=undefined}
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
    <el-dialog v-model="show" title="权重文件详情" width="min(840px, 94vw)" @closed="closeDetail">
      <el-alert v-if="reads.errors.detail" :title="reads.errors.detail" type="error" :closable="false"/>
      <el-skeleton v-else-if="reads.busy.detail" :rows="4" animated/>
      <p v-else-if="detail===null">远端没有返回详情。</p>
      <template v-else-if="detail">
        <dl class="detail"><div v-for="[key,label] in detailFields" :key="key"><dt>{{label}}</dt><dd>{{remoteField(detail,key)}}</dd></div></dl>
        <p>{{tagsView(detail).items.join('、')||tagsView(detail).label}}</p>
        <a v-if="weightRemoteLink(detail)" :href="weightRemoteLink(detail)" target="_blank" rel="noopener noreferrer">打开文件下载地址</a>
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
@media(max-width:1050px){.browser-grid{grid-template-columns:1fr}}
</style>

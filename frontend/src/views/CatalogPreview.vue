<script setup lang="ts">
import {onMounted,onUnmounted} from 'vue';
import {useCatalogView} from '../stores/catalog';
import type {CatalogAction,Entity,PreviewContext} from '../types/catalog';
import PageHeader from '../components/PageHeader.vue';
import CatalogEditor from '../components/CatalogEditor.vue';
import CatalogReferences from '../components/CatalogReferences.vue';
import PendingOperation from '../components/PendingOperation.vue';
const props=defineProps<{context:PreviewContext}>();
const view=useCatalogView();
const entities:Entity[]=['vendors','chips'];
const names={vendors:'厂商',chips:'芯片'};
// Status and its label are backend evidence, never inferred from templates or SDK booleans.
const readiness=(fact?:{status?:string;status_label?:string})=>fact?.status_label || fact?.status || '未核验';
const tone=(fact?:{status?:string})=>fact?.status==='convertible'?'success':['not_convertible','detection_failed','service_unavailable'].includes(fact?.status || '')?'danger':'info';
function rowAction(entity:Entity,id:string,command:CatalogAction|'detect'){if(command==='detect')void view.detect(id);else void view.openEditor(entity,id,command)}
function search(entity:Entity){view.filters[entity].page=1;void view.load(entity)}
function page(entity:Entity,value:number){view.filters[entity].page=value;void view.load(entity)}
onMounted(()=>void view.initialize(props.context));
onUnmounted(()=>{view.dispose();view.$dispose()});
</script>

<template>
  <section class="catalog-preview" :aria-label="context.management?'厂商与芯片字典正式管理':'厂商与芯片字典只读预览'">
    <PageHeader title="厂商与芯片" eyebrow="转换资源 / 字典目录" :description="context.management?'维护厂商与芯片身份，查看已有转换能力证据。':'浏览厂商、芯片型号与已有转换能力证据。'" :badge="context.management?'正式管理 · 并行验证':'只读预览'" @back="context.returnToManagement"/>
    <el-alert v-if="view.notice" :title="view.notice" type="success" :closable="false"/>
    <el-alert v-if="view.writeError&&!view.editing" :title="view.writeError" type="error" :closable="false"/>
    <PendingOperation v-if="!view.editing"/>
    <div class="preview-overview" aria-label="当前查询概况">
      <div><span>筛选后厂商</span><strong>{{ view.pages.vendors?.total ?? '—' }}</strong></div>
      <div><span>当前厂商</span><strong class="preview-current">{{ view.selectedName || '尚未选择' }}</strong></div>
      <div><span>筛选后芯片</span><strong>{{ view.pages.chips?.total ?? '—' }}</strong></div>
      <p>{{ context.management?'转换资格以服务端核验为准。':'编辑、检测与转换请前往完整管理。' }}<br>未知状态不代表已验证。</p>
    </div>
    <div class="preview-columns">
      <section v-for="entity in entities" :key="entity" class="preview-surface" :aria-label="`${names[entity]}列表`" :aria-busy="view.busy[entity]">
        <header class="preview-section-head"><div><h2>{{ entity==='vendors'?'厂商目录':`${view.selectedName || '厂商'} · 芯片型号` }}</h2><span>{{ entity==='vendors'?'选择厂商查看对应芯片':'能力来自已有资源证据' }}</span></div><div class="preview-actions"><el-button text :disabled="view.busy[entity] || (entity==='chips'&&!view.selected)" @click="view.load(entity)">刷新</el-button><el-button v-if="context.management" type="primary" :disabled="!!view.pending||view.saving||(entity==='chips'&&!view.selected)" @click="view.openEditor(entity)">新增{{ names[entity] }}</el-button></div></header>
        <form class="preview-filter" :class="{'preview-filter-vendor':entity==='vendors'&&context.management}" @submit.prevent="search(entity)">
          <el-input v-model="view.filters[entity].query" :aria-label="`搜索${names[entity]}`" :placeholder="`搜索${names[entity]}名称`" clearable />
          <el-select v-if="entity==='vendors'&&context.management" v-model="view.filters.vendors.template_id" aria-label="SDK 模板筛选" placeholder="全部 SDK 模板"><el-option label="全部 SDK 模板" value=""/><el-option v-for="item in view.pages.vendors?.templates || []" :key="item.id" :label="item.name" :value="item.id"/></el-select>
          <el-select v-model="view.filters[entity].enabled" placeholder="全部状态" :aria-label="`${names[entity]}状态`"><el-option label="全部状态" value=""/><el-option label="已启用" value="true"/><el-option label="已停用" value="false"/></el-select>
          <el-select v-model="view.filters[entity].sort" :aria-label="`${names[entity]}排序`"><el-option label="名称升序" value="name"/><el-option label="名称降序" value="name_desc"/><el-option label="稳定 ID" value="id"/></el-select>
          <el-button native-type="submit" type="primary" :disabled="view.busy[entity] || (entity==='chips'&&!view.selected)">查询</el-button>
        </form>
        <div v-if="view.errors[entity]" class="preview-feedback"><el-alert :title="view.errors[entity]" type="error" :closable="false" show-icon/><el-button @click="view.load(entity)">重新读取</el-button></div>
        <el-skeleton v-else-if="view.busy[entity]&&!view.pages[entity]" :rows="5" animated class="preview-skeleton"/>
        <el-empty v-else-if="entity==='chips'&&!view.selected" description="选择厂商后查看芯片型号"/>
        <el-table v-else :data="view.pages[entity]?.items || []" row-key="id" :row-class-name="({row}:any)=>entity==='vendors'&&row.id===view.selected?'preview-selected':''" empty-text="暂无匹配记录" table-layout="auto">
          <el-table-column :label="names[entity]+'名称'" min-width="150"><template #default="{row}"><el-button v-if="entity==='vendors'" link type="primary" class="preview-record-name" @click="view.choose(row.id,row.name)">{{ row.name }}</el-button><strong v-else>{{ row.name }}</strong><small class="preview-record-id">{{ entity==='vendors'?row.template_name || '未声明模板':row.sdk_code || 'SDK 目标未声明' }}</small></template></el-table-column>
          <el-table-column v-if="entity==='vendors'" label="芯片" width="70"><template #default="{row}">{{ row.chip_count ?? '—' }}</template></el-table-column>
          <el-table-column v-else label="能力证据" min-width="120"><template #default="{row}"><el-tag :type="tone(row.capability)" effect="plain">{{ readiness(row.capability) }}</el-tag><small class="preview-record-id">{{ row.capability?.allowed_precisions?.join(' / ') || '精度未确认' }}</small></template></el-table-column>
          <el-table-column label="状态" width="85"><template #default="{row}"><el-tag :type="row.enabled===true?'success':'info'" effect="plain">{{ row.enabled===true?'已启用':row.enabled===false?'已停用':'未知' }}</el-tag></template></el-table-column>
          <el-table-column label="操作" :width="context.management?155:65"><template #default="{row}"><el-button link type="primary" :aria-label="`查看${row.name}详情`" @click="view.showDetail(entity,row.id)">详情</el-button><template v-if="context.management"><el-button link :disabled="!!view.pending||view.saving" :aria-label="`编辑${row.name}`" @click="view.openEditor(entity,row.id)">编辑</el-button><el-dropdown trigger="click" :disabled="!!view.pending||view.saving" @command="rowAction(entity,row.id,$event)"><el-button link :aria-label="`${row.name}更多操作`" :disabled="!!view.pending||view.saving">更多</el-button><template #dropdown><el-dropdown-menu><el-dropdown-item :command="row.enabled?'disable':'enable'">{{ row.enabled?'停用':'启用' }}</el-dropdown-item><el-dropdown-item v-if="entity==='chips'" command="detect" :disabled="!!view.detecting">{{ view.detecting===row.id?'检测中…':'检测 SDK 能力' }}</el-dropdown-item><el-dropdown-item command="delete" divided>删除</el-dropdown-item></el-dropdown-menu></template></el-dropdown></template></template></el-table-column>
        </el-table>
        <footer class="preview-pagination"><span>{{ view.pages[entity] ? `共 ${view.pages[entity]?.total} 条` : '数量待确认' }}</span><el-pagination v-if="view.pages[entity]" layout="prev, pager, next" :pager-count="5" :page-size="10" :current-page="view.filters[entity].page" :total="view.pages[entity]?.total || 0" :aria-label="`${names[entity]}分页`" @current-change="page(entity,$event)"/></footer>
      </section>
    </div>
    <el-drawer v-model="view.drawer" title="字典详情" size="min(540px, 100vw)" :append-to-body="false" :lock-scroll="false" @close="view.closeDetail">
      <el-skeleton v-if="view.busy.detail" :rows="6" animated/>
      <el-alert v-else-if="view.errors.detail" :title="view.errors.detail" type="error" :closable="false"/>
      <template v-else-if="view.detail"><h2>{{ view.detail.item.name }}</h2><dl class="preview-details"><dt>稳定 ID</dt><dd>{{ view.detail.item.id }}</dd><dt>SDK / 模板</dt><dd>{{ view.detail.item.sdk_code || view.detail.item.template_name || '未声明' }}</dd><dt>业务引用</dt><dd>{{ view.detail.references?.reference_count ?? '未核验' }}</dd><dt>引用核验</dt><dd>{{ view.detail.references?.check_status || '未核验' }}</dd><dt>字典修订</dt><dd>{{ view.detail.revision }}</dd></dl>
        <CatalogReferences :references="view.detail.references"/>
        <h3>已有资源证据</h3><p v-if="!view.detail.item.capability?.resources?.length" class="preview-muted">没有匹配的资源证据。本页不会启动检测。</p>
        <article v-for="resource in view.detail.item.capability?.resources || []" :key="resource.resource_id" class="preview-resource"><strong>{{ resource.resource_name }}</strong><el-tag :type="tone(resource)">{{ readiness(resource) }}</el-tag><p>SDK {{ resource.sdk_version || '版本未知' }} · {{ resource.allowed_precisions?.join(' / ') || '精度未确认' }}</p><p>{{ resource.message }}</p><small>检测时间：{{ resource.last_checked_at || '未记录' }}</small></article>
      </template>
      <template #footer><el-button @click="view.closeDetail">关闭详情</el-button></template>
    </el-drawer>
    <CatalogEditor v-if="context.management&&view.editing"/>
  </section>
</template>

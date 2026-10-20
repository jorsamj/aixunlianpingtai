import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

import {
  normalizePublishConfig,
  computePlatformTreeRows,
  childPlatformChoices,
  localChipKey,
  publicationActionLabel,
  publicationPreflight,
  publicationWeightDetails,
  publicationResultMessage,
} from '../../static/modules/external-algorithm-publish.js';

test('weight status shows known facts and optional gaps without downgrading successful delivery',()=>{
  const html=publicationWeightDetails({artifacts:[{target:'rockchip',file_name:'model.rknn',remote_registered:true,
    compute_platform_id:'rk-child',mapped_chip_code:'RK3576',metadata_sync_status:'PENDING',size_bytes:123,sha256:'a'.repeat(64),
    metadata:{image_width:640,image_height:384,yolo_version:'YOLOv11s',tags:['smoke','fire']}}]});
  for(const fact of ['RK3576','rk-child','640','384','YOLOv11s','123','a'.repeat(64),'smoke','fire','可同步已确定的补充信息'])assert.ok(html.includes(fact),fact);
  const incomplete=publicationWeightDetails({artifacts:[{file_name:'best.pt',sync_status:'SYNCED',metadata_sync_status:'SYNCED',metadata_note:'部分扩展信息未提供：yoloVersion <unknown>'}]});
  assert.ok(incomplete.includes('部分扩展信息未提供：yoloVersion &lt;unknown&gt;'));
  assert.match(incomplete,/同步成功/);
  assert.doesNotMatch(incomplete,/同步失败|阻断/);
  const failed=publicationWeightDetails({artifacts:[{file_name:'model.rknn',metadata_note:'部分扩展信息未提供：tags',last_error:'真实远端错误 FIELD_REJECTED'}]});
  assert.match(failed,/部分扩展信息未提供：tags/);
  assert.match(failed,/真实远端错误 FIELD_REJECTED/);
  assert.match(publicationResultMessage({publication:{status:'PUBLISHED'},metadata_note:'tags未提供'}),/已同步到新畅联/);
  assert.match(publicationResultMessage({publication:{status:'PARTIAL'},conversion_failures:['真实接口失败']}),/尚未完整同步/);
});

test('publish config normalizes storage, compute mappings and recovery paths', () => {
  const config = normalizePublishConfig({
    config: {
      storage_source_id: 'oss-models',
      public_base_url: 'https://algorithm.example.com',
      publish_original_model: true,
      target_mappings: {
        rockchip: {compute_platform_id: 'cp-rk', chip_code: 'RK3568', enabled: true},
      },
    },
    storage_sources: [{id: 'oss-models', name: '模型 OSS', type: 'oss'}],
    compute_platforms: [{computePlatformId: 'cp-rk', computePlatformName: '瑞芯微'}],
  });
  assert.equal(config.storageSourceId, 'oss-models');
  assert.equal(config.publicBaseUrl, 'https://algorithm.example.com');
  assert.equal(config.publishOriginalModel, true);
  assert.equal(config.targetMappings.rockchip.compute_platform_id, 'cp-rk');
  assert.equal(config.targetMappings.rockchip.chip_code, 'RK3568');
  assert.equal(config.versionListByProduct, '/internal/algorithm/algorithm-version/listByProduct/{productId}');
  assert.equal(config.weightListByVersion, '/internal/algorithm/algorithm-weight/listByVersion/{algoVersionId}');
  assert.equal(config.storageSources.length, 1);
  assert.equal(config.computePlatforms.length, 1);
});

test('publish UI leaves model asset storage ownership to ModelArtifactRuntime', () => {
  const source = readFileSync(
    new URL('../../static/modules/external-algorithm-publish.js', import.meta.url),
    'utf8',
  );
  assert.match(source, /ModelArtifactRuntime is the single owner of model asset storage/);
  assert.match(source, /storage_source_id:\s*''/);
  assert.doesNotMatch(source, /storage_source_id:\s*config\?\.storageSourceId/);
});


test('version publish action reflects durable publication state', () => {
  assert.equal(publicationActionLabel({}), '同步到新畅联');
  assert.equal(publicationActionLabel({external_publish_requested_at: '2026-09-17T12:00:00Z'}), '待同步');
  assert.equal(publicationActionLabel({external_publish_status: 'failed'}), '重新同步');
  assert.equal(publicationActionLabel({external_publish_status: 'unknown'}), '重新同步');
  assert.equal(publicationActionLabel({external_publish_status: 'published'}), '已同步');
});


test('vendor mapping UI keeps universal original model mapping mandatory', () => {
  const source = readFileSync(
    new URL('../../static/modules/external-algorithm-publish.js', import.meta.url),
    'utf8',
  );
  assert.match(source, /厂商对应表/);
  assert.match(source, /通用是特殊映射/);
  assert.match(source, /训练刚完成、尚未转换的原始模型/);
  assert.match(source, /original 的畅联云算力环境映射/);
  assert.match(source, /enabled: key === 'original' \? true/);
  assert.match(source, /data-platform-tab-panel="vendor"/);
  assert.match(source, /拉取畅联云厂商/);
});

test('publish UI keeps manual sync primary and stale compute mappings visible', () => {
  const source = readFileSync(
    new URL('../../static/modules/external-algorithm-publish.js', import.meta.url),
    'utf8',
  );
  assert.match(source, /data-external-publish-automation="1"/);
  assert.match(source, /<summary>高级操作<\/summary>/);
  assert.match(source, /算力环境来自最近一次新畅联主数据同步/);
  assert.match(source, /同步到新畅联/);
});


test('manual publish preflight blocks stale product and analysis identity before artifacts', () => {
  const stale = publicationPreflight({
    identity_ready: false,
    identity_issues: [{code: 'EXTERNAL_MASTER_DATA_STALE'}],
    conversion_active: false,
  });
  assert.equal(stale.ready, false);
  assert.match(stale.message, /立即同步/);

  const analysis = publicationPreflight({
    identity_ready: false,
    identity_issues: [{code: 'EXTERNAL_VERSION_ANALYSIS_STALE'}],
    conversion_active: false,
  });
  assert.equal(analysis.ready, false);
  assert.match(analysis.message, /分析方式已失效/);
  assert.match(analysis.message, /不会自动改挂/);

  const inactive = publicationPreflight({
    identity_ready: false,
    identity_issues: [{code: 'EXTERNAL_ALGORITHM_INACTIVE'}],
    conversion_active: false,
  });
  assert.equal(inactive.ready, false);
  assert.match(inactive.message, /已在新畅联下架/);
});

test('manual publish preflight allows original model delivery while conversions are still running', () => {
  const trainingReady = publicationPreflight({
    conversion_active: true,
    transport_ready: true,
    identity_ready: true,
    discovered: [{target: 'original', publish_mapping_status: 'mapped'}],
    mapped_artifact_count: 1,
    blocked_artifact_count: 0,
    ignored_artifact_count: 0,
    publish_ready: true,
  });
  assert.equal(trainingReady.ready, true);

  assert.deepEqual(
    publicationPreflight({conversion_active: false, discovered: []}),
    {ready: false, message: '当前版本还没有可交付的训练模型或转换产物。'},
  );

  const deferred = publicationPreflight({
    conversion_active: false,
    discovered: [
      {target: 'original', publish_mapping_status: 'mapped'},
      {target: 'onnx', publish_mapping_status: 'blocked'},
      {target: 'rockchip', publish_mapping_status: 'mapped'},
    ],
    mapped_artifact_count: 2,
    blocked_artifact_count: 1,
    deferred_conversion_count: 1,
    ignored_artifact_count: 0,
    publish_ready: true,
  });
  assert.equal(deferred.ready, true);
  assert.match(deferred.message, /待映射后自动追加/);

  const blockedOriginal = publicationPreflight({
    conversion_active: false,
    discovered: [{target: 'original', publish_mapping_status: 'blocked'}],
    mapped_artifact_count: 0,
    blocked_artifact_count: 1,
    deferred_conversion_count: 0,
    ignored_artifact_count: 0,
    publish_ready: false,
  });
  assert.equal(blockedOriginal.ready, false);
  assert.match(blockedOriginal.message, /original/);
});

test('manual publish preflight blocks missing model delivery configuration', () => {
  const result = publicationPreflight({
    conversion_active: false,
    transport_ready: false,
    transport_issues: [
      {code: 'EXTERNAL_PUBLISH_CONFIG_INCOMPLETE', message: '尚未配置本平台外部访问地址'},
      {code: 'MODEL_ARTIFACT_STORAGE_NOT_CONFIGURED', message: '尚未配置算法与转换结果存储源'},
    ],
    discovered: [{target: 'rockchip', publish_mapping_status: 'mapped'}],
    mapped_artifact_count: 1,
    blocked_artifact_count: 0,
    ignored_artifact_count: 0,
    publish_ready: false,
  });

  assert.equal(result.ready, false);
  assert.match(result.message, /存储配置 → 算法与转换结果存储/);
  assert.match(result.message, /OSS \/ CDN/);
  assert.match(result.message, /测试存储/);
});


test('manual publish preflight accepts mapped artifacts and reports intentional ignores', () => {
  const result = publicationPreflight({
    conversion_active: false,
    discovered: [
      {target: 'original', publish_mapping_status: 'mapped'},
      {target: 'onnx', publish_mapping_status: 'ignored'},
    ],
    mapped_artifact_count: 1,
    blocked_artifact_count: 0,
    deferred_conversion_count: 0,
    ignored_artifact_count: 1,
    publish_ready: true,
  });

  assert.equal(result.ready, true);
  assert.match(result.message, /先同步原始模型/);
  assert.match(result.message, /1 个转换目标已明确关闭发布/);
});

test('manual publish fetches read-only status before write request', () => {
  const source = readFileSync(
    new URL('../../static/modules/external-algorithm-publish.js', import.meta.url),
    'utf8',
  );
  const start = source.indexOf('async function publishVersion(');
  const end = source.indexOf('function schedulePlatformPage()', start);
  assert.ok(start >= 0 && end > start);
  const block = source.slice(start, end);
  const statusRead = block.indexOf('const status = await requestJson(');
  const preflight = block.indexOf('publicationPreflight(status)');
  const publishWrite = block.indexOf("/publish\`, {method: 'POST'}");
  assert.ok(statusRead >= 0);
  assert.ok(preflight > statusRead);
  assert.ok(publishWrite > preflight);
  assert.doesNotMatch(source, /function decorateVersionRows\(/);
  assert.doesNotMatch(source, /registerDecorator/);
});


test('publish UI locks recovery endpoints to official OpenAPI', async () => {
  const source = readFileSync(
    new URL('../../static/modules/external-algorithm-publish.js', import.meta.url),
    'utf8',
  );
  assert.match(source, /官方同步接口/);
  assert.match(source, /创建、查询和删除均使用新畅联官方 OpenAPI 固定路径，不允许前端修改/);
  assert.doesNotMatch(source, /id="externalPublishVersionList"/);
  assert.doesNotMatch(source, /id="externalPublishWeightList"/);
  assert.match(source, /version_list_by_product: '\/internal\/algorithm\/algorithm-version\/listByProduct\/\{productId\}'/);
  assert.match(source, /weight_list_by_version: '\/internal\/algorithm\/algorithm-weight\/listByVersion\/\{algoVersionId\}'/);
});


test('version rollback is destructive and external deletion is explained in the UI', () => {
  const appSource = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
  assert.match(appSource, /删除当前版本并回退/);
  assert.match(appSource, /delete_current_version:true/);
  assert.match(appSource, /先删除新畅联对应算法版本及其权重/);
  assert.doesNotMatch(appSource, /id="rollbackDeleteCurrent"/);
});


test('compute platform tree shows full names but never equates a label with a local chip identity', () => {
  const remote = [
    {computePlatformId: 100, computePlatformName: '瑞芯微', parentId: 0, delFlag: 0},
    {computePlatformId: 101, computePlatformName: '边缘设备环境', parentId: 100, delFlag: 0},
    {computePlatformId: 102, computePlatformName: 'RK 设备档位', parentId: 100, delFlag: 1},
    {computePlatformId: 200, computePlatformName: 'ONNX', parentId: 0, delFlag: 0},
  ];
  const rows = computePlatformTreeRows(remote);
  assert.equal(rows.find(row => row.id === '101').path, '瑞芯微 / 边缘设备环境');
  assert.equal(rows.find(row => row.id === '101').active, true);
  assert.equal(rows.find(row => row.id === '102').active, false);
  assert.deepEqual(childPlatformChoices(remote, '100').map(row => row.id), ['101']);
  assert.equal(localChipKey('rk-3568'), 'RK3568');
  assert.equal(localChipKey('RK3576'), 'RK3576');
});

test('chip dictionary and individual child mappings survive frontend normalization', () => {
  const model = normalizePublishConfig({
    config: {target_mappings: {rockchip: {
      compute_platform_id: 'parent-rk',
      chip_mappings: {RK3568: 'child-edge', RK3576: 'child-model'},
    }}},
    chip_dictionary: {rockchip: ['RK3568', 'RK3576', 'RK3578']},
  });
  assert.deepEqual(model.targetMappings.rockchip.chip_mappings,
    {RK3568: 'child-edge', RK3576: 'child-model'});
  assert.deepEqual(model.chipDictionary.rockchip, ['RK3568', 'RK3576', 'RK3578']);
});


test('save refresh retains backend chip dictionary rather than replacing it with empty UI defaults', () => {
  const source = readFileSync(new URL('../../static/modules/external-algorithm-publish.js', import.meta.url), 'utf8');
  assert.match(source, /chip_dictionary: config\?\.chipDictionary/);
  assert.match(source, /chip_mappings: chipMappings/);
  assert.doesNotMatch(source, /if \(chip && code\) chip\.value = code/);
});


test('weight details distinguish frozen, local, prepared, confirmed and read-back tags',()=>{
  const html=publicationWeightDetails({artifacts:[{file_name:'best.pt',sync_status:'SYNCED',remote_registered:true,
    metadata_sync_status:'PENDING',metadata:{tags:['fire1','smoke1'],label_validation_status:'VERIFIED'},
    frozen_tags:['fire1','smoke1'],local_tags:['fire1','smoke1'],prepared_tags:['fire1','smoke1'],
    confirmed_tags:null,remote_tags:null,remote_tags_status:'NOT_RETURNED'}]});
  for(const text of ['冻结类别','本地类别','准备提交','已确认提交','远端未返回 tags','标签补齐待处理','同步成功','2 类'])assert.ok(html.includes(text),text);
  assert.ok(!html.includes('远端已验证：fire1'));
});


test('conversion delivery review shows independent owner selection and upload facts',()=>{
  const html=publicationWeightDetails({project_id:'p',algorithm:{id:'a'},version:{id:'v'},publication:{status:'PARTIAL'},artifacts:[
    {artifact_id:'old',file_name:'same.bmodel',target:'sophon',external_weight_id:'w-old',sync_status:'SYNCED',storage_status:'UPLOADED',compute_platform_id:'parent',chip_code:'bm1684x',sha256:'a'.repeat(64),remote_identity_status:'NOT_VERIFIED',review_required:true,recovery_plan:{suggested_operation:'REVIEW_PLATFORM_MIGRATION',target_compute_platform_id:'child',reason:'待核对真实分类关系'}},
    {artifact_id:'new',file_name:'same.bmodel',target:'sophon',sync_status:'UNKNOWN',storage_status:'UPLOADED',chip_code:'bm1684x',sha256:'b'.repeat(64),review_required:true,recovery_plan:{old_weight_id:'w-old',old_sha256:'a'.repeat(64),new_sha256:'b'.repeat(64),suggested_operation:'REVIEW_CONTENT_REPLACEMENT',reason:'替换合同待确认'}}]});
  for(const value of ['PARTIAL','old','new','w-old','UPLOADED','UNKNOWN','child','替换合同待确认','远端身份未读回验证','data-weight-select','仅保存本地交付意向'])assert.ok(html.includes(value),value);
  assert.match(html,/同步成功/);
});

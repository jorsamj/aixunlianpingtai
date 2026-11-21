import test from 'node:test';
import assert from 'node:assert/strict';
import {advancedPageInfo, advancedTab, ADVANCED_MENUS} from '../../static/modules/advanced-navigation.js';
import {normalizeNavigationPage} from '../../static/modules/navigation-stability.js';

test('four menu entries retain all seven canonical business page identities', () => {
  assert.deepEqual(ADVANCED_MENUS.map(item => item.title), ['算力与节点', '模型转换环境', 'AI 辅助配置', '存储管理']);
  for (const page of ['训练资源','服务节点','组件检测','部署资源','模型配置','存储配置','旧素材兼容迁移']) {
    assert.ok(advancedPageInfo(page), page);
    assert.equal(normalizeNavigationPage(page), page);
  }
  assert.equal(advancedPageInfo('服务节点').title, '算力与节点');
  assert.equal(advancedPageInfo('旧素材兼容迁移').title, '存储管理');
  assert.equal(advancedPageInfo('质量中心'), null);
});

test('new menu names delegate only to original route owners', () => {
  for (const item of ADVANCED_MENUS) assert.equal(normalizeNavigationPage(item.title), item.page);
  assert.equal(normalizeNavigationPage('部署插件'), '模型配置');
  assert.equal(advancedTab('组件检测').label, '环境诊断');
  assert.equal(advancedTab('模型配置', 'prompts').label, '提示词模板');
  assert.equal(advancedTab('存储配置', 'cache').label, '空间与缓存');
  assert.equal(advancedTab('部署资源', 'missing').id, 'resources');
});

import {expect, test} from '@playwright/test';
import {resolve} from 'node:path';

test('ChangLian weight details reconcile exact int64 evidence across provider pages', async ({page}) => {
  const provider = '/api/v63/external-algorithm-platform/provider';
  const productId = '9223372036854775801';
  const versionId = '9223372036854775802';
  const weightId = '9223372036854775803';
  const nearWeightId = '9223372036854775804';
  const fileSha256 = 'a'.repeat(64);
  const filePath = 'https://download.example.test/model.rknn';
  const detail = {
    productId, algoVersionId: versionId, weightId, fileName: 'current.rknn', fileSha256, filePath,
    analysisId: '9223372036854775805', computePlatformCode: 'rockchip', imageWidth: 640, imageHeight: 384,
    futureField: {operator: '原始证据'},
  };
  let scenario: 'match' | 'wrongScope' | 'nullTags' = 'match';
  const pages: string[] = [];
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: {writeText: async (value: string) => {sessionStorage.setItem('copied-weight-evidence', value);}},
    });
  });
  await page.route('**/app/**', route => {
    const asset = new URL(route.request().url()).pathname.slice('/app/'.length) || 'index.html';
    return route.fulfill({
      path: resolve('../static/vue-app', asset),
      contentType: asset.endsWith('.css') ? 'text/css' : asset.endsWith('.js') ? 'text/javascript' : 'text/html',
    });
  });
  await page.route('**/api/**', route => {
    const request = route.request();
    const {pathname, searchParams} = new URL(request.url());
    expect(request.method()).toBe('GET');
    if (pathname === '/api/auth/session') return route.fulfill({json: {authenticated: true, user: {username: '隔离用户'}}});
    if (pathname === '/api/projects') return route.fulfill({json: [{id: 'p', name: '项目 P'}]});
    const result = (data: unknown, total?: number) => route.fulfill({json: {ok: true, response: {code: 200, data, total}}});
    if (pathname === provider + '/products') {
      return result(searchParams.get('status') === '1' ? [{productId, productName: '目标产品'}] : []);
    }
    if (pathname === provider + '/versions/by-product/' + productId) {
      return result([{algoVersionId: versionId, versionName: '目标版本'}]);
    }
    if (pathname === provider + '/weights/by-version/' + versionId) {
      return result([{weightId, fileName: 'listed.rknn', tags: ['历史标签']}]);
    }
    if (pathname === provider + '/weights/' + weightId) {
      expect(searchParams.get('withTags')).toBe('true');
      return result(scenario === 'nullTags' ? {...detail, tags: null} : detail);
    }
    if (pathname === provider + '/weights/page') {
      const pageNo = searchParams.get('pageNum')!;
      pages.push(pageNo);
      expect(searchParams.get('algoVersionId')).toBe(versionId);
      expect(searchParams.get('pageSize')).toBe('50');
      expect(searchParams.get('withTags')).toBe('true');
      return pageNo === '1'
        ? result(Array.from({length: 50}, (_, index) => ({
          weightId: index === 0 ? nearWeightId : String(index), productId, algoVersionId: versionId, tags: ['旁路标签'],
        })), 51)
        : result([{weightId, productId: scenario === 'wrongScope' ? nearWeightId : productId,
          algoVersionId: versionId, tags: ['目标标签', '']}], 51);
    }
    return route.fulfill({status: 404, json: {detail: 'unexpected ' + pathname}});
  });
  await page.goto('/app/#/projects/p/changlian-data');
  await page.getByRole('button', {name: '读取畅联云', exact: true}).click();
  await page.getByRole('button', {name: '目标产品', exact: true}).click();
  await page.getByRole('button', {name: '目标版本', exact: true}).click();
  const open = page.getByRole('button', {name: 'listed.rknn', exact: true});
  const dialog = page.getByRole('dialog', {name: '权重文件详情'});
  const clipboard = () => page.evaluate(() => sessionStorage.getItem('copied-weight-evidence'));
  await open.click();
  await expect(dialog.getByText('目标标签', {exact: true})).toBeVisible();
  await expect(dialog.getByText('空字符串', {exact: true})).toBeVisible();
  await expect(dialog).toContainText('文件名称：列表 listed.rknn，详情 current.rknn');
  await expect(dialog).toContainText('历史标签');
  await expect(dialog).toContainText(detail.analysisId);
  expect(pages).toEqual(['1', '2']);
  for (const [name, value] of [
    ['复制权重文件 ID', weightId], ['复制文件地址', filePath], ['复制SHA256', fileSha256],
  ]) {
    await dialog.getByRole('button', {name, exact: true}).click();
    expect(await clipboard()).toBe(value);
  }
  await dialog.getByText('完整原始数据', {exact: true}).click();
  await dialog.getByRole('button', {name: '复制原始数据', exact: true}).click();
  const evidence = JSON.parse((await clipboard())!);
  expect(evidence.getInfo.data).toEqual(detail);
  expect(evidence.tagsQuery.map((entry: {data: {weightId: string}[]}) => entry.data[0].weightId))
    .toEqual([nearWeightId, weightId]);

  const close = dialog.getByRole('button', {name: '关闭此对话框', exact: true});
  await close.click();
  await expect(dialog).toBeHidden();
  scenario = 'wrongScope';
  await open.click();
  await expect(dialog).toContainText('权重详情与所选产品、版本或文件身份不一致');
  await expect(dialog.getByText('目标标签', {exact: true})).toHaveCount(0);
  expect(pages).toEqual(['1', '2', '1', '2']);
  scenario = 'nullTags';
  await dialog.getByRole('button', {name: '重新加载', exact: true}).click();
  await expect(dialog.locator('[data-tags-state="null"]')).toBeVisible();
  expect(pages).toEqual(['1', '2', '1', '2']);
});

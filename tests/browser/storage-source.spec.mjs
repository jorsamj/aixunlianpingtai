import {test, expect} from '@playwright/test';


test('storage configuration creates, health-checks, and removes a real local source', async ({page}) => {
  const name = `浏览器本地源-${Date.now()}`;
  await page.goto('/');

  await page.getByRole('button', {name: /展开高级功能/}).click();
  await page.getByRole('button', {name: /素材存储配置/}).click();
  await expect(page.getByRole('heading', {name: '素材存储配置', level: 2})).toBeVisible();
  await expect(page.getByText('平台本地存储', {exact: true})).toBeVisible();

  await page.getByRole('button', {name: /新增存储源/}).click();
  await page.locator('#ss61Name').fill(name);
  await page.locator('#ss61Type').selectOption('local');
  await page.getByRole('button', {name: '保存'}).click();

  const row = page.locator('.storage61-row').filter({hasText: name});
  await expect(row).toBeVisible();
  await row.getByRole('button', {name: '测试连接'}).click();
  await expect(row.getByText('AVAILABLE')).toBeVisible();

  page.once('dialog', dialog => dialog.accept());
  await row.getByRole('button', {name: '删除'}).click();
  await expect(page.locator('.storage61-row').filter({hasText: name})).toHaveCount(0);
});

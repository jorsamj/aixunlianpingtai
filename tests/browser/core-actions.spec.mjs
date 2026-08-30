import {test, expect} from '@playwright/test';


test('core navigation and create algorithm action respond without console errors', async ({page}) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await page.getByRole('button', {name: /算法列表/}).click();
  await page.getByRole('button', {name: /新建算法|创建算法/}).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect(page.getByText('算法名称')).toBeVisible();
  expect(errors).toEqual([]);
});

test('mobile navigation closes its drawer before main-page actions', async ({page}) => {
  await page.setViewportSize({width: 600, height: 760});
  await page.goto('/');
  await page.getByRole('button', {name: '打开菜单'}).click();
  await expect(page.locator('#sidebar')).toHaveClass(/mobile-open/);
  await page.getByRole('button', {name: /数据集/}).click();
  await expect(page.locator('#sidebar')).not.toHaveClass(/mobile-open/);
  await expect(page.locator('#sideBackdrop')).not.toHaveClass(/show/);
  await page.getByRole('button', {name: '批量操作'}).click();
  await expect(page.getByRole('button', {name: '取消批量'})).toBeVisible();
});

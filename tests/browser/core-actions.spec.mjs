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


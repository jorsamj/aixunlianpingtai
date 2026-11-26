import {expect, test} from '@playwright/test';
import {resolve} from 'node:path';

test('native video tasks submit original multipart fields and stop the created task', async ({page}) => {
  const api = '/api/v33/projects/p/video-tasks';
  const task = {id: 'frame-task', project_id: 'p', kind: 'VIDEO_FRAMES', video_name: 'fixture.mp4', split: 'unassigned', mode: 'fixed_count',
    fixed_count: 50, dataset_id: 'default', status: 'QUEUED', progress: 0};
  let created = false;
  let stopped = false;
  let multipart = '';
  const fields = new Map<string, string | File>();
  await page.route('**/app/**', route => {
    const name = new URL(route.request().url()).pathname.slice('/app/'.length) || 'index.html';
    return route.fulfill({path: resolve('../static/vue-app', name),
      contentType: name.endsWith('.js') ? 'text/javascript' : name.endsWith('.css') ? 'text/css' : 'text/html'});
  });
  await page.route('**/api/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === '/api/auth/session') return route.fulfill({json: {authenticated: true, user: {username: '隔离用户'}}});
    if (path === '/api/projects') return route.fulfill({json: [{id: 'p', name: '项目 P'}]});
    if (path === api && request.method() === 'POST') {
      multipart = request.headers()['content-type'];
      const response = new Response(request.postDataBuffer(), {headers: {'content-type': multipart}});
      (await response.formData()).forEach((value, key) => fields.set(key, value));
      created = true;
      return route.fulfill({status: 202, json: task});
    }
    const record = stopped ? {...task, status: 'CANCELLED'} : task;
    if (path === api) return route.fulfill({json: {items: created ? [record] : []}});
    if (path === api + '/frame-task/stop' && request.method() === 'POST') {
      stopped = true;
      return route.fulfill({json: {...task, status: 'CANCELLED'}});
    }
    if (path === api + '/frame-task') return route.fulfill({json: record});
    return route.fulfill({status: 404, json: {detail: 'unexpected ' + path}});
  });
  await page.goto('/app/#/projects/p/algorithms');
  await page.getByRole('link', {name: '视频切帧', exact: true}).click();
  await expect(page).toHaveURL(/video-tasks$/);
  await expect(page.getByText('暂无切帧任务')).toBeVisible();
  await page.getByRole('button', {name: '＋ 创建切帧任务', exact: true}).click();
  const dialog = page.getByRole('dialog', {name: '创建切帧任务'});
  await dialog.getByLabel('上传视频文件').setInputFiles({name: 'fixture.mp4', mimeType: 'video/mp4', buffer: Buffer.from('video')});
  await dialog.getByLabel('切帧方式').selectOption('fixed_count');
  await dialog.getByRole('button', {name: '创建任务', exact: true}).click();
  const row = page.getByRole('row', {name: /fixture.mp4/});
  await expect(row).toContainText('排队中');
  expect(multipart).toMatch(/^multipart\/form-data; boundary=/);
  expect(Object.fromEntries([...fields].filter(([key]) => key !== 'video'))).toEqual({
    split: 'unassigned', dataset_id: 'default', backend: 'auto', mode: 'fixed_count', fixed_count: '50',
  });
  expect((fields.get('video') as File).name).toBe('fixture.mp4');
  await row.getByRole('button', {name: '停止'}).click();
  await expect(row).toContainText('已停止');
  await row.getByRole('button', {name: '详情'}).click();
  const detail = page.getByRole('dialog', {name: '切帧任务详情'});
  await expect(detail).toContainText('已停止');
  await expect(detail.getByRole('link', {name: '查看素材库'})).toHaveAttribute('href', /materials$/);
});

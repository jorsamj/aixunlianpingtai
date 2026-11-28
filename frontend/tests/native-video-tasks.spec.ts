import {expect, test} from '@playwright/test';
import {resolve} from 'node:path';
import {createHash} from 'node:crypto';

for (const alreadyAccepted of [true, false]) {
test(`native video tasks recover ${alreadyAccepted ? 'an accepted' : 'an unregistered'} upload after reload`, async ({page}) => {
  const api = '/api/v33/projects/p/video-tasks';
  const task = {id: 'frame-task', project_id: 'p', kind: 'VIDEO_FRAMES', video_name: 'fixture.mp4', split: 'unassigned', mode: 'fixed_count',
    fixed_count: 50, dataset_id: 'default', status: 'QUEUED', progress: 0};
  let created = false;
  let stopped = false;
  let submissions=0, lookups=0, requestId='';
  let recoveryState = 'IN_FLIGHT';
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
      const supplied = String(fields.get('request_id') || '');
      if (submissions) expect(supplied).toBe(requestId);
      requestId = supplied;
      submissions++;
      created = alreadyAccepted || submissions > 1;
      if (submissions === 1) return route.abort();
      return route.fulfill({status: 202, json: {...task, request_id:requestId}});
    }
    if(path===api+'/by-request/'+requestId && requestId){
      lookups++;
      return route.fulfill({json:created ? {request_id:requestId,state:'ACCEPTED',task} : {request_id:requestId,state:recoveryState}});
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
  const entry = '/app/#/projects/p/algorithms';
  await page.goto(alreadyAccepted ? entry : 'http://training.test' + entry);
  if (!alreadyAccepted) await expect.poll(() => page.evaluate(() => globalThis.isSecureContext || !!crypto.subtle)).toBe(false);
  await page.getByRole('link', {name: '视频切帧', exact: true}).click();
  await expect(page).toHaveURL(/video-tasks$/);
  await expect(page.getByText('暂无切帧任务')).toBeVisible();
  await page.getByRole('button', {name: '＋ 创建切帧任务', exact: true}).click();
  const dialog = page.getByRole('dialog', {name: '创建切帧任务'});
  await dialog.getByLabel('上传视频文件').setInputFiles({name: 'fixture.mp4', mimeType: 'video/mp4', buffer: Buffer.from('video')});
  await dialog.getByLabel('切帧方式').selectOption('fixed_count');
  await dialog.getByRole('button', {name: '创建任务', exact: true}).click();
  await expect(dialog.getByText('创建结果未知，请按原请求核对。')).toBeVisible();
  const persisted = await page.evaluate(() => {
    const key = Object.keys(sessionStorage).find(value => value.startsWith('video-create:'))!;
    return JSON.parse(sessionStorage.getItem(key)!).fingerprint;
  });
  const chunkHash = createHash('sha256').update('video').digest();
  expect(persisted).toBe(createHash('sha256').update(chunkHash).digest('hex'));
  await page.reload();
  await expect.poll(()=>lookups).toBe(1);
  expect(submissions).toBe(1);
  if (!alreadyAccepted) {
    await expect(page.getByText('原请求正在登记，请稍后核对原请求。')).toBeVisible();
    await expect(page.getByRole('button', {name:'重试同一请求'})).toHaveCount(0);
    await expect(page.getByRole('button', {name:'＋ 创建切帧任务'})).toBeDisabled();
    recoveryState = 'UNREGISTERED';
    await page.getByRole('button', {name:'核对原请求'}).click();
    const original = page.getByLabel('重新选择原视频（fixture.mp4）');
    const retry = page.getByRole('button', {name:'重试同一请求'});
    await original.setInputFiles({name:'fixture.mp4', mimeType:'video/mp4', buffer:Buffer.from('other')});
    await retry.click();
    await expect(page.getByText('所选视频与原请求的文件不一致，请重新选择原视频。')).toBeVisible();
    expect(submissions).toBe(1);
    await original.setInputFiles({name:'fixture.mp4', mimeType:'video/mp4', buffer:Buffer.from('video')});
    await retry.click();
    await expect.poll(() => submissions).toBe(2);
  }
  const row = page.getByRole('row', {name: /fixture.mp4/});
  await expect(row).toContainText('排队中');
  expect(multipart).toMatch(/^multipart\/form-data; boundary=/);
  expect(Object.fromEntries([...fields].filter(([key]) => key !== 'video' && key !== 'request_id'))).toEqual({
    split: 'unassigned', dataset_id: 'default', backend: 'auto', mode: 'fixed_count', fixed_count: '50',
  });
  expect(requestId).toMatch(/^[A-Za-z0-9_-]{12,80}$/);
  expect((fields.get('video') as File).name).toBe('fixture.mp4');
  await row.getByRole('button', {name: '停止'}).click();
  await expect(row).toContainText('已停止');
  await row.getByRole('button', {name: '详情'}).click();
  const detail = page.getByRole('dialog', {name: '切帧任务详情'});
  await expect(detail).toContainText('已停止');
  await expect(detail.getByRole('link', {name: '查看素材库'})).toHaveAttribute('href', /materials$/);
});
}

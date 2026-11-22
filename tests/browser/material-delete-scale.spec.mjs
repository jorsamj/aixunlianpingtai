import {test, expect} from '@playwright/test';
import {spawn} from 'node:child_process';
import {createHash} from 'node:crypto';
import {mkdtempSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createServer} from 'node:net';

const JPEG = Buffer.from('/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAoHBwgHBgoICAgLCgoLDhgQDg0NDh0VFhEYIx8lJCIfIiEmKzcvJik0KSEiMEExNDk7Pj4+JS5ESUM8SDc9Pjv/2wBDAQoLCw4NDhwQEBw7KCIoOzs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozv/wAARCADwAUADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD1CiiitDMKKKKACiiigAooooAKKKKACiiigAooooA//2Q==', 'base64');

function freePort() {
  return new Promise(resolve => {
    const socket = createServer();
    socket.listen(0, '127.0.0.1', () => {
      const {port} = socket.address();
      socket.close(() => resolve(port));
    });
  });
}
async function startIsolated(env) {
  const port = await freePort();
  const origin = `http://127.0.0.1:${port}`;
  const child = spawn('python', ['-m', 'uvicorn', 'app:app', '--host', '127.0.0.1',
    '--port', String(port), '--log-level', 'info'], {env, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true});
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('isolated server startup timeout')), 40000);
    child.once('exit', code => { clearTimeout(timer); reject(new Error(`isolated server exited ${code}`)); });
    const onData = chunk => { if (String(chunk).includes('Uvicorn running on')) { clearTimeout(timer); resolve(); } };
    child.stdout.on('data', onData);
    child.stderr.on('data', onData);
  });
  return {origin, child};
}
function resultsPage(planId, total, cursor, prefix = 'img') {
  const pattern = new RegExp(`^${prefix}-(\\d+)$`);
  const start = cursor ? Number(pattern.exec(cursor)?.[1] || 0) : 0;
  const rows = Array.from({length: Math.max(0, Math.min(100, total - start))}, (_, offset) => {
    const index = start + offset + 1;
    return {image_id: `${prefix}-${String(index).padStart(6, '0')}`, item_state: 'succeeded'};
  });
  const last = rows.at(-1)?.image_id || null;
  return {items: rows, succeeded_image_ids: rows.map(row => row.image_id),
    next_cursor: rows.length && start + rows.length < total ? last : null,
    reclamation_state: 'DEFERRED_SAFETY_UNVERIFIED'};
}

function digestIds(ids) {
  const sorted = [...new Set(ids)].sort();
  const hash = createHash('sha256').update(sorted.join('\n'), 'utf8').digest('hex');
  return `sha256:${hash}:${sorted.length}`;
}
function imageIds(total, prefix = 'img') {
  return Array.from({length: total}, (_, index) => `${prefix}-${String(index + 1).padStart(6, '0')}`);
}

test('same-count foreign ids and pre-digest 501 records stay UNKNOWN', async ({page, request}) => {
  test.setTimeout(180_000);
  const data = mkdtempSync(join(tmpdir(), 'xjalgo-delete-proof-'));
  const env = {...process.env, MC_TRAIN_DATA_DIR: data, MC_PLATFORM_VERSION: 'browser-test',
    MC_ALLOW_MULTIPLE_PROJECTS_FOR_TESTS: '1', YOLO_CONFIG_DIR: join(data, 'ultralytics')};
  const {origin, child} = await startIsolated(env);
  try {
    const project = await (await request.post(origin + '/api/projects', {
      data: {name: '删除范围证明', labels: [{code: 'fire', display_name: '明火'}]},
    })).json();
    await request.post(`${origin}/api/projects/${project.id}/images`, {
      multipart: {files: {name: 'proof.jpg', mimeType: 'image/jpeg', buffer: JPEG}, dataset_id: 'default'},
    });
    const auth = await (await request.get(origin + '/api/auth/session')).json();
    const actorKey = JSON.stringify([auth.provider || '', auth.user?.username || '']);
    const recordKey = 'ai-material-delete:v1:' + JSON.stringify([actorKey, project.id]);
    let total = 0, planId = '', prefix = 'img';
    await page.route('**/api/v62/projects/*/material-batches/*/results*', route => {
      const url = new URL(route.request().url());
      return route.fulfill({json: resultsPage(planId, total, url.searchParams.get('cursor'), prefix)});
    });
    await page.route('**/api/v62/projects/*/material-batches/*', route => {
      const url = new URL(route.request().url());
      if (route.request().method() !== 'GET' || !planId
          || !url.pathname.endsWith(`/material-batches/${planId}`)) return route.continue();
      return route.fulfill({json: {id: planId, task_id: planId, project_id: project.id,
        operation: 'DELETE_INDEX', status: 'SUCCEEDED', total, succeeded: total,
        failed: 0, logical_removed: total, physical_retained: total, reclaimed_bytes: 0}});
    });

    async function runCase(name, plan, size, resultPrefix, digest, expected) {
      total = size; planId = plan; prefix = resultPrefix;
      await page.goto(origin + '/app/');
      await page.evaluate(([key, value]) => localStorage.setItem(key, value), [recordKey,
        JSON.stringify({project_id: project.id, plan_id: plan, operation: 'DELETE_INDEX',
          mode: 'selected', image_count: size,
          ...(digest === null ? {image_ids: imageIds(500)} : {id_digest: digest})})]);
      await page.goto(`${origin}/app/?proof=${name}#/projects/${project.id}/materials`);
      await expect(page.getByText('存在未完成的素材删除任务')).toBeVisible({timeout: 60000});
      expect(await page.evaluate(key => localStorage.getItem(key), recordKey)).not.toBeNull();
      await page.getByRole('button', {name: '查看删除任务', exact: true}).click();
      await expect(page.locator('.el-dialog')).toContainText(expected, {timeout: 30000});
      await page.locator('.el-dialog').getByRole('button', {name: '取消', exact: true}).click();
    }

    await runCase('foreign', 'proof-foreign', 2001, 'other',
      digestIds(imageIds(2001, 'img')), '身份异常');
    await runCase('legacy', 'proof-legacy', 501, 'img', null, '缺少完整范围摘要');
  } finally { child.kill(); }
});

test('501 and 2001 material deletions recover from server cursor pages without truncated local IDs', async ({page, request}) => {
  test.setTimeout(240_000);
  const data = mkdtempSync(join(tmpdir(), 'xjalgo-delete-scale-'));
  const env = {...process.env, MC_TRAIN_DATA_DIR: data, MC_PLATFORM_VERSION: 'browser-test',
    MC_ALLOW_MULTIPLE_PROJECTS_FOR_TESTS: '1', YOLO_CONFIG_DIR: join(data, 'ultralytics')};
  const {origin, child} = await startIsolated(env);
  try {
    const project = await (await request.post(origin + '/api/projects', {
      data: {name: '删除规模恢复', labels: [{code: 'fire', display_name: '明火'}]},
    })).json();
    const uploaded = await request.post(`${origin}/api/projects/${project.id}/images`, {
      multipart: {files: {name: 'scale.jpg', mimeType: 'image/jpeg', buffer: JPEG}, dataset_id: 'default'},
    });
    expect(uploaded.ok()).toBeTruthy();
    const auth = await (await request.get(origin + '/api/auth/session')).json();
    const actorKey = JSON.stringify([auth.provider || '', auth.user?.username || '']);
    const recordKey = 'ai-material-delete:v1:' + JSON.stringify([actorKey, project.id]);
    let total = 0, planId = '', resultPrefix = 'img';
    const resultRequests = [];
    await page.route('**/api/v62/projects/*/material-batches/*/results*', route => {
      const url = new URL(route.request().url());
      resultRequests.push({plan: planId, cursor: url.searchParams.get('cursor') || '',
        limit: Number(url.searchParams.get('limit') || 0)});
      return route.fulfill({json: resultsPage(planId, total, url.searchParams.get('cursor'), resultPrefix)});
    });
    await page.route('**/api/v62/projects/*/material-batches/*', route => {
      const url = new URL(route.request().url());
      if (route.request().method() !== 'GET' || !planId
          || !url.pathname.endsWith(`/material-batches/${planId}`)) return route.continue();
      return route.fulfill({json: {id: planId, task_id: planId, project_id: project.id,
        operation: 'DELETE_INDEX', status: 'SUCCEEDED', total, succeeded: total,
        failed: 0, logical_removed: total, physical_retained: total, reclaimed_bytes: 0,
        reclamation_state: 'DEFERRED_SAFETY_UNVERIFIED'}});
    });
    let creates = 0;
    page.on('request', req => {
      const url = new URL(req.url());
      if (req.method() === 'POST' && url.pathname.endsWith('/material-batches')) creates += 1;
    });

    async function recover(size, plan, options = {}) {
      total = size; planId = plan; resultPrefix = options.prefix || 'img';
      await page.addInitScript(([key, value]) => localStorage.setItem(key, value), [recordKey,
        JSON.stringify({project_id: project.id, plan_id: plan, operation: 'DELETE_INDEX',
          mode: 'selected', image_count: size,
          ...(options.digest === null ? {} : {id_digest: options.digest ??
            digestIds(imageIds(size, resultPrefix))})})]);
      await page.goto(`${origin}/app/?scale=${size}#/projects/${project.id}/materials`);
      await expect.poll(async () => page.evaluate(key => localStorage.getItem(key), recordKey),
        {timeout: 120000}).toBe(null);
    }

    await recover(501, 'plan-501');
    const first = resultRequests.filter(row => row.plan === 'plan-501');
    expect(first.length).toBe(6);
    expect(first.map(row => row.cursor)).toEqual(['', 'img-000100', 'img-000200',
      'img-000300', 'img-000400', 'img-000500']);
    expect(first.every(row => row.limit === 100)).toBe(true);
    expect(creates).toBe(0);

    resultRequests.length = 0;
    await recover(2001, 'plan-2001');
    const second = resultRequests.filter(row => row.plan === 'plan-2001');
    expect(second.length).toBe(21);
    expect(second.map(row => row.cursor)[0]).toBe('');
    expect(second.at(-1).cursor).toBe('img-002000');
    expect(creates).toBe(0);
  } finally { child.kill(); }
});

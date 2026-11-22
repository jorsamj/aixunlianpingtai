import {test, expect} from '@playwright/test';
import {spawn} from 'node:child_process';
import {mkdtempSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createServer} from 'node:net';

const JPEG = Buffer.from('/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAoHBwgHBgoICAgLCgoLDhgQDg0NDh0VFhEYIx8lJCIfIiEmKzcvJik0KSEiMEExNDk7Pj4+JS5ESUM8SDc9Pjv/2wBDAQoLCw4NDhwQEBw7KCIoOzs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozv/wAARCADwAUADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD1CiiitDMKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooA//2Q==', 'base64');

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
async function newProject(request, origin, name) {
  return (await request.post(origin + '/api/projects', {
    data: {name, labels: [{code: 'fire', display_name: '明火'}]},
  })).json();
}
function files(count, prefix = 'upload') {
  return Array.from({length: count}, (_, index) => ({
    name: `${prefix}-${String(index).padStart(3, '0')}.jpg`, mimeType: 'image/jpeg', buffer: JPEG,
  }));
}
async function openUpload(page, origin, projectId) {
  await page.goto(`${origin}/app/#/projects/${projectId}/materials`);
  await page.getByRole('button', {name: '上传图片（原生）', exact: true}).click();
  await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/materials/upload`));
  await expect(page.locator('.uppy-Dashboard')).toBeVisible({timeout: 45000});
  await expect(page.locator('.uppy-Dashboard input[type=file]').first()).toBeAttached();
}
async function chooseAndUpload(page, rows) {
  await page.locator('.uppy-Dashboard input[type=file]').first().setInputFiles(rows);
  const upload = page.locator('.uppy-StatusBar-actionBtn--upload');
  await expect(upload).toBeVisible({timeout: 15000});
  await upload.click();
}
const session = page => page.evaluate(() => {
  const key = Object.keys(localStorage).find(name => name.startsWith('material-upload-session:'));
  return key ? JSON.parse(localStorage.getItem(key)) : null;
});

test('native Vue uploads five images through the original request_id runtime and confirmation owner', async ({page, request}) => {
  test.setTimeout(180_000);
  const data = mkdtempSync(join(tmpdir(), 'xjalgo-native-upload-'));
  const env = {...process.env, MC_TRAIN_DATA_DIR: data, MC_PLATFORM_VERSION: 'browser-test',
    MC_ALLOW_MULTIPLE_PROJECTS_FOR_TESTS: '1', YOLO_CONFIG_DIR: join(data, 'ultralytics')};
  const {origin, child} = await startIsolated(env);
  const external = [];
  page.on('request', req => {
    const url = new URL(req.url());
    if (!['http:', 'https:'].includes(url.protocol)) return;
    if (url.hostname !== '127.0.0.1' && url.hostname !== 'localhost') external.push(url.href);
  });
  try {
    const project = await newProject(request, origin, '原生图片上传');
    await openUpload(page, origin, project.id);
    await chooseAndUpload(page, files(5));
    await expect(page.getByText(/服务器已确认 5 \/ 5 张/)).toBeVisible({timeout: 90000});
    await expect(page.locator('.upload-confirmation')).toContainText('成功入库', {timeout: 30000});
    const stored = await session(page);
    expect(stored.status).toBe('SUCCEEDED');
    expect(stored.requestIds).toHaveLength(1);
    expect(stored.batchIds).toEqual([stored.requestIds[0]]);
    const receipt = await (await request.get(
      `${origin}/api/v55/projects/${project.id}/upload-batches/${stored.requestIds[0]}`)).json();
    expect(receipt.upload_request_status).toBe('SUCCEEDED');
    expect(receipt.items).toHaveLength(5);
    const list = await (await request.get(
      `${origin}/api/v61/projects/${project.id}/materials?reader_view=true&page=1&page_size=48`)).json();
    expect(list.total).toBe(5);
    await page.getByRole('button', {name: '查看已上传素材（5 张）', exact: true}).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/materials$`));
    await expect(page.getByText(/已选 5 张/)).toBeVisible({timeout: 30000});
    expect(external).toEqual([]);
  } finally { child.kill(); }
});

test('a partially failed server batch keeps the confirmed successes and exposes failures', async ({page, request}) => {
  test.setTimeout(180_000);
  const data = mkdtempSync(join(tmpdir(), 'xjalgo-native-upload-fail-'));
  const env = {...process.env, MC_TRAIN_DATA_DIR: data, MC_PLATFORM_VERSION: 'browser-test',
    MC_ALLOW_MULTIPLE_PROJECTS_FOR_TESTS: '1', YOLO_CONFIG_DIR: join(data, 'ultralytics')};
  const {origin, child} = await startIsolated(env);
  try {
    const project = await newProject(request, origin, '原生图片部分失败');
    await openUpload(page, origin, project.id);
    await chooseAndUpload(page, [...files(2, 'good'), {name: 'bad.jpg', mimeType: 'image/jpeg',
      buffer: Buffer.from('this is not a real image')}]);
    await expect(page.getByText(/服务器已确认 3 \/ 3 张/)).toBeVisible({timeout: 90000});
    await expect(page.getByText(/失败 1/).first()).toBeVisible();
    await expect(page.locator('.failed')).toContainText('bad.jpg');
    const stored = await session(page);
    expect(stored.failed).toBe(1);
    const receipt = await (await request.get(
      `${origin}/api/v55/projects/${project.id}/upload-batches/${stored.requestIds[0]}`)).json();
    expect(receipt.items).toHaveLength(2);
    expect(receipt.upload_failed).toHaveLength(1);
    expect(receipt.upload_failed[0].name).toBe('bad.jpg');
  } finally { child.kill(); }
});

test('a lost upload response is recovered by the original request_id without a second upload', async ({page, request}) => {
  test.setTimeout(180_000);
  const data = mkdtempSync(join(tmpdir(), 'xjalgo-native-upload-recover-'));
  const env = {...process.env, MC_TRAIN_DATA_DIR: data, MC_PLATFORM_VERSION: 'browser-test',
    MC_ALLOW_MULTIPLE_PROJECTS_FOR_TESTS: '1', YOLO_CONFIG_DIR: join(data, 'ultralytics')};
  const {origin, child} = await startIsolated(env);
  try {
    const project = await newProject(request, origin, '原生图片响应丢失');
    let posts = 0, receipts = 0;
    page.on('request', req => {
      const url = new URL(req.url());
      if (req.method() === 'POST' && url.pathname === `/api/projects/${project.id}/images`) posts += 1;
      if (req.method() === 'GET' && url.pathname.includes('/upload-batches/')) receipts += 1;
    });
    let dropped = false;
    await page.route('**/api/projects/*/images', async route => {
      if (dropped) return route.continue();
      dropped = true;
      await route.fetch();
      return route.abort();
    });
    await openUpload(page, origin, project.id);
    await chooseAndUpload(page, files(3, 'recover'));
    await expect(page.getByText(/服务器已确认 3 \/ 3 张/)).toBeVisible({timeout: 120000});
    await expect(page.getByText(/失败 0/).first()).toBeVisible();
    expect(posts).toBe(1);
    expect(receipts).toBeGreaterThanOrEqual(1);
    const list = await (await request.get(
      `${origin}/api/v61/projects/${project.id}/materials?reader_view=true&page=1&page_size=48`)).json();
    expect(list.total).toBe(3);
    const stored = await session(page);
    expect(stored.status).toBe('SUCCEEDED');
  } finally { child.kill(); }
});

test('switching projects never shows the previous project upload progress', async ({page, request}) => {
  test.setTimeout(180_000);
  const data = mkdtempSync(join(tmpdir(), 'xjalgo-native-upload-switch-'));
  const env = {...process.env, MC_TRAIN_DATA_DIR: data, MC_PLATFORM_VERSION: 'browser-test',
    MC_ALLOW_MULTIPLE_PROJECTS_FOR_TESTS: '1', YOLO_CONFIG_DIR: join(data, 'ultralytics')};
  const {origin, child} = await startIsolated(env);
  try {
    const first = await newProject(request, origin, '上传项目一');
    const second = await newProject(request, origin, '上传项目二');
    await openUpload(page, origin, first.id);
    await chooseAndUpload(page, files(1, 'first'));
    await expect(page.getByText(/服务器已确认 1 \/ 1 张/)).toBeVisible({timeout: 90000});
    await expect(page.getByRole('button', {name: '查看已上传素材（1 张）', exact: true})).toBeVisible();

    await page.goto(`${origin}/app/?switch=${second.id}#/projects/${second.id}/materials/upload`);
    await expect(page.locator('.uppy-Dashboard')).toBeVisible({timeout: 45000});
    await expect(page.getByText(/服务器已确认 0 \/ 0 张/)).toBeVisible();
    await expect(page.getByRole('button', {name: /查看已上传素材/})).toHaveCount(0);
    const sessions = await page.evaluate(() => Object.keys(localStorage)
      .filter(key => key.startsWith('material-upload-session:')));
    expect(sessions).toEqual([`material-upload-session:${first.id}`]);
  } finally { child.kill(); }
});

test('more than 64 images are split into two original request ids', async ({page, request}) => {
  test.setTimeout(240_000);
  const data = mkdtempSync(join(tmpdir(), 'xjalgo-native-upload-chunks-'));
  const env = {...process.env, MC_TRAIN_DATA_DIR: data, MC_PLATFORM_VERSION: 'browser-test',
    MC_ALLOW_MULTIPLE_PROJECTS_FOR_TESTS: '1', YOLO_CONFIG_DIR: join(data, 'ultralytics')};
  const {origin, child} = await startIsolated(env);
  try {
    const project = await newProject(request, origin, '原生图片分批');
    const postBodies = [];
    page.on('request', req => {
      const url = new URL(req.url());
      if (req.method() === 'POST' && url.pathname === `/api/projects/${project.id}/images`)
        postBodies.push(req.postData() || '');
    });
    await openUpload(page, origin, project.id);
    await chooseAndUpload(page, files(65, 'chunk'));
    await expect(page.getByText(/服务器已确认 65 \/ 65 张/)).toBeVisible({timeout: 180000});
    expect(postBodies).toHaveLength(2);
    const stored = await session(page);
    expect(stored.requestIds).toHaveLength(2);
    expect(new Set(stored.requestIds).size).toBe(2);
    expect(stored.status).toBe('SUCCEEDED');
    const itemCounts = [];
    for (const requestId of stored.requestIds) {
      const receipt = await (await request.get(
        `${origin}/api/v55/projects/${project.id}/upload-batches/${requestId}`)).json();
      expect(receipt.upload_request_status).toBe('SUCCEEDED');
      itemCounts.push(receipt.items.length);
    }
    expect(itemCounts.sort((a, b) => a - b)).toEqual([1, 64]);
    const list = await (await request.get(
      `${origin}/api/v61/projects/${project.id}/materials?reader_view=true&page=1&page_size=48`)).json();
    expect(list.total).toBe(65);
  } finally { child.kill(); }
});

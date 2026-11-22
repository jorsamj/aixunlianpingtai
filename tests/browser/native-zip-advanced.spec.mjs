import {test, expect} from '@playwright/test';
import {spawn} from 'node:child_process';
import {mkdtempSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createServer} from 'node:net';

const JPEG = Buffer.from('/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAoHBwgHBgoICAgLCgoLDhgQDg0NDh0VFhEYIx8lJCIfIiEmKzcvJik0KSEiMEExNDk7Pj4+JS5ESUM8SDc9Pjv/2wBDAQoLCw4NDhwQEBw7KCIoOzs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozv/wAARCADwAUADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD1CiiitDMKKKKACiiigAooooA//2Q==', 'base64');

function freePort() {
  return new Promise(resolve => {
    const socket = createServer();
    socket.listen(0, '127.0.0.1', () => {
      const {port} = socket.address();
      socket.close(() => resolve(port));
    });
  });
}
function crc32(buffer) {
  let table = crc32.table;
  if (!table) {
    table = crc32.table = [];
    for (let n = 0; n < 256; n += 1) {
      let c = n;
      for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      table[n] = c >>> 0;
    }
  }
  let crc = 0xffffffff;
  for (const byte of buffer) crc = table[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}
function storedZip(entries) {
  const locals = [], centrals = [];
  let offset = 0;
  for (const entry of entries) {
    const name = Buffer.from(entry.name, 'utf8');
    const data = Buffer.isBuffer(entry.buffer) ? entry.buffer : Buffer.from(entry.buffer, 'utf8');
    const crc = crc32(data);
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0); local.writeUInt16LE(20, 4);
    local.writeUInt32LE(crc, 14); local.writeUInt32LE(data.length, 18);
    local.writeUInt32LE(data.length, 22); local.writeUInt16LE(name.length, 26);
    locals.push(local, name, data);
    const central = Buffer.alloc(46);
    central.writeUInt32LE(0x02014b50, 0); central.writeUInt16LE(20, 4); central.writeUInt16LE(20, 6);
    central.writeUInt32LE(crc, 16); central.writeUInt32LE(data.length, 20);
    central.writeUInt32LE(data.length, 24); central.writeUInt16LE(name.length, 28);
    central.writeUInt32LE(offset, 42);
    centrals.push(central, name);
    offset += local.length + name.length + data.length;
  }
  const centralBuffer = Buffer.concat(centrals);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0); end.writeUInt16LE(entries.length, 8);
  end.writeUInt16LE(entries.length, 10); end.writeUInt32LE(centralBuffer.length, 12);
  end.writeUInt32LE(offset, 16);
  return Buffer.concat([...locals, centralBuffer, end]);
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
async function openZip(page, origin, projectId) {
  await page.goto(`${origin}/app/#/projects/${projectId}/materials/zip`);
  await expect(page.locator('.uppy-Dashboard')).toBeVisible({timeout: 45000});
}
async function choose(page, zips) {
  await page.locator('.uppy-Dashboard input[type=file]').first().setInputFiles(zips);
  const upload = page.locator('.uppy-StatusBar-actionBtn--upload');
  await expect(upload).toBeVisible({timeout: 15000});
  await upload.click();
}

test('annotated ZIP maps two original classes and preserves real boxes and labels', async ({page, request}) => {
  test.setTimeout(240_000);
  const data = mkdtempSync(join(tmpdir(), 'xjalgo-zip-annotated-'));
  const env = {...process.env, MC_TRAIN_DATA_DIR: data, MC_PLATFORM_VERSION: 'browser-test',
    MC_ALLOW_MULTIPLE_PROJECTS_FOR_TESTS: '1', YOLO_CONFIG_DIR: join(data, 'ultralytics')};
  const {origin, child} = await startIsolated(env);
  try {
    const project = await (await request.post(origin + '/api/projects', {
      data: {name: 'ZIP 两类别映射', labels: [{code: 'fire', display_name: '明火'},
        {code: 'smoke', display_name: '烟雾'}]},
    })).json();
    const archive = storedZip([
      {name: 'images/a.jpg', buffer: JPEG},
      {name: 'labels/a.txt', buffer: '0 0.5 0.5 0.4 0.6\n1 0.25 0.25 0.2 0.2\n'},
      {name: 'images/b.jpg', buffer: JPEG},
      {name: 'labels/b.txt', buffer: '1 0.3 0.3 0.2 0.2\n'},
      {name: 'classes.txt', buffer: 'fire\nvehicle\n'},
    ]);
    await openZip(page, origin, project.id);
    await choose(page, [{name: 'annotated.zip', mimeType: 'application/zip', buffer: archive}]);
    const modal = page.locator('#native-zip-modal-root');
    await expect(modal.locator('.zip-label-confirm')).toBeVisible({timeout: 90000});
    await expect(modal.locator('[data-zip-class]')).toHaveCount(2);
    const vehicle = modal.locator('[data-zip-class]').filter({hasText: 'vehicle'});
    await vehicle.locator('select[data-zip-target]').selectOption('smoke');
    const folder = modal.locator('[data-zip-folder-row]').first();
    if (await folder.count()) {
      await folder.locator('select[aria-label="数据用途"]').selectOption({index: 1});
      await folder.locator('select[aria-label="素材类型"]').selectOption('positive');
      await folder.locator('select[aria-label="目标标签"]').selectOption(['fire']);
    }
    const confirm = modal.locator('[data-zip-confirm-button]');
    await expect(confirm).toBeEnabled({timeout: 15000});
    await confirm.click();

    await expect.poll(async () => {
      const result = await (await request.get(
        `${origin}/api/v19/projects/${project.id}/import/jobs`)).json();
      return result.items?.every(job => job.status === 'done') && result.items?.length === 1;
    }, {timeout: 120000}).toBe(true);
    const jobs = await (await request.get(
      `${origin}/api/v19/projects/${project.id}/import/jobs`)).json();
    expect(jobs.items[0].report.imported_images).toBe(2);
    expect(jobs.items[0].report.boxes).toBe(3);

    const list = await (await request.get(
      `${origin}/api/v61/projects/${project.id}/materials?reader_view=true&page=1&page_size=48`)).json();
    expect(list.total).toBe(2);
    const labels = [];
    let boxes = 0;
    for (const row of list.items) {
      const detail = await (await request.get(
        `${origin}/api/projects/${project.id}/annotations/${row.id}?reader_view=true`)).json();
      for (const box of detail.annotation?.boxes || []) {
        boxes += 1;
        if (box.label) labels.push(String(box.label));
      }
    }
    expect(boxes).toBe(3);
    expect(new Set(labels)).toEqual(new Set(['fire', 'smoke']));
    const projectDetail = await (await request.get(`${origin}/api/projects/${project.id}`)).json();
    expect(projectDetail.project.labels.map(label => String(label.code || label)).sort())
      .toEqual(['fire', 'smoke']);
  } finally { child.kill(); }
});

test('a paused ZIP resumes the original upload session without a second import job', async ({page, request}) => {
  test.setTimeout(240_000);
  const data = mkdtempSync(join(tmpdir(), 'xjalgo-zip-pause-'));
  const env = {...process.env, MC_TRAIN_DATA_DIR: data, MC_PLATFORM_VERSION: 'browser-test',
    MC_ALLOW_MULTIPLE_PROJECTS_FOR_TESTS: '1', YOLO_CONFIG_DIR: join(data, 'ultralytics')};
  const {origin, child} = await startIsolated(env);
  try {
    const project = await (await request.post(origin + '/api/projects', {
      data: {name: 'ZIP 暂停续传', labels: [{code: 'fire', display_name: '明火'}]},
    })).json();
    const sessionIds = [];
    page.on('response', async response => {
      const url = new URL(response.url());
      if (response.request().method() === 'POST' && url.pathname.endsWith('/datasets/default/import/uploads')) {
        try { const body = await response.json(); if (body.upload_id) sessionIds.push(String(body.upload_id)); }
        catch { /* response was navigated away */ }
      }
    });
    await page.route('**/import/uploads/*/parts/*', async route => {
      await new Promise(resolve => setTimeout(resolve, 900));
      return route.continue();
    });
    const archive = storedZip([
      {name: 'images/pause.jpg', buffer: JPEG},
      {name: 'padding.bin', buffer: Buffer.alloc(48 * 1024 * 1024, 7)},
    ]);
    await openZip(page, origin, project.id);
    await choose(page, [{name: 'pause.zip', mimeType: 'application/zip', buffer: archive}]);
    const pause = page.locator('[data-zip-pause]');
    await expect(pause).toBeVisible({timeout: 30000});
    await pause.click();
    await expect(page.locator('[data-zip-resume]')).toBeVisible({timeout: 60000});
    await expect(page.locator('.zip-transfer')).toContainText('已暂停');
    await page.locator('[data-zip-resume]').click();
    const modal = page.locator('#native-zip-modal-root');
    const confirm = modal.locator('[data-zip-confirm-button]');
    await expect(confirm).toBeVisible({timeout: 90000});
    const folder = modal.locator('[data-zip-folder-row]').first();
    await folder.locator('select[aria-label="数据用途"]').selectOption({index: 1});
    await folder.locator('select[aria-label="素材类型"]').selectOption('unclassified');
    await confirm.click();
    await expect.poll(async () => {
      const result = await (await request.get(
        `${origin}/api/v19/projects/${project.id}/import/jobs`)).json();
      return {count: result.items?.length || 0,
        done: result.items?.filter(job => job.status === 'done').length || 0};
    }, {timeout: 180000}).toEqual({count: 1, done: 1});
    expect(new Set(sessionIds).size).toBe(1);
    expect(sessionIds.length).toBeGreaterThanOrEqual(1);
    await page.goto(`${origin}/app/?reopen=1#/projects/${project.id}/materials/zip`);
    await expect(page.getByRole('row').filter({hasText: 'pause.zip'})).toBeVisible({timeout: 30000});
  } finally { child.kill(); }
});

test('three ZIPs keep unique identities and all complete without cross-task replacement', async ({page, request}) => {
  test.setTimeout(240_000);
  const data = mkdtempSync(join(tmpdir(), 'xjalgo-zip-multi-'));
  const env = {...process.env, MC_TRAIN_DATA_DIR: data, MC_PLATFORM_VERSION: 'browser-test',
    MC_ALLOW_MULTIPLE_PROJECTS_FOR_TESTS: '1', YOLO_CONFIG_DIR: join(data, 'ultralytics')};
  const {origin, child} = await startIsolated(env);
  try {
    const project = await (await request.post(origin + '/api/projects', {
      data: {name: 'ZIP 多任务', labels: [{code: 'fire', display_name: '明火'}]},
    })).json();
    const zips = ['multi-a.zip', 'multi-b.zip', 'multi-c.zip'].map(name => ({
      name, mimeType: 'application/zip',
      buffer: storedZip([{name: `images/${name}.jpg`, buffer: JPEG}]),
    }));
    await openZip(page, origin, project.id);
    await choose(page, zips);
    const modal = page.locator('#native-zip-modal-root');
    for (let index = 0; index < 3; index += 1) {
      const confirm = modal.locator('[data-zip-confirm-button]');
      await expect(confirm).toBeVisible({timeout: 90000});
      const key = await modal.locator('.zip-label-confirm').getAttribute('data-review-key');
      const folder = modal.locator('[data-zip-folder-row]').first();
      await folder.locator('select[aria-label="数据用途"]').selectOption({index: 1});
      await folder.locator('select[aria-label="素材类型"]').selectOption('unclassified');
      await expect(confirm).toBeEnabled({timeout: 15000});
      await confirm.click();
      await expect(modal.locator(`.zip-label-confirm[data-review-key="${key}"]`))
        .toHaveCount(0, {timeout: 60000});
    }
    await expect.poll(async () => {
      const result = await (await request.get(
        `${origin}/api/v19/projects/${project.id}/import/jobs`)).json();
      return {count: result.items?.length || 0,
        done: result.items?.filter(job => job.status === 'done').length || 0};
    }, {timeout: 180000}).toEqual({count: 3, done: 3});
    const result = await (await request.get(
      `${origin}/api/v19/projects/${project.id}/import/jobs`)).json();
    const ids = result.items.map(job => job.id);
    expect(new Set(ids).size).toBe(3);
    expect(new Set(result.items.map(job => job.file_name)).size).toBe(3);
    expect(result.items.every(job => job.report?.imported_images === 1)).toBe(true);
    const list = await (await request.get(
      `${origin}/api/v61/projects/${project.id}/materials?reader_view=true&page=1&page_size=48`)).json();
    expect(list.total).toBe(3);
    await expect(page.locator('.zip-live')).toBeVisible({timeout: 30000});
    const transferRows = await page.locator('[data-transfer-key]').count();
    expect(transferRows).toBeGreaterThanOrEqual(3);
  } finally { child.kill(); }
});
